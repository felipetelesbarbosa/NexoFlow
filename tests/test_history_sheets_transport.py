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
from tests.sheets_memory import Book, Client, GspreadSheet, Provisioner
from tests.test_history_publication import fixture, stream


def batch_get(book, ranges, params=None):
    result = []
    for target in ranges:
        title, area = target.split("!", 1)
        result.append(
            dict(
                range=target,
                values=book.worksheet(title.strip("'")).get(
                    area,
                    value_render_option=(params or {}).get(
                        "valueRenderOption", "FORMATTED_VALUE"
                    ),
                ),
            )
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

    def test_unallocated_rows_are_empty_without_reading_outside_live_grid(self):
        db, data = fixture(1)
        self.addCleanup(db.close)
        plan = self.pub.prepare(stream(data))
        self.remote.acquire()
        self.remote.preflight(plan["capacity"], self.pub_metadata(plan))
        self.remote.begin(plan["revision"], SCHEMAS)
        planned = plan["capacity"]["creations"][0]
        headers = SCHEMAS[planned["title"]]
        part = self.remote.ensure_part(planned, headers)
        ws = self.remote._physical(part)
        book = self.store.client.books[part["book"]]
        with patch.object(
            book, "values_batch_get", wraps=book.values_batch_get
        ) as read:
            writes = self.store._write_requests
            self.assertEqual(
                self.remote.read_rows(part, headers, [2, 201]), [None, None]
            )
            read.assert_not_called()
            self.assertEqual(ws.row_count, 1)
            self.assertEqual(self.store._write_requests, writes)
            # O plano/handle ainda apontam uma linha. Uma expansão de terceiro
            # deve ser percebida, inclusive com posições intercaladas e fora de ordem.
            ws.resize(rows=3)
            row = next(r for t, r in stream(data) if t == part["title"])
            ws.update(
                range_name=f"A3:{self.remote.manager.store_column(len(headers))}3",
                values=[[row[h] for h in headers]],
            )
            from order_history_sheets import normalized_cells

            self.assertEqual(
                self.remote.read_rows(part, headers, [4, 3, 2]),
                [None, normalized_cells(row), None],
            )
            ranges = read.call_args.args[0]
            self.assertEqual(len(ranges), 2)
            self.assertTrue(all("4:" not in r for r in ranges))
            ws.col_count += 1
            with self.assertRaisesRegex(ValueError, "COLUNAS_ALTERADAS"):
                self.remote.read_rows(part, headers, [2])

    def test_live_route_is_checked_per_phase_and_before_batch_without_per_file_reads(
        self,
    ):
        from contextlib import closing

        from history_publication import get
        from sheets_storage import STORAGE_SHEET

        mapping = self.store.book.add(
            STORAGE_SHEET, self.store._storage_layout.values()
        )
        live_context = GoogleSheetsStore.native_meta_context.__get__(self.store)
        with (
            patch("runtime_profile.segment", return_value="FARMA"),
            patch("runtime_profile.validate_sheet_destinations"),
            patch(
                "sheets_storage.configured_storage",
                return_value=self.store._storage_layout,
            ),
            patch.object(
                self.store, "native_meta_context", wraps=live_context
            ) as context,
        ):
            db, data = fixture(12)
            self.addCleanup(db.close)
            plan = self.pub.prepare(stream(data))
            context.reset_mock()
            pilot = self.pub.apply(plan, max_batches=1)
            self.assertEqual(pilot["applied_batches"], 1)
            self.assertEqual(context.call_count, 4)
            self.pub.apply(plan)
            self.assertEqual(self.pub.check(plan)["status"], "conferida")
            # Revalidar ao retomar; nenhuma cache permanente do mapa.
            mapping.values[-1][1] = "outro-historico"
            with self.assertRaisesRegex(ValueError, "mapa de arquivos mudou"):
                self.pub.apply(plan)
            with closing(self.pub._open(plan)) as journal:
                self.assertTrue(get(journal, "finished"))

    def test_route_changed_after_preflight_blocks_first_batch(self):
        from contextlib import closing

        from sheets_storage import STORAGE_SHEET

        mapping = self.store.book.add(
            STORAGE_SHEET, self.store._storage_layout.values()
        )
        live_context = GoogleSheetsStore.native_meta_context.__get__(self.store)
        ensure = self.remote.ensure_part

        def changed(planned, headers):
            part = ensure(planned, headers)
            mapping.values[-1][1] = "outro-historico"
            return part

        with (
            patch("runtime_profile.segment", return_value="FARMA"),
            patch("runtime_profile.validate_sheet_destinations"),
            patch(
                "sheets_storage.configured_storage",
                return_value=self.store._storage_layout,
            ),
            patch.object(self.store, "native_meta_context", wraps=live_context),
        ):
            db, data = fixture(1)
            self.addCleanup(db.close)
            plan = self.pub.prepare(stream(data))
            with patch.object(self.remote, "ensure_part", side_effect=changed):
                with self.assertRaisesRegex(ValueError, "mapa de arquivos mudou"):
                    self.pub.apply(plan, max_batches=1)
            with closing(self.pub._open(plan)) as journal:
                self.assertEqual(
                    journal.execute("SELECT DISTINCT state FROM batches").fetchall(),
                    [("pending",)],
                )
            self.assertFalse(list(Path(plan["journal"]).parent.glob("lote_*.json")))

    @patch("tests.sheets_memory.Sheet", GspreadSheet)
    def test_fresh_setup_through_pilot_resume_check_and_idempotence(self):
        from run_sheets_continuation import StorageSetup
        from sheets_storage import STORAGE_SHEET

        books = self.store.client.books
        for book in books.values():
            book.metadata.clear()
        hub = books["dashboard"]
        hub.sheets = [w for w in hub.sheets if w.title != "NexoFlow_Continuidade"]
        hub.add(STORAGE_SHEET, self.store._storage_layout.values())
        with patch(
            "run_sheets_continuation.configured_storage",
            return_value=self.store._storage_layout,
        ):
            setup = StorageSetup(self.store.client, "dashboard", "FARMA")
        self.addCleanup(setup.close)
        self.assertTrue(setup.configure(self.provider))
        setup.activate_connector(list(SCHEMAS))
        # Fronteiras pequenas no mesmo mecanismo oficial, sem fatos pré-gravados.
        setup.index.config.update(max_part_rows=5)
        setup.sheet.update(
            range_name=f"A1:C{len(setup.index.values())}", values=setup.index.values()
        )
        setup.close()
        self.store._continuity = RolloverManager(
            self.store,
            setup.sheet,
            setup.index,
            provisioner_factory=lambda: self.provider,
        )
        self.store._continuity.journal_path = (
            Path(self.tmp.name) / "fresh-creation.json"
        )
        self.remote = SheetsTransport(self.store)
        self.remote._drive = lambda book: dict(
            version=digest(
                [
                    books[book].fetch_sheet_metadata(),
                    [w.values for w in books[book].sheets],
                ]
            ),
            capabilities=dict(canEdit=True),
            parents=[],
        )
        self.pub = Publication(self.remote, "FARMA", Path(self.tmp.name) / "fresh")
        db, data = fixture(12)
        self.addCleanup(db.close)
        before = sum(b.data_writes for b in books.values())
        plan = self.pub.prepare(stream(data))
        self.assertEqual(sum(b.data_writes for b in books.values()), before)
        self.assertEqual(self.provider.creations, 0)
        pilot = self.pub.apply(plan, max_batches=1)
        self.assertGreater(pilot["remaining_batches"], 0)
        self.pub.check(plan)
        self.assertEqual(self.pub.rollback(plan, 1)["status"], "restaurado")
        complete = self.pub.apply(plan)
        self.assertEqual(complete["remaining_batches"], 0)
        self.pub.check(plan)
        self.assertEqual(
            self.store._continuity.index.config["history_publication"]["state"], "READY"
        )
        repeated = self.pub.prepare(stream(data))
        self.assertEqual(self.pub.apply(repeated)["applied_rows"], 0)

    @patch("tests.sheets_memory.Sheet", GspreadSheet)
    def test_root_blank_get_contract_and_header_response_loss_resume(self):
        from requests import Timeout

        db, data = fixture(1)
        self.addCleanup(db.close)
        plan = self.pub.prepare(stream(data))
        self.remote.acquire()
        self.remote.preflight(plan["capacity"], self.pub_metadata(plan))
        self.remote.begin(plan["revision"], SCHEMAS)
        planned = next(
            p for p in plan["capacity"]["creations"] if not p["book"].startswith("new:")
        )
        book = self.store.client.books[planned["book"]]
        ws = book.add_worksheet(title=planned["title"], rows=1, cols=planned["width"])
        self.assertEqual(ws.get("A1:A1", value_render_option="FORMULA"), [[]])
        ws.lose_response = True
        # A escrita é aceita, mas a resposta é perdida; retry confere o mesmo
        # cabeçalho antes de registrar a parte, sem duplicar a aba.
        with patch.object(
            self.store, "_write_with_retry", side_effect=lambda _, fn: fn()
        ):
            with self.assertRaises(Timeout):
                self.remote.ensure_part(planned, SCHEMAS[planned["title"]])
        count = len(book.sheets)
        actual = self.remote.ensure_part(planned, SCHEMAS[planned["title"]])
        self.assertEqual(len(book.sheets), count)
        self.assertEqual(actual["sheet"], ws.id)
        self.assertEqual(ws.values, [SCHEMAS[planned["title"]]])

    @patch("tests.sheets_memory.Sheet", GspreadSheet)
    def test_root_nonempty_header_or_hidden_structure_is_never_overwritten(self):
        from order_history import HistoryError
        from sheets_continuation import ContinuationError

        db, data = fixture(1)
        self.addCleanup(db.close)
        plan = self.pub.prepare(stream(data))
        self.remote.acquire()
        self.remote.preflight(plan["capacity"], self.pub_metadata(plan))
        self.remote.begin(plan["revision"], SCHEMAS)
        planned = next(
            p for p in plan["capacity"]["creations"] if not p["book"].startswith("new:")
        )
        book = self.store.client.books[planned["book"]]
        ws = book.add_worksheet(title=planned["title"], rows=1, cols=planned["width"])
        for values in ([[0]], [[False]], [[" "]], [['=""']], [["externo"]]):
            with self.subTest(values=values):
                ws.values = values
                with self.assertRaisesRegex(HistoryError, "CONTEUDO_DIVERGENTE"):
                    self.remote.ensure_part(planned, SCHEMAS[planned["title"]])
                self.assertEqual(ws.values, values)
                self.assertEqual(ws.writes, 0)
        ws.values = []
        ws.native_cells[0, 0] = {"note": "nota sintética"}
        with self.assertRaisesRegex(ContinuationError, "estrutura inesperada"):
            self.remote.ensure_part(planned, SCHEMAS[planned["title"]])
        self.assertEqual(ws.writes, 0)

    @patch("tests.sheets_memory.Sheet", GspreadSheet)
    def test_root_native_metadata_can_include_other_sheets_without_their_grid(self):
        db, data = fixture(1)
        self.addCleanup(db.close)
        plan = self.pub.prepare(stream(data))
        self.remote.acquire()
        self.remote.preflight(plan["capacity"], self.pub_metadata(plan))
        self.remote.begin(plan["revision"], SCHEMAS)
        planned = next(
            p for p in plan["capacity"]["creations"] if not p["book"].startswith("new:")
        )
        book = self.store.client.books[planned["book"]]
        fetch = book.fetch_sheet_metadata

        def metadata(**kwargs):
            result = fetch(**kwargs)
            if kwargs.get("params", {}).get("includeGridData"):
                ids = {s["properties"]["sheetId"] for s in result["sheets"]}
                result["sheets"].extend(
                    s
                    for s in fetch()["sheets"]
                    if s["properties"]["sheetId"] not in ids
                )
            return result

        with patch.object(book, "fetch_sheet_metadata", side_effect=metadata):
            part = self.remote.ensure_part(planned, SCHEMAS[planned["title"]])
        self.assertEqual(part["book"], planned["book"])
        self.assertTrue(book.worksheet("NexoFlow_Continuidade"))

    def pub_metadata(self, plan):
        from contextlib import closing

        from history_publication import get

        with closing(self.pub._open_local(plan)) as db:
            return get(db, "metadata")

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

    def test_same_oauth_folder_hidden_to_service_resumes_but_real_move_blocks(self):
        from sheets_continuation import ContinuationError

        db, data = fixture(12)
        self.addCleanup(db.close)
        plan = self.pub.prepare(stream(data))
        self.assertEqual(
            self.pub_metadata(plan)["permissions"]["historico"]["parents"], ["folder"]
        )
        self.pub.apply(plan, max_batches=1)
        target = next(
            book
            for book in self.store._continuity.index.files
            if book not in self.pub_metadata(plan)["books"]
        )
        before = sum(b.data_writes for b in self.store.client.books.values())
        self.provider.owner_parents[target] = ["moved"]
        with self.assertRaisesRegex(ContinuationError, "PASTA_OAUTH_ALTERADA"):
            self.pub.apply(plan)
        self.assertEqual(
            sum(b.data_writes for b in self.store.client.books.values()), before
        )
        self.provider.owner_parents[target] = ["folder"]
        self.assertEqual(self.pub.apply(plan)["remaining_batches"], 0)
        self.assertEqual(self.pub.check(plan)["status"], "conferida")

    def test_broadened_access_to_created_file_blocks_resume_without_new_rows(self):
        from sheets_continuation import ContinuationError

        db, data = fixture(9)
        self.addCleanup(db.close)
        plan = self.pub.prepare(stream(data))
        self.pub.apply(plan, max_batches=1)
        created = next(
            book
            for book in self.store._continuity.index.files
            if book not in self.pub_metadata(plan)["books"]
        )
        self.provider.permissions[created].append(dict(type="anyone", role="reader"))
        before = sum(b.data_writes for b in self.store.client.books.values())
        with self.assertRaisesRegex(ContinuationError, "acesso amplo"):
            self.pub.apply(plan)
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
