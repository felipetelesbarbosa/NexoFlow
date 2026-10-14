import unittest
from unittest.mock import Mock, patch

from gspread.exceptions import APIError

from sheets_migration import SheetsMigration
from sheets_native_copy import dimension_requests
from tests import test_sheets_migration as migration_fixtures


def server_error():
    response = Mock()
    response.json.return_value = {
        "error": {"code": 500, "message": "synthetic-copy-failure"}
    }
    return APIError(response)


class NativeCopyTests(unittest.TestCase):
    def setUp(self):
        migration_fixtures.SheetsMigrationTests.setUp(self)

    def test_copy_500_without_created_tab_falls_back_to_verified_native_blocks(self):
        with patch.object(self.planned[0], "copy_to", side_effect=server_error()):
            self.migration.copy_and_verify(self.planned)
        entry = self.migration.state["copies"]["Base_Contatos"]
        self.assertTrue(entry["block_copy"])
        self.assertTrue(entry["verified"])
        self.assertEqual(entry["copied_rows"], self.planned[0].row_count)
        target = self.client.books["operations"].sheets[0]
        self.assertEqual(target.values[:2], self.planned[0].values)

    def test_block_timeout_after_commit_replays_fixed_range_without_duplicate_rows(
        self,
    ):
        destination = self.client.books["operations"]
        original = destination.batch_update
        failed = False

        def lost_response(body):
            nonlocal failed
            result = original(body)
            if (
                any("updateCells" in request for request in body["requests"])
                and not failed
            ):
                failed = True
                raise TimeoutError("synthetic-ack-lost")
            return result

        with (
            patch.object(self.planned[0], "copy_to", side_effect=server_error()),
            patch.object(destination, "batch_update", side_effect=lost_response),
            self.assertRaises(TimeoutError),
        ):
            self.migration.copy_and_verify(self.planned)
        resumed = SheetsMigration(self.client, self.layout, self.journal)
        resumed.copy_and_verify(self.planned)
        self.assertEqual(len(destination.sheets), 1)
        self.assertEqual(len(destination.sheets[0].values), self.planned[0].row_count)
        self.assertTrue(resumed.state["copies"]["Base_Contatos"]["verified"])

    def test_complex_native_structure_blocks_fallback_without_touching_original(self):
        book = self.client.books["dashboard"]
        getter = book.fetch_sheet_metadata

        def with_merge(params=None):
            result = getter(params)
            result["sheets"][0]["merges"] = [
                {"sheetId": 10, "startRowIndex": 0, "endRowIndex": 1}
            ]
            return result

        with (
            patch.object(book, "fetch_sheet_metadata", side_effect=with_merge),
            patch.object(self.planned[0], "copy_to", side_effect=server_error()),
            self.assertRaisesRegex(ValueError, "estruturas"),
        ):
            self.migration.copy_and_verify(self.planned)
        self.assertFalse(self.client.books["operations"].sheets)
        self.assertIn(self.planned[0], book.sheets)

    def test_consecutive_dimension_properties_are_preserved_in_one_range(self):
        result = dimension_requests(
            99,
            "COLUMNS",
            2,
            [
                {"pixelSize": 143},
                {"pixelSize": 143},
                {"pixelSize": 200, "hiddenByUser": True},
            ],
        )
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["updateDimensionProperties"]["range"]["endIndex"], 4)
        self.assertTrue(
            result[1]["updateDimensionProperties"]["properties"]["hiddenByUser"]
        )
