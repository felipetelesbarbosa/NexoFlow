import json
import tempfile
import unittest
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from weni_update import (
    ContactUpdatePlan,
    GroupAction,
    PlanAuditError,
    _build_contact_plan,
    _load_state,
    _resolve_required_groups,
    _save_state,
    audit_plans,
    UpdateStats,
    UpdateWindow,
    run_update,
    load_review_snapshot,
    verify_review_snapshot,
    write_review_snapshot,
)


class WeniUpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        # Testes unitários nunca devem consumir o checkpoint/estado operacional
        # real de C:\NexoFlow\logs. Cada teste de run_update começa sem
        # conflitos pendentes herdados de uma execução anterior.
        self._load_state_patcher = patch(
            "weni_update._load_state",
            side_effect=lambda *args, **kwargs: {},
        )
        self._load_state_patcher.start()
        self.addCleanup(self._load_state_patcher.stop)

    def _purchase_contact(self, *, include_raw: bool = True) -> dict:
        fields = {"cpf": "52998224725"}
        if include_raw:
            fields["ultimo_pedido"] = json.dumps({
                "pedido_id": "123",
                "data_hora": "2026-10-03T12:00:00Z",
                "valor_total_compra": 25.5,
                "produtos": [
                    {"nome": "Produto A", "quantidade": 2,
                     "valor_unitario": 10.0, "valor_total": 20.0},
                    {"nome": "Produto B", "quantidade": 1,
                     "valor_unitario": 5.5, "valor_total": 5.5},
                ],
            })
        else:
            fields["pedido_id"] = "123"
        return {"uuid": "u-pedido", "fields": fields}

    def _purchase_api(self) -> Mock:
        farm = Mock()
        farm.get_cliente_by_cpf.return_value = {
            "id": "99", "cpf": "52998224725", "nome": "Cliente Teste",
            "ultimoPedido": {"id": "123", "codCliente": "99"},
        }
        farm.get_pedido.return_value = {
            "capa": {
                "id": "123", "codCliente": "99",
                "emissao": "2026-10-03T12:00:00Z",
                "status": 2, "cancelamento": "", "frete": 0,
            },
            "itens": [
                {"codPedido": "123", "codProduto": "A1", "nome": "Produto A",
                 "quantidade": 2, "valor": 10.0, "total": 20.0},
                {"codPedido": "123", "codProduto": "B1", "nome": "Produto B",
                 "quantidade": 1, "valor": 5.5, "total": 5.5},
            ],
        }
        return farm

    def _purchase_plan(self, contact: dict, farm: Mock | None = None,
                       *, captured_at: str = "2026-10-03T12:01:00Z") -> ContactUpdatePlan:
        return _build_contact_plan(
            contact,
            context_messages=[],
            candidate_message_ids=set(),
            farm_client=farm,
            opt_out_group_name="Opt-Out LGPD",
            opt_out_group_uuid="g-out",
            captured_at=captured_at,
        )

    def _incremental_purchase_client(self, contact: dict) -> Mock:
        client = Mock()
        client.list_fields.return_value = [
            {"key": "contact_urn_whatsapp"},
            {"key": "contact_urn_instagram"},
            {"key": "contact_urn_facebook"},
            {"key": "contact_canal_principal"},
        ]
        client.list_groups.return_value = [
            {"uuid": "g-in", "name": "Opt-In LGPD"},
            {"uuid": "g-out", "name": "Opt-Out LGPD"},
        ]
        client.list_contacts.return_value = [contact]
        client.list_messages.return_value = []
        return client

    def test_required_groups_are_resolved_with_one_api_listing(self) -> None:
        client = Mock()
        client.list_groups.return_value = [
            {"uuid": "g-in", "name": "Opt-In LGPD"},
            {"uuid": "g-out", "name": "Opt-Out LGPD"},
        ]
        result = _resolve_required_groups(
            client,
            ("Opt-In LGPD", "Opt-Out LGPD"),
        )
        self.assertEqual(result["Opt-In LGPD"], (True, "g-in"))
        self.assertEqual(result["Opt-Out LGPD"], (True, "g-out"))
        client.list_groups.assert_called_once_with()

    def test_audit_accepts_safe_age_plan(self) -> None:
        plan = ContactUpdatePlan(
            contact_uuid="u1",
            fields={"idade": 27, "maior_de_18_anos": "sim"},
        )
        audit_plans([plan], opt_out_group_available=True)

    def test_audit_rejects_inconsistent_age(self) -> None:
        plan = ContactUpdatePlan(
            contact_uuid="u1",
            fields={"idade": 17, "maior_de_18_anos": "sim"},
        )
        with self.assertRaises(PlanAuditError):
            audit_plans([plan], opt_out_group_available=True)

    def test_audit_rejects_purchase_without_confirmation(self) -> None:
        plan = ContactUpdatePlan(
            contact_uuid="u1",
            fields={"ultima_compra": "2026-10-03 12:00:00"},
            purchase_confirmed=False,
        )
        with self.assertRaises(PlanAuditError):
            audit_plans([plan], opt_out_group_available=True)

    def test_audit_rejects_malformed_fields_even_for_a_validated_order(self) -> None:
        malformed_fields = (
            {"pedido_data": "data inválida"},
            {"pedido_valor": -1},
            {"pedido_valor": float("nan")},
            {"pedido_valor": float("inf")},
            {"pedido_quantidade_itens": 0},
            {"pedido_quantidade_itens": -1},
            {"pedido_produtos": "Produto A x2"},
            {"pedido_produtos": json.dumps({"produtos": []})},
        )
        for fields in malformed_fields:
            with self.subTest(fields=fields):
                plan = ContactUpdatePlan(
                    contact_uuid="u-pedido", fields=fields, order_validated=True,
                )
                with self.assertRaises(PlanAuditError):
                    audit_plans([plan], opt_out_group_available=True)

    def test_audit_requires_optout_group_when_group_action_exists(self) -> None:
        plan = ContactUpdatePlan(
            contact_uuid="u1",
            fields={"opt_in_lgpd": "recusado"},
            group_actions=[
                GroupAction(
                    "add",
                    "Opt-Out LGPD",
                    "teste",
                    group_name="Opt-Out LGPD",
                )
            ],
        )
        with self.assertRaises(PlanAuditError):
            audit_plans(
                [plan],
                opt_out_group_available=False,
                opt_in_group_available=True,
            )

    def test_audit_requires_optin_group_when_group_action_exists(self) -> None:
        plan = ContactUpdatePlan(
            contact_uuid="u1",
            fields={"opt_in_lgpd": "ativo"},
            group_actions=[
                GroupAction(
                    "add",
                    "Opt-In LGPD",
                    "teste",
                    group_name="Opt-In LGPD",
                )
            ],
        )
        with self.assertRaisesRegex(PlanAuditError, "Opt-In LGPD"):
            audit_plans(
                [plan],
                opt_out_group_available=True,
                opt_in_group_available=False,
            )

    def test_build_plan_adds_refused_contact_to_optout(self) -> None:
        contact = {
            "uuid": "u1",
            "urns": ["whatsapp:5591999999999"],
            "groups": [],
            "fields": {},
        }
        messages = [
            {
                "id": "q1",
                "created_on": "2026-10-03T12:00:00Z",
                "direction": "out",
                "text": "Você aceita o tratamento de dados conforme a LGPD?",
            },
            {
                "id": "a1",
                "created_on": "2026-10-03T12:00:01Z",
                "direction": "in",
                "text": "Não",
            },
        ]
        plan = _build_contact_plan(
            contact,
            context_messages=messages,
            candidate_message_ids={"a1"},
            farm_client=None,
            opt_out_group_name="Opt-Out LGPD",
            opt_out_group_uuid="g-out",
            captured_at="2026-10-03T12:01:00Z",
            opt_in_group_name="Opt-In LGPD",
            opt_in_group_uuid="g-in",
        )
        self.assertEqual(plan.fields["opt_in_lgpd"], "recusado")
        self.assertEqual(plan.fields["contact_urn"], "whatsapp:5591999999999")
        actions = {(a.action, a.group_name, a.group) for a in plan.group_actions}
        self.assertEqual(actions, {("add", "Opt-Out LGPD", "g-out")})
        self.assertEqual(plan.fields["contact_urn_whatsapp"], "whatsapp:5591999999999")
        self.assertEqual(plan.fields["contact_canal_principal"], "whatsapp")

    def test_build_plan_multichannel_writes_specific_urns_and_principal(self) -> None:
        contact = {
            "uuid": "u-multi",
            "urns": ["instagram:222", "facebook:333", "whatsapp:111"],
            "groups": [],
            "fields": {},
        }
        plan = _build_contact_plan(
            contact,
            context_messages=[],
            candidate_message_ids=set(),
            farm_client=None,
            opt_out_group_name="Opt-Out LGPD",
            opt_out_group_uuid="g-out",
            captured_at="2026-10-03T12:01:00Z",
            opt_in_group_name="Opt-In LGPD",
            opt_in_group_uuid="g-in",
        )
        self.assertEqual(plan.fields["contact_urn"], "whatsapp:111")
        self.assertEqual(plan.fields["contact_urn_whatsapp"], "whatsapp:111")
        self.assertEqual(plan.fields["contact_urn_instagram"], "instagram:222")
        self.assertEqual(plan.fields["contact_urn_facebook"], "facebook:333")
        self.assertEqual(plan.fields["contact_canal_principal"], "whatsapp")
        self.assertEqual(plan.contact_channel, "whatsapp")

    def test_build_plan_instagram_only_does_not_invent_whatsapp(self) -> None:
        contact = {
            "uuid": "u-instagram",
            "urns": ["instagram:999"],
            "groups": [],
            "fields": {},
        }
        plan = _build_contact_plan(
            contact,
            context_messages=[],
            candidate_message_ids=set(),
            farm_client=None,
            opt_out_group_name="Opt-Out LGPD",
            opt_out_group_uuid="g-out",
            captured_at="2026-10-03T12:01:00Z",
            opt_in_group_name="Opt-In LGPD",
            opt_in_group_uuid="g-in",
        )
        self.assertEqual(plan.fields["contact_urn"], "instagram:999")
        self.assertEqual(plan.fields["contact_urn_instagram"], "instagram:999")
        self.assertEqual(plan.fields["contact_canal_principal"], "instagram")
        self.assertNotIn("contact_urn_whatsapp", plan.fields)
        self.assertNotIn("contact_urn_facebook", plan.fields)

    def test_build_plan_facebook_messenger_is_classified_as_facebook(self) -> None:
        contact = {
            "uuid": "u-facebook",
            "urns": ["messenger:abc"],
            "groups": [],
            "fields": {},
        }
        plan = _build_contact_plan(
            contact,
            context_messages=[],
            candidate_message_ids=set(),
            farm_client=None,
            opt_out_group_name="Opt-Out LGPD",
            opt_out_group_uuid="g-out",
            captured_at="2026-10-03T12:01:00Z",
            opt_in_group_name="Opt-In LGPD",
            opt_in_group_uuid="g-in",
        )
        self.assertEqual(plan.fields["contact_urn"], "messenger:abc")
        self.assertEqual(plan.fields["contact_urn_facebook"], "messenger:abc")
        self.assertEqual(plan.fields["contact_canal_principal"], "facebook")

    def test_audit_rejects_wrong_channel_specific_urn(self) -> None:
        plan = ContactUpdatePlan(
            contact_uuid="u-bad-channel",
            fields={"contact_urn_instagram": "whatsapp:5591999999999"},
        )
        with self.assertRaisesRegex(PlanAuditError, "contact_urn_instagram"):
            audit_plans([plan], opt_out_group_available=True, opt_in_group_available=True)

    def test_build_plan_active_syncs_optin_and_optout(self) -> None:
        contact = {
            "uuid": "u1",
            "groups": [{"uuid": "g-out", "name": "Opt-Out LGPD"}],
            "fields": {"opt_in_lgpd": "ativo"},
        }
        plan = _build_contact_plan(
            contact,
            context_messages=[],
            candidate_message_ids=set(),
            farm_client=None,
            opt_out_group_name="Opt-Out LGPD",
            opt_out_group_uuid="g-out",
            captured_at="2026-10-03T12:01:00Z",
            opt_in_group_name="Opt-In LGPD",
            opt_in_group_uuid="g-in",
        )
        actions = {(a.action, a.group_name, a.group) for a in plan.group_actions}
        self.assertEqual(
            actions,
            {
                ("add", "Opt-In LGPD", "g-in"),
                ("remove", "Opt-Out LGPD", "g-out"),
            },
        )
        self.assertEqual(plan.group_actions[0].action, "add")
        self.assertEqual(plan.group_actions[0].group_name, "Opt-In LGPD")

    def test_build_plan_refused_syncs_optout_and_optin(self) -> None:
        contact = {
            "uuid": "u1",
            "groups": [{"uuid": "g-in", "name": "Opt-In LGPD"}],
            "fields": {"opt_in_lgpd": "recusado"},
        }
        plan = _build_contact_plan(
            contact,
            context_messages=[],
            candidate_message_ids=set(),
            farm_client=None,
            opt_out_group_name="Opt-Out LGPD",
            opt_out_group_uuid="g-out",
            captured_at="2026-10-03T12:01:00Z",
            opt_in_group_name="Opt-In LGPD",
            opt_in_group_uuid="g-in",
        )
        actions = {(a.action, a.group_name, a.group) for a in plan.group_actions}
        self.assertEqual(
            actions,
            {
                ("remove", "Opt-In LGPD", "g-in"),
                ("add", "Opt-Out LGPD", "g-out"),
            },
        )
        self.assertEqual(plan.group_actions[0].action, "add")
        self.assertEqual(plan.group_actions[0].group_name, "Opt-Out LGPD")

    def test_build_plan_consistent_lgpd_groups_need_no_action(self) -> None:
        for value, group_uuid, group_name in (
            ("ativo", "g-in", "Opt-In LGPD"),
            ("recusado", "g-out", "Opt-Out LGPD"),
        ):
            with self.subTest(value=value):
                contact = {
                    "uuid": "u1",
                    "groups": [{"uuid": group_uuid, "name": group_name}],
                    "fields": {"opt_in_lgpd": value},
                }
                plan = _build_contact_plan(
                    contact,
                    context_messages=[],
                    candidate_message_ids=set(),
                    farm_client=None,
                    opt_out_group_name="Opt-Out LGPD",
                    opt_out_group_uuid="g-out",
                    captured_at="2026-10-03T12:01:00Z",
                    opt_in_group_name="Opt-In LGPD",
                    opt_in_group_uuid="g-in",
                )
                self.assertEqual(plan.group_actions, [])

    def test_build_plan_updates_blank_cpf_from_explicit_message(self) -> None:
        contact = {
            "uuid": "u1",
            "fields": {"cpf": ""},
        }
        messages = [
            {
                "id": "m1",
                "created_on": "2026-10-03T12:00:00Z",
                "direction": "in",
                "text": "Meu CPF é 529.982.247-25",
            }
        ]
        plan = _build_contact_plan(
            contact,
            context_messages=messages,
            candidate_message_ids={"m1"},
            farm_client=None,
            opt_out_group_name="Opt-Out LGPD",
            opt_out_group_uuid="g1",
            captured_at="2026-10-03T12:01:00Z",
        )
        self.assertEqual(plan.fields["cpf"], "52998224725")
        self.assertEqual(plan.previous["cpf"], "")
        self.assertEqual(plan.evidence["cpf"]["message_id"], "m1")
        audit_plans([plan], opt_out_group_available=True)

    def test_build_plan_replaces_old_cpf_with_most_recent_customer_cpf(self) -> None:
        contact = {
            "uuid": "u1",
            "fields": {"cpf": "52998224725"},
        }
        messages = [
            {
                "id": "m2",
                "created_on": "2026-10-03T12:10:00Z",
                "direction": "in",
                "text": "Meu CPF correto é 168.995.350-09",
            }
        ]
        plan = _build_contact_plan(
            contact,
            context_messages=messages,
            candidate_message_ids={"m2"},
            farm_client=None,
            opt_out_group_name="Opt-Out LGPD",
            opt_out_group_uuid="g1",
            captured_at="2026-10-03T12:11:00Z",
        )
        self.assertEqual(plan.previous["cpf"], "52998224725")
        self.assertEqual(plan.fields["cpf"], "16899535009")
        audit_plans([plan], opt_out_group_available=True)

    def test_same_cpf_with_different_format_is_not_rewritten(self) -> None:
        contact = {
            "uuid": "u1",
            "fields": {"cpf": "529.982.247-25"},
        }
        messages = [
            {
                "id": "m1",
                "created_on": "2026-10-03T12:00:00Z",
                "direction": "in",
                "text": "CPF: 52998224725",
            }
        ]
        plan = _build_contact_plan(
            contact,
            context_messages=messages,
            candidate_message_ids={"m1"},
            farm_client=None,
            opt_out_group_name="Opt-Out LGPD",
            opt_out_group_uuid="g1",
            captured_at="2026-10-03T12:01:00Z",
        )
        self.assertNotIn("cpf", plan.fields)

    def test_audit_rejects_invalid_cpf(self) -> None:
        plan = ContactUpdatePlan(contact_uuid="u1", fields={"cpf": "11111111111"})
        with self.assertRaisesRegex(PlanAuditError, "CPF inválido"):
            audit_plans([plan], opt_out_group_available=True)

    def test_state_is_written_atomically_and_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            payload = {"last_success_utc": "2026-10-03T12:00:00Z"}
            _save_state(payload, path)
            self.assertEqual(_load_state(path), payload)

    def test_confirmed_purchase_populates_expected_fields(self) -> None:
        contact = self._purchase_contact()
        farm = self._purchase_api()
        plan = self._purchase_plan(contact, farm)
        self.assertTrue(plan.order_validated)
        self.assertTrue(plan.purchase_confirmed)
        self.assertEqual(plan.fields["pedido_id"], "123")
        self.assertEqual(plan.fields["pedido_valor"], 25.5)
        self.assertEqual(plan.fields["pedido_quantidade_itens"], 3)
        self.assertEqual(plan.fields["pedido_data"], "2026-10-03T09:00:00-03:00")
        self.assertEqual(plan.fields["ultima_compra"], "2026-10-03T09:00:00-03:00")
        products = json.loads(plan.fields["pedido_produtos"])
        self.assertIsInstance(products, dict)
        self.assertEqual(products["pedido_id"], "123")
        self.assertEqual(products["status_confirmacao"], "CONFIRMADO_API")
        self.assertEqual(products["farmalider_status_pedido"], "2")
        self.assertEqual(products["farmalider_status_pedido_nome"], "Concluído")
        self.assertEqual(float(products["valor_total_compra"]), 25.5)
        self.assertEqual(float(products["quantidade_itens"]), 3)
        self.assertEqual(len(products["produtos"]), 2)
        self.assertEqual(products["produtos"][0]["nome"], "Produto A")
        farm.get_cliente_by_cpf.assert_called_once_with("52998224725")
        farm.get_pedido.assert_called_once_with("123")
        audit_plans([plan], opt_out_group_available=True)

    def test_api_resolves_structured_order_without_raw_payload(self) -> None:
        contact = self._purchase_contact(include_raw=False)
        contact["fields"].pop("pedido_id")
        farm = self._purchase_api()
        plan = self._purchase_plan(contact, farm)
        final_fields = {**contact["fields"], **plan.fields}
        self.assertTrue(plan.order_validated)
        self.assertTrue(plan.purchase_confirmed)
        self.assertEqual(final_fields["pedido_id"], "123")
        self.assertEqual(final_fields["pedido_data"], "2026-10-03T09:00:00-03:00")
        self.assertEqual(final_fields["pedido_valor"], 25.5)
        self.assertEqual(final_fields["pedido_quantidade_itens"], 3)
        self.assertEqual(len(json.loads(final_fields["pedido_produtos"])["produtos"]), 2)
        self.assertEqual(final_fields["ultima_compra"], final_fields["pedido_data"])
        audit_plans([plan], opt_out_group_available=True)

    def test_cancelled_order_updates_five_fields_without_latest_purchase(self) -> None:
        contact = self._purchase_contact()
        contact["fields"]["ultima_compra"] = "2026-10-01T10:00:00-03:00"
        farm = self._purchase_api()
        farm.get_pedido.return_value["capa"]["cancelamento"] = "2026-10-03T13:00:00Z"
        plan = self._purchase_plan(contact, farm)
        self.assertTrue(plan.order_validated)
        self.assertFalse(plan.purchase_confirmed)
        self.assertEqual(set(plan.fields), {
            "pedido_id", "pedido_data", "pedido_produtos",
            "pedido_quantidade_itens", "pedido_valor",
        })
        self.assertNotIn("ultima_compra", plan.fields)
        self.assertEqual(contact["fields"]["ultima_compra"], "2026-10-01T10:00:00-03:00")
        products = json.loads(plan.fields["pedido_produtos"])
        self.assertEqual(products["status_confirmacao"], "CANCELADO_API")
        self.assertEqual(products["farmalider_cancelamento"], "2026-10-03T13:00:00Z")
        audit_plans([plan], opt_out_group_available=True)

    def test_only_completed_api_orders_advance_latest_purchase(self) -> None:
        statuses = (
            (0, "Em processamento"),
            (1, "Em trânsito"),
            (2, "Concluído"),
            (3, "Cancelado"),
            (4, "Pronto para rota"),
            (99, ""),
            ("CONFIRMADO", ""),
        )
        order_fields = {
            "pedido_id", "pedido_data", "pedido_produtos",
            "pedido_quantidade_itens", "pedido_valor",
        }
        for status, label in statuses:
            with self.subTest(status=status):
                contact = self._purchase_contact()
                contact["fields"]["ultima_compra"] = "2026-10-01T10:00:00-03:00"
                farm = self._purchase_api()
                farm.get_pedido.return_value["capa"]["status"] = status
                # State 3 alone must preserve cancellation; no timestamp exists.
                self.assertEqual(farm.get_pedido.return_value["capa"]["cancelamento"], "")
                plan = self._purchase_plan(contact, farm)
                self.assertTrue(plan.order_validated)
                self.assertEqual(plan.purchase_confirmed, status == 2)
                self.assertEqual(set(plan.fields), order_fields | ({"ultima_compra"} if status == 2 else set()))
                products = json.loads(plan.fields["pedido_produtos"])
                self.assertEqual(products["farmalider_status_pedido"], str(status))
                self.assertEqual(products["farmalider_status_pedido_nome"], label)
                self.assertEqual(products["status_confirmacao"], "CANCELADO_API" if status == 3 else "CONFIRMADO_API")
                if status == 2:
                    self.assertEqual(plan.fields["ultima_compra"], "2026-10-03T09:00:00-03:00")
                else:
                    self.assertNotIn("ultima_compra", plan.fields)
                audit_plans([plan], opt_out_group_available=True)

                applied_contact = deepcopy(contact)
                applied_contact["fields"].update(plan.fields)
                second = self._purchase_plan(
                    applied_contact, farm, captured_at="2026-10-03T13:01:00Z",
                )
                self.assertTrue(second.order_validated)
                self.assertEqual(second.purchase_confirmed, status == 2)
                self.assertEqual(second.fields, {})
                self.assertEqual(second.evidence, {})

    def test_complete_weni_order_without_api_remains_unconfirmed(self) -> None:
        contact = self._purchase_contact()
        plan = self._purchase_plan(contact)
        self.assertTrue(plan.order_validated)
        self.assertFalse(plan.purchase_confirmed)
        self.assertEqual(set(plan.fields), {
            "pedido_id", "pedido_data", "pedido_produtos",
            "pedido_quantidade_itens", "pedido_valor",
        })
        self.assertEqual(plan.fields["pedido_valor"], 25.5)
        self.assertEqual(plan.fields["pedido_quantidade_itens"], 3)
        self.assertNotIn("ultima_compra", plan.fields)
        products = json.loads(plan.fields["pedido_produtos"])
        self.assertEqual(products["status_confirmacao"], "NAO_CONFIRMADO_API")
        self.assertEqual(products["origem_pedido"], "WENI_ULTIMO_PEDIDO")
        audit_plans([plan], opt_out_group_available=True)

    def test_purchase_dates_use_belem_day_at_utc_midnight_boundary(self) -> None:
        contact = self._purchase_contact(include_raw=False)
        farm = self._purchase_api()
        farm.get_pedido.return_value["capa"]["emissao"] = "2026-10-04T01:30:00Z"
        plan = self._purchase_plan(contact, farm)
        self.assertEqual(plan.fields["pedido_data"], "2026-10-03T22:30:00-03:00")
        self.assertEqual(plan.fields["ultima_compra"], "2026-10-03T22:30:00-03:00")

    def test_api_identity_mismatches_do_not_produce_order_writes(self) -> None:
        for mismatch in ("cpf", "cliente", "codPedido"):
            with self.subTest(mismatch=mismatch):
                contact = self._purchase_contact(include_raw=False)
                farm = self._purchase_api()
                if mismatch == "cpf":
                    farm.get_cliente_by_cpf.return_value["cpf"] = "11144477735"
                elif mismatch == "cliente":
                    farm.get_pedido.return_value["capa"]["codCliente"] = "100"
                else:
                    farm.get_pedido.return_value["itens"][0]["codPedido"] = "999"
                plan = self._purchase_plan(contact, farm)
                self.assertFalse(plan.order_validated)
                self.assertFalse(plan.purchase_confirmed)
                self.assertFalse(set(plan.fields) & {
                    "pedido_id", "pedido_data", "pedido_produtos",
                    "pedido_quantidade_itens", "pedido_valor", "ultima_compra",
                })

    def test_purchase_plan_is_idempotent_after_applying_structured_fields(self) -> None:
        for api_available in (False, True):
            with self.subTest(api_available=api_available):
                contact = self._purchase_contact()
                farm = self._purchase_api() if api_available else None
                first = self._purchase_plan(contact, farm)
                applied_contact = deepcopy(contact)
                applied_contact["fields"].update(first.fields)
                second = self._purchase_plan(
                    applied_contact, farm, captured_at="2026-10-03T13:01:00Z",
                )
                self.assertTrue(second.order_validated)
                self.assertEqual(second.fields, {})

    def test_api_freight_preserves_original_weni_difference_on_idempotent_rerun(self) -> None:
        contact = self._purchase_contact()
        farm = self._purchase_api()
        farm.get_pedido.return_value["capa"]["frete"] = 5
        first = self._purchase_plan(contact, farm)
        self.assertTrue(first.order_validated)
        self.assertTrue(first.purchase_confirmed)
        self.assertEqual(first.fields["pedido_valor"], 30.5)
        self.assertEqual(first.fields["ultima_compra"], "2026-10-03T09:00:00-03:00")
        products = json.loads(first.fields["pedido_produtos"])
        self.assertEqual(products["status_validacao"], "ATENÇÃO_TOTAL_DIVERGENTE")
        self.assertEqual(products["status_confirmacao"], "CONFIRMADO_API")
        self.assertEqual(products["valor_total_compra"], "30.50")
        self.assertEqual(products["valor_total_api_itens"], "25.50")
        self.assertEqual(products["farmalider_frete"], "5.00")
        self.assertEqual(products["valor_total_weni"], "25.50")
        self.assertEqual(products["diferenca_total_weni_api"], "-5.00")
        audit_plans([first], opt_out_group_available=True)

        applied_contact = deepcopy(contact)
        applied_contact["fields"].update(first.fields)
        second = self._purchase_plan(
            applied_contact, farm, captured_at="2026-10-03T13:01:00Z",
        )
        self.assertTrue(second.order_validated)
        self.assertTrue(second.purchase_confirmed)
        self.assertEqual(second.fields, {})
        self.assertEqual(second.evidence, {})
        self.assertEqual(json.loads(applied_contact["fields"]["pedido_produtos"]), products)

    def test_divergent_weni_total_without_api_does_not_validate_order(self) -> None:
        contact = self._purchase_contact()
        raw = json.loads(contact["fields"]["ultimo_pedido"])
        raw["valor_total_compra"] = 30.5
        contact["fields"]["ultimo_pedido"] = json.dumps(raw)
        plan = self._purchase_plan(contact)
        self.assertFalse(plan.order_validated)
        self.assertFalse(plan.purchase_confirmed)
        self.assertFalse(plan.has_changes)
        self.assertEqual(plan.fields, {})
        self.assertEqual(plan.evidence, {})

    def test_validated_unconfirmed_order_survives_frozen_review_roundtrip(self) -> None:
        plan = self._purchase_plan(self._purchase_contact())
        stats = UpdateStats(
            contacts_considered=1, plans_with_changes=1, field_changes=len(plan.fields),
        )
        self.assertTrue(plan.order_validated)
        self.assertFalse(plan.purchase_confirmed)
        with tempfile.TemporaryDirectory() as tmp:
            review = Path(tmp) / "review.json"
            _, _, digest = write_review_snapshot(
                [plan], stats, full=True, json_path=review,
                captured_at_utc="2026-10-03T12:01:00Z",
            )
            loaded, payload, loaded_digest = load_review_snapshot(full=True, json_path=review)
            self.assertTrue(payload["plans"][0]["order_validated"])
            self.assertTrue(loaded[0].order_validated)
            self.assertFalse(loaded[0].purchase_confirmed)
            self.assertEqual(loaded[0].fields, plan.fields)
            self.assertEqual(loaded[0].guards, plan.guards)
            self.assertEqual(loaded_digest, digest)
            audit_plans(loaded, opt_out_group_available=True)
            self.assertEqual(verify_review_snapshot(loaded, full=True, json_path=review), digest)
            with self.assertRaisesRegex(PlanAuditError, "plano mudou"):
                verify_review_snapshot(
                    [replace(plan, order_validated=False)], full=True, json_path=review,
                )
        audit_plans([plan], opt_out_group_available=True)

    def test_incremental_order_apply_rechecks_identity_and_queues_conflicts(self) -> None:
        started = datetime(2026, 10, 3, 12, 1, tzinfo=timezone.utc)
        for changed_source in ("cpf", "ultimo_pedido"):
            with self.subTest(changed_source=changed_source):
                contact = self._purchase_contact()
                client = self._incremental_purchase_client(contact)
                current = deepcopy(contact)
                if changed_source == "cpf":
                    current["fields"]["cpf"] = "11144477735"
                else:
                    changed_order = json.loads(current["fields"]["ultimo_pedido"])
                    changed_order["pedido_id"] = "999"
                    current["fields"]["ultimo_pedido"] = json.dumps(changed_order)
                client.get_contact.return_value = current
                with (
                    patch("weni_update.WeniClient", return_value=client),
                    patch("weni_update._open_farmalider", return_value=self._purchase_api()),
                    patch("weni_update.resolve_window", return_value=UpdateWindow(
                        started_at=started, after=started, full=False,
                    )),
                    patch("weni_update._append_audit") as audit_mock,
                    patch("weni_update._save_state") as save_mock,
                ):
                    result = run_update(apply=True, full=False)
                self.assertEqual(result.contacts_conflicted, 1)
                self.assertEqual(result.contacts_updated, 0)
                self.assertEqual(result.contacts_failed, 0)
                client.get_contact.assert_called_once_with(uuid="u-pedido")
                client.update_contact_fields.assert_not_called()
                client.contact_group_action.assert_not_called()
                save_mock.assert_called_once()
                self.assertEqual(save_mock.call_args.args[0]["pending_conflict_uuids"], ["u-pedido"])
                self.assertEqual(audit_mock.call_args.args[0]["status"], "conflict_skipped")
                self.assertIn(changed_source, audit_mock.call_args.args[0]["error"])

    def test_incremental_order_apply_skips_fields_already_written_concurrently(self) -> None:
        started = datetime(2026, 10, 3, 12, 1, tzinfo=timezone.utc)
        contact = self._purchase_contact()
        farm = self._purchase_api()
        planned = self._purchase_plan(contact, farm)
        current = deepcopy(contact)
        current["fields"].update(planned.fields)
        client = self._incremental_purchase_client(contact)
        client.get_contact.return_value = current
        with (
            patch("weni_update.WeniClient", return_value=client),
            patch("weni_update._open_farmalider", return_value=farm),
            patch("weni_update.resolve_window", return_value=UpdateWindow(
                started_at=started, after=started, full=False,
            )),
            patch("weni_update._append_audit") as audit_mock,
            patch("weni_update._save_state") as save_mock,
        ):
            result = run_update(apply=True, full=False)
        self.assertEqual(result.contacts_already_satisfied, 1)
        self.assertEqual(result.contacts_conflicted, 0)
        self.assertEqual(result.contacts_updated, 0)
        client.get_contact.assert_called_once_with(uuid="u-pedido")
        client.update_contact_fields.assert_not_called()
        client.contact_group_action.assert_not_called()
        self.assertEqual(save_mock.call_args.args[0]["pending_conflict_uuids"], [])
        self.assertEqual(audit_mock.call_args.args[0]["status"], "already_satisfied")



    def test_review_snapshot_contains_human_readable_changes(self) -> None:
        plan = ContactUpdatePlan(
            contact_uuid="u1",
            contact_name="Maria",
            contact_urn="whatsapp:5591999999999",
            fields={"opt_in_lgpd": "recusado", "cpf": "52998224725", "idade": 27},
            previous={"opt_in_lgpd": "ativo", "cpf": "", "idade": None},
            evidence={
                "opt_in_lgpd": {
                    "message_id": "m1",
                    "created_on": "2026-10-03T12:00:00Z",
                    "reason": "recusa explícita",
                }
            },
            group_actions=[
                GroupAction(
                    "add",
                    "g1",
                    "opt_in_lgpd recusado",
                    group_name="Opt-Out LGPD",
                )
            ],
        )
        stats = UpdateStats(
            messages_incoming=5,
            contacts_considered=1,
            plans_with_changes=1,
            field_changes=3,
            group_actions=1,
        )
        with tempfile.TemporaryDirectory() as tmp:
            json_path = Path(tmp) / "review.json"
            _, txt_path, digest = write_review_snapshot(
                [plan],
                stats,
                full=True,
                json_path=json_path,
                captured_at_utc="2026-10-03T12:00:00Z",
            )
            text = txt_path.read_text(encoding="utf-8-sig")
            self.assertIn("Maria", text)
            self.assertIn("ativo  ->  recusado", text)
            self.assertIn("cpf: <vazio>  ->  52998224725", text)
            self.assertIn("Contatos com CPF detectado/alterado: 1", text)
            self.assertIn("ADICIONAR em Opt-Out LGPD", text)
            self.assertIn("Inclusões em Opt-Out LGPD: 1", text)
            self.assertIn("Inclusões em Opt-In LGPD: 0", text)
            self.assertIn(digest, text)
            self.assertIn("plano fica CONGELADO", text)
            loaded, payload, loaded_digest = load_review_snapshot(
                full=True,
                json_path=json_path,
            )
            self.assertEqual(len(loaded), 1)
            self.assertEqual(payload["captured_at_utc"], "2026-10-03T12:00:00Z")
            self.assertEqual(loaded_digest, digest)
            self.assertEqual(verify_review_snapshot([plan], full=True, json_path=json_path), digest)

    def test_review_snapshot_blocks_changed_plan(self) -> None:
        plan = ContactUpdatePlan(contact_uuid="u1", fields={"idade": 27}, previous={"idade": None})
        stats = UpdateStats(contacts_considered=1, plans_with_changes=1, field_changes=1)
        with tempfile.TemporaryDirectory() as tmp:
            json_path = Path(tmp) / "review.json"
            write_review_snapshot(
                [plan],
                stats,
                full=True,
                json_path=json_path,
                captured_at_utc="2026-10-03T12:00:00Z",
            )
            changed = ContactUpdatePlan(
                contact_uuid="u1",
                fields={"idade": 28},
                previous={"idade": None},
            )
            with self.assertRaisesRegex(PlanAuditError, "plano mudou"):
                verify_review_snapshot([changed], full=True, json_path=json_path)

    @patch("weni_update._save_state")
    @patch("weni_update._append_audit")
    @patch("weni_update.WeniClient")
    def test_full_apply_uses_frozen_snapshot_without_recalculating_history(
        self,
        client_cls,
        append_audit_mock,
        save_state_mock,
    ) -> None:
        plan = ContactUpdatePlan(
            contact_uuid="u1",
            contact_name="Maria",
            fields={"idade": 27},
            previous={"idade": None},
        )
        stats = UpdateStats(contacts_considered=1, plans_with_changes=1, field_changes=1)
        with tempfile.TemporaryDirectory() as tmp:
            review = Path(tmp) / "review.json"
            write_review_snapshot(
                [plan],
                stats,
                full=True,
                json_path=review,
                captured_at_utc="2026-10-03T12:00:00Z",
            )

            client = client_cls.return_value
            client.list_fields.return_value = [
                {"key": "contact_urn_whatsapp"},
                {"key": "contact_urn_instagram"},
                {"key": "contact_urn_facebook"},
                {"key": "contact_canal_principal"},
            ]

            def list_groups(name=None):
                groups = [
                    {"uuid": "g-in", "name": "Opt-In LGPD"},
                    {"uuid": "g-out", "name": "Opt-Out LGPD"},
                ]
                if name is None:
                    return groups
                return [item for item in groups if item["name"] == name]

            client.list_groups.side_effect = list_groups
            client.get_contact.return_value = {
                "uuid": "u1",
                "groups": [],
                "fields": {},
            }

            result = run_update(
                apply=True,
                full=True,
                require_review=review,
            )

            self.assertEqual(result.contacts_updated, 1)
            self.assertEqual(result.contacts_conflicted, 0)
            client.list_messages.assert_not_called()
            client.list_contacts.assert_not_called()
            client.update_contact_fields.assert_called_once_with("u1", {"idade": 27})
            save_state_mock.assert_called_once()
            saved = save_state_mock.call_args.args[0]
            self.assertEqual(saved["last_success_utc"], "2026-10-03T12:00:00Z")
            append_audit_mock.assert_called_once()

    @patch("weni_update._save_state")
    @patch("weni_update._append_audit")
    @patch("weni_update.WeniClient")
    def test_full_apply_skips_only_changed_contact_and_continues(
        self,
        client_cls,
        append_audit_mock,
        save_state_mock,
    ) -> None:
        plans = [
            ContactUpdatePlan(
                contact_uuid="u1",
                contact_name="Mudou",
                fields={"idade": 27},
                previous={"idade": None},
            ),
            ContactUpdatePlan(
                contact_uuid="u2",
                contact_name="Estável",
                fields={"idade": 31},
                previous={"idade": None},
            ),
        ]
        stats = UpdateStats(contacts_considered=2, plans_with_changes=2, field_changes=2)
        with tempfile.TemporaryDirectory() as tmp:
            review = Path(tmp) / "review.json"
            write_review_snapshot(
                plans,
                stats,
                full=True,
                json_path=review,
                captured_at_utc="2026-10-03T12:00:00Z",
            )

            client = client_cls.return_value
            client.list_fields.return_value = [
                {"key": "contact_urn_whatsapp"},
                {"key": "contact_urn_instagram"},
                {"key": "contact_urn_facebook"},
                {"key": "contact_canal_principal"},
            ]
            client.list_groups.side_effect = lambda name=None: (
                [
                    {"uuid": "g-in", "name": "Opt-In LGPD"},
                    {"uuid": "g-out", "name": "Opt-Out LGPD"},
                ]
                if name is None
                else [{"uuid": "g-in" if name == "Opt-In LGPD" else "g-out", "name": name}]
            )

            def get_contact(*, uuid=None, urn=None):
                if uuid == "u1":
                    return {"uuid": "u1", "groups": [], "fields": {"idade": 29}}
                if uuid == "u2":
                    return {"uuid": "u2", "groups": [], "fields": {}}
                return None

            client.get_contact.side_effect = get_contact

            result = run_update(
                apply=True,
                full=True,
                require_review=review,
            )

            self.assertEqual(result.contacts_conflicted, 1)
            self.assertEqual(result.contacts_updated, 1)
            client.update_contact_fields.assert_called_once_with("u2", {"idade": 31})
            save_state_mock.assert_called_once()
            statuses = [call.kwargs.get("status") for call in []]
            self.assertEqual(append_audit_mock.call_count, 2)

    @patch("weni_update._save_state")
    @patch("weni_update._append_audit")
    @patch("weni_update._open_farmalider", return_value=None)
    @patch("weni_update.resolve_window")
    @patch("weni_update.WeniClient")
    def test_apply_syncs_active_lgpd_to_optin_and_removes_optout(
        self,
        client_cls,
        resolve_window_mock,
        _open_farmalider_mock,
        append_audit_mock,
        save_state_mock,
    ) -> None:
        from datetime import datetime, timezone

        started = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
        resolve_window_mock.return_value = UpdateWindow(
            started_at=started,
            after=started,
            full=False,
        )
        client = client_cls.return_value
        client.list_fields.return_value = [
            {"key": "contact_urn_whatsapp"},
            {"key": "contact_urn_instagram"},
            {"key": "contact_urn_facebook"},
            {"key": "contact_canal_principal"},
        ]

        def list_groups(name=None):
            groups = [
                {"uuid": "g-in", "name": "Opt-In LGPD"},
                {"uuid": "g-out", "name": "Opt-Out LGPD"},
            ]
            if name is None:
                return groups
            return [item for item in groups if item["name"] == name]

        client.list_groups.side_effect = list_groups
        client.list_messages.return_value = []
        client.list_contacts.return_value = [
            {
                "uuid": "u1",
                "groups": [{"uuid": "g-out", "name": "Opt-Out LGPD"}],
                "fields": {"opt_in_lgpd": "ativo"},
            }
        ]

        stats = run_update(apply=True, full=False)

        self.assertEqual(stats.group_actions, 2)
        self.assertEqual(stats.contacts_updated, 1)
        client.contact_group_action.assert_any_call("u1", action="add", group="g-in")
        client.contact_group_action.assert_any_call("u1", action="remove", group="g-out")
        self.assertEqual(client.contact_group_action.call_count, 2)
        client.update_contact_fields.assert_not_called()
        save_state_mock.assert_called_once()
        append_audit_mock.assert_called_once()


    @patch("weni_update._save_state")
    @patch("weni_update._append_audit")
    @patch("weni_update._open_farmalider", return_value=None)
    @patch("weni_update.resolve_window")
    @patch("weni_update.WeniClient")
    def test_dry_run_never_writes_or_advances_checkpoint(
        self,
        client_cls,
        resolve_window_mock,
        _open_farmalider_mock,
        append_audit_mock,
        save_state_mock,
    ) -> None:
        from datetime import datetime, timezone

        started = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
        resolve_window_mock.return_value = UpdateWindow(
            started_at=started,
            after=started,
            full=False,
        )
        client = client_cls.return_value
        client.list_fields.return_value = [
            {"key": "contact_urn_whatsapp"},
            {"key": "contact_urn_instagram"},
            {"key": "contact_urn_facebook"},
            {"key": "contact_canal_principal"},
        ]
        client.list_groups.return_value = [{"uuid": "g1", "name": "Opt-Out LGPD"}]
        client.list_messages.return_value = []
        client.list_contacts.return_value = [
            {
                "uuid": "u1",
                "urns": ["whatsapp:5591999999999"],
                "groups": [],
                "fields": {},
            }
        ]

        stats = run_update(apply=False, full=False)

        self.assertEqual(stats.plans_with_changes, 1)
        client.update_contact_fields.assert_not_called()
        client.contact_group_action.assert_not_called()
        save_state_mock.assert_not_called()
        append_audit_mock.assert_called_once()

    @patch("weni_update._save_state")
    @patch("weni_update._append_audit")
    @patch("weni_update._open_farmalider", return_value=None)
    @patch("weni_update.resolve_window")
    @patch("weni_update.WeniClient")
    def test_full_apply_without_review_is_blocked_before_write(
        self,
        client_cls,
        resolve_window_mock,
        _open_farmalider_mock,
        append_audit_mock,
        save_state_mock,
    ) -> None:
        from datetime import datetime, timezone

        started = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
        resolve_window_mock.return_value = UpdateWindow(
            started_at=started,
            after=None,
            full=True,
        )
        client = client_cls.return_value
        client.list_fields.return_value = [
            {"key": "contact_urn_whatsapp"},
            {"key": "contact_urn_instagram"},
            {"key": "contact_urn_facebook"},
            {"key": "contact_canal_principal"},
        ]
        client.list_groups.return_value = [{"uuid": "g1", "name": "Opt-Out LGPD"}]
        client.list_messages.return_value = []
        client.list_contacts.return_value = [
            {
                "uuid": "u1",
                "urns": ["whatsapp:5591999999999"],
                "groups": [],
                "fields": {},
            }
        ]

        with self.assertRaisesRegex(PlanAuditError, "snapshot de revisão humana"):
            run_update(apply=True, full=True)

        client.update_contact_fields.assert_not_called()
        client.contact_group_action.assert_not_called()
        save_state_mock.assert_not_called()
        append_audit_mock.assert_not_called()

    @patch("weni_update._save_state")
    @patch("weni_update._append_audit")
    @patch("weni_update._open_farmalider", return_value=None)
    @patch("weni_update.resolve_window")
    @patch("weni_update.WeniClient")
    def test_apply_failure_never_advances_checkpoint(
        self,
        client_cls,
        resolve_window_mock,
        _open_farmalider_mock,
        append_audit_mock,
        save_state_mock,
    ) -> None:
        from datetime import datetime, timezone

        started = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
        resolve_window_mock.return_value = UpdateWindow(
            started_at=started,
            after=started,
            full=False,
        )
        client = client_cls.return_value
        client.list_fields.return_value = [
            {"key": "contact_urn_whatsapp"},
            {"key": "contact_urn_instagram"},
            {"key": "contact_urn_facebook"},
            {"key": "contact_canal_principal"},
        ]
        client.list_groups.return_value = [{"uuid": "g1", "name": "Opt-Out LGPD"}]
        client.list_messages.return_value = []
        client.list_contacts.return_value = [
            {
                "uuid": "u1",
                "urns": ["whatsapp:5591999999999"],
                "groups": [],
                "fields": {},
            }
        ]
        client.update_contact_fields.side_effect = RuntimeError("falha simulada")

        with self.assertRaisesRegex(RuntimeError, "checkpoint não foi avançado"):
            run_update(apply=True, full=False)

        client.update_contact_fields.assert_called_once()
        save_state_mock.assert_not_called()
        append_audit_mock.assert_called_once()

    @patch("weni_update._open_farmalider", return_value=None)
    @patch("weni_update.resolve_window")
    @patch("weni_update.WeniClient")
    def test_missing_multichannel_fields_blocks_before_contact_reads(
        self, client_cls, resolve_window_mock, _open_farmalider_mock
    ) -> None:
        from datetime import datetime, timezone

        started = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
        resolve_window_mock.return_value = UpdateWindow(
            started_at=started,
            after=started,
            full=False,
        )
        client = client_cls.return_value
        client.list_fields.return_value = [
            {"key": "contact_urn_whatsapp"},
            {"key": "contact_canal_principal"},
        ]

        with self.assertRaisesRegex(PlanAuditError, "contact_urn_facebook"):
            run_update(apply=False, full=False)

        client.list_messages.assert_not_called()
        client.list_contacts.assert_not_called()
        client.update_contact_fields.assert_not_called()
        client.contact_group_action.assert_not_called()


