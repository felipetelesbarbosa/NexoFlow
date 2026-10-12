"""Snapshots legados não classificam nem apagam uma compra oficial nova."""

import json
import unittest

from farmalider_integration import apply_pedido_api_confirmation
from pharmacy_scope import (
    filter_pharmacy_order,
    plan_pharmacy_scope,
    sanitize_contact_order,
)
from tests.test_pharmacy_scope import fixture


class PharmacyScopeFreshnessTests(unittest.TestCase):
    def test_current_get_replaces_old_pet_snapshot_and_preserves_human_freight(self):
        old, _, _ = fixture(pet_only=True)
        current = dict(old, pedido_id="703", pedido_chave="FARMALIDER:703")
        payload = {
            "capa": {
                "id": 703,
                "codCliente": 321,
                "emissao": "2026-10-09T10:00:00-03:00",
                "status": 2,
                "formaPagamento": 3,
                "frete": 5,
            },
            "itens": [
                {
                    "codPedido": 703,
                    "codProduto": 999,
                    "descricao": "Protetor solar humano",
                    "categoria": "Dermocosméticos",
                    "quantidade": 1,
                    "valor": 18,
                    "total": 18,
                }
            ],
        }
        order, items = apply_pedido_api_confirmation(
            current,
            [],
            payload,
            linked_cliente_id="321",
            confirmed_at="2026-10-11T12:00:00Z",
        )
        snapshot = json.loads(order["ultimo_pedido_raw"])
        self.assertEqual(snapshot["pedido_id"], "703")
        self.assertEqual(snapshot["produtos"][0]["categoria"], "Dermocosméticos")
        self.assertNotIn("Ração", order["ultimo_pedido_raw"])
        filtered, retained = filter_pharmacy_order(order, items)
        self.assertEqual(filtered["valor_total_faturamento"], "23.00")
        self.assertEqual(filtered["farmalider_frete"], "5.00")
        self.assertEqual(len(retained), 1)

    def test_legacy_pet_identity_or_time_cannot_remove_new_human_order(self):
        old, _, _ = fixture(pet_only=True)
        raw = json.loads(old["ultimo_pedido_raw"])
        raw["produtos"][0].update(nome="Fórmula XYZ", categoria="Veterinária")
        for raw_id, raw_time in (
            ("700", "2026-10-01T10:00:00-03:00"),
            ("703", "2026-09-01T10:00:00-03:00"),
        ):
            with self.subTest(raw_id=raw_id, raw_time=raw_time):
                raw.update(pedido_id=raw_id, data_hora=raw_time)
                current, items, _ = fixture(order_id="703")
                current["ultimo_pedido_raw"] = json.dumps(raw)
                current["valor_total_compra"] = "18.00"
                current["valor_total_faturamento"] = "23.00"
                scope = plan_pharmacy_scope([current], items[:1])
                self.assertEqual(scope.removed_order_keys, set())
                self.assertEqual(len(scope.orders), 1)
                self.assertEqual(scope.orders[0]["farmalider_frete"], "5")
                self.assertEqual(scope.orders[0]["valor_total_faturamento"], "23.00")
                snapshot = json.loads(scope.orders[0]["ultimo_pedido_raw"])
                self.assertEqual(snapshot["pedido_id"], "703")
                self.assertEqual(snapshot["valor_total_compra"], "23.00")
                self.assertEqual(snapshot["farmalider_frete"], "5")
                self.assertEqual(snapshot["quantidade_itens"], "2")
                self.assertEqual(
                    snapshot["produtos"][0]["nome"], items[0]["produto_nome"]
                )
                self.assertNotIn("Veterinária", scope.orders[0]["ultimo_pedido_raw"])
                self.assertEqual(scope.removed_item_keys, set())

    def test_stale_animal_raw_without_current_items_is_cleared_without_guessing_values(
        self,
    ):
        old, _, _ = fixture(pet_only=True)
        old.update(
            pedido_id="703", valor_total_compra="18", valor_total_faturamento="23"
        )
        cleaned, retained = filter_pharmacy_order(old, [])
        self.assertEqual(cleaned["ultimo_pedido_raw"], "")
        self.assertEqual(cleaned["valor_total_faturamento"], "23")
        self.assertEqual(cleaned["farmalider_frete"], "5")
        self.assertEqual(retained, [])

    def test_category_is_not_copied_to_another_product_at_the_same_position(self):
        order, items, _ = fixture(pet_only=True)
        payload = json.loads(order["ultimo_pedido_raw"])
        payload["produtos"][0].update(nome="Fórmula XYZ", categoria="Veterinária")
        order["ultimo_pedido_raw"] = json.dumps(payload)
        items[0]["produto_nome"] = "Paracetamol 500 mg"
        items[0]["categoria"] = "Medicamentos humanos"
        scope = plan_pharmacy_scope([order], items)
        self.assertEqual(scope.removed_order_keys, set())
        self.assertEqual(scope.removed_item_keys, set())
        self.assertEqual(scope.items[0]["categoria"], "Medicamentos humanos")

    def test_old_pet_contact_raw_is_cleared_without_erasing_new_human_fields(self):
        _, _, current = fixture()
        _, _, old = fixture(pet_only=True, order_id="699")
        current.update(
            ultimo_pedido=old["ultimo_pedido"],
            pedido_id="703",
            pedido_produtos="Protetor solar humano",
            pedido_quantidade_itens="1",
            pedido_valor_produtos="18",
            pedido_valor="18",
        )
        cleaned = sanitize_contact_order(current)
        self.assertEqual(cleaned["ultimo_pedido"], "")
        self.assertEqual(cleaned["pedido_id"], "703")
        self.assertEqual(cleaned["pedido_produtos"], "Protetor solar humano")
        self.assertEqual(cleaned["pedido_valor"], "18")
        self.assertEqual(cleaned["cpf"], current["cpf"])
        self.assertEqual(cleaned["opt_in_lgpd"], current["opt_in_lgpd"])


if __name__ == "__main__":
    unittest.main()
