"""O último pedido oficial incompleto nunca reativa uma compra anterior."""

import unittest
from copy import deepcopy
from datetime import datetime
from unittest.mock import Mock

from farmalider_client import FarmaliderError
from farmalider_integration import resolve_contact_order
from recompra import cancelled_order_reason, propose, resolve_latest
from tests.test_pedido_resolution import cliente_payload, pedido_payload
from tests.test_recompra import NOW, STRUCTURE, fixture


class LatestOrderValidationTests(unittest.TestCase):
    def setUp(self):
        self.contact, _, _ = fixture(grouped=True)
        self.contact["fields"].update(
            pedido_id="123", pedido_data="18/09/26 12:21:00", pedido_status="2"
        )
        self.saved = {"purchase": {"pedido_id": "123"}}
        self.customer = cliente_payload()
        self.customer["ultimoPedido"].update(
            id=456, emissao="2026-10-09T12:00:00", status=2
        )
        self.customer["itens"] = []
        self.latest = {"capa": deepcopy(self.customer["ultimoPedido"]), "itens": []}
        self.old = pedido_payload()
        self.old["capa"].update(emissao="2026-09-18T12:21:00", status=2)
        self.farm = Mock()
        self.farm.get_cliente_by_cpf.return_value = self.customer
        self.farm.get_pedido.side_effect = lambda order_id: (
            self.latest if order_id == "456" else self.old
        )

    def resolve(self):
        return resolve_latest(
            self.contact, self.farm, NOW.isoformat(), saved=self.saved
        )

    def assert_no_old_campaign(self, order, items, *, validation="CANCELADO_SEM_ITENS"):
        self.farm.get_pedido.assert_called_once_with("456")
        self.assertEqual(order["pedido_id"], "456")
        self.assertEqual(order["status_validacao"], validation)
        self.assertEqual(items, [])
        plan = propose(self.contact, order, items, STRUCTURE, self.saved, now=NOW)
        self.assertEqual(plan["action"], "remove")
        self.assertEqual(plan["fields"], {})
        self.assertFalse(plan["due_today"])
        return plan

    def test_new_order_without_items_does_not_recover_saved_old_order(self):
        order, items = self.resolve()
        self.assertEqual(order["status_confirmacao"], "CANCELADO_API")
        self.assert_no_old_campaign(order, items)

    def test_new_order_not_found_preserves_structured_item_failure(self):
        self.farm.get_pedido.side_effect = None
        self.farm.get_pedido.return_value = None
        order, items = self.resolve()
        self.assertEqual(order["status_confirmacao"], "ERRO_ITENS_PEDIDO_API")
        self.assert_no_old_campaign(order, items, validation="ERRO")

    def test_new_order_api_error_does_not_recover_saved_old_order(self):
        self.farm.get_pedido.side_effect = FarmaliderError("Falha sintética")
        order, items = self.resolve()
        self.assertEqual(order["status_confirmacao"], "ERRO_ITENS_PEDIDO_API")
        self.assert_no_old_campaign(order, items, validation="ERRO")

    def test_cancelled_header_without_items_blocks_old_purchase(self):
        for signal, reason in (
            ({"status": 3}, "PEDIDO_STATUS_3_CANCELADO"),
            ({"formaPagamento": 0}, "PAGAMENTO_0_CANCELADO"),
            ({"cancelamento": "2026-10-09T12:01:00"}, "PEDIDO_CANCELADO"),
        ):
            with self.subTest(signal=signal):
                self.setUp()
                self.latest["capa"].update(signal)
                order, items = self.resolve()
                plan = self.assert_no_old_campaign(order, items)
                self.assertEqual(cancelled_order_reason(order), reason)
                self.assertEqual(plan["reason"], reason)

    def test_cancelled_customer_header_is_kept_when_order_get_fails(self):
        self.customer["ultimoPedido"]["status"] = 3
        self.farm.get_pedido.side_effect = FarmaliderError("Falha sintética")
        order, items = self.resolve()
        plan = self.assert_no_old_campaign(order, items, validation="ERRO")
        self.assertEqual(plan["reason"], "PEDIDO_STATUS_3_CANCELADO")

    def test_new_order_items_can_be_recovered_from_same_official_id(self):
        self.latest["itens"] = deepcopy(self.old["itens"])
        self.latest["itens"][0]["codPedido"] = 456
        order, items = self.resolve()
        self.farm.get_pedido.assert_called_once_with("456")
        self.assertEqual(order["pedido_id"], "456")
        self.assertEqual(order["status_validacao"], "OK")
        plan = propose(self.contact, order, items, STRUCTURE, self.saved, now=NOW)
        self.assertEqual(plan["action"], "replace")
        self.assertEqual(plan["order_id"], "456")
        self.assertEqual(plan["fields"]["pedido_data"], "2026-10-09T12:00:00-03:00")

    def test_malformed_latest_id_never_uses_weni_or_saved_old_id(self):
        for raw_id in (None, "", True, 0, "inválido"):
            with self.subTest(raw_id=raw_id):
                self.customer["ultimoPedido"]["id"] = raw_id
                self.farm.get_pedido.reset_mock()
                order, items = self.resolve()
                self.assertEqual(order["status_confirmacao"], "PEDIDO_ID_INVALIDO_API")
                self.assertEqual(items, [])
                self.farm.get_pedido.assert_not_called()

    def test_general_resolver_rejects_concrete_latest_with_invalid_id(self):
        self.customer["ultimoPedido"].pop("id")
        order, items = resolve_contact_order(
            self.contact, farm_client=self.farm, captured_at=NOW.isoformat()
        )
        self.assertEqual(order["status_confirmacao"], "PEDIDO_ID_INVALIDO_API")
        self.assertEqual(items, [])
        self.farm.get_pedido.assert_not_called()

    def test_negative_header_requires_matching_order_and_customer(self):
        for field, value, reason in (
            ("id", 789, "PEDIDO_ID_DIVERGENTE_API"),
            ("codCliente", 789, "PEDIDO_CLIENTE_DIVERGENTE_API"),
        ):
            with self.subTest(field=field):
                self.setUp()
                self.latest["capa"].update({field: value, "status": 3})
                order, items = self.resolve()
                self.assertEqual(order["status_confirmacao"], reason)
                self.assertEqual(items, [])
                self.assertEqual(cancelled_order_reason(order), "")

    def test_newer_weni_reference_blocks_older_api_campaign_for_any_order_id(self):
        for current_id in ("123", "456"):
            for reference in ("09/10/26 12:21:00", "09-10-2026 12:21"):
                with self.subTest(current_id=current_id, reference=reference):
                    contact, order, items = fixture(grouped=True)
                    order.update(
                        pedido_id="123",
                        pedido_chave="FARMALIDER:123",
                        data_hora="2026-09-18T12:21:00-03:00",
                    )
                    contact["fields"].update(
                        pedido_id=current_id, pedido_data=reference
                    )
                    plan = propose(
                        contact,
                        order,
                        items,
                        STRUCTURE,
                        now=datetime(2026, 10, 11, 19, 0, tzinfo=NOW.tzinfo),
                    )
                    self.assertEqual(plan["reason"], "PEDIDO_ANTIGO_BLOQUEADO")
                    self.assertEqual(plan["action"], "remove")
                    self.assertEqual(plan["fields"], {})
                    self.assertEqual(plan["event_at"], "")
                    self.assertFalse(plan["due_today"])

    def test_newer_saved_reference_blocks_older_api_campaign(self):
        contact, order, items = fixture(grouped=True)
        order["data_hora"] = "2026-09-18T12:21:00-03:00"
        contact["fields"]["pedido_data"] = "18/09/26 12:21:00"
        plan = propose(
            contact,
            order,
            items,
            STRUCTURE,
            saved={"purchase": {"data_hora": "2026-10-09T12:21:00-03:00"}},
            now=datetime(2026, 10, 11, 19, 0, tzinfo=NOW.tzinfo),
        )
        self.assertEqual(plan["reason"], "PEDIDO_ANTIGO_BLOQUEADO")
        self.assertEqual(plan["action"], "remove")
        self.assertEqual(plan["fields"], {})
        self.assertEqual(plan["event_at"], "")


if __name__ == "__main__":
    unittest.main()
