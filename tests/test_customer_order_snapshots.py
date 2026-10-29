"""Snapshots de clientes/segmento e conferência de endereço, sem APIs reais."""

import tempfile
import unittest
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path
from unittest.mock import Mock, patch

from analytics import normalize_contact
from delivery_tickets import reconcile_tickets
from farmalider_client import FarmaliderClient
from farmalider_customers import CustomerDirectory, enrichment, matching_order_address
from main import FarmaliderSettings, build_orders, validate_contacts
from recompra import apply_review, build_plans, load_state, make_review
from tests.test_delivery_tickets import NOW, contact, selection
from tests.test_farmalider_customers import CPF, customer, customer_snapshot
from tests.test_recompra import STRUCTURE
from weni_update import (
    REQUIRED_ORDER_FIELDS,
    ContactUpdatePlan,
    _apply_customer_enrichment,
    audit_plans,
)


class CustomerSnapshotIndexTests(unittest.TestCase):
    def test_wrapped_response_keeps_customer_and_order_with_separate_ids(self):
        index = CustomerDirectory([customer_snapshot()])
        self.assertEqual(index.candidates(CPF)[0]["id"], 17)
        self.assertEqual(index.latest_by_cpf(CPF)[0]["ultimoPedido"]["id"], 8)
        self.assertEqual(index.order_by_id("8")["capa"]["codCliente"], 17)
        self.assertIsNone(index.order_by_id("17"))

    def test_only_complete_owned_consistent_snapshots_are_used(self):
        for change in (
            "missing_items",
            "wrong_items",
            "wrong_owner",
            "invalid_date",
            "unknown_status",
            "wrong_segment",
        ):
            with self.subTest(change=change):
                payload = customer_snapshot()
                if change == "missing_items":
                    payload.pop("itens")
                elif change == "wrong_items":
                    payload["itens"][0]["codPedido"] = 99
                elif change == "wrong_owner":
                    payload["ultimoPedido"]["codCliente"] = 99
                elif change == "invalid_date":
                    payload["ultimoPedido"]["emissao"] = "sem data"
                elif change == "unknown_status":
                    payload["ultimoPedido"]["status"] = 999
                else:
                    payload["ultimoPedido"]["segmento"] = "PET"
                index = CustomerDirectory([payload])
                self.assertIsNone(index.latest_by_cpf(CPF))
                self.assertIsNone(index.order_by_id("8"))
                self.assertEqual(len(index.candidates(CPF)), 1)

    def test_missing_last_order_never_means_no_purchase(self):
        for latest in (None, {}, "incorreto"):
            with self.subTest(latest=latest):
                payload = customer_snapshot()
                payload["ultimoPedido"] = latest
                self.assertIsNone(CustomerDirectory([payload]).latest_by_cpf(CPF))

    def test_divergent_duplicate_customer_does_not_choose_first_snapshot(self):
        first = customer_snapshot()
        second = deepcopy(first)
        second["itens"][0]["total"] = 99
        index = CustomerDirectory([first, second])
        self.assertIn("17", index.conflicted_ids)
        self.assertIsNone(index.latest_by_cpf(CPF))
        self.assertIsNone(index.order_by_id("8"))

    def test_same_order_id_with_two_owners_never_shares_items(self):
        index = CustomerDirectory([customer_snapshot(), customer_snapshot(id=18)])
        self.assertIn("8", index.conflicted_orders)
        self.assertIsNone(index.order_by_id("8"))
        self.assertIsNone(index.latest_by_cpf(CPF))

    def test_partial_cpf_candidates_do_not_hide_customer_without_snapshot(self):
        index = CustomerDirectory([customer_snapshot(), customer(id=18)])
        self.assertIsNone(index.latest_by_cpf(CPF))
        self.assertEqual(len(index.candidates(CPF)), 2)

    def test_snapshots_are_independent_copies_and_discard_unneeded_fields(self):
        payload = customer_snapshot()
        payload["ultimoPedido"]["obs"] = "NAO-PUBLICAR"
        index = CustomerDirectory([payload])
        first = index.latest_by_cpf(CPF)
        first[0]["itens"][0]["descricao"] = "alterado"
        self.assertNotEqual(index.order_by_id("8")["itens"][0]["descricao"], "alterado")
        self.assertNotIn("obs", index.order_by_id("8")["capa"])
        self.assertNotIn("rg", index.candidates(CPF)[0])


