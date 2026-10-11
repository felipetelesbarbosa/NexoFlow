"""Caracteriza o contrato do parser antes de separar itens e totais."""

import json
import unittest

from analytics import parse_ultimo_pedido_raw
from pedido_utils import serialize_pedido_products


class OrderParserCharacterizationTests(unittest.TestCase):
    def payload(self):
        return {
            "pedido_id": "321",
            "data_hora": "2026-10-03T01:00:00Z",
            "valor_total_compra": "24,50",
            "quantidade_itens": "1.5",
            "farmalider_frete": "5,50",
            "produtos": [
                {
                    "codProduto": "9001",
                    "quantidade": "1.5",
                    "valor_unitario": "15.00",
                    "valor_total": "19.00",
                }
            ],
        }

    def parse(self, payload):
        return parse_ultimo_pedido_raw(
            json.dumps(payload),
            contact_uuid="contato-ficticio",
            phone="5591000000000",
            client_name="Cliente Fictício",
            cpf="0",
            modified_on="2026-10-03T01:30:00Z",
            captured_at="2026-10-03T02:00:00Z",
        )

    def test_items_preserve_discount_fractional_quantity_and_customer_context(self):
        order, items = self.parse(self.payload())
        self.assertEqual(order["status_validacao"], "OK")
        self.assertEqual(order["pedido_chave"], "FARMALIDER:321")
        self.assertEqual(order["valor_total_compra"], "19.00")
        self.assertEqual(order["valor_total_itens"], "19.00")
        self.assertEqual(order["valor_total_faturamento"], "24.50")
        self.assertEqual(order["diferenca_total"], "0.00")
        self.assertEqual(order["quantidade_itens"], "1.5")
        self.assertEqual(len(items), 1)
        self.assertEqual(
            {key: value for key, value in items[0].items() if key != "item_chave"},
            {
                "pedido_chave": "FARMALIDER:321",
                "pedido_id": "321",
                "data_hora": "2026-10-03T01:00:00Z",
                "data": "2026-10-02",
                "hora": "22:00:00",
                "contact_uuid": "contato-ficticio",
                "telefone": "5591000000000",
                "cliente": "Cliente Fictício",
                "produto_ordem": "1",
                "produto_nome": "",
                "produto_codigo": "9001",
                "quantidade": "1.5",
                "valor_unitario": "15.00",
                "valor_total": "19.00",
                "capturado_em": "2026-10-03T02:00:00Z",
            },
        )

    def test_total_tolerance_includes_freight_and_accepts_one_cent(self):
        for total, expected in (
            ("24.51", "OK"),
            ("24.49", "OK"),
            ("24.52", "ATENÇÃO_TOTAL_DIVERGENTE"),
        ):
            with self.subTest(total=total):
                payload = self.payload()
                payload["valor_total_compra"] = total
                order, items = self.parse(payload)
                self.assertEqual(order["status_validacao"], expected)
                self.assertEqual(len(items), 1)

    def test_serialization_keeps_item_array_separate_from_text_metadata(self):
        order, items = self.parse(self.payload())
        snapshot = json.loads(serialize_pedido_products(order, items))
        self.assertEqual(snapshot["pedido_id"], "321")
        self.assertEqual(snapshot["farmalider_frete"], "5.50")
        self.assertEqual(snapshot["quantidade_itens"], "1.5")
        self.assertEqual(
            snapshot["produtos"],
            [{
                "nome": None,
                "codigo": "9001",
                "quantidade": "1.5",
                "valor_unitario": "15.00",
                "valor_total": "19.00",
            }],
        )

    def test_invalid_later_item_discards_all_items(self):
        payload = self.payload()
        payload["produtos"].append({"nome": "Produto Fictício"})
        order, items = self.parse(payload)
        self.assertEqual(order["status_validacao"], "ERRO")
        self.assertEqual(order["status_confirmacao"], "ERRO_DADOS_WENI")
        self.assertEqual(order["erro_parse"], "quantidade está vazio.")
        self.assertEqual(items, [])
        self.assertEqual(order["contact_uuid"], "contato-ficticio")
        self.assertEqual(order["cpf_normalizado"], "0")

    def test_invalid_products_keep_specific_messages_and_empty_items(self):
        for product, message in (
            ("produto", "produto na posição 1 não é um objeto."),
            ({}, "produto na posição 1 sem nome ou código."),
            (
                {"nome": "Produto", "quantidade": "-1"},
                "quantidade não pode ser negativa.",
            ),
            (
                {
                    "nome": "Produto",
                    "quantidade": "1",
                    "valor_unitario": "-1",
                    "valor_total": "1",
                },
                "produto 1 possui valor negativo.",
            ),
        ):
            with self.subTest(product=product):
                payload = self.payload()
                payload["produtos"] = [product]
                order, items = self.parse(payload)
                self.assertEqual(order["status_validacao"], "ERRO")
                self.assertEqual(order["erro_parse"], message)
                self.assertEqual(items, [])

    def test_quantity_and_freight_validation_fail_closed(self):
        for update, message in (
            (
                {"quantidade_itens": "2"},
                "quantidade_itens diverge da soma das quantidades dos produtos.",
            ),
            ({"farmalider_frete": "-1"}, "farmalider_frete não pode ser negativo."),
            ({"farmalider_frete": "NaN"}, "farmalider_frete deve ser finito."),
        ):
            with self.subTest(update=update):
                payload = self.payload()
                payload.update(update)
                order, items = self.parse(payload)
                self.assertEqual(order["status_validacao"], "ERRO")
                self.assertEqual(order["erro_parse"], message)
                self.assertEqual(items, [])

    def test_empty_products_are_accepted_without_invented_items(self):
        payload = self.payload()
        payload.update(
            produtos=[], valor_total_compra="5.50", quantidade_itens="0"
        )
        order, items = self.parse(payload)
        self.assertEqual(order["status_validacao"], "OK")
        self.assertEqual(order["quantidade_produtos"], "0")
        self.assertEqual(order["quantidade_itens"], "0")
        self.assertEqual(order["valor_total_itens"], "0.00")
        self.assertEqual(order["valor_total_faturamento"], "5.50")
        self.assertEqual(items, [])
