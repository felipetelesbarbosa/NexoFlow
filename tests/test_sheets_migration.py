import copy
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sheets_migration import SheetsMigration
from sheets_storage import STORAGE_SHEET, SheetsStorage


class Sheet:
    def __init__(self, book, title, values, sheet_id):
        self.book, self.title, self.values, self.id = (
            book,
            title,
            copy.deepcopy(values),
            sheet_id,
        )
        self.row_count, self.col_count = max(len(values), 3), 2

    def get(self, target):
        return copy.deepcopy(self.values)

    def update(self, *, range_name, values, **kwargs):
        self.values = copy.deepcopy(values)

    def update_title(self, title):
        self.title = title

    def copy_to(self, destination_id):
        destination = self.book.client.books[destination_id]
        target = destination.add_worksheet(
            title="Cópia de " + self.title, rows=self.row_count, cols=self.col_count
        )
        target.values = copy.deepcopy(self.values)
        if self.book.client.fail_copy_once:
            self.book.client.fail_copy_once = False
            raise TimeoutError("synthetic-copy-response-lost")
        return {"sheetId": target.id}


class Book:
    def __init__(self, client, key):
        self.client, self.id = client, key
        self.sheets = []

    def worksheets(self):
        return self.sheets[:]

    def add_worksheet(self, *, title, rows, cols):
        ws = Sheet(self, title, [], len(self.sheets) + 1)
        ws.row_count, ws.col_count = rows, cols
        self.sheets.append(ws)
        return ws

    def get_worksheet_by_id(self, sheet_id):
        return next(ws for ws in self.sheets if ws.id == sheet_id)

    def del_worksheet(self, ws):
        self.sheets.remove(ws)

    def values_batch_get(self, ranges, params):
        result = []
        for target in ranges:
            title = target.split("!")[0].strip("'")
            start, end = map(int, re.search(r"!A(\d+):[A-Z]+(\d+)", target).groups())
            ws = next(ws for ws in self.sheets if ws.title == title)
            result.append({"values": copy.deepcopy(ws.values[start - 1 : end])})
        return {"valueRanges": result}

    def fetch_sheet_metadata(self, params=None):
        result = []
        for ws in self.sheets:
            start, end = 0, 2
            if params and params.get("ranges"):
                matched = re.search(r"!A(\d+):[A-Z]+(\d+)", params["ranges"][0])
                start, end = int(matched[1]) - 1, int(matched[2])
            result.append(
                {
                    "properties": {
                        "sheetId": ws.id,
                        "title": ws.title,
                        "gridProperties": {
                            "rowCount": ws.row_count,
                            "columnCount": ws.col_count,
                        },
                    },
                    "data": [
                        {
                            "startRow": start,
                            "rowData": [
                                {
                                    "values": [
                                        {
                                            "userEnteredValue": {
                                                "stringValue": str(value)
                                            }
                                        }
                                        for value in row
                                    ]
                                }
                                for row in ws.values[start:end]
                            ],
                        }
                    ],
                }
            )
        return {"sheets": result}

    def batch_update(self, body):
        replies = []
        for request in body["requests"]:
            if "addSheet" in request:
                props = request["addSheet"]["properties"]
                grid = props["gridProperties"]
                ws = self.add_worksheet(
                    title=props["title"],
                    rows=grid["rowCount"],
                    cols=grid["columnCount"],
                )
                replies.append({"addSheet": {"properties": {"sheetId": ws.id}}})
            elif "updateCells" in request:
                update = request["updateCells"]
                bounds = update["range"]
                ws = self.get_worksheet_by_id(bounds["sheetId"])
                while len(ws.values) < bounds["endRowIndex"]:
                    ws.values.append([])
                for index, row in enumerate(update["rows"], bounds["startRowIndex"]):
                    ws.values[index] = [
                        cell.get("userEnteredValue", {}).get("stringValue", "")
                        for cell in row["values"]
                    ]
                replies.append({})
            else:
                replies.append({})
        return {"replies": replies}


class Client:
    def __init__(self):
        self.books = {
            key: Book(self, key) for key in ("dashboard", "operations", "history")
        }
        self.fail_copy_once = False

    def open_by_key(self, key):
        return self.books[key]


