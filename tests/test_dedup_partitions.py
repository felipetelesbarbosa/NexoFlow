"""Mapeamento de reparos nativos entre arquivos, sem perda de fatos financeiros."""

import unittest
from copy import deepcopy
from types import SimpleNamespace

import dedup_bi as core
from dedup_partitions import matches_current, split_table
from sheets_continuation import ContinuationError, Part, fingerprint


class PartitionRepairTests(unittest.TestCase):
    def snapshots(self, title, headers, rows):
        return [
            (
                Part(
                    title, number, f"b{number}", 10, len(headers), fingerprint(headers)
                ),
                SimpleNamespace(id=10),
                [headers[:], *deepcopy(data)],
            )
            for number, data in enumerate(rows)
        ]

    def test_identity_updates_target_correct_file_and_preserve_money(self):
        title, headers = (
            "BI_Clientes",
            ["cliente_chave", "cliente", "faturamento_identificado"],
        )
        parts = self.snapshots(
            title, headers, [[["c1", "Primeiro", 100]], [["c2", "Nome anterior", 200]]]
        )
        before = [headers, ["c1", "Primeiro", 100], ["c2", "Nome anterior", 200]]
        desired = [headers, ["c1", "Primeiro", 100], ["c2", "Nome correto", 200]]
        change = core.diff_table(title, before, desired, removed_uuids=set())
        tables = split_table(title, change, parts)
        self.assertFalse(tables[title + "::b0::10"]["updates"])
        target = tables[title + "::b1::10"]
        self.assertEqual(
            target["updates"],
            [{"row": 2, "column": 2, "header": "cliente", "value": "Nome correto"}],
        )
        self.assertFalse(target["deletions"])
        self.assertEqual(target["after"][1][2], 200)
        self.assertEqual(parts[1][2][1][1], "Nome anterior")
        requests = core.requests_for({"tables": {"local": target}})
        self.assertEqual(requests[0]["updateCells"]["range"]["startRowIndex"], 1)
        self.assertEqual(requests[0]["updateCells"]["range"]["startColumnIndex"], 1)

    def test_deletion_uses_local_row_and_never_shifts_another_file(self):
        title, headers = "BI_Publico", ["contato_chave", "nome"]
        bad = core.opaque_key("contato", "duplicado")
        rows = [[["a", "Antes"]], [[bad, "Errado"], ["b", "Depois"]]]
        parts = self.snapshots(title, headers, rows)
        before = [headers, *rows[0], *rows[1]]
        desired = [headers, rows[0][0], rows[1][1]]
        change = core.diff_table(title, before, desired, removed_uuids={"duplicado"})
        tables = split_table(title, change, parts)
        self.assertEqual(tables[title + "::b0::10"]["after"], parts[0][2])
        self.assertEqual(tables[title + "::b1::10"]["deletions"], [2])
        self.assertEqual(
            tables[title + "::b1::10"]["after"], [headers, ["b", "Depois"]]
        )
        self.assertTrue(matches_current(tables, {title: parts}, "before_hash"))
        self.assertFalse(matches_current(tables, {title: parts}, "after_hash"))
        after = [
            (part, ws, tables[title + f"::{part.book_id}::{part.sheet_id}"]["after"])
            for part, ws, _ in parts
        ]
        self.assertTrue(matches_current(tables, {title: after}, "after_hash"))

    def test_out_of_bounds_and_financial_changes_remain_blocked(self):
        headers = ["cliente_chave", "cliente", "faturamento_identificado"]
        parts = self.snapshots("BI_Clientes", headers, [[["c", "Nome", 100]]])
        with self.assertRaisesRegex(ValueError, "fora do reparo"):
            core.diff_table(
                "BI_Clientes",
                parts[0][2],
                [headers, ["c", "Nome", 101]],
                removed_uuids=set(),
            )
        with self.assertRaises(ContinuationError):
            split_table(
                "BI_Clientes",
                {"updates": [{"row": 99, "column": 2, "value": "x"}], "deletions": []},
                parts,
            )


