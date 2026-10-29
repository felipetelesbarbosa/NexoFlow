"""Prevenção da admissão com fontes sintéticas e sem APIs reais."""

import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from farmalider_client import FarmaliderError
from recompra import (
    apply_review,
    guard,
    load_state,
    make_review,
    propose,
    validate_flow_guards,
)
from recompra_cleanup import (
    apply_cleanup_review,
    make_cleanup_review,
    read_cleanup_review,
    write_cleanup_review,
)
from recompra_profiles import (
    CANCEL_EXPRESSION,
    PET_REFUSAL_EXPRESSION,
    PetRecompraClient,
    profile_for,
    profile_settings,
)
from tests.test_farmalider_customers import CPF, customer_snapshot
from tests.test_recompra import NOW, STRUCTURE, fixture
from weni_client import WeniError


class PreventionTests(unittest.TestCase):
    def test_cancellation_representations_never_populate_group(self):
        for key, values in (
            ("pedido_status", ("3", "3.0", 3.0, "Cancelado", "cancelada")),
            (
                "pedido_forma_pagamento",
                ("0", "0.0", 0.0, "_", "Cancelado", "cancelada"),
            ),
        ):
            for value in values:
                with self.subTest(key=key, value=value):
                    contact, order, items = fixture(24, grouped=True)
                    contact["fields"][key] = value
                    plan = propose(contact, order, items, STRUCTURE, now=NOW)
                    self.assertEqual(plan["action"], "remove")
                    self.assertEqual(plan["fields"], {})

    def test_pre_apply_guard_captures_status_payment_order_and_both_refusals(self):
        contact, _, _ = fixture(24)
        original = guard(contact)
        for key in (
            "pedido_status",
            "pedido_forma_pagamento",
            "pedido_id",
            "opt_in_marketing",
        ):
            with self.subTest(key=key):
                contact["fields"][key] = "mudou"
                self.assertNotEqual(original, guard(contact))
                del contact["fields"][key]


def safe_flow(segment):
    from recompra import DAY_EXPRESSION, REFUSAL_EXPRESSION

    days = profile_for(segment).days
    specs = [
        ("@contact.groups", "has_group", ["g-out"], False),
        (
            PET_REFUSAL_EXPRESSION if segment == "PET" else REFUSAL_EXPRESSION,
            "has_phrase",
            ["MKT_RECUSADO"],
            False,
        ),
        (DAY_EXPRESSION.replace("25", str(days)), "has_phrase", [f"D{days}_OK"], True),
        ("@fields.pedido_produtos", "has_text", [], True),
        (CANCEL_EXPRESSION, "has_phrase", ["CANCELADO"], False),
    ]
    nodes = []
    for idx, (operand, kind, arguments, accept) in enumerate(specs):
        following = str(idx + 1)
        nodes.append(
            {
                "uuid": str(idx),
                "actions": [],
                "router": {
                    "operand": operand,
                    "cases": [
                        {"type": kind, "arguments": arguments, "category_uuid": "yes"}
                    ],
                    "categories": [
                        {"uuid": "yes", "exit_uuid": "yes"},
                        {"uuid": "no", "exit_uuid": "no"},
                    ],
                    "default_category_uuid": "no",
                },
                "exits": [
                    {
                        "uuid": "yes",
                        "destination_uuid": following if accept else "reject",
                    },
                    {
                        "uuid": "no",
                        "destination_uuid": "reject" if accept else following,
                    },
                ],
            }
        )
    nodes += [
        {
            "uuid": "5",
            "actions": [
                {"type": "send_msg", "templating": {"template": {"name": "recompra"}}}
            ],
            "exits": [],
        },
        {
            "uuid": "reject",
            "actions": [{"type": "remove_contact_groups"}],
            "exits": [{"uuid": "end", "destination_uuid": None}],
        },
    ]
    return {"uuid": "flow", "nodes": nodes}


