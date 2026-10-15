"""Gravações novas não usam a detecção de tabelas do values.append."""

import unittest
from copy import deepcopy
from unittest.mock import Mock, patch

from requests.exceptions import Timeout

from google_sheets import GoogleSheetsStore
from tests.test_analytics_order_flow import MemoryWorksheet


class FixedSheetInsertionsTests(unittest.TestCase):
    def store(self):
        store = GoogleSheetsStore.__new__(GoogleSheetsStore)
        store._read_with_retry = Mock(side_effect=lambda label, operation: operation())
        store._write_with_retry = Mock(side_effect=lambda label, operation: operation())
        return store

    def test_blank_last_columns_do_not_shift_insertions_or_duplicate_on_next_load(self):
        ws = MemoryWorksheet(
            "Pedidos_FarmaLider", ["pedido_chave", "pedido_id", "opcional"]
        )
        ws.values.append(["old", "1", ""])
        ws.append_rows = Mock(
            side_effect=AssertionError("values.append must not be called")
        )
        ws.update = Mock(wraps=ws.update)
        store = self.store()
        rows = [{"pedido_chave": "new", "pedido_id": "2", "opcional": ""}]
        first = store._upsert_records_detailed(ws, rows, "pedido_chave")
        second = store._upsert_records_detailed(ws, rows, "pedido_chave")
        self.assertEqual((first.inserted, second.inserted, second.unchanged), (1, 0, 1))
        self.assertEqual(
            ws.values,
            [
                ["pedido_chave", "pedido_id", "opcional"],
                ["old", "1", ""],
                ["new", "2", ""],
            ],
        )
        self.assertEqual(ws.update.call_args.kwargs["range_name"], "A3:C3")
        ws.update.assert_called_once()
        ws.append_rows.assert_not_called()

    def test_api_padding_does_not_become_extra_headers_or_extra_columns(self):
        ws = MemoryWorksheet("Pedidos_FarmaLider", ["pedido_chave", "valor"])
        ws.values = [["pedido_chave", "valor", "", "", ""], ["old", "10", "", "", ""]]
        ws.update = Mock(wraps=ws.update)
        result = self.store()._upsert_records_detailed(
            ws, [{"pedido_chave": "new", "valor": "20"}], "pedido_chave"
        )
        self.assertEqual(ws.update.call_args.kwargs["range_name"], "A3:B3")
        self.assertEqual(ws.update.call_args.kwargs["values"], [["new", "20"]])
        self.assertEqual(
            result.final_records[-1], {"pedido_chave": "new", "valor": "20"}
        )

    def test_populated_out_of_schema_cells_stop_every_write(self):
        store = self.store()
        ws = Mock(title="Pedidos_FarmaLider", row_count=10)
        ws.get_all_values.return_value = [
            ["pedido_chave", "valor", "", ""],
            ["old", "10", "corrompido", ""],
        ]
        with self.assertRaisesRegex(RuntimeError, "fora das colunas"):
            store._upsert_records_detailed(
                ws, [{"pedido_chave": "old", "valor": "99"}], "pedido_chave"
            )
        ws.resize.assert_not_called()
        ws.update.assert_not_called()
        ws.batch_update.assert_not_called()
        ws.append_rows.assert_not_called()

    def test_batches_use_disjoint_fixed_ranges_without_inserting_extra_rows(self):
        store = self.store()
        ws = MemoryWorksheet("Tabela", ["id", "valor"])
        ws.values.append(["old", "0"])
        ws.update = Mock(wraps=ws.update)
        with patch("google_sheets.GOOGLE_SHEETS_APPEND_BATCH_SIZE", 2):
            result = store._upsert_records_detailed(
                ws, [{"id": str(i), "valor": str(i)} for i in range(5)], "id"
            )
        self.assertEqual(result.inserted, 5)
        self.assertEqual(
            [call.kwargs["range_name"] for call in ws.update.call_args_list],
            ["A3:B4", "A5:B6", "A7:B7"],
        )
        self.assertEqual(len(ws.values), 7)

    def test_retry_refuses_to_overwrite_a_different_key_in_the_destination(self):
        store = GoogleSheetsStore.__new__(GoogleSheetsStore)
        store._last_write_started_at = 0.0
        store._read_requests = store._write_requests = 0
        store._read_with_retry = Mock(side_effect=lambda label, call: call())
        store._wait_before_write = Mock()
        ws = Mock(title="Tabela", row_count=10)
        values = [["id"], ["old"]]
        ws.get_all_values.side_effect = lambda: deepcopy(values)

        def changed(**kwargs):
            values.append(["other"])
            raise Timeout("Resposta perdida")

        ws.update.side_effect = changed
        with (
            patch("google_sheets.time.sleep"),
            patch("google_sheets.refresh_network_route"),
        ):
            with self.assertRaisesRegex(RuntimeError, "Destino.*mudou"):
                store._append_keyed_batch(
                    ws, [["new"]], ["id"], "id", "RAW", start_row=3
                )
        self.assertEqual(values[-1], ["other"])
        ws.update.assert_called_once()
