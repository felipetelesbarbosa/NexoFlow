"""Recompra FARMA usa exclusivamente uma base geral por fase, sem I/O por contato."""

import unittest
from contextlib import closing
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from farmalider_client import (
    FarmaliderAuthError,
    FarmaliderClient,
    FarmaliderError,
    FarmaliderLookupError,
)
from recompra import (
    RecompraReadCache,
    apply_review,
    build_plans,
    incomplete_query_summary,
    load_state,
    make_review,
    write_review,
)
from recompra_cleanup import make_cleanup_review
from recompra_group_audit import audit_group
from recompra_profiles import PetRecompraClient
from tests.test_farmalider_customers import CPF, customer_snapshot
from tests.test_recompra import NOW, STRUCTURE, fixture
from tests.test_recompra_prevention import weni_fixture


class RecompraBulkOnlyTests(unittest.TestCase):
    def test_bulk_preparation_does_not_rewrite_entire_history_for_every_contact(self):
        contacts = []
        for i in range(600):
            contact = fixture(24)[0]
            contact["uuid"] = str(i)
            contacts.append(contact)
        with (
            closing(FarmaliderClient("synthetic")) as farm,
            patch.object(
                farm, "_request_json", return_value=[customer_snapshot()]
            ) as request,
            patch("customer_observations.record_directory") as journal,
        ):
            plans = build_plans(
                contacts, farm, STRUCTURE, {"contacts": {}}, now=NOW, workers=4
            )
            self.assertEqual(len(plans), 600)
            self.assertTrue(all(p["action"] == "add" for p in plans))
            self.assertEqual(journal.call_count, 1)
            self.assertEqual(request.call_count, 1)

    def test_missing_or_partial_customer_stays_pending_without_individual_http(self):
        partial = customer_snapshot()
        partial["itens"] = None
        for payload in ([], [partial]):
            with (
                closing(FarmaliderClient("synthetic")) as farm,
                patch.object(farm, "_request_json", return_value=payload) as request,
            ):
                reads = RecompraReadCache(farm)
                with self.assertRaises(FarmaliderLookupError) as raised:
                    reads.get_cliente_by_cpf(CPF)
                self.assertEqual(
                    raised.exception.code,
                    "PEDIDO_NAO_CONFIRMADO_BASE_GERAL"
                    if payload
                    else "CPF_NAO_CONFIRMADO_BASE_GERAL",
                )
                self.assertEqual(request.call_count, 1)
                self.assertIn("clientes/FARMA", request.call_args.args[0])

    def test_explicit_null_is_absence_but_omitted_order_is_pending(self):
        payload = customer_snapshot()
        payload["ultimoPedido"] = None
        payload["itens"] = []
        with (
            closing(FarmaliderClient("synthetic")) as farm,
            patch.object(farm, "_request_json", return_value=[payload]) as request,
        ):
            reads = RecompraReadCache(farm)
            self.assertIsNone(reads.get_cliente_by_cpf(CPF)[0]["ultimoPedido"])
            self.assertEqual(request.call_count, 1)

    def test_complete_snapshot_is_reused_even_after_lru_eviction(self):
        with (
            closing(FarmaliderClient("synthetic")) as farm,
            patch.object(
                farm, "_request_json", return_value=[customer_snapshot()]
            ) as request,
        ):
            reads = RecompraReadCache(farm, max_entries=1)
            first = reads.get_cliente_by_cpf(CPF)
            reads.get_pedido("8")
            first[0]["cliente"]["nome"] = "changed"
            self.assertNotEqual(
                reads.get_cliente_by_cpf(CPF)[0]["cliente"]["nome"], "changed"
            )
            self.assertEqual(request.call_count, 1)

    def test_omitted_order_is_pending_without_individual_http(self):
        payload = customer_snapshot()
        del payload["ultimoPedido"]
        with (
            closing(FarmaliderClient("synthetic")) as farm,
            patch.object(farm, "_request_json", return_value=[payload]) as request,
        ):
            plans = build_plans(
                [fixture()[0]], farm, STRUCTURE, {"contacts": {}}, now=NOW
            )
            self.assertEqual(incomplete_query_summary(plans)["contatos"], 1)
            self.assertNotEqual(plans[0]["action"], "add")
            self.assertEqual(request.call_count, 1)

    def test_invalid_order_guards_do_not_trigger_individual_fallback(self):
        cases = [
            ("status", 3),
            ("formaPagamento", 0),
            ("formaPagamento", 999),
            ("segmento", "PET"),
            ("codCliente", 999),
            ("emissao", "malformed"),
        ]
        for key, value in cases:
            payload = customer_snapshot()
            payload["ultimoPedido"][key] = value
            with (
                self.subTest(field=key, value=value),
                closing(FarmaliderClient("synthetic")) as farm,
                patch.object(farm, "_request_json", return_value=[payload]) as request,
            ):
                plans = build_plans(
                    [fixture()[0]], farm, STRUCTURE, {"contacts": {}}, now=NOW
                )
                self.assertNotEqual(plans[0]["action"], "add")
                self.assertEqual(request.call_count, 1)

    def test_ambiguous_or_incomplete_identity_is_not_admitted(self):
        other = customer_snapshot(id=18)
        other["ultimoPedido"]["id"] = 9
        other["itens"][0]["codPedido"] = 9
        for records in (
            [customer_snapshot(), other],
            [customer_snapshot(), {"cliente": deepcopy(other["cliente"])}],
        ):
            with (
                self.subTest(records=len(records)),
                closing(FarmaliderClient("synthetic")) as farm,
                patch.object(farm, "_request_json", return_value=records) as request,
            ):
                plans = build_plans(
                    [fixture()[0]], farm, STRUCTURE, {"contacts": {}}, now=NOW
                )
                self.assertNotEqual(plans[0]["action"], "add")
                self.assertEqual(request.call_count, 1)

    def test_one_incomplete_contact_does_not_discard_valid_plan(self):
        valid = fixture()[0]
        missing = deepcopy(valid)
        missing["uuid"] = "missing"
        missing["fields"]["cpf"] = "11144477735"
        with (
            closing(FarmaliderClient("synthetic")) as farm,
            patch.object(
                farm, "_request_json", return_value=[customer_snapshot()]
            ) as request,
        ):
            plans = build_plans(
                [valid, missing], farm, STRUCTURE, {"contacts": {}}, now=NOW
            )
            by_uuid = {p["contact_uuid"]: p for p in plans}
            self.assertEqual(by_uuid[valid["uuid"]]["action"], "add")
            self.assertEqual(
                by_uuid["missing"]["reason"], "CPF_NAO_CONFIRMADO_BASE_GERAL"
            )
            self.assertEqual(incomplete_query_summary(plans)["contatos"], 1)
            self.assertEqual(request.call_count, 1)

    def test_optout_is_applied_without_loading_general_endpoint(self):
        with (
            closing(FarmaliderClient("synthetic")) as farm,
            patch.object(farm, "_request_json") as request,
        ):
            person = fixture(grouped=True, marketing="Não")[0]
            plans = build_plans([person], farm, STRUCTURE, {"contacts": {}}, now=NOW)
            self.assertEqual(plans[0]["action"], "remove")
            self.assertEqual(plans[0]["reason"], "RECUSA_MARKETING")
            request.assert_not_called()

    def test_general_failure_does_not_fan_out_and_authentication_stays_critical(self):
        contacts = [fixture()[0]]
        for exc in (FarmaliderError("synthetic"), FarmaliderAuthError("synthetic")):
            with (
                self.subTest(error=type(exc).__name__),
                closing(FarmaliderClient("synthetic")) as farm,
                patch.object(farm, "_request_json", side_effect=exc) as request,
            ):
                if isinstance(exc, FarmaliderAuthError):
                    with self.assertRaises(FarmaliderAuthError):
                        build_plans(
                            contacts, farm, STRUCTURE, {"contacts": {}}, now=NOW
                        )
                else:
                    plans = build_plans(
                        contacts, farm, STRUCTURE, {"contacts": {}}, now=NOW
                    )
                    self.assertEqual(incomplete_query_summary(plans)["contatos"], 1)
                self.assertEqual(request.call_count, 1)

    def test_partial_apply_and_new_review_preserve_confirmed_writes(self):
        valid = fixture()[0]
        missing = deepcopy(valid)
        missing["uuid"] = "missing"
        missing["fields"]["cpf"] = "11144477735"
        structure = {**STRUCTURE, "segment": "FARMA"}
        weni, live = weni_fixture("FARMA", [valid, missing])
        with (
            TemporaryDirectory() as folder,
            closing(FarmaliderClient("synthetic")) as farm,
            patch.object(
                farm, "_request_json", return_value=[customer_snapshot()]
            ) as request,
            patch("recompra.inspect_structure", return_value=structure),
        ):
            path = Path(folder) / "state.json"
            audit = Path(folder) / "audit.jsonl"
            state = load_state(path)
            plans = build_plans([valid, missing], farm, structure, state, now=NOW)
            review = make_review(plans, structure, now=NOW, state=state)
            result = apply_review(
                review,
                weni,
                farm,
                state_path=path,
                audit_path=audit,
                now_fn=lambda: NOW,
            )
            self.assertEqual(result, {"aplicados": 1, "consultas_pendentes": 1})
            self.assertTrue(live[valid["uuid"]]["groups"])
            self.assertFalse(live["missing"]["groups"])
            self.assertEqual(
                request.call_count, 2
            )  # Simulação e aplicação: bases novas.
            applied_writes = weni.update_contact_fields.call_count
            group_writes = weni.contact_group_action.call_count
            farm.reset_execution_reads()
            state = load_state(path)
            plans = build_plans(list(live.values()), farm, structure, state, now=NOW)
            review = make_review(plans, structure, now=NOW, state=state)
            result = apply_review(
                review,
                weni,
                farm,
                state_path=path,
                audit_path=audit,
                now_fn=lambda: NOW,
            )
            self.assertEqual(result.get("sem_mudanca"), 1)
            self.assertEqual(result.get("consultas_pendentes"), 1)
            self.assertEqual(weni.update_contact_fields.call_count, applied_writes)
            self.assertEqual(weni.contact_group_action.call_count, group_writes)
            self.assertTrue(audit.exists())

    def test_null_ignores_orphan_items_and_does_not_create_pending_query(self):
        for items in (None, [], [{"codPedido": 999, "descricao": "órfão"}]):
            payload = customer_snapshot()
            payload["ultimoPedido"] = None
            payload["itens"] = items
            with (
                self.subTest(items=bool(items)),
                closing(FarmaliderClient("synthetic")) as farm,
                patch.object(farm, "_request_json", return_value=[payload]) as request,
            ):
                plans = build_plans(
                    [fixture()[0]], farm, STRUCTURE, {"contacts": {}}, now=NOW
                )
                self.assertEqual(plans[0]["reason"], "SEM_PEDIDO_CONFIRMADO")
                self.assertEqual(incomplete_query_summary(plans)["contatos"], 0)
                self.assertEqual(request.call_count, 1)

    def test_invalid_cpf_keeps_identity_check_on_general_snapshot(self):
        for name, allowed in (("Cliente Sintético", True), ("Outra Pessoa", False)):
            person = fixture()[0]
            person["fields"]["cpf"] = "12345678900"
            payload = customer_snapshot(cpf="12345678900", nome=name)
            with (
                self.subTest(identity_matches=allowed),
                closing(FarmaliderClient("synthetic")) as farm,
                patch.object(farm, "_request_json", return_value=[payload]) as request,
            ):
                plans = build_plans(
                    [person], farm, STRUCTURE, {"contacts": {}}, now=NOW
                )
                self.assertEqual(plans[0]["action"] == "add", allowed)
                self.assertEqual(request.call_count, 1)

    def test_past_d25_deadline_and_empty_items_do_not_admit(self):
        for days, items in ((25, True), (26, True), (2, False)):
            payload = customer_snapshot()
            payload["ultimoPedido"]["emissao"] = (
                NOW - timedelta(days=days)
            ).isoformat()
            if not items:
                payload["itens"] = []
            with (
                self.subTest(days=days, items=items),
                closing(FarmaliderClient("synthetic")) as farm,
                patch.object(farm, "_request_json", return_value=[payload]) as request,
            ):
                plans = build_plans(
                    [fixture()[0]], farm, STRUCTURE, {"contacts": {}}, now=NOW
                )
                self.assertNotEqual(plans[0]["action"], "add")
                self.assertEqual(request.call_count, 1)

    def test_cleanup_uses_one_general_base_without_repeated_history_writes(self):
        contacts = []
        for index in range(600):
            person = fixture(grouped=True)[0]
            person["uuid"] = str(index)
            contacts.append(person)
        weni, _ = weni_fixture("FARMA", contacts)
        payload = customer_snapshot()
        payload["ultimoPedido"]["status"] = 3
        with (
            closing(FarmaliderClient("synthetic")) as farm,
            patch.object(farm, "_request_json", return_value=[payload]) as request,
            patch("customer_observations.record_directory") as journal,
        ):
            review = make_cleanup_review(weni, farm, "FARMA", now_fn=lambda: NOW)
            self.assertEqual(len(review["plans"]), 600)
            self.assertEqual(request.call_count, 1)
            self.assertEqual(journal.call_count, 1)

    def test_group_audit_shares_bulk_only_read_policy(self):
        person = fixture(grouped=True)[0]
        weni, _ = weni_fixture("FARMA", [person])
        weni.iter_group_contacts.side_effect = lambda group: iter([deepcopy(person)])
        with (
            TemporaryDirectory() as folder,
            closing(FarmaliderClient("synthetic")) as farm,
            patch.object(farm, "_request_json", return_value=[]) as request,
            patch("customer_observations.record_directory") as journal,
        ):
            audit_group(weni, farm, STRUCTURE, Path(folder) / "group.json", now=NOW)
            self.assertEqual(request.call_count, 1)
            self.assertEqual(journal.call_count, 1)

    def test_known_weni_blocks_are_removed_without_api_even_if_api_is_unavailable(self):
        for segment, client_type in (
            ("FARMA", FarmaliderClient),
            ("PET", PetRecompraClient),
        ):
            for field, value in (
                ("pedido_status", "3"),
                ("pedido_forma_pagamento", "0"),
                ("pedido_forma_pagamento", "999"),
            ):
                person = fixture(grouped=True)[0]
                person["fields"][field] = value
                structure = {**STRUCTURE, "segment": segment}
                weni, live = weni_fixture(segment, [person])
                with (
                    self.subTest(segment=segment, field=field, value=value),
                    TemporaryDirectory() as folder,
                    closing(client_type("synthetic")) as farm,
                    patch.object(
                        farm,
                        "_request_json",
                        side_effect=FarmaliderAuthError("unavailable"),
                    ) as request,
                    patch("recompra.inspect_structure", return_value=structure),
                ):
                    path = Path(folder) / "state.json"
                    state = load_state(path)
                    plans = build_plans([person], farm, structure, state, now=NOW)
                    self.assertEqual(plans[0]["action"], "remove")
                    review = make_review(plans, structure, now=NOW, state=state)
                    result = apply_review(
                        review,
                        weni,
                        farm,
                        state_path=path,
                        audit_path=Path(folder) / "audit.jsonl",
                        now_fn=lambda: NOW,
                    )
                    self.assertEqual(result, {"aplicados": 1})
                    self.assertFalse(live[person["uuid"]]["groups"])
                    request.assert_not_called()

    def test_pending_members_are_visible_in_txt_and_not_silently_removed(self):
        partial = customer_snapshot()
        partial.pop("itens")
        person = fixture(grouped=True)[0]
        other = deepcopy(person)
        other["uuid"] = "missing"
        other["fields"]["cpf"] = "11144477735"
        weni, live = weni_fixture("FARMA", [person, other])
        with (
            TemporaryDirectory() as folder,
            closing(FarmaliderClient("synthetic")) as farm,
            patch.object(farm, "_request_json", return_value=[partial]) as request,
            patch("recompra.inspect_structure", return_value=STRUCTURE),
        ):
            path = Path(folder) / "state.json"
            state = load_state(path)
            plans = build_plans([person, other], farm, STRUCTURE, state, now=NOW)
            self.assertTrue(all(p["action"] == "" and not p["fields"] for p in plans))
            review = make_review(plans, STRUCTURE, now=NOW, state=state)
            review_path = Path(folder) / "review.json"
            write_review(review, review_path)
            report = review_path.with_suffix(".txt").read_text(encoding="utf-8-sig")
            self.assertIn("CPF_NAO_CONFIRMADO_BASE_GERAL", report)
            self.assertIn("PEDIDO_NAO_CONFIRMADO_BASE_GERAL", report)
            self.assertIn("Contatos já no grupo com consulta pendente: 2", report)
            self.assertNotIn("OUTRO_MOTIVO", report)
            result = apply_review(
                review,
                weni,
                farm,
                state_path=path,
                audit_path=Path(folder) / "audit.jsonl",
                now_fn=lambda: NOW,
            )
            self.assertEqual(result, {"consultas_pendentes": 2})
            self.assertTrue(all(c["groups"] for c in live.values()))
            weni.contact_group_action.assert_not_called()
            weni.update_contact_fields.assert_not_called()
            self.assertEqual(request.call_count, 1)

    def test_auth_failure_during_apply_remains_critical(self):
        person = fixture()[0]
        weni, _ = weni_fixture("FARMA", [person])
        with (
            TemporaryDirectory() as folder,
            closing(FarmaliderClient("synthetic")) as farm,
            patch.object(
                farm, "_request_json", return_value=[customer_snapshot()]
            ) as request,
            patch("recompra.inspect_structure", return_value=STRUCTURE),
        ):
            path = Path(folder) / "state.json"
            state = load_state(path)
            plans = build_plans([person], farm, STRUCTURE, state, now=NOW)
            review = make_review(plans, STRUCTURE, now=NOW, state=state)
            request.side_effect = FarmaliderAuthError("synthetic")
            with self.assertRaises(FarmaliderAuthError):
                apply_review(
                    review,
                    weni,
                    farm,
                    state_path=path,
                    audit_path=Path(folder) / "audit.jsonl",
                    now_fn=lambda: NOW,
                )
            weni.update_contact_fields.assert_not_called()
            weni.contact_group_action.assert_not_called()