class SheetsMigrationTests(unittest.TestCase):
    def setUp(self):
        self.sleep = patch("sheets_migration.time.sleep").start()
        self.addCleanup(patch.stopall)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.client = Client()
        self.layout = SheetsStorage("dashboard", "operations", "history")
        self.journal = Path(directory.name) / "private" / "migration.json"
        original = self.client.books["dashboard"]
        original.sheets = [
            Sheet(
                original,
                "Base_Contatos",
                [["id", "nome"], ["synthetic-1", "Exemplo"]],
                10,
            ),
            Sheet(
                original,
                "Historico_Alteracoes",
                [
                    ["acao", "id"],
                    ["Inserido", "synthetic-1"],
                    ["Atualizado", "synthetic-1"],
                ],
                11,
            ),
            Sheet(original, "BI_Status", [["estado", "valor"], ["OK", "1"]], 12),
        ]
        self.migration = SheetsMigration(self.client, self.layout, self.journal)
        self.planned = self.migration.plan(
            {"Base_Contatos", "Historico_Alteracoes", "BI_Status"}
        )

    def test_copy_verify_activate_remove_preserves_bi_ids_and_data(self):
        bi = self.client.books["dashboard"].sheets[-1]
        self.migration.copy_and_verify(self.planned)
        self.migration.activate(self.planned)
        self.migration.remove_originals(self.planned, routines_stopped=True)
        self.assertEqual(
            [ws.title for ws in self.client.books["dashboard"].sheets],
            ["BI_Status", STORAGE_SHEET],
        )
        self.assertIs(self.client.books["dashboard"].sheets[0], bi)
        self.assertEqual(
            self.client.books["history"].sheets[0].values[-1],
            ["Atualizado", "synthetic-1"],
        )
        self.assertTrue(
            all(entry["removed"] for entry in self.migration.state["copies"].values())
        )

    def test_source_or_destination_change_prevents_deletion(self):
        self.migration.copy_and_verify(self.planned)
        self.migration.activate(self.planned)
        self.client.books["operations"].sheets[0].values[1][1] = "changed"
        with self.assertRaisesRegex(ValueError, "alterada"):
            self.migration.remove_originals(self.planned, routines_stopped=True)
        self.assertIn(self.planned[0], self.client.books["dashboard"].sheets)

    def test_ambiguous_copy_response_resumes_without_second_copy(self):
        self.client.fail_copy_once = True
        with self.assertRaises(TimeoutError):
            self.migration.copy_and_verify(self.planned)
        resumed = SheetsMigration(self.client, self.layout, self.journal)
        resumed.copy_and_verify(self.planned)
        self.assertEqual(len(self.client.books["operations"].sheets), 1)
        self.assertTrue(resumed.state["copies"]["Base_Contatos"]["verified"])

    def test_existing_destination_is_never_overwritten(self):
        self.client.books["operations"].add_worksheet(
            title="Base_Contatos", rows=3, cols=2
        )
        with self.assertRaisesRegex(ValueError, "não será sobrescrita"):
            self.migration.copy_and_verify(self.planned)
        self.assertNotIn(
            STORAGE_SHEET, [ws.title for ws in self.client.books["dashboard"].sheets]
        )

    def test_activation_requires_every_copy_and_removal_requires_stopped_routines(self):
        with self.assertRaises(ValueError):
            self.migration.activate(self.planned)
        self.migration.copy_and_verify(self.planned)
        self.migration.activate(self.planned)
        with self.assertRaises(ValueError):
            self.migration.remove_originals(self.planned, routines_stopped=False)

    def test_remaining_formula_dependency_blocks_removal(self):
        self.migration.copy_and_verify(self.planned)
        self.migration.activate(self.planned)
        self.client.books["dashboard"].sheets[2].values[1][1] = "='Base_Contatos'!B2"
        with self.assertRaisesRegex(ValueError, "Fórmula"):
            self.migration.remove_originals(self.planned, routines_stopped=True)
        self.assertIn(self.planned[0], self.client.books["dashboard"].sheets)

    def test_delivery_tickets_are_moved_even_outside_the_main_schema(self):
        original = self.client.books["dashboard"]
        tickets = Sheet(
            original,
            "Tickets_Delivery_Weni",
            [["ticket", "pedido"], ["synthetic-ticket", "synthetic-order"]],
            13,
        )
        original.sheets.append(tickets)
        plan = self.migration.plan(
            {"Base_Contatos", "Historico_Alteracoes", "BI_Status"}
        )
        self.assertIn(tickets, plan)
        self.migration.copy_and_verify(plan)
        self.assertIn(
            "Tickets_Delivery_Weni",
            [ws.title for ws in self.client.books["operations"].sheets],
        )

    def test_new_rows_after_verification_prevent_deleting_original(self):
        self.migration.copy_and_verify(self.planned)
        self.migration.activate(self.planned)
        self.planned[0].row_count += 1
        with self.assertRaisesRegex(ValueError, "Dimensões"):
            self.migration.remove_originals(self.planned, routines_stopped=True)
        self.assertIn(self.planned[0], self.client.books["dashboard"].sheets)