if __name__ == "__main__":
    unittest.main()


class GoogleAdsWeniUpdateTests(unittest.TestCase):
    def _contact(self, fields=None):
        return {
            "uuid": "u-google",
            "urns": ["whatsapp:5591999999999"],
            "groups": [],
            "fields": fields or {},
        }

    def _available_fields(self):
        from weni_update import ALLOWED_WRITE_FIELDS
        return set(ALLOWED_WRITE_FIELDS)

    def test_google_ads_pmax_populates_first_and_last_without_changing_urn(self):
        message = {
            "id": "g1",
            "created_on": "2026-10-03T12:00:00Z",
            "direction": "in",
            "urn": "whatsapp:5591999999999",
            "metadata": {
                "source_url": (
                    "https://example.com/?utm_source=google&utm_medium=cpc"
                    "&utm_campaign_type=performance_max&gclid=GCLID123"
                )
            },
        }
        plan = _build_contact_plan(
            self._contact(),
            context_messages=[message],
            candidate_message_ids={"g1"},
            farm_client=None,
            opt_out_group_name="Opt-Out LGPD",
            opt_out_group_uuid="g-out",
            captured_at="2026-10-03T12:01:00Z",
            opt_in_group_name="Opt-In LGPD",
            opt_in_group_uuid="g-in",
            available_weni_fields=self._available_fields(),
        )
        self.assertEqual(plan.fields["contact_urn"], "whatsapp:5591999999999")
        self.assertEqual(plan.fields["primeiro_anuncio_origem"], "Google Ads")
        self.assertEqual(plan.fields["ultimo_anuncio_origem"], "Google Ads")
        self.assertEqual(plan.fields["primeiro_anuncio_clique_id"], "GCLID123")
        self.assertEqual(plan.fields["ultimo_anuncio_clique_id"], "GCLID123")
        self.assertEqual(plan.fields["primeiro_anuncio_tipo_campanha"], "Performance Max")
        self.assertEqual(plan.fields["ultimo_anuncio_tipo_campanha"], "Performance Max")
        self.assertEqual(plan.fields["primeiro_anuncio_canal_destino"], "whatsapp")
        self.assertEqual(plan.fields["ultimo_anuncio_canal_destino"], "whatsapp")

    def test_google_ads_does_not_replace_existing_first_ad(self):
        fields = {
            "primeiro_anuncio_origem": "Meta Ads",
            "primeiro_anuncio_id": "META-1",
            "primeiro_anuncio_data": "2026-10-01 10:00:00",
        }
        message = {
            "id": "g2",
            "created_on": "2026-10-03T12:00:00Z",
            "direction": "in",
            "urn": "messenger:abc",
            "metadata": {"source_url": "https://example.com/?utm_source=google&utm_medium=paid_search&gclid=G2"},
        }
        plan = _build_contact_plan(
            self._contact(fields),
            context_messages=[message],
            candidate_message_ids={"g2"},
            farm_client=None,
            opt_out_group_name="Opt-Out LGPD",
            opt_out_group_uuid="g-out",
            captured_at="2026-10-03T12:01:00Z",
            opt_in_group_name="Opt-In LGPD",
            opt_in_group_uuid="g-in",
            available_weni_fields=self._available_fields(),
        )
        self.assertNotIn("primeiro_anuncio_origem", plan.fields)
        self.assertNotIn("primeiro_anuncio_id", plan.fields)
        self.assertEqual(plan.fields["ultimo_anuncio_origem"], "Google Ads")
        self.assertEqual(plan.fields["ultimo_anuncio_canal_destino"], "facebook")

    def test_newer_google_ads_updates_last_ad_but_older_does_not(self):
        fields = {
            "ultimo_anuncio_origem": "Meta Ads",
            "ultimo_anuncio_id": "META-2",
            "ultimo_anuncio_data": "2026-10-03 11:00:00",
        }
        older = {
            "id": "g-old",
            "created_on": "2026-10-03T10:00:00Z",
            "direction": "in",
            "urn": "whatsapp:1",
            "metadata": {"source_url": "https://example.com/?gclid=OLD&utm_source=google&utm_medium=cpc"},
        }
        plan_old = _build_contact_plan(
            self._contact(fields),
            context_messages=[older],
            candidate_message_ids={"g-old"},
            farm_client=None,
            opt_out_group_name="Opt-Out LGPD",
            opt_out_group_uuid="g-out",
            captured_at="2026-10-03T12:01:00Z",
            opt_in_group_name="Opt-In LGPD",
            opt_in_group_uuid="g-in",
            available_weni_fields=self._available_fields(),
        )
        self.assertNotIn("ultimo_anuncio_origem", plan_old.fields)

        newer = dict(older)
        newer["id"] = "g-new"
        newer["created_on"] = "2026-10-03T12:00:00Z"
        newer["metadata"] = {"source_url": "https://example.com/?gclid=NEW&utm_source=google&utm_medium=cpc"}
        plan_new = _build_contact_plan(
            self._contact(fields),
            context_messages=[newer],
            candidate_message_ids={"g-new"},
            farm_client=None,
            opt_out_group_name="Opt-Out LGPD",
            opt_out_group_uuid="g-out",
            captured_at="2026-10-03T12:01:00Z",
            opt_in_group_name="Opt-In LGPD",
            opt_in_group_uuid="g-in",
            available_weni_fields=self._available_fields(),
        )
        self.assertEqual(plan_new.fields["ultimo_anuncio_origem"], "Google Ads")
        self.assertEqual(plan_new.fields["ultimo_anuncio_clique_id"], "NEW")

    def test_optional_google_fields_are_skipped_when_not_created_in_weni(self):
        base_fields = {
            "contact_urn_whatsapp",
            "contact_urn_instagram",
            "contact_urn_facebook",
            "contact_canal_principal",
            "contact_urn",
            "primeiro_anuncio_origem",
            "primeiro_anuncio_id",
            "primeiro_anuncio_titulo",
            "primeiro_anuncio_url",
            "primeiro_anuncio_clique_id",
            "primeiro_anuncio_data",
            "ultimo_anuncio_origem",
            "ultimo_anuncio_id",
            "ultimo_anuncio_titulo",
            "ultimo_anuncio_url",
            "ultimo_anuncio_clique_id",
            "ultimo_anuncio_data",
        }
        message = {
            "id": "g3",
            "created_on": "2026-10-03T12:00:00Z",
            "direction": "in",
            "urn": "instagram:123",
            "metadata": {"source_url": "https://example.com/?gclid=G3&utm_source=google&utm_medium=display"},
        }
        contact = {
            "uuid": "u-instagram-google",
            "urns": ["instagram:123"],
            "groups": [],
            "fields": {},
        }
        plan = _build_contact_plan(
            contact,
            context_messages=[message],
            candidate_message_ids={"g3"},
            farm_client=None,
            opt_out_group_name="Opt-Out LGPD",
            opt_out_group_uuid="g-out",
            captured_at="2026-10-03T12:01:00Z",
            opt_in_group_name="Opt-In LGPD",
            opt_in_group_uuid="g-in",
            available_weni_fields=base_fields,
        )
        self.assertEqual(plan.fields["ultimo_anuncio_origem"], "Google Ads")
        self.assertNotIn("ultimo_anuncio_tipo_campanha", plan.fields)
        self.assertNotIn("ultimo_anuncio_canal_destino", plan.fields)
