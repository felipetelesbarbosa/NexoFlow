import json
import unittest

from analytics import parse_ultimo_pedido_raw


class WebhookPreparationTests(unittest.TestCase):
    def test_reusable_raw_parser(self):
        payload = {
            "data_hora": "2026-09-30T16:07:00Z",
            "valor_total_compra": 110.80,
            "produtos": [
                {
                    "nome": "Produto A",
                    "quantidade": 2,
                    "valor_unitario": 8.50,
                    "valor_total": 16.00,
                },
                {
                    "nome": "Produto B",
                    "quantidade": 1,
                    "valor_unitario": 94.80,
                    "valor_total": 94.80,
                },
            ],
        }

        order, items = parse_ultimo_pedido_raw(
            json.dumps(payload),
            contact_uuid="abc-123",
            phone="+5591999999999",
            client_name="Cliente",
            captured_at="2026-09-30T16:08:00+00:00",
        )

        self.assertEqual(order["status_validacao"], "OK")
        self.assertEqual(order["valor_total_compra"], "110.80")
        self.assertEqual(len(items), 2)

    def test_same_raw_parser_generates_stable_key(self):
        raw = json.dumps({
            "data_hora": "2026-09-30T16:07:00Z",
            "valor_total_compra": 10,
            "produtos": [{
                "nome": "Produto",
                "quantidade": 1,
                "valor_unitario": 10,
                "valor_total": 10,
            }],
        })

        first, _ = parse_ultimo_pedido_raw(
            raw,
            contact_uuid="abc",
            captured_at="2026-09-30T16:08:00+00:00",
        )
        second, _ = parse_ultimo_pedido_raw(
            raw,
            contact_uuid="abc",
            captured_at="2026-09-30T17:08:00+00:00",
        )

        self.assertEqual(
            first["pedido_chave"],
            second["pedido_chave"],
        )


if __name__ == "__main__":
    unittest.main()