def weni_fixture(segment, contacts):
    profile = profile_for(segment)
    client = Mock()
    live = {c["uuid"]: deepcopy(c) for c in contacts}
    client.get_org.return_value = {
        "uuid": segment,
        "name": "Delivery " + profile.brand,
        "timezone": "America/Belem",
    }
    client.list_groups.return_value = [
        {"uuid": "g-recompra", "name": profile.group},
        {"uuid": "g-out", "name": "Opt-Out Marketing"},
    ]
    client.list_fields.return_value = [
        {"key": key, "value_type": kind}
        for key, kind in (
            ("pedido_data", "datetime"),
            ("pedido_produtos", "text"),
            ("pedido_status", "text"),
            ("pedido_forma_pagamento", "text"),
        )
    ]
    client.list_campaigns.return_value = [
        {"uuid": "campaign", "name": profile.group, "group": {"uuid": "g-recompra"}}
    ]
    client.list_campaign_events.return_value = [
        {
            "uuid": "event",
            "relative_to": {"key": "pedido_data"},
            "offset": profile.days,
            "unit": "days",
            "delivery_hour": -1,
            "flow": {"uuid": "flow", "name": profile.flow},
        }
    ]
    client.get_flow_definition.return_value = {"flows": [safe_flow(segment)]}
    client.iter_contacts.side_effect = lambda: iter(deepcopy(list(live.values())))
    client.get_contact.side_effect = lambda *, uuid: deepcopy(live.get(uuid))
    client.update_contact_fields.side_effect = lambda uid, fields: live[uid][
        "fields"
    ].update(fields)

    def group_action(uid, *, action, group):
        live[uid]["groups"] = [g for g in live[uid]["groups"] if g["uuid"] != group]
        if action == "add":
            live[uid]["groups"].append({"uuid": group, "name": profile.group})

    client.contact_group_action.side_effect = group_action
    return client, live


