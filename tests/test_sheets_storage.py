import unittest
from unittest.mock import Mock

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
