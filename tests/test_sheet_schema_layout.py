import json
import unittest
from unittest.mock import Mock

from google_sheets import GoogleSheetsStore


class SheetSchemaLayoutTests(unittest.TestCase):
    def store(self, layout=None):
        store = GoogleSheetsStore.__new__(GoogleSheetsStore)
        store._headers_cache = {}
        store._control_values_cache = None
        store.book = Mock()
        store.book.worksheets.return_value = []
        values = [
            ["chave", "valor"],
            [store.SCHEMA_CONTROL_KEY, store.schema_fingerprint()],
        ]
        if layout is not None:
            values.append([store.SCHEMA_HEADERS_CONTROL_KEY, json.dumps(layout)])
        store.control = Mock()
        store.control.get_all_values.return_value = values
        store._read_with_retry = Mock(
            side_effect=lambda description, operation: operation()
        )
        store._assign_sheet_handles = Mock(return_value=True)
        store.ensure_structure = Mock()
        store.set_controls = Mock()
        return store

    def test_cached_layout_keeps_physical_order_after_columns_are_appended(self):
        layout = {
            title: list(headers)
            for title, headers in GoogleSheetsStore._schema_map().items()
        }
        original = layout["Base_Contatos"]
        fields = [
            "pedido_id",
            "pedido_data",
            "pedido_status",
            "pedido_produtos",
            "pedido_quantidade_itens",
            "pedido_valor",
        ]
        layout["Base_Contatos"] = [h for h in original if h not in fields] + fields
        store = self.store(layout)
        store._initialize_structure(validate_structure=False)
        self.assertEqual(store._headers_cache["Base_Contatos"], layout["Base_Contatos"])
        store.ensure_structure.assert_not_called()
        store.set_controls.assert_not_called()

    def test_old_or_invalid_cache_revalidates_and_records_actual_headers(self):
        for layout in (None, {"Base_Contatos": ["contact_uuid"]}):
            with self.subTest(layout=layout):
                store = self.store(layout)
                physical = {
                    title: list(headers)
                    for title, headers in store._schema_map().items()
                }
                store.ensure_structure.side_effect = (
                    lambda store=store, physical=physical, **kwargs: (
                        store._headers_cache.update(physical)
                    )
                )
                store._initialize_structure(validate_structure=False)
                store.ensure_structure.assert_called_once()
                saved = store.set_controls.call_args.args[0]
                self.assertEqual(
                    json.loads(saved[store.SCHEMA_HEADERS_CONTROL_KEY]), physical
                )


if __name__ == "__main__":
    unittest.main()
# NexoFlow 1.5.8
