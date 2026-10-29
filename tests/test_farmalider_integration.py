import json
import unittest

from analytics import (
    build_sales_metrics,
    is_valid_cpf,
    normalize_cpf,
    parse_ultimo_pedido_raw,
)
from farmalider_integration import (
    apply_pedido_api_confirmation,
    cliente_link_status,
)


class FarmaliderIntegrationTests(unittest.TestCase):
    def test_normalize_cpf(self):
        self.assertEqual(
            normalize_cpf("529.982.247-25"),
            "52998224725",
        )

    def test_numeric_cpf_lost_leading_zeros_is_restored_only_with_valid_checksum(self):
        full = "00000000191"
        self.assertTrue(is_valid_cpf(full))
        for raw in ("191", 191):
            self.assertEqual(normalize_cpf(raw), full)
            self.assertTrue(is_valid_cpf(raw))
        for raw in ("0", "123", "11111111111", "", "¹", "１２３"):
            self.assertEqual(normalize_cpf(raw), raw)
            self.assertFalse(is_valid_cpf(raw))
        self.assertEqual(normalize_cpf("52998224724"), "52998224724")
        self.assertFalse(is_valid_cpf("52998224724"))

    def test_zero_restored_valid_cpf_does_not_require_name_phone_or_email(self):
        self.assertEqual(
            cliente_link_status(
                "191",
                {"id": 321, "cpf": 191, "nome": "Cliente Teste"},
                weni_identity={},
            )[:2],
            ("CPF_CONFIRMADO", "321"),
        )

    def test_valid_cpf(self):
        self.assertTrue(is_valid_cpf("529.982.247-25"))
        self.assertFalse(is_valid_cpf("111.111.111-11"))

    def test_cliente_link(self):
        status, cliente_id, nome = cliente_link_status(
            "52998224725",
            {
                "id": 321,
                "cpf": 52998224725,
                "nome": "Cliente Teste",
            },
        )
        self.assertEqual(status, "CPF_CONFIRMADO")
        self.assertEqual(cliente_id, "321")
        self.assertEqual(nome, "Cliente Teste")

    def test_pedido_id_becomes_official_key(self):
        raw = json.dumps(
            {
                "pedido_id": 123456,
                "data_hora": "2026-09-30T16:07:00Z",
                "valor_total_compra": 110.80,
                "produtos": [
                    {
                        "nome": "Produto",
                        "quantidade": 1,
                        "valor_unitario": 110.80,
                        "valor_total": 110.80,
                    }
                ],
            }
        )
        order, items = parse_ultimo_pedido_raw(
            raw,
            contact_uuid="uuid-1",
            captured_at="2026-09-30T16:10:00+00:00",
        )
        self.assertEqual(order["pedido_id"], "123456")
        self.assertEqual(order["pedido_chave"], "FARMALIDER:123456")
        self.assertEqual(order["status_confirmacao"], "NAO_CONFIRMADO_API")
        self.assertEqual(items[0]["pedido_id"], "123456")

    def test_api_confirms_order_and_customer(self):
        raw = json.dumps(
            {
                "pedido_id": 123456,
                "data_hora": "2026-09-30T16:07:00Z",
                "valor_total_compra": 110.80,
                "produtos": [
                    {
                        "nome": "Produto",
                        "quantidade": 2,
                        "valor_unitario": 55.40,
                        "valor_total": 110.80,
                    }
                ],
            }
        )
        order, items = parse_ultimo_pedido_raw(
            raw,
            contact_uuid="uuid-1",
            captured_at="2026-09-30T16:10:00+00:00",
        )
        pedido_api = {
            "capa": {
                "id": 123456,
                "publicId": "00000000-0000-0000-0000-000000000001",
                "emissao": "2026-09-30T16:08:00Z",
                "codFilial": 24,
                "status": 1,
                "codCliente": 321,
                "formaPagamento": 1,
                "cupom": 999,
                "frete": 0,
                "pedidoWeb": "WEB-1",
                "cancelamento": None,
                "entrega": None,
            },
            "itens": [
                {
                    "codPedido": 123456,
                    "codProduto": 9999,
                    "descricao": "Produto oficial",
                    "quantidade": 2,
                    "valor": 55.40,
                    "total": 110.80,
                    "filialId": 24,
                    "desconto": 0,
                }
            ],
        }
        order, items = apply_pedido_api_confirmation(
            order,
            items,
            pedido_api,
            linked_cliente_id="321",
            confirmed_at="2026-09-30T16:11:00+00:00",
        )

        self.assertEqual(order["status_confirmacao"], "CONFIRMADO_API")
        self.assertEqual(order["data_hora"], "2026-09-30T13:08:00-03:00")
        self.assertEqual(order["valor_total_api_itens"], "110.80")
        self.assertEqual(order["quantidade_itens_api"], "2")
        self.assertEqual(order["farmalider_forma_pagamento"], "1")
        self.assertEqual(order["farmalider_forma_pagamento_nome"], "Dinheiro")
        self.assertEqual(items[0]["produto_nome"], "Produto oficial")

    def test_cancelled_order_is_not_counted_in_sales_metric(self):
        order = {
            "pedido_chave": "FARMALIDER:1",
            "data": "2026-09-30",
            "contact_uuid": "u1",
            "valor_total_compra": "100.00",
            "status_validacao": "OK",
            "status_confirmacao": "CONFIRMADO_API",
            "farmalider_cancelamento": "2026-09-30T20:00:00Z",
        }
        rows = build_sales_metrics([order], [])
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
# NexoFlow 1.5.3