class CleanupTests(unittest.TestCase):
    def test_review_roundtrip_partial_apply_and_resume_do_not_repeat_removals(self):
        for segment in ("FARMA", "PET"):
            with self.subTest(segment=segment), TemporaryDirectory() as tmp:
                contacts = []
                for uid in ("local", "api", "good", "pending"):
                    c, _, _ = fixture(24, grouped=True)
                    c["uuid"] = uid
                    c["groups"][0]["name"] = profile_for(segment).group
                    contacts.append(c)
                contacts[0]["fields"]["pedido_status"] = "cancelada"
                client, _ = weni_fixture(segment, contacts)
                farm = Mock()

                def resolve(contact, *args, **kwargs):
                    if contact["uuid"] == "pending":
                        raise FarmaliderError("falha sintética")
                    _, order, items = fixture(
                        24, status="3" if contact["uuid"] == "api" else "2"
                    )
                    return order, items

                root = Path(tmp)
                with patch("recompra_cleanup.resolve_latest", side_effect=resolve):
                    review = make_cleanup_review(
                        client, farm, segment, now_fn=lambda: NOW
                    )
                    self.assertEqual(len(review["plans"]), 3)
                    write_cleanup_review(review, root / "review.json")
                    review = read_cleanup_review(root / "review.json", segment)
                    result = apply_cleanup_review(
                        review,
                        client,
                        farm,
                        state_path=root / "state.json",
                        audit_path=root / "audit.jsonl",
                        now_fn=lambda: NOW,
                    )
                    self.assertEqual(result, {"removidos": 2, "consultas_pendentes": 1})
                    self.assertEqual(client.contact_group_action.call_count, 2)
                    self.assertTrue(
                        all(
                            c.kwargs["action"] == "remove"
                            for c in client.contact_group_action.call_args_list
                        )
                    )
                    second = make_cleanup_review(
                        client, farm, segment, now_fn=lambda: NOW
                    )
                    apply_cleanup_review(
                        second,
                        client,
                        farm,
                        state_path=root / "state.json",
                        audit_path=root / "audit.jsonl",
                        now_fn=lambda: NOW,
                    )
                    self.assertEqual(client.contact_group_action.call_count, 2)
                client.update_contact_fields.assert_not_called()
                client.start_flow.assert_not_called()
                self.assertFalse((root / "state.json").exists())

    def test_change_after_review_is_not_removed(self):
        contact, _, _ = fixture(24, grouped=True)
        contact["fields"]["pedido_status"] = "3"
        client, live = weni_fixture("FARMA", [contact])
        farm = Mock()
        review = make_cleanup_review(client, farm, "FARMA", now_fn=lambda: NOW)
        live["u1"]["fields"]["pedido_status"] = "2"
        with TemporaryDirectory() as tmp:
            result = apply_cleanup_review(
                review,
                client,
                farm,
                state_path=Path(tmp) / "state.json",
                audit_path=Path(tmp) / "audit.jsonl",
                now_fn=lambda: NOW,
            )
        self.assertEqual(result, {"conflitos": 1})
        client.contact_group_action.assert_not_called()

    def test_uncertain_post_stops_and_never_retries(self):
        contact, _, _ = fixture(24, grouped=True)
        contact["fields"]["pedido_forma_pagamento"] = "0.0"
        client, _ = weni_fixture("FARMA", [contact])
        farm = Mock()
        review = make_cleanup_review(client, farm, "FARMA", now_fn=lambda: NOW)
        client.contact_group_action.side_effect = WeniError("resposta perdida")
        with TemporaryDirectory() as tmp, self.assertRaises(WeniError):
            apply_cleanup_review(
                review,
                client,
                farm,
                state_path=Path(tmp) / "state.json",
                audit_path=Path(tmp) / "audit.jsonl",
                now_fn=lambda: NOW,
            )
        client.contact_group_action.assert_called_once()

    def test_review_cannot_be_applied_to_another_segment(self):
        c, _, _ = fixture(grouped=True)
        c["fields"]["pedido_status"] = "3"
        weni, _ = weni_fixture("FARMA", [c])
        review = make_cleanup_review(weni, Mock(), "FARMA", now_fn=lambda: NOW)
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "review.json"
            write_cleanup_review(review, path)
            with self.assertRaises(RuntimeError):
                read_cleanup_review(path, "PET")


