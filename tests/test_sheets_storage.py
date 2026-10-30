import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from google_sheets import GoogleSheetsStore
from sheets_storage import STORAGE_SHEET, SheetsStorage


class SheetsStorageTests(unittest.TestCase):
    def layout(self):
        return SheetsStorage("dashboard", "operations", "history")

    def test_roles_preserve_bi_and_route_all_operational_handles(self):
        layout = self.layout()
        self.assertEqual(
            SheetsStorage.from_values(layout.values(), "dashboard"), layout
        )
        for title in GoogleSheetsStore._schema_map():
            expected = (
                "dashboard"
                if title.startswith("BI_")
                else ("history" if title == "Historico_Alteracoes" else "operations")
            )
            self.assertEqual(layout.destination(title), expected)

    def test_invalid_remote_configuration_fails_closed(self):
        values = self.layout().values()
        for candidate in (
            values[:3],
            values + [values[2]],
            [["wrong", "header"]] + values[1:],
            values[:3] + [["operacao", "dashboard"], values[4]],
            values[:4] + [["historico", "https://example.invalid"]],
        ):
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                SheetsStorage.from_values(candidate, "dashboard")

    def test_initialization_uses_remote_files_and_ignores_stale_original_copies(self):
        layout = self.layout()
        store = GoogleSheetsStore.__new__(GoogleSheetsStore)
        store._hub_id = "dashboard"
        store._headers_cache = {}
        store._control_values_cache = None
        store.book = Mock()
        old_base = Mock(title="Base_Contatos")
        config = Mock(title=STORAGE_SHEET)
        config.get.return_value = layout.values()
        bi = Mock(title="BI_Status")
        store.book.worksheets.return_value = [old_base, config, bi]
        operation = Mock()
        new_base = Mock(title="Base_Contatos")
        operation.worksheets.return_value = [new_base] + [
            Mock(title=title)
            for title in ("Pedidos_FarmaLider", "Itens_Pedidos_FarmaLider", "Controle")
        ]
        history_book = Mock()
        history = Mock(title="Historico_Alteracoes")
        history_book.worksheets.return_value = [history]
        store.client = Mock()
        store.client.open_by_key.side_effect = lambda key: {
            "operations": operation,
            "history": history_book,
        }[key]
        store._read_with_retry = Mock(side_effect=lambda label, call: call())
        store._assign_sheet_handles = Mock(return_value=False)
        store.ensure_structure = Mock()
        store.set_controls = Mock()
        store._initialize_structure(validate_structure=False)
        self.assertIs(store._known_sheets["Base_Contatos"], new_base)
        self.assertIs(store._book_for_title("Historico_Alteracoes"), history_book)
        self.assertIs(store._book_for_title("BI_Status"), store.book)
        self.assertIs(store._book_for_title("Tickets_Delivery_Weni"), operation)
        self.assertNotIn(STORAGE_SHEET, store._known_sheets)

    def test_single_file_remains_compatible_without_remote_configuration(self):
        store = GoogleSheetsStore.__new__(GoogleSheetsStore)
        store.book = Mock()
        self.assertIs(store._book_for_title("Historico_Alteracoes"), store.book)
        self.assertIs(store._book_for_title("BI_Status"), store.book)

    def test_wrong_destination_without_data_does_not_create_empty_tables(self):
        store = GoogleSheetsStore.__new__(GoogleSheetsStore)
        store._hub_id = "dashboard"
        store.book = Mock()
        config = Mock(title=STORAGE_SHEET)
        config.get.return_value = self.layout().values()
        store.book.worksheets.return_value = [config]
        empty_book = Mock()
        empty_book.worksheets.return_value = []
        store.client = Mock()
        store.client.open_by_key.return_value = empty_book
        store._read_with_retry = Mock(side_effect=lambda label, call: call())
        store.ensure_structure = Mock()
        with self.assertRaisesRegex(RuntimeError, "abas essenciais"):
            store._initialize_structure(validate_structure=False)
        store.ensure_structure.assert_not_called()


class ExplicitStorageTests(unittest.TestCase):
    def test_explicit_ids_route_without_remote_map_for_both_profiles(self):
        from runtime_profile import validate_sheet_destinations
        from sheets_storage import configured_storage

        settings = SimpleNamespace(
            GOOGLE_OPERATIONS_SPREADSHEET_ID="operations",
            GOOGLE_HISTORY_SPREADSHEET_ID="history",
        )
        with (
            patch("project_paths.load_private_settings", return_value=settings),
            patch(
                "runtime_profile.validate_sheet_destinations",
                wraps=validate_sheet_destinations,
            ),
        ):
            self.assertEqual(
                configured_storage("dashboard"),
                SheetsStorage("dashboard", "operations", "history"),
            )
        settings.GOOGLE_HISTORY_SPREADSHEET_ID = ""
        with patch("project_paths.load_private_settings", return_value=settings):
            with self.assertRaises(ValueError):
                configured_storage("dashboard")

    def test_disagreement_local_and_remote_blocks_before_mutations(self):
        test = SheetsStorageTests()
        layout = test.layout()
        store = GoogleSheetsStore.__new__(GoogleSheetsStore)
        store._hub_id = "dashboard"
        store.book = Mock()
        config = Mock(title=STORAGE_SHEET)
        config.get.return_value = layout.values()
        store.book.worksheets.return_value = [config]
        store._read_with_retry = lambda _, call: call()
        store.client = Mock()
        with patch(
            "sheets_storage.configured_storage",
            return_value=SheetsStorage("dashboard", "different", "history"),
        ):
            with self.assertRaisesRegex(ValueError, "divergem"):
                store._initialize_structure(validate_structure=False)
        store.client.open_by_key.assert_not_called()
