"""O cadastro sem pedidos não altera as guardas nem confirma vendas sozinho."""

import tempfile
import unittest
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from analytics import normalize_contact
from delivery_tickets import reconcile_tickets
from farmalider_client import FarmaliderClient
from farmalider_customers import CustomerDirectory
from main import FarmaliderSettings, build_orders, validate_contacts
from recompra import apply_review, build_plans, load_state, make_review, resolve_latest
from tests.test_delivery_tickets import NOW, contact, farm, selection
from tests.test_farmalider_customers import CPF, customer
from tests.test_recompra import STRUCTURE
from weni_update import (
    REQUIRED_ORDER_FIELDS,
    ContactUpdatePlan,
    PlanAuditError,
    UpdateStats,
    _apply_customer_enrichment,
    _prepare_frozen_plan_for_apply,
    audit_plans,
    load_review_snapshot,
    write_review_snapshot,
)

AVAILABLE = REQUIRED_ORDER_FIELDS | {
    "genero",
    "idade",
    "maior_de_18_anos",
    "cep",
    "cidade",
    "estado",
    "bairro",
}


class CustomerDirectoryFlowTests(unittest.TestCase):
    def setUp(self):
        mode = patch(
            "secrets_config.FARMALIDER_CUSTOMER_DIRECTORY_MODE", "on", create=True
        )
        mode.start()
        self.addCleanup(mode.stop)
        self.client = FarmaliderClient("token-sintetico")
        self.addCleanup(self.client.close)
        self.contact = contact()
        self.contact["fields"]["cpf"] = CPF
        self.contact["name"] = "😊"
        self.api_customer = customer(id=101)
        self.api_customer["enderecos"][0]["clienteId"] = 101
        mock = farm()
        self.full_payload = deepcopy(mock.get_cliente_by_cpf.return_value)
        self.full_payload["cliente"] = deepcopy(self.api_customer)
        self.full_payload["segmento"] = "FARMA"
        self.full_payload["ultimoPedido"].update(
            {
                key: self.api_customer["enderecos"][0].get(key)
                for key in (
                    "cep",
                    "uf",
                    "cidade",
                    "bairro",
                    "logradouro",
                    "numero",
                    "complemento",
                )
            }
        )
        self.pedido = {
            "capa": self.full_payload["ultimoPedido"],
            "itens": self.full_payload["itens"],
        }

    def response(self, path, **kwargs):
        if path.endswith("/clientes/FARMA"):
            return [deepcopy(self.api_customer)]
        if "/cliente/cpf/" in path:
            return deepcopy(self.full_payload)
        if "/pedido/" in path:
            return deepcopy(self.pedido)
        raise AssertionError("Consulta inesperada")

    def metadata_plan(self):
        self.client.customer_directory = CustomerDirectory(
            [{**self.full_payload, "cliente": self.api_customer}]
        )
        plan = ContactUpdatePlan(contact_uuid=self.contact["uuid"])
        _apply_customer_enrichment(plan, self.contact, self.client, NOW, AVAILABLE)
        return plan

    def audit(self, plan):
        audit_plans([plan], opt_out_group_available=True)

    def prepare(self, plan, current):
        return _prepare_frozen_plan_for_apply(
            plan,
            current,
            opt_in_group_name="",
            opt_in_group_uuid="",
            opt_out_group_name="",
            opt_out_group_uuid="",
        )

    def test_weni_metadata_has_reproducible_source_without_purchase_or_consent_changes(
        self,
    ):
        plan = self.metadata_plan()
        self.assertEqual(plan.fields["genero"], "Feminino")
        self.assertEqual(plan.fields["idade"], "36")
        self.assertEqual(plan.fields["cidade"], "Belém")
        self.assertFalse(plan.group_actions)
        self.assertFalse(
            set(plan.fields)
            & {"cpf", "nome", "email", "telefone", "opt_in_lgpd", "pedido_data"}
        )
        self.audit(plan)
        self.assertNotIn("rg", plan.guards["__farmalider_cadastro"]["customer"])

    def test_unavailable_weni_fields_are_not_created_or_proposed(self):
        self.client.customer_directory = CustomerDirectory([self.api_customer])
        plan = ContactUpdatePlan(contact_uuid=self.contact["uuid"])
        _apply_customer_enrichment(
            plan, self.contact, self.client, NOW, REQUIRED_ORDER_FIELDS
        )
        self.assertEqual(plan.fields, {})

    def test_wrong_or_missing_source_blocks_api_metadata_write(self):
        for change in ("remove", "gender", "customer", "contact"):
            with self.subTest(change=change):
                plan = self.metadata_plan()
                if change == "remove":
                    del plan.guards["__farmalider_cadastro"]
                elif change == "gender":
                    plan.fields["genero"] = "Masculino"
                elif change == "customer":
                    plan.guards["__farmalider_cadastro"]["customer"]["cpf"] = "123"
                else:
                    plan.guards["__farmalider_cadastro"]["contact"]["uuid"] = (
                        "outra-pessoa"
                    )
                with self.assertRaises(PlanAuditError):
                    self.audit(plan)

    def test_changed_cpf_conflicts_before_apply(self):
        for key in ("cpf",):
            with self.subTest(key=key):
                plan = self.metadata_plan()
                current = deepcopy(self.contact)
                current["fields"][key] = "dado posterior"
                prepared, reason = self.prepare(plan, current)
                self.assertIsNone(prepared)
                self.assertTrue(reason)

    def test_valid_cpf_does_not_gain_a_name_or_phone_requirement(self):
        plan = self.metadata_plan()
        current = deepcopy(self.contact)
        current["fields"]["nome"] = "Outro nome do canal"
        current["name"] = "👍"
        current["urns"] = ["tel:+5585999999999"]
        prepared, reason = self.prepare(plan, current)
        self.assertEqual(reason, "")
        self.audit(prepared)

    def test_invalid_cpf_identity_changes_remain_guarded(self):
        self.contact["fields"]["cpf"] = "123"
        self.api_customer["cpf"] = 123
        plan = self.metadata_plan()
        current = deepcopy(self.contact)
        current["fields"]["nome"] = "Outro nome"
        prepared, reason = self.prepare(plan, current)
        self.assertIsNone(prepared)
        self.assertTrue(reason)

    def test_partial_metadata_apply_resumes_without_repeating_fields(self):
        plan = self.metadata_plan()
        current = deepcopy(self.contact)
        current["fields"]["genero"] = plan.fields["genero"]
        prepared, reason = self.prepare(plan, current)
        self.assertEqual(reason, "")
        self.assertNotIn("genero", prepared.fields)
        self.audit(prepared)

    def test_source_survives_frozen_review_hash_roundtrip(self):
        plan = self.metadata_plan()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "revisao.json"
            write_review_snapshot(
                [plan], UpdateStats(), full=True, json_path=path, captured_at_utc=NOW
            )
            plans, _, _ = load_review_snapshot(full=True, json_path=path)
            self.audit(plans[0])
            self.assertEqual(plans[0].guards, plan.guards)

    def test_analytics_uses_directory_for_identity_but_live_cpf_for_latest_purchase(
        self,
    ):
        second = deepcopy(self.contact)
        second["uuid"] = "10000000-0000-0000-0000-000000000002"
        contacts = [self.contact, second]
        rows = [normalize_contact(c, NOW) for c in contacts]
        responses, statuses = {}, {}
        with patch.object(
            self.client, "_request_json", side_effect=self.response
        ) as get:
            stats = validate_contacts(
                rows,
                farm_client=self.client,
                farm_settings=FarmaliderSettings(True, "token-sintetico", False),
                sync_time=NOW,
                cliente_responses_by_cpf=responses,
                cliente_lookup_status_by_cpf=statuses,
            )
            self.assertEqual(get.call_count, 1)
            self.assertEqual(responses, {})
            self.assertEqual(stats.confirmed, 2)
            self.assertEqual(rows[0]["genero"], "Feminino")
            orders, items, _ = build_orders(
                contacts,
                rows_by_uuid={r["contact_uuid"]: r for r in rows},
                farm_client=self.client,
                sync_time=NOW,
                cliente_responses_by_cpf=responses,
                cliente_lookup_status_by_cpf=statuses,
            )
            self.assertEqual(len(orders), 1)
            self.assertEqual(len(items), 1)
            self.assertEqual(orders[0]["pedido_id"], "201")
            paths = [c.args[0] for c in get.call_args_list]
            self.assertEqual(sum("/cliente/cpf/" in p for p in paths), 1)
            self.assertEqual(sum("/pedido/" in p for p in paths), 0)

    def test_recompra_cannot_treat_cadastral_record_as_missing_order(self):
        with patch.object(
            self.client, "_request_json", side_effect=self.response
        ) as get:
            self.client.prepare_customer_directory(expected_contacts=500)
            self.client.get_cliente_cadastro_by_cpf(CPF)
            order, items = resolve_latest(self.contact, self.client, NOW)
            self.assertEqual(order["status_confirmacao"], "CONFIRMADO_API")
            self.assertEqual(order["pedido_id"], "201")
            self.assertTrue(items)
            self.assertEqual(get.call_count, 2)

    def test_planilhas_share_reads_and_preserve_customer_evidence(self):
        with patch.object(self.client, "_request_json", side_effect=self.response):
            plans, data = reconcile_tickets(
                selection(),
                [self.contact],
                self.client,
                captured_at=NOW,
                available_fields=AVAILABLE,
            )
        self.assertEqual(plans[0].fields["genero"], "Feminino")
        self.assertEqual(data["orders"][0]["pedido_id"], "201")
        self.audit(plans[0])

    def test_missing_directory_customer_is_not_a_missing_order(self):
        self.client.customer_directory = CustomerDirectory([])
        with patch.object(self.client, "_request_json", side_effect=self.response):
            order, _ = resolve_latest(self.contact, self.client, NOW)
        self.assertEqual(order["pedido_id"], "201")

    def test_recompra_apply_rechecks_new_order_instead_of_using_dry_run_cache(self):
        self.full_payload["ultimoPedido"]["emissao"] = "2026-10-07T10:00:00"
        self.pedido["capa"]["emissao"] = "2026-10-07T10:00:00"
        now = datetime.fromisoformat(NOW)
        from unittest.mock import Mock

        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(
                self.client, "_request_json", side_effect=self.response
            ) as get,
        ):
            path = Path(folder) / "state.json"
            state = load_state(path)
            plans = build_plans([self.contact], self.client, STRUCTURE, state, now=now)
            self.assertEqual(plans[0]["action"], "add")
            review = make_review(plans, STRUCTURE, now=now, state=state)
            self.full_payload["ultimoPedido"]["id"] = 202
            self.full_payload["itens"][0]["codPedido"] = 202
            self.pedido = {
                "capa": self.full_payload["ultimoPedido"],
                "itens": self.full_payload["itens"],
            }
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
            weni.contact_group_action.assert_not_called()
            weni.update_contact_fields.assert_not_called()
            paths = [call.args[0] for call in get.call_args_list]
            self.assertEqual(sum("/clientes/FARMA" in p for p in paths), 2)
            self.assertEqual(sum("/cliente/cpf/" in p for p in paths), 2)

    def test_cadastral_date_is_never_used_as_purchase_date(self):
        self.api_customer["cadastro"] = "2026-10-08T10:00:00"
        self.full_payload["ultimoPedido"] = None
        self.client.customer_directory = CustomerDirectory([self.api_customer])
        with patch.object(
            self.client, "_request_json", return_value=self.full_payload
        ) as get:
            order, items = resolve_latest(self.contact, self.client, NOW)
        self.assertIsNone(order)
        self.assertEqual(items, [])
        get.assert_called_once()