class LastOrderAddressTests(unittest.TestCase):
    def person(self, payload=None):
        return CustomerDirectory([payload or customer_snapshot()]).by_id["17"]

    def test_matches_formatting_accents_state_name_and_street_abbreviation(self):
        payload = customer_snapshot()
        payload["ultimoPedido"].update(
            logradouro="R. SINTETICA", cidade="Belém", uf="Pará", cep="66023-170"
        )
        self.assertEqual(
            matching_order_address(self.person(payload))[0], "ENDERECO_CONFIRMADO"
        )

    def test_uses_matching_secondary_address_instead_of_unrelated_principal(self):
        payload = customer_snapshot()
        secondary = deepcopy(payload["cliente"]["enderecos"][0])
        secondary.update(id=5, principal=0)
        payload["cliente"]["enderecos"][0].update(
            cidade="Ananindeua", cep="67000001", logradouro="Outra rua"
        )
        payload["cliente"]["enderecos"].append(secondary)
        person = self.person(payload)
        status, address = matching_order_address(person)
        self.assertEqual((status, address["id"]), ("ENDERECO_CONFIRMADO", 5))
        self.assertEqual(enrichment({}, person, date(2026, 10, 21))["cidade"], "Belém")

    def test_same_cep_cannot_hide_other_street_number_or_apartment(self):
        for field, value in (
            ("logradouro", "Outra rua"),
            ("numero", "999"),
            ("complemento", "Apto 2"),
        ):
            with self.subTest(field=field):
                payload = customer_snapshot()
                payload["ultimoPedido"][field] = value
                person = self.person(payload)
                self.assertEqual(
                    matching_order_address(person)[0], "ENDERECO_DIVERGENTE"
                )
                self.assertFalse(
                    set(enrichment({}, person, date(2026, 10, 21)))
                    & {"cidade", "estado", "bairro", "cep"}
                )

    def test_missing_or_ambiguous_addresses_do_not_fill_location(self):
        for change, expected in (
            ("missing_order", "SEM_ULTIMO_PEDIDO"),
            ("missing_field", "ENDERECO_PEDIDO_INCOMPLETO"),
            ("customer_incomplete", "ENDERECO_CADASTRAL_INCOMPLETO"),
            ("duplicate", "ENDERECO_AMBIGUO"),
        ):
            with self.subTest(change=change):
                payload = customer_snapshot()
                if change == "missing_order":
                    payload.pop("ultimoPedido")
                elif change == "missing_field":
                    payload["ultimoPedido"].pop("numero")
                elif change == "customer_incomplete":
                    payload["cliente"]["enderecos"][0]["logradouro"] = None
                else:
                    payload["cliente"]["enderecos"].append(
                        deepcopy(payload["cliente"]["enderecos"][0])
                    )
                person = self.person(payload)
                self.assertEqual(matching_order_address(person)[0], expected)
                self.assertNotIn("cidade", enrichment({}, person, date(2026, 10, 21)))

    def test_another_customer_order_or_foreign_address_does_not_validate_address(self):
        for part in ("order", "address"):
            with self.subTest(part=part):
                payload = customer_snapshot()
                if part == "order":
                    payload["ultimoPedido"]["codCliente"] = 99
                else:
                    payload["cliente"]["enderecos"][0]["clienteId"] = 99
                self.assertNotEqual(
                    matching_order_address(self.person(payload))[0],
                    "ENDERECO_CONFIRMADO",
                )


