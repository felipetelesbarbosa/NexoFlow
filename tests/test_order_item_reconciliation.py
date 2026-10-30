import unittest
from copy import deepcopy
from unittest.mock import Mock

from analytics import ORDER_ITEM_COLUMNS, build_sales_metrics
from google_sheets import GoogleSheetsStore, UpsertResult, column_letter


class OrderItemReconciliationTests(unittest.TestCase):
    def store(self, records):
        store = GoogleSheetsStore.__new__(GoogleSheetsStore)
        store.order_items = Mock(title="Itens_Pedidos_FarmaLider")
        store._headers_cache = {}
        store._write_with_retry = Mock(
            side_effect=lambda description, operation: operation()
        )
        store._upsert_records_detailed = Mock(
            return_value=UpsertResult(0, 1, 0, [], records)
        )
        return store

    def test_corrected_snapshot_removes_only_stale_items_of_affected_order(self):
        current = [
            {
                "pedido_chave": "FARMALIDER:1",
                "item_chave": "one",
                "quantidade": "2",
                "data": "2026-10-06",
            },
            {
                "pedido_chave": "FARMALIDER:1",
                "item_chave": "stale",
                "quantidade": "9",
                "data": "2026-10-06",
            },
            {
                "pedido_chave": "FARMALIDER:2",
                "item_chave": "other",
                "quantidade": "5",
                "data": "2026-10-06",
            },
        ]
        store = self.store(current)
        result = store.upsert_order_items_detailed([current[0]])
        store.order_items.batch_clear.assert_called_once_with(
            [f"A3:{column_letter(len(ORDER_ITEM_COLUMNS))}3"]
        )
        self.assertEqual(result.removed, 1)
        self.assertEqual(
            [r["item_chave"] for r in result.final_records], ["one", "other"]
        )
        sales = build_sales_metrics(
            [
                {
                    "pedido_chave": "FARMALIDER:1",
                    "data": "2026-10-06",
                    "contact_uuid": "u1",
                    "status_validacao": "OK",
                    "status_confirmacao": "CONFIRMADO_API",
                    "farmalider_status_pedido": "2",
                    "valor_total_compra": "20",
                },
            ],
            result.final_records,
        )
        self.assertEqual(len(sales), 1)
        # The stale nine units are absent; other orders do not enter this sale.
        from analytics import SALES_METRIC_COLUMNS

        self.assertEqual(
            str(sales[0][SALES_METRIC_COLUMNS.index("unidades_vendidas")]), "2"
        )

    def test_equal_or_empty_snapshot_does_not_clear_other_orders(self):
        current = [{"pedido_chave": "FARMALIDER:2", "item_chave": "other"}]
        for incoming in (current, []):
            with self.subTest(incoming=incoming):
                store = self.store(current)
                result = store.upsert_order_items_detailed(incoming)
                store.order_items.batch_clear.assert_not_called()
                self.assertEqual(result.removed, 0)
                self.assertEqual(result.final_records, current)

    def test_duplicate_new_keys_create_one_row_and_repeat_without_writes(self):
        headers = ["pedido_chave", "contact_uuid", "valor_total_compra"]
        values = [headers]
        ws = Mock(title="Pedidos_FarmaLider", row_count=1000)
        ws.get_all_values.side_effect = lambda: deepcopy(values)
        ws.update.side_effect = lambda **kwargs: values.extend(
            deepcopy(kwargs["values"])
        )
        store = GoogleSheetsStore.__new__(GoogleSheetsStore)
        store._read_with_retry = Mock(
            side_effect=lambda description, operation: operation()
        )
        store._write_with_retry = Mock(
            side_effect=lambda description, operation: operation()
        )
        incoming = [
            {
                "pedido_chave": "FARMALIDER:1",
                "contact_uuid": "u1",
                "valor_total_compra": "20",
            },
            {
                "pedido_chave": "FARMALIDER:1",
                "contact_uuid": "u2",
                "valor_total_compra": "20",
            },
        ]
        result = store._upsert_records_detailed(ws, incoming, "pedido_chave")
        self.assertEqual(result.inserted, 1)
        self.assertEqual(result.updated, 0)
        self.assertEqual(len(values), 2)
        self.assertEqual(result.final_records[0]["contact_uuid"], "u2")
        ws.batch_update.assert_not_called()
        writes = store._write_with_retry.call_count
        repeated = store._upsert_records_detailed(ws, incoming, "pedido_chave")
        self.assertEqual(
            (repeated.inserted, repeated.updated, repeated.unchanged), (0, 0, 1)
        )
        self.assertEqual(store._write_with_retry.call_count, writes)

    def test_invalid_snapshot_is_rejected_before_any_write(self):
        store = self.store([])
        with self.assertRaises(ValueError):
            store.upsert_order_items_detailed([{"item_chave": "one"}])
        store._upsert_records_detailed.assert_not_called()
        store._write_with_retry.assert_not_called()


if __name__ == "__main__":
    unittest.main()
# NexoFlow 1.5.7
