"""Contrato de tipos/persistência Weni com respostas inteiramente sintéticas."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from weni_client import WeniError
from weni_update import (
    REQUIRED_MULTICHANNEL_FIELDS,
    REQUIRED_ORDER_FIELDS,
    ContactUpdatePlan,
    GroupAction,
    PlanAuditError,
    _available_weni_fields,
    _execute_contact_plan,
    run_update,
)


class WeniFieldContractTests(unittest.TestCase):
    def metadata(self):
        fields = [
            {"key": key, "value_type": "text"}
            for key in sorted(REQUIRED_MULTICHANNEL_FIELDS | REQUIRED_ORDER_FIELDS)
        ]
        for field in fields:
            if field["key"] in {"pedido_id", "pedido_status", "pedido_valor"}:
                field["value_type"] = "numeric"
            if field["key"] == "pedido_data":
                field["value_type"] = "datetime"
        return fields

    def test_text_lists_and_payment_allow_other_documented_field_types(self):
        client = Mock()
        client.list_fields.return_value = self.metadata()
        self.assertEqual(
            _available_weni_fields(client),
            REQUIRED_MULTICHANNEL_FIELDS | REQUIRED_ORDER_FIELDS,
        )
        client.list_fields.assert_called_once()

    def test_incompatible_quantity_or_payment_type_blocks_before_mutations(self):
        for key in ("pedido_quantidade_itens", "pedido_forma_pagamento"):
            with self.subTest(key=key):
                client, farm = Mock(), Mock()
                fields = self.metadata()
                next(field for field in fields if field["key"] == key)["value_type"] = (
                    "numeric"
                )
                client.list_fields.return_value = fields
                with (
                    patch("weni_update.secrets.WENI_API_TOKEN", "synthetic-token"),
                    patch("weni_update.WeniClient", return_value=client),
                    patch("weni_update._open_farmalider", return_value=farm),
                ):
                    with self.assertRaisesRegex(PlanAuditError, key):
                        run_update(apply=True)
                client.update_contact_fields.assert_not_called()
                client.contact_group_action.assert_not_called()
                client.list_contacts.assert_not_called()
                farm.get_cliente_by_cpf.assert_not_called()
                farm.get_pedido.assert_not_called()

    def test_engine_type_alias_and_legacy_missing_metadata(self):
        client = Mock()
        client.list_fields.return_value = [
            {"key": "pedido_quantidade_itens", "type": "number"}
        ]
        with self.assertRaises(PlanAuditError):
            _available_weni_fields(client)
        client.list_fields.return_value = [
            {"key": key} for key in REQUIRED_ORDER_FIELDS
        ]
        self.assertEqual(_available_weni_fields(client), REQUIRED_ORDER_FIELDS)

    def test_delivery_apply_uses_same_preflight_before_weni_or_sheets_writes(self):
        from delivery_tickets import (
            apply_delivery_review,
            reconcile_tickets,
            write_delivery_review,
        )
        from tests.test_delivery_tickets import NOW, contact, farm, selection

        plans, delivery = reconcile_tickets(
            selection(),
            [contact()],
            farm(),
            captured_at=NOW,
            available_fields=REQUIRED_ORDER_FIELDS,
        )
        client, factory = Mock(), Mock()
        fields = self.metadata()
        next(field for field in fields if field["key"] == "pedido_forma_pagamento")[
            "value_type"
        ] = "numeric"
        client.list_fields.return_value = fields
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "review.json"
            write_delivery_review(plans, delivery, path)
            with self.assertRaises(PlanAuditError):
                apply_delivery_review(path, client, store_factory=factory)
        client.get_contact.assert_not_called()
        client.update_contact_fields.assert_not_called()
        client.contact_group_action.assert_not_called()
        factory.assert_not_called()

    def test_persisted_fields_are_compared_semantically_without_second_get(self):
        client = Mock()
        client.update_contact_fields.return_value = {
            "fields": {
                "pedido_quantidade_itens": "2, 1",
                "pedido_forma_pagamento": "Cancelado",
                "pedido_data": "2026-10-09T15:00:00Z",
                "pedido_valor": "15.50",
            }
        }
        plan = ContactUpdatePlan(
            "synthetic-uuid",
            fields={
                "pedido_quantidade_itens": "2, 1",
                "pedido_forma_pagamento": "Cancelado",
                "pedido_data": "09/10/26 12:00:00",
                "pedido_valor": 15.5,
            },
        )
        _execute_contact_plan(client, plan)
        client.update_contact_fields.assert_called_once()
        client.get_contact.assert_not_called()

    def test_null_or_truncated_numeric_response_blocks_remaining_group_actions(self):
        for persisted in (None, "2", 2):
            with self.subTest(persisted=persisted):
                client = Mock()
                client.update_contact_fields.return_value = {
                    "fields": {"pedido_quantidade_itens": persisted}
                }
                plan = ContactUpdatePlan(
                    "synthetic-private-uuid",
                    fields={"pedido_quantidade_itens": "2, 1"},
                    group_actions=[GroupAction("add", "synthetic-optin", "synthetic")],
                )
                with self.assertRaises(WeniError) as caught:
                    _execute_contact_plan(client, plan)
                self.assertIn("pedido_quantidade_itens", str(caught.exception))
                self.assertNotIn("synthetic-private-uuid", str(caught.exception))
                self.assertNotIn("2, 1", str(caught.exception))
                client.contact_group_action.assert_not_called()
                client.update_contact_fields.assert_called_once()

    def test_minimal_response_is_not_misrepresented_as_readback_failure(self):
        for response in ({}, {"result": "accepted"}):
            with self.subTest(response=response):
                client = Mock()
                client.update_contact_fields.return_value = response
                _execute_contact_plan(
                    client,
                    ContactUpdatePlan(
                        "synthetic-uuid", fields={"pedido_quantidade_itens": "2, 1"}
                    ),
                )
                client.update_contact_fields.assert_called_once()
                client.get_contact.assert_not_called()
