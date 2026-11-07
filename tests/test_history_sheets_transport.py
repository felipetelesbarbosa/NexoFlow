"""Publicador e adaptador reais sobre o protocolo Sheets/Drive em memória."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from google_sheets import GoogleSheetsStore
from history_publication import Publication
from history_sheets_transport import SheetsTransport
from order_history import digest
from order_history_sheets import SCHEMAS
from sheets_continuation import ContinuationIndex, allocated_cells, stamp_book
from sheets_partitions import RolloverManager, roots_for
from sheets_storage import SheetsStorage
from tests.sheets_memory import Book, Client, Provisioner
from tests.test_history_publication import fixture, stream


def batch_get(book, ranges, params=None):
    result = []
    for target in ranges:
        title, area = target.split("!", 1)
        result.append(
            dict(range=target, values=book.worksheet(title.strip("'")).get(area))
        )
    return dict(valueRanges=result)


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.patch = patch.object(Book, "values_batch_get", batch_get, create=True)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.delay = patch("google_sheets.GOOGLE_SHEETS_WRITE_DELAY_SECONDS", 0)
        self.delay.start()
        self.addCleanup(self.delay.stop)
        store = GoogleSheetsStore.__new__(GoogleSheetsStore)
        books = {k: Book(k) for k in ("dashboard", "operations", "history")}
        books["history"].add("Legado", [], rows=18_413_260, cols=1)
        store.book = books["dashboard"]
        store._hub_id = "dashboard"
        store.client = Client(books)
        store._storage_layout = SheetsStorage("dashboard", "operations", "history")
        store._storage_books = books
        store._headers_cache = {}
        store._read_requests = store._write_requests = 0
        store._last_write_started_at = 0
        store.native_meta_context = lambda: dict(
            segment="FARMA",
            dashboard="dashboard",
            operations="operations",
            history="history",
        )
        index = ContinuationIndex("dashboard", "FARMA", roots_for(store))
        index.config.update(
            threshold=18_000_000, max_part_rows=5, connector_tables=list(SCHEMAS)
        )
        sheet = store.book.add(
            "NexoFlow_Continuidade", index.values(), rows=100, cols=3
        )
        provider = Provisioner(store.client)
        manager = RolloverManager(
            store, sheet, index, provisioner_factory=lambda: provider
        )
        manager.journal_path = Path(self.tmp.name) / "creation.json"
        store._continuity = manager
        for role, book_id in roots_for(store).items():
            stamp_book(books[book_id], hub=store._hub_id, segment="FARMA", role=role)
        self.store = store
        self.provider = provider
        self.remote = SheetsTransport(store)

        def info(book):
            b = manager._book(book)
            return dict(
                version=digest(
                    [b.fetch_sheet_metadata(), [w.values for w in b.sheets]]
                ),
                capabilities={"canEdit": True},
                parents=[],
            )

        self.remote._drive = info
        self.pub = Publication(self.remote, "FARMA", Path(self.tmp.name))

    def test_legacy_table_in_wrong_root_blocks_before_new_copy(self):
        from order_history import HistoryError

        db, data = fixture(1)
        self.addCleanup(db.close)
        title = "Historico_Pedidos"
        self.store._storage_books["operations"].add(
            title, [SCHEMAS[title], [data[title][0][h] for h in SCHEMAS[title]]]
        )
        with self.assertRaisesRegex(HistoryError, "ABA_ORFA"):
            self.pub.prepare(stream(data))
        self.assertEqual(self.provider.creations, 0)
        self.assertEqual(
            sum(b.data_writes for b in self.store.client.books.values()), 0
        )

    def test_real_transport_rolls_and_reads_back_exact_cells(self):
        db, data = fixture(12)
        self.addCleanup(db.close)
        plan = self.pub.prepare(stream(data))
        self.assertEqual(self.provider.creations, 0)
        self.assertTrue(
            all(
                p["book"].startswith("new:")
                for p in plan["capacity"]["creations"]
                if p["title"].startswith("Historico_")
            )
        )
        first = self.pub.apply(plan, max_batches=1)
        self.assertEqual(first["applied_rows"], 4)
        final = self.pub.apply(plan)
        self.assertEqual(final["remaining_batches"], 0)
        self.assertEqual(
            allocated_cells(
                self.store._storage_books["history"].fetch_sheet_metadata()
            ),
            18_413_260,
        )
        self.assertEqual(
            self.store._continuity.index.config["history_publication"]["state"], "READY"
        )
        self.assertGreater(self.provider.creations, 2)
        before = sum(b.data_writes for b in self.store.client.books.values())
        repeated = self.pub.prepare(stream(data))
        self.assertEqual(self.pub.apply(repeated)["applied_rows"], 0)
        self.assertEqual(
            sum(b.data_writes for b in self.store.client.books.values()), before
        )

    def test_folder_or_edit_permission_change_blocks_before_write(self):
        from order_history import HistoryError

        db, data = fixture(2)
        self.addCleanup(db.close)
        plan = self.pub.prepare(stream(data))
        original = self.remote._drive
        for change in (
            dict(parents=["outra_pasta"]),
            dict(capabilities={"canEdit": False}),
        ):
            self.remote._drive = lambda book, change=change: dict(
                original(book), **change
            )
            before = sum(b.data_writes for b in self.store.client.books.values())
            with self.assertRaisesRegex(HistoryError, "PASTA_OU_PERMISSOES"):
                self.pub.apply(plan)
            self.assertEqual(
                sum(b.data_writes for b in self.store.client.books.values()), before
            )
        self.remote._drive = original

    def test_old_part_update_cancellation_ltv_and_empty_window(self):
        from order_history import normalize_order
        from order_history_sheets import tables
        from order_history_store import HistoryStore
        from tests.test_order_history import NOW, order

        db, data = fixture(12)
        self.addCleanup(db.close)
        self.pub.apply(self.pub.prepare(stream(data)))
        history = HistoryStore(db, "FARMA")
        changed = order(1, status=3, segment="FARMA")
        history.upsert(
            normalize_order(changed, "FARMA", NOW), now=NOW, mode="historica"
        )
        db.commit()
        plan = self.pub.prepare(stream(tables(history)))
        self.assertEqual(plan["table_stats"]["Historico_Pedidos"]["updated"], 1)
        self.assertGreater(plan["table_stats"]["Historico_Itens"]["inactivated"], 0)
        self.assertEqual(plan["table_stats"]["BI_LTV_Clientes"]["updated"], 1)
        original = next(
            p
            for p in self.remote.describe(SCHEMAS)["parts"]
            if p["title"] == "Historico_Pedidos" and p["number"] == 0
        )
        self.pub.apply(plan)
        rows = dict(self.remote.scan(original, SCHEMAS["Historico_Pedidos"]))
        index = SCHEMAS["Historico_Pedidos"].index("estado")
        self.assertEqual(rows[2][index], "cancelado")
        self.assertEqual(
            self.pub.check(plan)["conference"]["diferenca_pedidos_ltv_centavos"], 0
        )

    def test_same_sku_different_item_ids_and_empty_source(self):
        from copy import deepcopy

        from order_history import normalize_order
        from order_history_sheets import tables
        from order_history_store import HistoryStore
        from tests.test_order_history import NOW, order

        db, _ = fixture(0)
        self.addCleanup(db.close)
        history = HistoryStore(db, "FARMA")
        empty = self.pub.prepare(stream(tables(history)))
        self.pub.apply(empty)
        self.assertEqual(
            self.pub.check(empty)["conference"]["diferenca_pedidos_ltv_centavos"], 0
        )
        row = order(1, segment="FARMA")
        second = deepcopy(row["itens"][0])
        second["id"] = "segundo-item-sintetico"
        row["itens"].append(second)
        history.upsert(normalize_order(row, "FARMA", NOW), now=NOW, mode="historica")
        db.commit()
        plan = self.pub.prepare(stream(tables(history)))
        self.assertEqual(plan["table_stats"]["Historico_Itens"]["inserted"], 2)
        self.pub.apply(plan)
        total = self.pub.check(plan)["conference"]["observado"]["recortes"][-1]
        self.assertEqual(total["itens_linhas_validas"], 2)
        self.assertEqual(total["faturamento_centavos"], 16000)
