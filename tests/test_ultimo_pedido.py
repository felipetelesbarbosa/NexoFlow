import json
import unittest

from analytics import (
    BASE_COLUMNS,
    ORDER_COLUMNS,
    ORDER_ITEM_COLUMNS,
    build_sales_metrics,
    normalize_contact,
    parse_ultimo_pedido,
)

EXAMPLE_PAYLOAD = {
    "data_hora": "2026-09-30T16:07:00Z",
    "valor_total_compra": 110.80,
    "farmalider_status_pedido": 2,
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
        self.assertEqual(order["hora"], "13:07:00")
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
        self.assertEqual(metrics, [])

    def derived_contact(self, *, raw="", date="2026-10-03T01:00:00Z", metadata=None):
        envelope = {
            "pedido_id": "321",
            "farmalider_status_pedido": 2,
            "produtos": [
                {
                    "codigo": "9001",
                    "nome": "",
                    "quantidade": 2,
                    "valor_unitario": "10.00",
                    "valor_total": "19.00",
                }
            ],
            **(metadata or {}),
        }
        contact = sample_contact(raw)
        contact["fields"].update(
            {
                "pedido_id": {"value": "321"},
                "pedido_data": {"value": date},
                "pedido_produtos": {"value": json.dumps(envelope)},
                "pedido_quantidade_itens": {"value": "2"},
                "pedido_valor": {"value": "19.00"},
            }
        )
        return contact

    def test_derived_order_with_product_code_reaches_sales_without_raw(self):
        contact = self.derived_contact()
        order, items = parse_ultimo_pedido(contact, "2026-10-03T04:00:00Z")
        self.assertEqual(order["pedido_chave"], "FARMALIDER:321")
        self.assertEqual(order["data"], "2026-10-02")
        self.assertEqual(order["hora"], "22:00:00")
        self.assertEqual(order["ultimo_pedido_raw"], "")
        self.assertEqual(order["status_confirmacao"], "NAO_CONFIRMADO_API")
        self.assertEqual(items[0]["produto_nome"], "")
        self.assertEqual(items[0]["produto_codigo"], "9001")
        self.assertEqual(items[0]["valor_total"], "19.00")
        self.assertEqual(build_sales_metrics([order], items), [])

    def test_populated_invalid_raw_is_preserved_without_derived_recovery(self):
        contact = self.derived_contact(raw="{invalid original}")
        order, items = parse_ultimo_pedido(contact, "2026-10-03T04:00:00Z")
        self.assertEqual(order["status_validacao"], "ERRO")
        self.assertEqual(order["ultimo_pedido_raw"], "{invalid original}")
        self.assertTrue(order["erro_parse"])
        self.assertEqual(items, [])

    def test_verified_snapshot_can_update_only_the_same_official_order(self):
        raw = json.dumps({**EXAMPLE_PAYLOAD, "pedido_id": "321"})
        contact = self.derived_contact(raw=raw)
        order, _ = parse_ultimo_pedido(contact, "2026-10-03T04:00:00Z")
        self.assertEqual(order["data_hora"], EXAMPLE_PAYLOAD["data_hora"])
        contact["fields"]["pedido_produtos"]["value"] = json.dumps(
            {
                **json.loads(contact["fields"]["pedido_produtos"]["value"]),
                "status_confirmacao": "CONFIRMADO_API",
                "origem_pedido": "FARMALIDER_API",
            }
        )
        order, _ = parse_ultimo_pedido(contact, "2026-10-03T04:00:00Z")
        self.assertEqual(order["pedido_id"], "321")
        self.assertEqual(order["data_hora"], "2026-10-03T01:00:00Z")
        self.assertEqual(order["valor_total_compra"], "19.00")
        self.assertEqual(order["ultimo_pedido_raw"], raw)
        contact["fields"]["pedido_data"]["value"] = "2026-09-29T13:00:00-03:00"
        older, _ = parse_ultimo_pedido(contact, "2026-10-03T04:00:00Z")
        self.assertEqual(older["data_hora"], EXAMPLE_PAYLOAD["data_hora"])

    def test_verified_different_or_missing_order_id_cannot_replace_populated_raw(self):
        for original_id in (None, "999", "invalid", "0"):
            with self.subTest(original_id=original_id):
                payload = dict(EXAMPLE_PAYLOAD)
                if original_id is not None:
                    payload["pedido_id"] = original_id
                raw = json.dumps(payload)
                contact = self.derived_contact(
                    raw=raw,
                    metadata={
                        "status_confirmacao": "CONFIRMADO_API",
                        "origem_pedido": "FARMALIDER_API",
                    },
                )
                order, items = parse_ultimo_pedido(contact, "2026-10-03T04:00:00Z")
                self.assertEqual(order["data_hora"], EXAMPLE_PAYLOAD["data_hora"])
                self.assertEqual(order["valor_total_compra"], "110.80")
                self.assertEqual(order["ultimo_pedido_raw"], raw)
                self.assertEqual(len(items), 3)

    def test_same_order_snapshot_preserves_cancellation_without_replacing_identity(
        self,
    ):
        raw = json.dumps({**EXAMPLE_PAYLOAD, "pedido_id": "321"})
        contact = self.derived_contact(
            raw=raw,
            metadata={
                "status_confirmacao": "CANCELADO_API",
                "origem_pedido": "FARMALIDER_API",
                "farmalider_status_pedido": "3",
                "farmalider_status_pedido_nome": "Cancelado",
            },
        )
        order, items = parse_ultimo_pedido(contact, "2026-10-03T04:00:00Z")
        self.assertEqual(order["pedido_id"], "321")
        self.assertEqual(order["ultimo_pedido_raw"], raw)
        self.assertEqual(order["status_confirmacao"], "CANCELADO_API")
        self.assertEqual(order["farmalider_status_pedido_nome"], "Cancelado")
        self.assertEqual(build_sales_metrics([order], items), [])

    def test_derived_id_must_match_product_envelope(self):
        contact = self.derived_contact(metadata={"pedido_id": "other"})
        order, items = parse_ultimo_pedido(contact, "2026-10-03T04:00:00Z")
        self.assertEqual(order["status_validacao"], "ERRO")
        self.assertEqual(items, [])

    def test_legacy_product_summary_and_missing_prices_are_not_invented(self):
        contact = self.derived_contact()
        for products in ("Produto x2", [{"nome": "Produto", "quantidade": 2}]):
            with self.subTest(products=products):
                contact["fields"]["pedido_produtos"] = products
                order, items = parse_ultimo_pedido(contact, "2026-10-03T04:00:00Z")
                self.assertEqual(order["status_validacao"], "ERRO")
                self.assertEqual(items, [])

    def test_nonfinite_values_and_quantity_mismatch_are_errors(self):
        for value in ("NaN", "Infinity", "-Infinity", True):
            with self.subTest(value=value):
                payload = {**EXAMPLE_PAYLOAD, "valor_total_compra": value}
                order, items = parse_ultimo_pedido(
                    sample_contact(json.dumps(payload)), "2026-10-03T04:00:00Z"
                )
                self.assertEqual(order["status_validacao"], "ERRO")
                self.assertEqual(items, [])
        contact = self.derived_contact()
        contact["fields"]["pedido_quantidade_itens"] = "1"
        order, items = parse_ultimo_pedido(contact, "2026-10-03T04:00:00Z")
        self.assertEqual(order["status_validacao"], "ERRO")
        self.assertEqual(items, [])

    def test_derived_snapshot_normalization_and_keys_are_stable(self):
        contact = self.derived_contact()
        row = normalize_contact(contact, "2026-10-03T04:00:00Z")
        for key in (
            "pedido_id",
            "pedido_data",
            "pedido_produtos",
            "pedido_quantidade_itens",
            "pedido_valor",
        ):
            self.assertIn(key, BASE_COLUMNS)
            self.assertTrue(row[key])
        self.assertIn("produto_codigo", ORDER_ITEM_COLUMNS)
        first, items1 = parse_ultimo_pedido(contact, "2026-10-03T04:00:00Z")
        second, items2 = parse_ultimo_pedido(contact, "2026-10-04T04:00:00Z")
        self.assertEqual(first["pedido_chave"], second["pedido_chave"])
        self.assertEqual(items1[0]["item_chave"], items2[0]["item_chave"])

    def test_canonical_freight_total_round_trips_without_false_divergence(self):
        contact = self.derived_contact(
            metadata={
                "status_confirmacao": "CONFIRMADO_API",
                "status_validacao": "OK",
                "farmalider_frete": "9.99",
                "valor_total_compra": "28.99",
                "valor_origem": "SOMA_ITENS_MAIS_FRETE_API",
            }
        )
        contact["fields"]["pedido_valor"] = "28.99"
        order, items = parse_ultimo_pedido(contact, "2026-10-03T04:00:00Z")
        self.assertEqual(order["status_validacao"], "OK")
        self.assertEqual(order["valor_total_itens"], "19.00")
        self.assertEqual(order["valor_total_compra"], "19.00")
        self.assertEqual(order["valor_total_faturamento"], "28.99")
        self.assertEqual(order["diferenca_total"], "0.00")
        self.assertEqual(items[0]["valor_total"], "19.00")

    def test_partial_api_total_does_not_become_complete_after_round_trip(self):
        contact = self.derived_contact(
            metadata={
                "status_confirmacao": "CONFIRMADO_API",
                "status_validacao": "ATENCAO_TOTAL_PARCIAL",
                "valor_origem": "SOMA_ITENS_API",
            }
        )
        order, items = parse_ultimo_pedido(contact, "2026-10-03T04:00:00Z")
        self.assertEqual(order["status_validacao"], "ATENCAO_TOTAL_PARCIAL")
        self.assertEqual(build_sales_metrics([order], items), [])

    def test_derived_snapshot_preserves_official_enum_label_without_inventing_unknowns(
        self,
    ):
        self.assertIn("farmalider_status_pedido_nome", ORDER_COLUMNS)
        contact = self.derived_contact(
            metadata={
                "status_confirmacao": "CANCELADO_API",
                "farmalider_status_pedido": "3",
                "farmalider_status_pedido_nome": "Cancelado",
                "farmalider_cancelamento": "",
            }
        )
        order, items = parse_ultimo_pedido(contact, "2026-10-03T04:00:00Z")
        self.assertEqual(order["farmalider_status_pedido_nome"], "Cancelado")
        self.assertEqual(build_sales_metrics([order], items), [])
        unknown = self.derived_contact(metadata={"farmalider_status_pedido": "99"})
        unknown_order, _ = parse_ultimo_pedido(unknown, "2026-10-03T04:00:00Z")
        self.assertEqual(unknown_order["farmalider_status_pedido_nome"], "")


if __name__ == "__main__":
    unittest.main()
# NexoFlow 1.5.3