class PetProfileTests(unittest.TestCase):
    def test_pet_window_and_animal_products_have_separate_policy(self):
        structure = {**STRUCTURE, "segment": "PET"}
        for days in (25, 29, 30, 31, -1):
            c, o, items = fixture(days)
            items[0]["produto_nome"] = "Ração para cães"
            plan = propose(c, o, items, structure, now=NOW)
            self.assertEqual(plan["action"] == "add", 0 <= days < 30)
            self.assertEqual(plan["within_window"], 0 <= days <= 30)
        c, o, items = fixture(24)
        items[0]["produto_nome"] = "Ração para cães"
        pet = propose(c, o, items, structure, now=NOW)
        self.assertEqual(pet["action"], "add")
        self.assertEqual(propose(c, o, items, STRUCTURE, now=NOW)["action"], "")
        with self.assertRaises(RuntimeError):
            make_review([pet], STRUCTURE, now=NOW)
        self.assertEqual(set(pet["fields"]), {"pedido_data", "pedido_produtos"})

    def test_pet_credentials_never_fall_back_to_farma(self):
        with self.assertRaises(ValueError):
            profile_settings(SimpleNamespace(WENI_API_TOKEN="FARMA_SYNTHETIC"), "PET")
        self.assertNotEqual(profile_for("PET").directory, profile_for().directory)

    def test_pet_directory_and_orders_cannot_use_farma_snapshot(self):
        snapshot = customer_snapshot()
        snapshot["ultimoPedido"]["segmento"] = "PET"
        client = PetRecompraClient("TOKEN_SINTETICO")
        self.addCleanup(client.close)
        with patch.object(
            client, "get_clientes_segmento", return_value=[snapshot]
        ) as fetch:
            self.assertTrue(client.get_cliente_by_cpf(CPF))
            self.assertEqual(client.get_pedido(8)["capa"]["segmento"], "PET")
            fetch.assert_called_once_with("PET")
        with (
            patch.object(
                client, "_request_json", return_value={"capa": {"segmento": "FARMA"}}
            ),
            self.assertRaises(FarmaliderError),
        ):
            client.get_pedido(99)
        with (
            patch.object(client, "_request_json", return_value={"segmento": "FARMA"}),
            self.assertRaises(FarmaliderError),
        ):
            client.get_cliente_by_cpf("11111111111")

    def test_both_flow_guards_reject_missing_cancellation_gate(self):
        for segment in ("FARMA", "PET"):
            flow = safe_flow(segment)
            self.assertTrue(validate_flow_guards(flow, "g-out", segment=segment))
            flow["nodes"][3]["exits"][0]["destination_uuid"] = "5"
            self.assertFalse(validate_flow_guards(flow, "g-out", segment=segment))

    def test_pet_apply_revalidates_and_has_separate_files(self):
        from recompra import inspect_structure

        c, o, items = fixture(29)
        items[0]["produto_nome"] = "Ração para cães"
        client, live = weni_fixture("PET", [c])
        structure = inspect_structure(client, segment="PET")
        self.assertEqual(structure["errors"], [])
        with TemporaryDirectory() as tmp:
            state, audit = Path(tmp) / "pet.json", Path(tmp) / "pet.jsonl"
            plan = propose(c, o, items, structure, now=NOW)
            review = make_review([plan], structure, state=load_state(state), now=NOW)
            with patch("recompra.resolve_latest", return_value=(o, items)):
                self.assertEqual(
                    apply_review(
                        review,
                        client,
                        Mock(),
                        state_path=state,
                        audit_path=audit,
                        now_fn=lambda: NOW,
                    ),
                    {"aplicados": 1},
                )
                next_review = make_review(
                    [
                        propose(
                            live["u1"],
                            o,
                            items,
                            structure,
                            saved=load_state(state)["contacts"]["u1"],
                            now=NOW,
                        )
                    ],
                    structure,
                    state=load_state(state),
                    now=NOW,
                )
                self.assertEqual(
                    apply_review(
                        next_review,
                        client,
                        Mock(),
                        state_path=state,
                        audit_path=audit,
                        now_fn=lambda: NOW,
                    ),
                    {"sem_mudanca": 1},
                )
            client.contact_group_action.assert_called_once_with(
                "u1", action="add", group="g-recompra"
            )


