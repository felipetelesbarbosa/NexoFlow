import unittest
from unittest.mock import Mock

from gspread.exceptions import APIError

from google_sheets import GoogleSheetsStore


class SheetCapacityTests(unittest.TestCase):
    def fixture(self, rows):
        store = GoogleSheetsStore.__new__(GoogleSheetsStore)
        store._read_with_retry = Mock(side_effect=lambda description, call: call())
        store._write_with_retry = Mock(side_effect=lambda description, call: call())
        ws = Mock(title="Pedidos_FarmaLider", row_count=rows)
        ws.get_all_values.return_value = [["pedido_chave", "valor"], ["old", "10"]]
        return store, ws

    def test_exact_growth_precedes_existing_updates_and_appends(self):
        store, ws = self.fixture(2)
        operations = []
        ws.resize.side_effect = lambda **kwargs: operations.append(("resize", kwargs))
        ws.batch_update.side_effect = lambda *args, **kwargs: operations.append(
            ("update", None)
        )
        ws.append_rows.side_effect = lambda *args, **kwargs: operations.append(
            ("append", None)
        )
        result = store._upsert_records_detailed(
            ws,
            [
                {"pedido_chave": "old", "valor": "20"},
                {"pedido_chave": "new", "valor": "30"},
            ],
            "pedido_chave",
        )
        self.assertEqual(
            operations, [("resize", {"rows": 3}), ("update", None), ("append", None)]
        )
        self.assertEqual((result.updated, result.inserted), (1, 1))

    def test_existing_room_is_preserved_without_shrinking(self):
        store, ws = self.fixture(100)
        store._upsert_records_detailed(ws, [{"pedido_chave": "new"}], "pedido_chave")
        ws.resize.assert_not_called()
        ws.append_rows.assert_called_once()

    def test_capacity_failure_does_not_partially_update_existing_orders(self):
        store, ws = self.fixture(2)
        response = Mock()
        response.json.return_value = {
            "error": {
                "code": 400,
                "message": "This action would increase the number of cells in the workbook above the limit of 20000000 cells.",
            }
        }
        ws.resize.side_effect = APIError(response)
        with self.assertRaisesRegex(RuntimeError, "Nenhuma gravação"):
            store._upsert_records_detailed(
                ws,
                [{"pedido_chave": "old", "valor": "20"}, {"pedido_chave": "new"}],
                "pedido_chave",
            )
        ws.batch_update.assert_not_called()
        ws.append_rows.assert_not_called()

    def test_update_only_does_not_require_more_capacity(self):
        store, ws = self.fixture(2)
        store._upsert_records_detailed(
            ws, [{"pedido_chave": "old", "valor": "20"}], "pedido_chave"
        )
        ws.resize.assert_not_called()
        ws.append_rows.assert_not_called()