class PartitionRepairTransactionTests(unittest.TestCase):
    def make(self, root):
        from dedup_sheets import DedupSheets
        from google_sheets import GoogleSheetsStore
        from sheets_continuation import ContinuationIndex
        from sheets_partitions import RolloverManager, roots_for
        from sheets_storage import SheetsStorage
        from tests.sheets_memory import Book, Client

        books = {
            key: Book(key)
            for key in ("dashboard", "operations", "history", "continuation")
        }
        base_headers = ["contact_uuid", "nome", "canal_urn", "cidade"]
        before_base = [
            base_headers,
            ["can", "Cliente correto", "whatsapp", "Belém"],
            ["duplicado", "Cliente errado", "whatsapp", "Belém"],
        ]
        sources_before = {title: [["contact_uuid"]] for title in core.SOURCE_TITLES}
        sources_before["Base_Contatos"] = before_base
        template = {title: [core.SCHEMAS[title]] for title in core.DETAIL_TITLES}
        template.update(
            {
                "BI_Pedidos": [core.BI_ORDERS_COLUMNS],
                "BI_Delivery_Pedidos": [core.DELIVERY_ORDER_COLUMNS],
                "BI_Resumo_Diario": [core.BI_SUMMARY_COLUMNS, ["2026-10-10"]],
                "BI_Canais": [core.BI_CHANNEL_COLUMNS],
                "BI_Conversao": [core.BI_CONVERSION_COLUMNS],
            }
        )
        current, _ = core.prepare_targets(
            sources_before,
            template,
            {},
            removed_uuids=set(),
            updated_at="2026-10-10T12:00:00Z",
        )
        for title, values in sources_before.items():
            books["operations"].add(
                title, values[:2] if title == "Base_Contatos" else values
            )
        books["operations"].add("Controle", [["chave", "valor"]])
        for title, values in current.items():
            books["dashboard"].add(
                title, values[:2] if title == "BI_Publico" else values
            )
        more = books["continuation"].add(
            "BI_Publico", [current["BI_Publico"][0], *current["BI_Publico"][2:]]
        )
        context = GoogleSheetsStore.__new__(GoogleSheetsStore)
        context.book, context._hub_id = books["dashboard"], "dashboard"
        context._storage_layout = SheetsStorage("dashboard", "operations", "history")
        context._storage_books = {k: v for k, v in books.items() if k != "continuation"}
        context.client = Client(books)
        context._read_with_retry = lambda _, f: f()
        context._write_with_retry = lambda _, f: f()
        context._headers_cache = {}
        index = ContinuationIndex("dashboard", "FARMA", roots_for(context))
        index.files["continuation"] = {
            "role": "dashboard",
            "number": 1,
            "source": "dashboard",
        }
        initial = books["dashboard"].worksheet("BI_Publico")
        for number, book_id, ws in (
            (0, "dashboard", initial),
            (1, "continuation", more),
        ):
            part = Part(
                "BI_Publico",
                number,
                book_id,
                ws.id,
                len(current["BI_Publico"][0]),
                fingerprint(current["BI_Publico"][0]),
            )
            index.parts[part.key] = part
        index_sheet = context.book.add(
            "NexoFlow_Continuidade", index.values(), rows=100, cols=3
        )
        context.client.properties["continuation"] = {
            "nexoflow_hub": "dashboard",
            "nexoflow_segment": "FARMA",
            "nexoflow_role": "dashboard",
        }
        manager = RolloverManager(context, index_sheet, index)
        context._continuity = manager
        manager.journal_path = root / "history.json"
        store = DedupSheets.__new__(DedupSheets)
        store.client, store.hub, store.layout = (
            context.client,
            context.book,
            context._storage_layout,
        )
        store.books, store.continuity = manager.books, manager
        store.handles = {
            k: {ws.title: ws for ws in b.worksheets()} for k, b in manager.books.items()
        }
        return store, more, books

    @staticmethod
    def reopen_after_expiry(store):
        import time

        from sheets_continuation import ContinuationIndex, SheetsLease, fingerprint

        manager = store.continuity
        manager.lease.release()
        manager.lease = SheetsLease(store.hub, now=lambda: time.time() + 301)
        manager.index = ContinuationIndex.parse(
            manager.sheet.get_all_values(),
            hub=manager.index.config["hub"],
            segment=manager.index.config["segment"],
            roots=manager.index.config["roots"],
        )
        manager.persisted_hash = fingerprint(manager.index.values())

    def test_real_builder_repair_recovers_lost_response_without_repeating_deletion(
        self,
    ):
        import tempfile
        from pathlib import Path

        from requests import Timeout

        from dedup_partitions import refresh

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store, more, books = self.make(root)
            books["continuation"].lose_data_response = True
            with self.assertRaises(Timeout):
                refresh(store, {"duplicado"}, set(), root)
            self.assertEqual(more.get_all_values(), [core.SCHEMAS["BI_Publico"]])
            self.assertEqual(books["continuation"].data_writes, 1)
            self.reopen_after_expiry(store)
            refresh(store, {"duplicado"}, set(), root)
            self.assertEqual(books["continuation"].data_writes, 1)
            self.assertEqual(
                store.continuity.index.status["BI_Publico"]["state"], "READY"
            )
            self.assertEqual(
                sum(
                    p["rows"]
                    for p in store.continuity.index.status["BI_Publico"]["parts"]
                ),
                1,
            )
            refresh(store, {"duplicado"}, set(), root)
            self.assertEqual(books["continuation"].data_writes, 1)

    def test_ambiguous_send_never_replays_delete_or_overwrites_manual_edit(self):
        import tempfile
        from pathlib import Path

        from requests import Timeout

        from dedup_partitions import refresh

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store, more, books = self.make(root)
            books["continuation"].lose_data_response = True
            with self.assertRaises(Timeout):
                refresh(store, {"duplicado"}, set(), root)
            self.reopen_after_expiry(store)
            more.resize(rows=2)
            more.values.append(["nova-chave", "cliente fora da revisão"])
            with self.assertRaisesRegex(ContinuationError, "incerto"):
                refresh(store, {"duplicado"}, set(), root)
            self.assertEqual(books["continuation"].data_writes, 1)
            self.assertEqual(more.values[-1][0], "nova-chave")