class RecompraCliProfileTests(unittest.TestCase):
    def test_pet_real_cli_dry_run_check_and_apply_keep_profile_and_state(self):
        import contextlib
        import io
        import os

        import secrets_config
        from run_recompra import main

        contact, order, items = fixture(29)
        items[0]["produto_nome"] = "Ração para cães"
        client, _ = weni_fixture("PET", [contact])
        farm = Mock()
        settings = {
            "PET": {
                "SEGMENTO": "PET",
                "WENI_API_TOKEN": "PET_SINTETICO",
                "FARMALIDER_API_TOKEN": "API_PET_SINTETICA",
                "FARMALIDER_USE_HML": True,
                "RECOMPRA_ENABLED": True,
            }
        }
        with TemporaryDirectory() as tmp, contextlib.ExitStack() as stack:
            previous = os.getcwd()
            os.chdir(tmp)
            stack.callback(os.chdir, previous)
            stack.enter_context(
                patch.object(secrets_config, "PERFIS", settings, create=True)
            )
            stack.enter_context(patch("weni_client.WeniClient", return_value=client))
            creator = stack.enter_context(
                patch("recompra_profiles.PetRecompraClient", return_value=farm)
            )
            stack.enter_context(patch("recompra.now_local", return_value=NOW))
            clock = stack.enter_context(
                patch("recompra.datetime", wraps=__import__("datetime").datetime)
            )
            clock.now.return_value = NOW
            stack.enter_context(
                patch("recompra.resolve_latest", return_value=(order, items))
            )
            stack.enter_context(patch("proxy_config.configure_proxy"))
            stack.enter_context(patch("logging_config.configure_logging"))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            self.assertEqual(main(["--perfil", "PET", "--dry-run"]), 0)
            client.contact_group_action.assert_not_called()
            review = "logs/PET/recompra_review.json"
            self.assertTrue(Path(review).is_file())
            self.assertEqual(
                main(["--perfil", "FARMA", "--apply", "--require-review", review]), 1
            )
            client.contact_group_action.assert_not_called()
            self.assertEqual(
                main(["--perfil", "PET", "--check-review", "--require-review", review]),
                0,
            )
            self.assertEqual(
                main(["--perfil", "PET", "--apply", "--require-review", review]), 0
            )
            self.assertTrue(Path("logs/PET/recompra_state.json").exists())
            self.assertFalse(Path("logs/recompra_state.json").exists())
            creator.assert_called_with("API_PET_SINTETICA", use_hml=True)
            client.contact_group_action.assert_called_once_with(
                "u1", action="add", group="g-recompra"
            )

    def test_cleanup_cli_roundtrip_requires_review_and_never_adds(self):
        import contextlib
        import io
        import os

        from run_recompra import main

        contact, _, _ = fixture(24, grouped=True)
        contact["fields"]["pedido_status"] = "3"
        client, _ = weni_fixture("FARMA", [contact])
        with TemporaryDirectory() as tmp, contextlib.ExitStack() as stack:
            previous = os.getcwd()
            os.chdir(tmp)
            stack.callback(os.chdir, previous)
            stack.enter_context(patch("weni_client.WeniClient", return_value=client))
            stack.enter_context(
                patch("weni_update._open_farmalider", return_value=Mock())
            )
            stack.enter_context(patch("proxy_config.configure_proxy"))
            stack.enter_context(patch("logging_config.configure_logging"))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            self.assertEqual(main(["--cleanup-cancelled", "--dry-run"]), 0)
            client.contact_group_action.assert_not_called()
            self.assertEqual(
                main(
                    [
                        "--cleanup-cancelled",
                        "--apply",
                        "--require-review",
                        "logs/recompra_cancelados_review.json",
                    ]
                ),
                0,
            )
            client.contact_group_action.assert_called_once_with(
                "u1", action="remove", group="g-recompra"
            )
            client.update_contact_fields.assert_not_called()


class FreshCancellationTests(unittest.TestCase):
    def test_status_or_payment_changes_before_admission_never_populate_either_group(
        self,
    ):
        from recompra import inspect_structure

        for segment in ("FARMA", "PET"):
            for key, cancelled in (
                ("pedido_status", "3"),
                ("pedido_forma_pagamento", "Cancelado"),
            ):
                with (
                    self.subTest(segment=segment, key=key),
                    TemporaryDirectory() as tmp,
                ):
                    c, o, items = fixture(24)
                    client, live = weni_fixture(segment, [c])
                    structure = inspect_structure(client, segment=segment)
                    state, audit = Path(tmp) / "state.json", Path(tmp) / "audit.jsonl"
                    plan = propose(c, o, items, structure, now=NOW)
                    review = make_review(
                        [plan], structure, now=NOW, state=load_state(state)
                    )

                    def get_contact(
                        *, uuid, client=client, live=live, key=key, cancelled=cancelled
                    ):
                        if client.update_contact_fields.called:
                            live[uuid]["fields"][key] = cancelled
                        return deepcopy(live[uuid])

                    client.get_contact.side_effect = get_contact
                    with patch("recompra.resolve_latest", return_value=(o, items)):
                        result = apply_review(
                            review,
                            client,
                            Mock(),
                            state_path=state,
                            audit_path=audit,
                            now_fn=lambda: NOW,
                        )
                    self.assertEqual(result, {"conflitos": 1})
                    client.contact_group_action.assert_not_called()

    def test_pet_bulk_order_flows_through_real_identity_and_order_validation(self):
        from recompra import resolve_latest

        for status, payment, expected in (
            (2, 5, "add"),
            (3, 5, "remove"),
            (2, 0, "remove"),
        ):
            with self.subTest(status=status, payment=payment):
                snapshot = customer_snapshot()
                snapshot["ultimoPedido"].update(
                    segmento="PET", status=status, formaPagamento=payment
                )
                snapshot["itens"][0]["descricao"] = "Ração para cães"
                farm = PetRecompraClient("TOKEN_SINTETICO")
                try:
                    c, _, _ = fixture(grouped=expected == "remove")
                    if expected == "remove":
                        c["groups"][0]["name"] = profile_for("PET").group
                    with patch.object(
                        farm, "get_clientes_segmento", return_value=[snapshot]
                    ):
                        order, items = resolve_latest(c, farm, NOW.isoformat())
                        plan = propose(
                            c, order, items, {**STRUCTURE, "segment": "PET"}, now=NOW
                        )
                    self.assertEqual(plan["action"], expected)
                    self.assertEqual(plan["fields"] == {}, expected == "remove")
                finally:
                    farm.close()


