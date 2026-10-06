"""Synthetic integration of latest order resolution, persistence and BI."""
import re
import unittest
from unittest.mock import Mock

from analytics import (
    ORDER_COLUMNS, ORDER_ITEM_COLUMNS, build_bi_conversion_records,
    build_bi_summary_record, build_sales_metrics, normalize_contact,
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
    def fixture(self, *, cancelled=False, partial=False):
        contact = {"uuid": "synthetic-u1", "fields": {"cpf": "52998224725"}}
        client = Mock()
        client.get_cliente_by_cpf.return_value = {
            "cliente": {"id": 99, "cpf": "52998224725", "nome": "Cliente sintético"},
            "ultimoPedido": {"id": 500, "codCliente": 99},
        }
        capa = {"id": 500, "codCliente": 99, "emissao": "2026-10-05T10:00:00",
                "status": 3 if cancelled else 2,
                "cancelamento": "2026-10-05T11:00:00" if cancelled else None}
        if not partial:
            capa["frete"] = "9.99"
        client.get_pedido.return_value = {
            "capa": capa,
            "itens": [{"codPedido": 500, "codProduto": 9001, "quantidade": 2,
                       "valor": "10.00", "total": "19.50"}],
        }
        client.metrics_snapshot.return_value = {
            "total_requests": 1, "retries": 0, "rate_limits": 0, "server_errors": 0,
            "network_errors": 0, "average_response_ms": 1, "max_response_ms": 1,
            "effective_delay_ms": 0,
        }
        return contact, client

    def resolve_and_persist(self, contact, client):
        _, _, processed = split_contacts([contact])
        row = normalize_contact(contact, "2026-10-05T14:00:00Z")
        responses = {}
        validate_contacts([row], farm_client=client,
                          farm_settings=FarmaliderSettings(True, "synthetic-token", False),
                          sync_time="2026-10-05T14:00:00Z", cliente_responses_by_cpf=responses)
        orders, items, _ = build_orders(processed, rows_by_uuid={row["contact_uuid"]: row},
            farm_client=client, sync_time="2026-10-05T14:00:00Z", cliente_responses_by_cpf=responses)
        store = GoogleSheetsStore.__new__(GoogleSheetsStore)
        store.orders = MemoryWorksheet("Pedidos", ORDER_COLUMNS)
        store.order_items = MemoryWorksheet("Itens_Pedido", ORDER_ITEM_COLUMNS)
        store._read_with_retry = lambda label, operation: operation()
        store._write_with_retry = lambda label, operation: operation()
        first = store.upsert_orders_detailed(orders)
        stored_items = store.upsert_order_items_detailed(items)
        repeated = store.upsert_orders_detailed(orders)
        repeated_items = store.upsert_order_items_detailed(items)
        self.assertEqual(first.inserted, 1)
        self.assertEqual(repeated.inserted, 0)
        self.assertEqual(repeated_items.inserted, 0)
        self.assertEqual(repeated.unchanged, 1)
        self.assertEqual(repeated_items.unchanged, len(items))
        client.get_cliente_by_cpf.assert_called_once_with("52998224725")
        client.get_pedido.assert_called_once_with("500")
        return row, repeated.final_records, stored_items.final_records

    def test_cpf_only_contact_resolves_latest_order_once_and_persists_for_bi(self):
        contact, client = self.fixture()
        row, orders, items = self.resolve_and_persist(contact, client)
        self.assertEqual(orders[0]["pedido_chave"], "FARMALIDER:500")
        self.assertEqual(orders[0]["valor_total_compra"], "29.49")
        self.assertEqual(orders[0]["valor_origem"], "SOMA_ITENS_MAIS_FRETE_API")
        self.assertEqual(items[0]["produto_codigo"], "9001")
        self.assertEqual(items[0]["produto_nome"], "")
        self.assertEqual(build_sales_metrics(orders, items),
                         [["2026-10-05", 1, 1, 1, "2", "29.49", "29.49"]])
        summary = build_bi_summary_record([row], orders, items,
            snapshot_date="2026-10-05", updated_at="2026-10-05T14:00:00Z")
        self.assertEqual(summary["faturamento_total"], 29.49)
        self.assertEqual(summary["unidades_vendidas_dia"], 2)

    def test_textual_codproduto_is_persisted_as_name_without_changing_sales(self):
        contact, client = self.fixture()
        client.get_pedido.return_value["itens"][0]["codProduto"] = "Produto sintético A"
        _, orders, items = self.resolve_and_persist(contact, client)
        self.assertEqual(items[0]["produto_nome"], "Produto sintético A")
        self.assertEqual(items[0]["produto_codigo"], "")
        self.assertEqual(items[0]["quantidade"], "2")
        self.assertEqual(items[0]["valor_total"], "19.50")
        self.assertEqual(build_sales_metrics(orders, items),
            [["2026-10-05", 1, 1, 1, "2", "29.49", "29.49"]])

    def test_explicit_api_name_and_description_take_priority_over_codproduto_text(self):
        for field in ("nome", "descricao"):
            with self.subTest(field=field):
                contact, client = self.fixture()
                client.get_pedido.return_value["itens"][0].update({
                    "codProduto": "Texto alternativo do produto", field: "Descrição explícita atual"})
                _, _, items = self.resolve_and_persist(contact, client)
                self.assertEqual(items[0]["produto_nome"], "Descrição explícita atual")
                self.assertEqual(items[0]["produto_codigo"], "")

    def test_repeated_product_names_keep_distinct_items_and_idempotent_sales(self):
        contact, client = self.fixture()
        client.get_pedido.return_value["itens"] = [
            {"codPedido": 500, "codProduto": "Produto sintético repetido",
             "quantidade": 2, "valor": "10.00", "total": "19.50"},
            {"codPedido": 500, "codProduto": "Produto sintético repetido",
             "quantidade": 1, "valor": "10.00", "total": "9.75"},
        ]
        row = normalize_contact(contact, "2026-10-05T14:00:00Z")
        responses = {"52998224725": client.get_cliente_by_cpf.return_value}
        kwargs = {"rows_by_uuid": {row["contact_uuid"]: row}, "farm_client": client,
                  "cliente_responses_by_cpf": responses}
        first_orders, first_items, _ = build_orders([contact], sync_time="2026-10-05T14:00:00Z", **kwargs)
        next_orders, next_items, _ = build_orders([contact], sync_time="2026-10-05T14:10:00Z", **kwargs)
        self.assertEqual([item["produto_ordem"] for item in first_items],
                         [item["produto_ordem"] for item in next_items])
        self.assertEqual(len(first_items), 2)
        self.assertEqual({item["produto_ordem"] for item in first_items}, {"1", "2"})
        self.assertEqual(len({item["item_chave"] for item in first_items}), 2)
        self.assertEqual({item["produto_nome"] for item in first_items}, {"Produto sintético repetido"})
        self.assertEqual({item["produto_codigo"] for item in first_items}, {""})
        store = GoogleSheetsStore.__new__(GoogleSheetsStore)
        store.orders = MemoryWorksheet("Pedidos", ORDER_COLUMNS)
        store.order_items = MemoryWorksheet("Itens_Pedido", ORDER_ITEM_COLUMNS)
        store._read_with_retry = lambda label, operation: operation()
        store._write_with_retry = lambda label, operation: operation()
        store.upsert_orders_detailed(first_orders)
        store.upsert_order_items_detailed(first_items)
        repeated = store.upsert_orders_detailed(next_orders)
        repeated_items = store.upsert_order_items_detailed(next_items)
        self.assertEqual(repeated.unchanged, 1)
        self.assertEqual(repeated_items.unchanged, 2)
        self.assertEqual(repeated.inserted, 0)
        self.assertEqual(repeated_items.inserted, 0)
        self.assertEqual(len(store.orders.values), 2)
        self.assertEqual(len(store.order_items.values), 3)
        self.assertEqual(build_sales_metrics(repeated.final_records, repeated_items.final_records),
            [["2026-10-05", 1, 1, 1, "3", "39.24", "39.24"]])
        client.get_cliente_by_cpf.assert_not_called()
        self.assertEqual(client.get_pedido.call_count, 2)

    def test_cancelled_latest_order_is_saved_without_sales_or_buyers(self):
        contact, client = self.fixture(cancelled=True)
        row, orders, items = self.resolve_and_persist(contact, client)
        self.assertEqual(orders[0]["status_confirmacao"], "CANCELADO_API")
        self.assertEqual(len(items), 1)
        self.assertEqual(build_sales_metrics(orders, items), [])
        summary = build_bi_summary_record([row], orders, items,
            snapshot_date="2026-10-05", updated_at="2026-10-05T14:00:00Z")
        self.assertEqual(summary["pedidos_total"], 0)
        self.assertEqual(summary["faturamento_total"], 0)
        conversion = build_bi_conversion_records([row], orders,
            snapshot_date="2026-10-05", updated_at="2026-10-05T14:00:00Z")
        self.assertEqual(conversion[-1]["quantidade"], 0)

    def test_official_cancelled_enum_without_timestamp_is_saved_and_excluded(self):
        contact, client = self.fixture()
        client.get_pedido.return_value["capa"].update({"status": 3, "cancelamento": None})
        row, orders, items = self.resolve_and_persist(contact, client)
        self.assertEqual(orders[0]["farmalider_status_pedido"], "3")
        self.assertEqual(orders[0]["farmalider_status_pedido_nome"], "Cancelado")
        self.assertEqual(orders[0]["status_confirmacao"], "CANCELADO_API")
        self.assertEqual(build_sales_metrics(orders, items), [])
        summary = build_bi_summary_record([row], orders, items,
            snapshot_date="2026-10-05", updated_at="2026-10-05T14:00:00Z")
        self.assertEqual(summary["faturamento_total"], 0)
        self.assertEqual(summary["pedidos_total"], 0)
        self.assertEqual(summary["clientes_compradores_total"], 0)

    def test_all_api_states_are_persisted_but_only_completed_orders_reach_sales(self):
        for status in (0, 1, 2, 3, 4, 99, None):
            with self.subTest(status=status):
                contact, client = self.fixture()
                client.get_pedido.return_value["capa"].update({"status": status, "cancelamento": None})
                _, orders, items = self.resolve_and_persist(contact, client)
                self.assertEqual(len(orders), 1)
                self.assertEqual(len(items), 1)
                if status == 2:
                    self.assertEqual(build_sales_metrics(orders, items),
                        [["2026-10-05", 1, 1, 1, "2", "29.49", "29.49"]])
                else:
                    self.assertEqual(build_sales_metrics(orders, items), [])

    def test_missing_freight_or_official_total_preserves_partial_audit_without_sales(self):
        contact, client = self.fixture(partial=True)
        _, orders, items = self.resolve_and_persist(contact, client)
        self.assertEqual(orders[0]["valor_origem"], "SOMA_ITENS_API")
        self.assertEqual(orders[0]["status_validacao"], "ATENCAO_TOTAL_PARCIAL")
        self.assertEqual(build_sales_metrics(orders, items), [])

    def test_two_contacts_with_same_cpf_persist_one_order_and_one_revenue(self):
        first, client = self.fixture()
        second = {"uuid": "synthetic-u2", "fields": {
            **first["fields"], "primeiro_anuncio_id": "different-ad"}}
        first["fields"]["primeiro_anuncio_id"] = "first-ad"
        contacts = [first, second]
        rows = [normalize_contact(contact, "2026-10-05T14:00:00Z") for contact in contacts]
        responses = {}
        validate_contacts(rows, farm_client=client,
            farm_settings=FarmaliderSettings(True, "synthetic-token", False),
            sync_time="2026-10-05T14:00:00Z", cliente_responses_by_cpf=responses)
        by_uuid = {row["contact_uuid"]: row for row in rows}
        forward = build_orders(contacts, rows_by_uuid=by_uuid, farm_client=client,
            sync_time="2026-10-05T14:00:00Z", cliente_responses_by_cpf=responses)
        reverse = build_orders(list(reversed(contacts)), rows_by_uuid=by_uuid, farm_client=client,
            sync_time="2026-10-05T14:00:00Z", cliente_responses_by_cpf=responses)
        self.assertEqual(forward, reverse)
        orders, items, stats = forward
        self.assertEqual(len(orders), 1)
        self.assertEqual(len(items), 1)
        self.assertEqual(stats.confirmed_api, 1)
        self.assertEqual(orders[0]["contact_uuid"], "synthetic-u1")
        self.assertEqual(orders[0]["primeiro_anuncio_id"], "")
        self.assertEqual(items[0]["contact_uuid"], orders[0]["contact_uuid"])
        store = GoogleSheetsStore.__new__(GoogleSheetsStore)
        store.orders = MemoryWorksheet("Pedidos", ORDER_COLUMNS)
        store.order_items = MemoryWorksheet("Itens_Pedido", ORDER_ITEM_COLUMNS)
        store._read_with_retry = lambda label, operation: operation()
        store._write_with_retry = lambda label, operation: operation()
        persisted = store.upsert_orders_detailed(orders)
        persisted_items = store.upsert_order_items_detailed(items)
        self.assertEqual(len(store.orders.values), 2)
        self.assertEqual(len(store.order_items.values), 2)
        self.assertEqual(build_sales_metrics(persisted.final_records, persisted_items.final_records),
            [["2026-10-05", 1, 1, 1, "2", "29.49", "29.49"]])
        summary = build_bi_summary_record(rows, persisted.final_records, persisted_items.final_records,
            snapshot_date="2026-10-05", updated_at="2026-10-05T14:00:00Z")
        self.assertEqual(summary["contatos_total"], 2)
        self.assertEqual(summary["pedidos_total"], 1)
        self.assertEqual(summary["clientes_compradores_total"], 1)
        self.assertEqual(summary["faturamento_total"], 29.49)


if __name__ == "__main__":
    unittest.main()
