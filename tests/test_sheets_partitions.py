"""Integração da rotina real de upsert/BI com continuações físicas e timeouts."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from google_sheets import GoogleSheetsStore
from sheets_continuation import ContinuationError, ContinuationIndex, allocated_cells
from sheets_partitions import RolloverManager, roots_for
from sheets_storage import SheetsStorage
from tests.sheets_memory import Book, Client, Provisioner


class SheetsPartitionTests(unittest.TestCase):
    def setUp(self):
        self.delay = patch("google_sheets.GOOGLE_SHEETS_WRITE_DELAY_SECONDS", 0)
        self.delay.start()
        self.sleep = patch("google_sheets.time.sleep")
        self.sleep.start()
        self.route = patch("google_sheets.refresh_network_route")
        self.route.start()
        self.addCleanup(self.delay.stop)
        self.addCleanup(self.sleep.stop)
        self.addCleanup(self.route.stop)

    def make(
        self,
        title,
        headers,
        rows=(),
        *,
        extra=0,
        max_rows=500000,
        segment="FARMA",
        connector=False,
    ):
        books = {key: Book(key) for key in ("dashboard", "operations", "history")}
        role = (
            "dashboard"
            if title.startswith("BI_")
            else "history"
            if title == "Historico_Alteracoes"
            else "operations"
        )
        ws = books[role].add(title, [headers, *rows])
        if extra:
            books[role].add("Outra aba", [], rows=extra, cols=1)
        store = GoogleSheetsStore.__new__(GoogleSheetsStore)
        store.book = books["dashboard"]
        store.client = Client(books)
        store._hub_id = "dashboard"
        store._storage_layout = SheetsStorage("dashboard", "operations", "history")
        store._storage_books = books
        store._headers_cache = {title: headers}
        store._last_write_started_at = 0
        store._read_requests = store._write_requests = 0
        index = ContinuationIndex("dashboard", segment, roots_for(store))
        index.config.update(
            threshold=1000,
            max_part_rows=max_rows,
            connector_tables=[title] if connector else [],
        )
        index_ws = store.book.add(
            "NexoFlow_Continuidade", index.values(), rows=100, cols=3
        )
        provisioner = Provisioner(store.client)
        manager = RolloverManager(
            store, index_ws, index, provisioner_factory=lambda: provisioner
        )
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        manager.journal_path = Path(temporary.name) / "history.json"
        store._continuity = manager
        return store, ws, provisioner

    def test_upsert_rolls_before_capacity_and_revalidates_orders_in_old_parts(self):
        for segment in ("FARMA", "PET"):
            with self.subTest(segment=segment):
                store, ws, drive = self.make(
                    "Pedidos_FarmaLider",
                    ["pedido_chave", "valor", "status"],
                    [["old", "10", "0"]],
                    extra=990,
                    segment=segment,
                )
                records = [
                    {"pedido_chave": key, "valor": "12", "status": "2"}
                    for key in ("old", "two", "three", "four")
                ]
                result = store._upsert_records_detailed(ws, records, "pedido_chave")
                self.assertEqual((result.inserted, result.updated), (3, 1))
                self.assertEqual(drive.creations, 1)
                self.assertEqual(drive.shared, ["continuation1"])
                self.assertLessEqual(
                    allocated_cells(ws.book.fetch_sheet_metadata()), 1000
                )
                repeated = store._upsert_records_detailed(ws, records, "pedido_chave")
                self.assertEqual(
                    (repeated.inserted, repeated.updated, repeated.unchanged), (0, 0, 4)
                )
                self.assertEqual(drive.creations, 1)
                self.assertEqual(len(repeated.final_records), 4)
                corrected = store._upsert_records_detailed(
                    ws, [{"pedido_chave": "three", "status": "3"}], "pedido_chave"
                )
                self.assertEqual(corrected.updated, 1)
                self.assertEqual(
                    {r["pedido_chave"]: r["status"] for r in corrected.final_records},
                    {"old": "2", "two": "2", "three": "3", "four": "2"},
                )

    def test_reopening_store_reads_all_parts_with_the_service_account(self):
        store, ws, drive = self.make(
            "Pedidos_FarmaLider", ["pedido_chave", "valor"], max_rows=3
        )
        store._upsert_records_detailed(
            ws,
            [{"pedido_chave": str(i), "valor": str(i * 10)} for i in range(5)],
            "pedido_chave",
        )
        values = store._continuity.sheet.get_all_values()
        index = ContinuationIndex.parse(
            values, hub=store._hub_id, segment="FARMA", roots=roots_for(store)
        )
        store._continuity.close()
        store._continuity = RolloverManager(
            store,
            store.book.worksheet("NexoFlow_Continuidade"),
            index,
            provisioner_factory=lambda: self.fail(
                "Reading existing continuations must not require OAuth"
            ),
        )
        self.assertEqual(
            [row[0] for row in store._table_values(ws)[1:]], ["0", "1", "2", "3", "4"]
        )
        self.assertEqual(drive.creations, 2)

    def test_timeout_after_writing_repeats_fixed_coordinates_without_duplicate(self):
        store, ws, drive = self.make(
            "Pedidos_FarmaLider", ["pedido_chave", "valor"], max_rows=3
        )
        ws.lose_response = True
        records = [{"pedido_chave": str(i), "valor": "10"} for i in range(4)]
        with self.assertRaisesRegex(ContinuationError, "não confirmou"):
            store._upsert_records_detailed(ws, records, "pedido_chave")
        old = store._continuity
        old.close()
        import json

        from sheets_continuation import LEASE_ID

        lease = json.loads(store.book.metadata[LEASE_ID]["metadataValue"])
        lease["expires"] = 1
        store.book.metadata[LEASE_ID]["metadataValue"] = json.dumps(lease)
        index = ContinuationIndex.parse(
            old.sheet.get_all_values(),
            hub=store._hub_id,
            segment="FARMA",
            roots=roots_for(store),
        )
        store._continuity = RolloverManager(
            store, old.sheet, index, provisioner_factory=lambda: drive
        )
        result = store._upsert_records_detailed(ws, records, "pedido_chave")
        self.assertEqual(result.inserted, 2)
        self.assertEqual(
            [r[0] for r in store._table_values(ws)[1:]], ["0", "1", "2", "3"]
        )
        self.assertEqual(drive.creations, 1)

    def test_bi_requires_connector_before_overflow_and_publishes_all_parts(self):
        store, ws, drive = self.make(
            "BI_Itens", ["item_chave", "receita_item"], [["previous", 9]], max_rows=3
        )
        rows = [[str(i), i + 1] for i in range(5)]
        with self.assertRaisesRegex(ContinuationError, "conector NexoFlow"):
            store._replace_table(ws, ws.values[0], rows)
        self.assertEqual(ws.get_all_values()[1:], [["previous", 9]])
        self.assertEqual(drive.creations, 0)
        store._continuity.index.config["connector_tables"] = [ws.title]
        store._replace_table(ws, ws.values[0], rows)
        self.assertEqual(store._table_values(ws)[1:], rows)
        state = store._continuity.index.status[ws.title]
        self.assertEqual(state["state"], "READY")
        self.assertEqual(sum(p["rows"] for p in state["parts"]), 5)
        store._replace_table(ws, ws.values[0], [["only", 50]])
        self.assertEqual(store._table_values(ws)[1:], [["only", 50]])

    def test_history_is_appended_across_parts_without_rewriting_older_events(self):
        store, ws, drive = self.make(
            "Historico_Alteracoes",
            ["contact_uuid", "acao"],
            [["old", "Inserido"]],
            max_rows=3,
        )
        store.history = ws
        store._continuity.append_history(
            ws, [["a", "Atualizado"], ["b", "Atualizado"], ["c", "Inserido"]]
        )
        self.assertEqual(
            store._table_values(ws),
            [
                ["contact_uuid", "acao"],
                ["old", "Inserido"],
                ["a", "Atualizado"],
                ["b", "Atualizado"],
                ["c", "Inserido"],
            ],
        )
        self.assertEqual(drive.creations, 1)

    def test_foreign_segment_part_is_rejected_before_data_can_be_read(self):
        store, ws, drive = self.make("Pedidos_FarmaLider", ["pedido_chave"], max_rows=2)
        store._upsert_records_detailed(
            ws, [{"pedido_chave": "a"}, {"pedido_chave": "b"}], "pedido_chave"
        )
        manager = store._continuity
        manager.books.pop("continuation1")
        manager.handles.clear()
        store.client.properties["continuation1"]["nexoflow_segment"] = "PET"
        with self.assertRaisesRegex(ContinuationError, "segmento"):
            manager.read(ws)

    def test_changed_access_blocks_resume_before_any_new_share(self):
        store, ws, provider = self.make(
            "Pedidos_FarmaLider", ["pedido_chave"], max_rows=2
        )
        original = provider.prepare_intent
        calls = [0]

        def access(*args, **kwargs):
            result = original(*args, **kwargs)
            calls[0] += 1
            if calls[0] == 2:
                result["parents"] = ["another_folder"]
            return result

        with patch.object(provider, "prepare_intent", side_effect=access):
            with self.assertRaisesRegex(ContinuationError, "acessos da origem mudaram"):
                store._upsert_records_detailed(
                    ws, [{"pedido_chave": "a"}, {"pedido_chave": "b"}], "pedido_chave"
                )
        self.assertEqual(provider.creations, 1)
        self.assertEqual(provider.shared, [])
        self.assertEqual(len(store._continuity.index.intents), 1)

    def test_unchanged_bi_is_confirmed_after_activation_or_interrupted_publication(
        self,
    ):
        store, ws, _ = self.make(
            "BI_Itens", ["item_chave", "receita_item"], [["a", 10]]
        )
        for previous in (None, {"state": "WRITING", "revision": "a" * 32}):
            if previous:
                store._continuity.index.status[ws.title] = previous
            else:
                store._continuity.index.status.pop(ws.title, None)
            changed = store._replace_table(ws, ws.values[0], [["a", 10]])
            self.assertFalse(changed)
            self.assertEqual(store._continuity.index.status[ws.title]["state"], "READY")
            self.assertEqual(
                store._continuity.index.status[ws.title]["parts"],
                [{"number": 0, "rows": 1}],
            )
            self.assertEqual(ws.writes, 0)

    def test_history_response_lost_resumes_exact_rows_without_duplicate_event(self):
        import json

        from sheets_continuation import LEASE_ID

        store, ws, provider = self.make(
            "Historico_Alteracoes",
            ["contact_uuid", "acao"],
            [["old", "Inserido"]],
            max_rows=3,
        )
        store.history = ws
        manager = store._continuity
        ws.lose_response = True
        with self.assertRaisesRegex(ContinuationError, "não confirmou"):
            manager.append_history(ws, [["a", "Atualizado"], ["b", "Inserido"]])
        self.assertTrue(manager.journal_path.is_file())
        manager.close()
        lease = json.loads(store.book.metadata[LEASE_ID]["metadataValue"])
        lease["expires"] = 1
        store.book.metadata[LEASE_ID]["metadataValue"] = json.dumps(lease)
        index = ContinuationIndex.parse(
            manager.sheet.get_all_values(),
            hub="dashboard",
            segment="FARMA",
            roots=roots_for(store),
        )
        resumed = RolloverManager(
            store, manager.sheet, index, provisioner_factory=lambda: provider
        )
        resumed.journal_path = manager.journal_path
        store._continuity = resumed
        resumed.resume_history()
        self.assertEqual(
            store._table_values(ws)[1:],
            [["old", "Inserido"], ["a", "Atualizado"], ["b", "Inserido"]],
        )
        self.assertFalse(resumed.journal_path.exists())
        self.assertEqual(provider.creations, 1)

    def test_pending_history_does_not_overwrite_conflicting_cells(self):
        import json

        from sheets_continuation import LEASE_ID

        store, ws, _ = self.make("Historico_Alteracoes", ["contact_uuid", "acao"])
        store.history = ws
        manager = store._continuity
        ws.lose_response = True
        with self.assertRaises(ContinuationError):
            manager.append_history(ws, [["a", "Atualizado"]])
        ws.values[1] = ["other", "manual"]
        manager.close()
        lease = json.loads(store.book.metadata[LEASE_ID]["metadataValue"])
        lease["expires"] = 1
        store.book.metadata[LEASE_ID]["metadataValue"] = json.dumps(lease)
        manager.lease.uncertain = False
        with self.assertRaisesRegex(ContinuationError, "não sobrescrever"):
            manager.resume_history()
        self.assertEqual(ws.values[1], ["other", "manual"])
        self.assertTrue(manager.journal_path.exists())