class CanonicalPetMarketingTests(unittest.TestCase):
    def test_pet_uses_canonical_field_while_farma_keeps_existing_rule(self):
        c, o, items = fixture(24)
        c["fields"].update(marketing_opt_in="Não", opt_in_marketing="Sim")
        self.assertEqual(
            propose(c, o, items, {**STRUCTURE, "segment": "PET"}, now=NOW)["action"],
            "add",
        )
        self.assertEqual(
            propose(c, o, items, STRUCTURE, now=NOW)["reason"], "RECUSA_MARKETING"
        )
        c["fields"].update(marketing_opt_in="Sim", opt_in_marketing="Não")
        self.assertEqual(
            propose(c, o, items, {**STRUCTURE, "segment": "PET"}, now=NOW)["reason"],
            "RECUSA_MARKETING",
        )
        c["fields"]["opt_in_marketing"] = "Sim"
        c["groups"].append({"uuid": "g-out", "name": "Opt-Out Marketing"})
        self.assertEqual(
            propose(c, o, items, {**STRUCTURE, "segment": "PET"}, now=NOW)["reason"],
            "RECUSA_MARKETING",
        )

    def test_legacy_pet_flow_remains_accepted_during_migration(self):
        from recompra_profiles import PET_LEGACY_REFUSAL_EXPRESSION

        f = safe_flow("PET")
        f["nodes"][1]["router"]["operand"] = PET_LEGACY_REFUSAL_EXPRESSION
        self.assertTrue(validate_flow_guards(f, "g-out", segment="PET"))

    def test_pet_audit_counts_the_canonical_field(self):
        from recompra_review_audit import _add_marketing, _marketing_counts

        counts = _marketing_counts()
        _add_marketing(
            counts,
            {
                "segment": "PET",
                "guard": {
                    "fields": {"marketing_opt_in": "Não", "opt_in_marketing": "Sim"}
                },
            },
            "g-out",
        )
        self.assertEqual(counts["affirmative_value"], 1)
        self.assertEqual(counts["refused_value"], 0)


class InvalidPaymentPreventionTests(unittest.TestCase):
    def test_invalid_payment_does_not_enter_any_campaign(self):
        for segment in ("FARMA", "PET"):
            for payment in ("", "99", "-1", "desconhecido"):
                c, o, items = fixture(24, grouped=True)
                c["groups"][0]["name"] = (
                    "Recompra Pets Líder" if segment == "PET" else "Recompra FarmaLíder"
                )
                o["farmalider_forma_pagamento"] = payment
                plan = propose(c, o, items, {**STRUCTURE, "segment": segment}, now=NOW)
                self.assertEqual(plan["action"], "remove")
                self.assertEqual(plan["reason"], "PAGAMENTO_INVALIDO")
                self.assertEqual(plan["fields"], {})
