"""Synthetic integration tests for the FarmaLíder-first order architecture."""
import json
import re
import unittest
from unittest.mock import Mock

from analytics import (
    ORDER_COLUMNS,
    ORDER_ITEM_COLUMNS,
    build_bi_conversion_records,
    build_bi_summary_record,
    build_sales_metrics,
    normalize_contact,
)
from google_sheets import GoogleSheetsStore
from main import FarmaliderSettings, build_orders, split_contacts, validate_contacts


class MemoryWorksheet:
    def __init__(self, title, headers):
        self.title = title
        self.values = [list(headers)]

    def get_all_values(self):
        return [row[:] for row in self.values]

    def append_rows(self, rows, **kwargs):
        self.values.extend([row[:] for row in rows])

    def batch_update(self, updates, **kwargs):
        for update in updates:
            row = int(re.search(r"A(\d+):", update["range"])[1])
            self.values[row - 1] = update["values"][0][:]


class AnalyticsOrderFlowTests(unittest.TestCase):
    def fixture(self, *, status=2, cancelled=False, freight="9.99"):
        contact = {"uuid": "synthetic-u1", "fields": {"cpf": "52998224725"}}
        client = Mock()
        cliente_items = [{
            "codPedido": 500,
            "codProduto": 9001,
            "descricao": "Produto sintético",
            "quantidade": 2,
            "valor": "10.00",
            "total": "19.50",
        }]
        client.get_cliente_by_cpf.return_value = {
            "cliente": {
                "id": 99,
                "cpf": "52998224725",
                "nome": "Cliente sintético",
            },
            "ultimoPedido": {
                "id": 500,
                "codCliente": 99,
                "emissao": "2026-10-05T10:00:00",
                "status": status,
                "formaPagamento": 2,
                "frete": freight,
                "cancelamento": (
                    "2026-10-05T11:00:00" if cancelled else None
                ),
            },
            "itens": cliente_items,
        }
        client.get_pedido.return_value = {
            "capa": {
                "id": 500,
                "codCliente": 99,
                "emissao": "2026-10-05T10:00:00",
                "status": status,
                "formaPagamento": 2,
                "frete": freight,
                "cancelamento": (
                    "2026-10-05T11:00:00" if cancelled else None
                ),
            },
            "itens": [dict(cliente_items[0])],
        }
        client.metrics_snapshot.return_value = {
            "total_requests": 1,
            "retries": 0,
            "rate_limits": 0,
            "server_errors": 0,
            "network_errors": 0,
            "average_response_ms": 1,
            "max_response_ms": 1,
            "effective_delay_ms": 0,
        }
        return contact, client

    def resolve_and_persist(self, contact, client):
        _, _, processed = split_contacts([contact])
        row = normalize_contact(contact, "2026-10-05T14:00:00Z")
        responses = {}
        validate_contacts(
            [row],
            farm_client=client,
            farm_settings=FarmaliderSettings(True, "synthetic-token", False),
            sync_time="2026-10-05T14:00:00Z",
            cliente_responses_by_cpf=responses,
        )
        orders, items, _ = build_orders(
            processed,
            rows_by_uuid={row["contact_uuid"]: row},
            farm_client=client,
            sync_time="2026-10-05T14:00:00Z",
            cliente_responses_by_cpf=responses,
        )
        store = GoogleSheetsStore.__new__(GoogleSheetsStore)
        store.orders = MemoryWorksheet("Pedidos", ORDER_COLUMNS)
        store.order_items = MemoryWorksheet("Itens_Pedido", ORDER_ITEM_COLUMNS)
        store._read_with_retry = lambda label, operation: operation()
        store._write_with_retry = lambda label, operation: operation()
        first = store.upsert_orders_detailed(orders)
        first_items = store.upsert_order_items_detailed(items)
        repeated = store.upsert_orders_detailed(orders)
        repeated_items = store.upsert_order_items_detailed(items)
        self.assertEqual(first.inserted, 1)
        self.assertEqual(repeated.inserted, 0)
        self.assertEqual(repeated.unchanged, 1)
        self.assertEqual(repeated_items.inserted, 0)
        self.assertEqual(repeated_items.unchanged, len(items))
        return row, repeated.final_records, first_items.final_records

    def test_normalized_contact_exposes_raw_status_payment_and_labels(self):
        contact = {
            "uuid": "u1",
            "fields": {
                "pedido_status": "3",
                "pedido_forma_pagamento": "2",
            },
        }
        row = normalize_contact(contact, "2026-10-05T14:00:00Z")
        self.assertEqual(row["pedido_status"], "3")
        self.assertEqual(row["pedido_status_nome"], "Cancelado")
        self.assertEqual(row["pedido_forma_pagamento"], "2")
        self.assertEqual(row["pedido_forma_pagamento_nome"], "Débito")

    def test_cpf_contact_uses_description_and_item_total_without_freight(self):
        contact, client = self.fixture()
        row, orders, items = self.resolve_and_persist(contact, client)
        self.assertEqual(orders[0]["pedido_chave"], "FARMALIDER:500")
        self.assertEqual(orders[0]["valor_total_compra"], "19.50")
        self.assertEqual(orders[0]["valor_origem"], "SOMA_ITENS_API")
        self.assertEqual(orders[0]["farmalider_frete"], "9.99")
        self.assertEqual(orders[0]["farmalider_forma_pagamento"], "2")
        self.assertEqual(
            orders[0]["farmalider_forma_pagamento_nome"], "Débito"
        )
        self.assertEqual(items[0]["produto_codigo"], "9001")
        self.assertEqual(items[0]["produto_nome"], "Produto sintético")
        self.assertEqual(
            build_sales_metrics(orders, items),
            [["2026-10-05", 1, 1, 1, "2", "19.50", "19.50"]],
        )
        summary = build_bi_summary_record(
            [row],
            orders,
            items,
            snapshot_date="2026-10-05",
            updated_at="2026-10-05T14:00:00Z",
        )
        self.assertEqual(summary["faturamento_total"], 19.5)
        self.assertEqual(summary["unidades_vendidas_dia"], 2)

    def test_api_first_ignores_stale_weni_order_identity(self):
        contact, client = self.fixture()
        contact["fields"]["ultimo_pedido"] = json.dumps({
            "pedido_id": "400",
            "data_hora": "2026-10-01T10:00:00-03:00",
            "valor_total_compra": "1.00",
            "produtos": [{
                "nome": "Pedido antigo",
                "quantidade": 1,
                "valor_unitario": 1,
                "valor_total": 1,
            }],
        })
        _, orders, items = self.resolve_and_persist(contact, client)
        self.assertEqual(orders[0]["pedido_id"], "500")
        self.assertEqual(items[0]["produto_nome"], "Produto sintético")
        client.get_cliente_by_cpf.assert_called_once_with("52998224725")
        client.get_pedido.assert_called_once_with("500")

    def test_pedido_endpoint_description_is_final_product_name(self):
        contact, client = self.fixture()
        client.get_cliente_by_cpf.return_value["itens"][0]["descricao"] = (
            "Descrição do GET CPF"
        )
        client.get_pedido.return_value["itens"][0]["descricao"] = (
            "Descrição atual do GET pedido"
        )
        _, orders, items = self.resolve_and_persist(contact, client)
        self.assertEqual(orders[0]["status_validacao"], "OK")
        self.assertEqual(
            items[0]["produto_nome"], "Descrição atual do GET pedido"
        )

    def test_missing_description_rejects_pedido_snapshot(self):
        contact, client = self.fixture()
        del client.get_pedido.return_value["itens"][0]["descricao"]
        del client.get_cliente_by_cpf.return_value["itens"][0]["descricao"]
        _, orders, items = self.resolve_and_persist(contact, client)
        self.assertEqual(items, [])
        self.assertTrue(
            not orders or orders[0]["status_validacao"] == "ERRO"
        )

    def test_cancelled_latest_order_is_auditable_but_not_sale(self):
        contact, client = self.fixture(status=3, cancelled=True)
        _, orders, items = self.resolve_and_persist(contact, client)
        self.assertEqual(orders[0]["status_confirmacao"], "CANCELADO_API")
        self.assertEqual(orders[0]["farmalider_status_pedido"], "3")
        self.assertEqual(build_sales_metrics(orders, items), [])
        conversion = build_bi_conversion_records(
            [],
            orders,
            snapshot_date="2026-10-05",
            updated_at="2026-10-05T14:00:00Z",
        )
        self.assertEqual(conversion[-1]["quantidade"], 0)

    def test_documented_non_cancelled_states_enter_sales(self):
        for status in (0, 1, 2, 4):
            with self.subTest(status=status):
                contact, client = self.fixture(status=status)
                _, orders, items = self.resolve_and_persist(contact, client)
                self.assertEqual(len(build_sales_metrics(orders, items)), 1)

    def test_cancelled_and_unknown_states_stay_out_of_sales(self):
        for status in (3, 99):
            with self.subTest(status=status):
                contact, client = self.fixture(status=status)
                _, orders, items = self.resolve_and_persist(contact, client)
                self.assertEqual(build_sales_metrics(orders, items), [])

    def test_repeated_product_descriptions_keep_distinct_items(self):
        contact, client = self.fixture()
        second = {
            "codPedido": 500,
            "codProduto": 9002,
            "descricao": "Produto sintético",
            "quantidade": 1,
            "valor": "5.00",
            "total": "5.00",
        }
        client.get_pedido.return_value["itens"].append(second)
        client.get_cliente_by_cpf.return_value["itens"].append(dict(second))
        _, orders, items = self.resolve_and_persist(contact, client)
        self.assertEqual(len(items), 2)
        self.assertEqual(
            [item["produto_nome"] for item in items],
            ["Produto sintético", "Produto sintético"],
        )
        self.assertEqual(orders[0]["valor_total_compra"], "24.50")

    def test_two_contacts_same_cpf_keep_single_official_order(self):
        first, client = self.fixture()
        second = {
            "uuid": "synthetic-u2",
            "fields": {"cpf": "52998224725"},
        }
        rows = [
            normalize_contact(first, "2026-10-05T14:00:00Z"),
            normalize_contact(second, "2026-10-05T14:00:00Z"),
        ]
        responses = {"52998224725": client.get_cliente_by_cpf.return_value}
        orders, items, _ = build_orders(
            [first, second],
            rows_by_uuid={row["contact_uuid"]: row for row in rows},
            farm_client=client,
            sync_time="2026-10-05T14:00:00Z",
            cliente_responses_by_cpf=responses,
        )
        self.assertEqual(len(orders), 1)
        self.assertEqual(len(items), 1)
        self.assertEqual(orders[0]["pedido_id"], "500")


if __name__ == "__main__":
    unittest.main()

# NexoFlow 1.0