class BulkOrderFlowTests(unittest.TestCase):
    def setUp(self):
        settings = patch(
            "secrets_config.FARMALIDER_CUSTOMER_DIRECTORY_MODE", "on", create=True
        )
        settings.start()
        self.addCleanup(settings.stop)
        self.client = FarmaliderClient("token-sintetico")
        self.addCleanup(self.client.close)
        self.payload = customer_snapshot(id=101)
        self.payload["cliente"]["enderecos"][0]["clienteId"] = 101
        self.payload["ultimoPedido"]["id"] = 201
        self.payload["itens"][0]["codPedido"] = 201
        self.contact = contact()
        self.contact["fields"]["cpf"] = CPF
        self.contact["name"] = "😊"

    def test_analytics_two_contacts_need_only_one_bulk_request_and_keep_latest_provenance(
        self,
    ):
        second = deepcopy(self.contact)
        second["uuid"] = "10000000-0000-0000-0000-000000000002"
        contacts = [self.contact, second]
        rows = [normalize_contact(c, NOW) for c in contacts]
        responses, statuses = {}, {}
        with patch.object(
            self.client, "_request_json", return_value=[self.payload]
        ) as get:
            validate_contacts(
                rows,
                farm_client=self.client,
                farm_settings=FarmaliderSettings(True, "token-sintetico", False),
                sync_time=NOW,
                cliente_responses_by_cpf=responses,
                cliente_lookup_status_by_cpf=statuses,
            )
            orders, items, _ = build_orders(
                contacts,
                rows_by_uuid={r["contact_uuid"]: r for r in rows},
                farm_client=self.client,
                sync_time=NOW,
                cliente_responses_by_cpf=responses,
                cliente_lookup_status_by_cpf=statuses,
            )
            self.assertEqual(get.call_count, 1)
            self.assertTrue(get.call_args.args[0].endswith("/clientes/FARMA"))
            self.assertEqual(orders[0]["origem_pedido"], "FARMALIDER_CLIENTES_FARMA")
            self.assertEqual((len(orders), len(items)), (1, 1))
            self.assertIn("ultimoPedido", responses[CPF][0])
            self.assertGreater(
                self.client.metrics_snapshot()["customer_directory_order_hits"], 0
            )

    def test_invalid_shared_cpf_is_selected_per_person_without_borrowing_orders(self):
        self.payload["cliente"]["cpf"] = 123
        self.contact["fields"]["cpf"] = "123"
        self.contact["fields"]["nome"] = "Pessoa"
        other = deepcopy(self.payload)
        other["cliente"].update(id=102, nome="Outra Pessoa", celular=91999999999)
        other["ultimoPedido"].update(id=202, codCliente=102)
        other["itens"][0]["codPedido"] = 202
        with patch.object(
            self.client, "_request_json", return_value=[self.payload, other]
        ) as get:
            plans = build_plans(
                [self.contact],
                self.client,
                STRUCTURE,
                {"contacts": {}},
                now=datetime.fromisoformat(NOW),
            )
            self.assertEqual(plans[0]["order_id"], "201")
            self.assertEqual(plans[0]["action"], "add")
            self.assertEqual(get.call_count, 1)

    def test_analytics_preserves_already_observed_latest_order_older_than_twenty_days(
        self,
    ):
        self.payload["ultimoPedido"]["emissao"] = "2026-08-01T10:00:00"
        rows = [normalize_contact(self.contact, NOW)]
        responses, statuses = {}, {}
        with patch.object(
            self.client, "_request_json", return_value=[self.payload]
        ) as get:
            validate_contacts(
                rows,
                farm_client=self.client,
                farm_settings=FarmaliderSettings(True, "token-sintetico", False),
                sync_time=NOW,
                cliente_responses_by_cpf=responses,
                cliente_lookup_status_by_cpf=statuses,
            )
            args = dict(
                rows_by_uuid={r["contact_uuid"]: r for r in rows},
                farm_client=self.client,
                sync_time=NOW,
                cliente_responses_by_cpf=responses,
                cliente_lookup_status_by_cpf=statuses,
            )
            prior, _, _ = build_orders([self.contact], **args)
            preserved, items, _ = build_orders(
                [self.contact], existing_orders=prior, **args
            )
            self.assertTrue(prior)
            self.assertEqual((preserved, items), ([], []))
            self.assertEqual(get.call_count, 1)

    def test_weni_and_planilhas_keep_address_evidence_with_one_bulk_request(self):
        with patch.object(
            self.client, "_request_json", return_value=[self.payload]
        ) as get:
            self.client.prepare_customer_directory(expected_contacts=500)
            plan = ContactUpdatePlan(contact_uuid=self.contact["uuid"])
            available = {
                "genero",
                "idade",
                "maior_de_18_anos",
                "cidade",
                "estado",
                "bairro",
                "cep",
            }
            _apply_customer_enrichment(plan, self.contact, self.client, NOW, available)
            audit_plans([plan], opt_out_group_available=True)
            self.assertEqual(plan.fields["cidade"], "Belém")
            plans, data = reconcile_tickets(
                selection(),
                [self.contact],
                self.client,
                captured_at=NOW,
                available_fields=available | REQUIRED_ORDER_FIELDS,
            )
            self.assertTrue(plans)
            self.assertEqual(data["orders"][0]["pedido_id"], "201")
            self.assertEqual(get.call_count, 1)

    def test_recompra_apply_fetches_new_bulk_and_blocks_order_changed_after_review(
        self,
    ):
        now = datetime.fromisoformat(NOW)
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(
                self.client,
                "_request_json",
                side_effect=lambda *a, **k: [deepcopy(self.payload)],
            ) as get,
        ):
            path = Path(folder) / "state.json"
            state = load_state(path)
            plans = build_plans([self.contact], self.client, STRUCTURE, state, now=now)
            self.assertEqual(plans[0]["action"], "add")
            review = make_review(plans, STRUCTURE, now=now, state=state)
            self.payload["ultimoPedido"]["id"] = 202
            self.payload["itens"][0]["codPedido"] = 202
            weni = Mock()
            weni.get_contact.return_value = self.contact
            with patch("recompra.inspect_structure", return_value=STRUCTURE):
                result = apply_review(
                    review,
                    weni,
                    self.client,
                    state_path=path,
                    audit_path=Path(folder) / "audit.jsonl",
                    now_fn=lambda: now,
                )
            self.assertEqual(result["conflitos"], 1)
            self.assertEqual(get.call_count, 2)
            weni.contact_group_action.assert_not_called()
            weni.update_contact_fields.assert_not_called()

    def test_empty_items_and_cancellation_stay_excluded_from_recompra(self):
        for kind in ("empty", "cancelled", "pet"):
            with self.subTest(kind=kind):
                self.client.reset_execution_reads()
                payload = deepcopy(self.payload)
                if kind == "empty":
                    payload["itens"] = []
                elif kind == "cancelled":
                    payload["ultimoPedido"]["status"] = 3
                else:
                    payload["itens"][0]["descricao"] = "Ração para cães"
                with patch.object(
                    self.client, "_request_json", return_value=[payload]
                ) as get:
                    plans = build_plans(
                        [self.contact],
                        self.client,
                        STRUCTURE,
                        {"contacts": {}},
                        now=datetime.fromisoformat(NOW),
                    )
                    self.assertNotEqual(plans[0]["action"], "add")
                    self.assertEqual(get.call_count, 1)

    def test_incomplete_bulk_reuses_complete_individual_cpf_order(self):
        incomplete = deepcopy(self.payload)
        incomplete.pop("itens")
        with patch.object(
            self.client,
            "_request_json",
            side_effect=[
                [incomplete],
                self.payload,
                {"capa": self.payload["ultimoPedido"], "itens": self.payload["itens"]},
            ],
        ) as get:
            plans = build_plans(
                [self.contact],
                self.client,
                STRUCTURE,
                {"contacts": {}},
                now=datetime.fromisoformat(NOW),
            )
            self.assertEqual(plans[0]["action"], "add")
            self.assertEqual(get.call_count, 2)
