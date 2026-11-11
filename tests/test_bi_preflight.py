"""Prévia real de capacidade: preserva a guarda e evita escrita parcial previsível."""

import copy
import unittest
from unittest.mock import patch

import tests.test_sheets_partitions as fixtures
from bi_preflight import BIContinuationPending, Replacement, check_replacements
from sheets_continuation import ContinuationError, allocated_cells


class BIPreflightTests(unittest.TestCase):
    def setUp(self):
        fixtures.SheetsPartitionTests.setUp(self)

    def make(self, *args, **kwargs):
        return fixtures.SheetsPartitionTests.make(self, *args, **kwargs)

    def test_unconfirmed_source_blocks_without_fact_grid_manifest_or_lock_write(self):
        for segment in ("FARMA", "PET"):
            with self.subTest(segment=segment):
                store, ws, drive = self.make(
                    "BI_Itens",
                    ["chave", "valor"],
                    [["old", 2]],
                    max_rows=3,
                    segment=segment,
                )
                before = copy.deepcopy(store._continuity.index.values())
                with self.assertRaisesRegex(
                    BIContinuationPending, "BI_Itens: 3 linhas"
                ):
                    check_replacements(store, [Replacement(ws, ["chave", "valor"], 3)])
                self.assertEqual(ws.writes, 0)
                self.assertEqual(ws.row_count, 2)
                self.assertEqual(drive.creations, 0)
                self.assertEqual(store._continuity.index.values(), before)
                self.assertEqual(store._continuity.sheet.get_all_values(), before)
                self.assertEqual(store.book.metadata, {})

    def test_global_growth_of_previous_table_consumes_space(self):
        store, ws, _ = self.make("BI_Itens", ["key", "value"])
        first = store.book.add("BI_Clientes", [["key", "value"]])
        store._headers_cache[first.title] = ["key", "value"]
        cells = allocated_cells(store.book.fetch_sheet_metadata())
        store._continuity.index.config["threshold"] = cells + 8
        store._continuity.persisted_hash = self.persist(store)
        # Sozinha, a segunda tabela cabe. O grupo inteiro excede a reserva.
        check_replacements(store, [Replacement(ws, ["key", "value"], 3)])
        with self.assertRaisesRegex(BIContinuationPending, "BI_Itens"):
            check_replacements(
                store,
                [
                    Replacement(first, ["key", "value"], 3),
                    Replacement(ws, ["key", "value"], 3),
                ],
            )
        self.assertEqual((ws.writes, first.writes), (0, 0))

    @staticmethod
    def persist(store):
        from sheets_continuation import fingerprint

        values = store._continuity.index.values()
        store._continuity.sheet.values = copy.deepcopy(values)
        return fingerprint(values)

    def test_reserved_empty_grid_above_threshold_is_not_free_capacity(self):
        store, ws, _ = self.make("BI_Itens", ["key", "value"], [["old", 1]])
        ws.row_count = 500000
        with patch.object(ws, "get", wraps=ws.get) as read:
            with self.assertRaises(BIContinuationPending):
                check_replacements(store, [Replacement(ws, ["key", "value"], 2)])
        calls = [call.args[0] for call in read.call_args_list]
        self.assertEqual(len(calls), 51)  # cabeçalho + chave em blocos de 10 mil
        self.assertEqual(calls[1], "A2:A10001")
        self.assertEqual(calls[-1], "A490002:A500000")
        self.assertEqual(ws.row_count, 500000)
        self.assertEqual(ws.writes, 0)

    def test_confirmed_source_and_existing_continuations_use_official_writer(self):
        for segment in ("FARMA", "PET"):
            with self.subTest(segment=segment):
                store, ws, drive = self.make(
                    "BI_Itens",
                    ["key", "value"],
                    max_rows=3,
                    connector=True,
                    segment=segment,
                )
                rows = [[str(i), i] for i in range(5)]
                check_replacements(
                    store, [Replacement(ws, ["key", "value"], len(rows))]
                )
                self.assertEqual(drive.creations, 0)
                store._replace_table(ws, ["key", "value"], rows, force=True)
                self.assertEqual(drive.creations, 2)
                self.assertEqual(
                    store._continuity.index.status[ws.title]["state"], "READY"
                )
                check_replacements(
                    store, [Replacement(ws, ["key", "value"], len(rows))]
                )
                self.assertEqual(store._continuity.read(ws)[1:], rows)
                self.assertEqual(drive.creations, 2)

    def test_remote_header_or_manifest_change_still_blocks(self):
        for change in ("header", "manifest", "late_manifest"):
            with self.subTest(change=change):
                store, ws, _ = self.make("BI_Itens", ["key", "value"])
                if change == "header":
                    ws.values[0] = ["wrong", "value"]
                elif change == "manifest":
                    store._continuity.sheet.values.append(["invalid"])
                else:
                    original = ws.get

                    def changed(*args, original=original, store=store, **kwargs):
                        result = original(*args, **kwargs)
                        store._continuity.sheet.values.append(["invalid"])
                        return result

                    ws.get = changed
                with self.assertRaises(ContinuationError):
                    check_replacements(store, [Replacement(ws, ["key", "value"], 1)])
                self.assertEqual(ws.writes, 0)

    def test_unconfirmed_table_that_fits_remains_allowed_and_empty_table_fits(self):
        store, ws, _ = self.make("BI_Itens", ["key", "value"], max_rows=3)
        for size in (0, 1, 2):
            check_replacements(store, [Replacement(ws, ["key", "value"], size)])
        self.assertEqual(ws.writes, 0)

    def test_looker_command_blocks_real_group_before_first_table_write(self):
        from unittest.mock import Mock

        from looker_bi import SCHEMAS
        from run_looker import run

        store, items, drive = self.make("BI_Itens", SCHEMAS["BI_Itens"], max_rows=3)
        for title, headers in SCHEMAS.items():
            ws = items if title == "BI_Itens" else store.book.add(title, [headers])
            setattr(store, "looker_" + title, ws)
            store._headers_cache[title] = headers
        tables = {title: [] for title in SCHEMAS}
        tables["BI_Itens"] = [
            [
                str(i),
                "order",
                "client",
                "2026-11-01",
                "sku",
                "Sintético",
                "",
                1,
                10,
                10,
                1,
                "",
            ]
            for i in range(3)
        ]
        store.load_base_snapshot = Mock(return_value=([], [], set()))
        store.load_order_records = Mock(return_value=[])
        store.load_order_item_records = Mock(return_value=[])
        store.get_control = Mock(return_value="2026-11-01")
        store.migrate_bi_summary_numbers = Mock()
        store.close = Mock()
        before = copy.deepcopy(store._continuity.index.values())
        with (
            patch("google_sheets.GoogleSheetsStore", return_value=store),
            patch("proxy_config.configure_proxy"),
            patch("logging_config.configure_logging"),
            patch("looker_bi.build_looker_tables", return_value=tables),
            self.assertLogs(level="WARNING") as output,
        ):
            self.assertEqual(run(["--inicio", "2026-11-01", "--fim", "2026-11-03"]), 3)
        self.assertIn("BI_Itens", " ".join(output.output))
        self.assertNotIn("Traceback", " ".join(output.output))
        self.assertEqual(store._continuity.index.values(), before)
        self.assertEqual(drive.creations, 0)
        self.assertTrue(all(ws.writes == 0 for ws in store.book.sheets))
        store.migrate_bi_summary_numbers.assert_not_called()
        store.close.assert_called_once()
