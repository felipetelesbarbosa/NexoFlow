import json
import unittest

from analytics import (
    build_sales_metrics,
    normalize_contact,
    parse_ultimo_pedido,
)


EXAMPLE_PAYLOAD = {
    "data_hora": "2026-09-30T16:07:00Z",
    "valor_total_compra": 110.80,
    "produtos": [
        {
            "nome": "Dipirona Gotas 20ml",
            "quantidade": 2,
            "valor_unitario": 8.50,
            "valor_total": 16.00,
        },
        {
            "nome": "Amoxicilina 500mg 21 caps",
            "quantidade": 1,
            "valor_unitario": 34.90,
            "valor_total": 34.90,
        },
        {
            "nome": "Protetor Solar FPS 50 200ml",
            "quantidade": 1,
            "valor_unitario": 59.90,
            "valor_total": 59.90,
        },
    ],
}

EXAMPLE_JSON = json.dumps(
    EXAMPLE_PAYLOAD,
    ensure_ascii=False,
)


def sample_contact(raw=EXAMPLE_JSON):
    return {
        "uuid": "contact-123",
        "name": "Cliente Teste",
        "urns": ["tel:+5591999999999"],
        "created_on": "2026-09-01T10:00:00Z",
        "modified_on": "2026-09-30T16:08:00Z",
        "fields": {
            "nome": "Cliente Teste",
            "cpf": "12345678900",
            "ultimo_pedido": {"value": raw},
        },
    }


class UltimoPedidoTests(unittest.TestCase):
    def test_parses_user_example(self):
        order, items = parse_ultimo_pedido(
            sample_contact(),
            "2026-09-30T16:10:00+00:00",
        )

        self.assertIsNotNone(order)
        self.assertEqual(order["data_hora"], "2026-09-30T16:07:00Z")
        self.assertEqual(order["data"], "2026-09-30")
        self.assertEqual(order["hora"], "16:07:00")
        self.assertEqual(order["valor_total_compra"], "110.80")
        self.assertEqual(order["valor_total_itens"], "110.80")
        self.assertEqual(order["quantidade_produtos"], "3")
        self.assertEqual(order["quantidade_itens"], "4")
        self.assertEqual(order["status_validacao"], "OK")
        self.assertEqual(len(items), 3)

    def test_does_not_recalculate_item_total(self):
        _, items = parse_ultimo_pedido(
            sample_contact(),
            "2026-09-30T16:10:00+00:00",
        )
        self.assertEqual(items[0]["valor_total"], "16.00")

    def test_same_contact_and_datetime_produce_same_order_key(self):
        first, _ = parse_ultimo_pedido(
            sample_contact(),
            "2026-09-30T16:10:00+00:00",
        )
        second, _ = parse_ultimo_pedido(
            sample_contact(),
            "2026-09-30T17:10:00+00:00",
        )
        self.assertEqual(
            first["pedido_chave"],
            second["pedido_chave"],
        )

    def test_invalid_json_creates_error_record(self):
        order, items = parse_ultimo_pedido(
            sample_contact("{não é json"),
            "2026-09-30T16:10:00+00:00",
        )
        self.assertEqual(order["status_validacao"], "ERRO")
        self.assertTrue(order["erro_parse"])
        self.assertEqual(items, [])

    def test_normalize_contact_keeps_raw_ultimo_pedido(self):
        row = normalize_contact(
            sample_contact(),
            "2026-09-30T16:10:00+00:00",
        )
        self.assertIn('"data_hora"', row["ultimo_pedido"])

    def test_sales_metrics_do_not_duplicate_order_per_product(self):
        order, items = parse_ultimo_pedido(
            sample_contact(),
            "2026-09-30T16:10:00+00:00",
        )
        metrics = build_sales_metrics([order], items)
        self.assertEqual(
            metrics,
            [["2026-09-30", 1, 0, 1, "4", "110.80", "0.00"]],
        )


if __name__ == "__main__":
    unittest.main()
