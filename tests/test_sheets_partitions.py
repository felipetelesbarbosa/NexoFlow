"""Integração da rotina real de upsert/BI com continuações físicas e timeouts."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from requests import Timeout

from google_sheets import GoogleSheetsStore
from sheets_continuation import ContinuationError, ContinuationIndex, allocated_cells
from sheets_partitions import RolloverManager, roots_for
from sheets_storage import SheetsStorage
from tests.sheets_memory import Book, Client, GspreadSheet, Provisioner
from tests.test_sheets_continuation import metadata_api_error


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

    def test_final_lease_quota_recovers_manifest_without_repeating_fact_writes(self):
        for segment in ("FARMA", "PET"):
            with self.subTest(segment=segment):
                store, ws, _ = self.make(
                    "BI_Conversao", ["chave", "valor"], segment=segment
                )
                manager = store._continuity
                original_values = ws.get_all_values
                original_metadata = store.book.fetch_sheet_metadata
                failure = [False]
                triggered = [False]

                def values(
                    original_values=original_values,
                    triggered=triggered,
                    failure=failure,
                    manager=manager,
                    **kwargs,
                ):
                    result = original_values(**kwargs)
                    if (
                        kwargs.get("value_render_option") == "UNFORMATTED_VALUE"
                        and not triggered[0]
                    ):
                        triggered[0] = failure[0] = True
                        manager.lease.renewed_at = 0
                    return result

                def metadata(
                    failure=failure,
                    original_metadata=original_metadata,
                    **kwargs,
                ):
                    if (
                        failure[0]
                        and kwargs.get("params", {}).get("fields")
                        == "developerMetadata"
                    ):
                        failure[0] = False
                        raise metadata_api_error(429)
                    return original_metadata(**kwargs)

                manager.lease.sleep = Mock()
                records = [{"chave": "sintetica", "valor": "12.34"}]
                with (
                    patch.object(ws, "get_all_values", side_effect=values),
                    patch.object(
                        store.book, "fetch_sheet_metadata", side_effect=metadata
                    ),
                    self.assertLogs(level="WARNING"),
                ):
                    result = store._upsert_records_detailed(ws, records, "chave")
                self.assertTrue(triggered[0])
                self.assertEqual(result.inserted, 1)
                manager.lease.sleep.assert_called_once_with(65)
                self.assertEqual(manager.index.status[ws.title]["state"], "READY")
                persisted = ContinuationIndex.parse(
                    manager.sheet.get_all_values(),
                    hub=store._hub_id,
                    segment=segment,
                    roots=roots_for(store),
                )
                self.assertEqual(persisted.status[ws.title]["state"], "READY")
                before_writes = ws.writes
                repeated = store._upsert_records_detailed(ws, records, "chave")
                self.assertEqual(
                    (repeated.inserted, repeated.updated, repeated.unchanged), (0, 0, 1)
                )
                self.assertEqual(ws.writes, before_writes)
                self.assertEqual(
                    ws.get_all_values(), [["chave", "valor"], ["sintetica", "12.34"]]
                )

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

    def creation_candidate(self, *, title="Página1", values=()):
        store, _, provider = self.make("Historico_Pedidos", ["chave", "valor"])
        manager = store._continuity
        original = provider.create

        def create(intent, **kwargs):
            file_id = original(intent, **kwargs)
            book = store.client.books[file_id]
            initial = book.sheets[0]
            book.sheets[0] = GspreadSheet(
                book,
                title,
                list(values),
                initial.id,
                rows=initial.row_count,
                cols=initial.col_count,
            )
            return file_id

        provider.create = Mock(side_effect=create)
        return manager, provider

    def test_initial_empty_sheet_uses_real_gspread_contract(self):
        for values in ([], [[]], [[""]], [["", ""], ["", ""]]):
            for include_empty in (False, True):
                for title in ("Página1", "Historico_Pedidos"):
                    with self.subTest(
                        values=values, include_empty=include_empty, title=title
                    ):
                        manager, provider = self.creation_candidate(
                            title=title, values=values
                        )
                        original = provider.share

                        def share(
                            file_id,
                            intent,
                            original=original,
                            manager=manager,
                            include_empty=include_empty,
                        ):
                            original(file_id, intent)
                            candidate = manager.store.client.books[file_id].sheets[0]
                            candidate.include_empty_values = include_empty

                        with patch.object(provider, "share", side_effect=share):
                            snapshot = manager._create_part(
                                "Historico_Pedidos", ["chave", "valor"]
                            )
                        self.assertEqual(
                            snapshot.worksheet.values, [["chave", "valor"]]
                        )
                        self.assertEqual(snapshot.worksheet.row_count, 1)
                        self.assertEqual(snapshot.worksheet.frozen_row_count, 0)
                        self.assertEqual(provider.creations, 1)
                        self.assertEqual(manager.index.intents, {})
                        self.assertEqual(
                            snapshot.worksheet.reads[0]["valueRenderOption"], "FORMULA"
                        )
                        manager.close()

    def test_one_row_anchor_keeps_capacity_without_freezing_all_rows(self):
        store, ws, provider = self.make("Pedidos_FarmaLider", ["chave", "valor"])
        ws.book.sheets.remove(ws)
        ws.book.add("Outra aba", [], rows=998, cols=1)
        created = store._get_or_create_sheet("Pedidos_FarmaLider", ["chave", "valor"])
        self.assertEqual(created.row_count, 1)
        self.assertEqual(created.frozen_row_count, 0)
        self.assertEqual(allocated_cells(created.book.fetch_sheet_metadata()), 1000)
        self.assertEqual(provider.creations, 0)

    def test_normal_root_creation_still_freezes_header_with_free_rows(self):
        store, ws, _ = self.make("Pedidos_FarmaLider", ["chave", "valor"])
        ws.book.sheets.remove(ws)
        manager = store._continuity
        store._continuity = None
        created = store._get_or_create_sheet("Pedidos_FarmaLider", ["chave", "valor"])
        self.assertGreater(created.row_count, 1)
        self.assertEqual(created.frozen_row_count, 1)
        manager.close()

    def test_unexpected_content_is_preserved_before_resize_or_header_write(self):
        for values in (
            [["manual"]],
            [[0]],
            [[False]],
            [[" "]],
            [[None]],
            [['=""']],
            [["chave", "valor"], ['=""']],
        ):
            for title in ("Página1", "Historico_Pedidos"):
                with self.subTest(values=values, title=title):
                    manager, provider = self.creation_candidate(
                        title=title, values=values
                    )
                    original = provider.share

                    def share(file_id, intent, original=original, manager=manager):
                        original(file_id, intent)
                        candidate = manager.store.client.books[file_id].sheets[0]
                        candidate.formatted_values = []

                    with patch.object(provider, "share", side_effect=share):
                        with self.assertRaises(ContinuationError):
                            manager._create_part(
                                "Historico_Pedidos", ["chave", "valor"]
                            )
                    candidate = manager.store.client.books["continuation1"].sheets[0]
                    self.assertEqual(candidate.values, values)
                    self.assertEqual(
                        (candidate.row_count, candidate.col_count), (1000, 26)
                    )
                    self.assertEqual(candidate.writes, 0)
                    self.assertEqual(candidate.title, title)
                    self.assertIn("Historico_Pedidos#0", manager.index.intents)
                    self.assertEqual(manager.index.parts, {})
                    manager.close()

    def test_multiple_sheets_are_rejected_even_with_matching_title(self):
        for title in ("Página1", "Historico_Pedidos"):
            with self.subTest(title=title):
                manager, provider = self.creation_candidate(
                    title=title,
                    values=[["chave", "valor"]] if title == "Historico_Pedidos" else [],
                )
                original = provider.share

                def share(file_id, intent, original=original, manager=manager):
                    original(file_id, intent)
                    manager.store.client.books[file_id].add("Outra aba", [["manual"]])

                with patch.object(provider, "share", side_effect=share):
                    with self.assertRaisesRegex(ContinuationError, "abas inesperadas"):
                        manager._create_part("Historico_Pedidos", ["chave", "valor"])
                book = manager.store.client.books["continuation1"]
                self.assertEqual(len(book.sheets), 2)
                self.assertEqual(book.sheets[0].writes, 0)
                self.assertEqual(book.sheets[0].row_count, 1000)
                self.assertEqual(book.sheets[1].values, [["manual"]])
                manager.close()

    def test_invisible_cell_structure_is_preserved_before_resize(self):
        for field, content in (
            ("note", "anotação"),
            ("dataValidation", {"strict": True}),
            ("userEnteredFormat", {"backgroundColor": {"red": 1}}),
        ):
            with self.subTest(field=field):
                manager, provider = self.creation_candidate()
                original = provider.share

                def share(
                    file_id,
                    intent,
                    original=original,
                    manager=manager,
                    field=field,
                    content=content,
                ):
                    original(file_id, intent)
                    candidate = manager.store.client.books[file_id].sheets[0]
                    candidate.native_cells[999, 25] = {field: content}

                with patch.object(provider, "share", side_effect=share):
                    with self.assertRaisesRegex(
                        ContinuationError, "estrutura inesperada"
                    ):
                        manager._create_part("Historico_Pedidos", ["chave", "valor"])
                candidate = manager.store.client.books["continuation1"].sheets[0]
                self.assertEqual(candidate.native_cells[999, 25], {field: content})
                self.assertEqual((candidate.row_count, candidate.col_count), (1000, 26))
                self.assertEqual(candidate.title, "Página1")
                self.assertEqual(candidate.writes, 0)
                manager.close()

    def test_unexpected_sheet_structure_or_extra_metadata_blocks_resize(self):
        for field in (
            "protectedRanges",
            "merges",
            "bandedRanges",
            "rowGroups",
            "columnGroups",
            "slicers",
            "tables",
            "extra_sheet",
            "changed_id",
            "changed_title",
            "changed_grid",
        ):
            with self.subTest(field=field):
                manager, provider = self.creation_candidate()
                original = provider.share

                def share(
                    file_id, intent, original=original, manager=manager, field=field
                ):
                    original(file_id, intent)
                    book = manager.store.client.books[file_id]
                    fetch = book.fetch_sheet_metadata

                    def metadata(**kwargs):
                        result = fetch(**kwargs)
                        params = kwargs.get("params", {})
                        if not params.get("ranges"):
                            properties = result["sheets"][0]["properties"]
                            if field == "extra_sheet":
                                result["sheets"].append(
                                    {"properties": {"sheetId": 999}}
                                )
                            elif field == "changed_id":
                                properties["sheetId"] = 999
                            elif field == "changed_title":
                                properties["title"] = "Outra aba"
                            elif field == "changed_grid":
                                properties["gridProperties"]["rowCount"] += 1
                        elif (
                            not field.startswith("changed_") and field != "extra_sheet"
                        ):
                            result["sheets"][0][field] = [
                                {"range": {"startRowIndex": 999}}
                            ]
                        return result

                    book.fetch_sheet_metadata = Mock(side_effect=metadata)

                with patch.object(provider, "share", side_effect=share):
                    with self.assertRaisesRegex(
                        ContinuationError,
                        "estrutura inesperada|grade da nova continuação mudou",
                    ):
                        manager._create_part("Historico_Pedidos", ["chave", "valor"])
                candidate = manager.store.client.books["continuation1"].sheets[0]
                self.assertEqual((candidate.row_count, candidate.col_count), (1000, 26))
                self.assertEqual(candidate.title, "Página1")
                self.assertEqual(candidate.writes, 0)
                if field == "extra_sheet" or field.startswith("changed_"):
                    params = candidate.book.fetch_sheet_metadata.call_args.kwargs[
                        "params"
                    ]
                    self.assertNotIn("ranges", params)
                    self.assertNotIn("data(", params["fields"])
                manager.close()

    def test_lost_rename_or_header_response_resumes_same_intent_without_duplicate(self):
        import json

        from sheets_continuation import LEASE_ID

        for step in ("update_title", "update"):
            with self.subTest(step=step):
                manager, provider = self.creation_candidate()
                original = provider.share

                def share(
                    file_id, intent, original=original, manager=manager, step=step
                ):
                    original(file_id, intent)
                    candidate = manager.store.client.books[file_id].sheets[0]
                    operation = getattr(candidate, step)

                    def lost(*args, **kwargs):
                        operation(*args, **kwargs)
                        raise Timeout("resposta perdida sintética")

                    setattr(candidate, step, Mock(side_effect=lost))

                with patch.object(provider, "share", side_effect=share):
                    with self.assertRaisesRegex(ContinuationError, "não confirmou"):
                        manager._create_part("Historico_Pedidos", ["chave", "valor"])
                candidate = manager.store.client.books["continuation1"].sheets[0]
                setattr(candidate, step, getattr(GspreadSheet, step).__get__(candidate))
                # Reabrir o índice persistido, como uma nova execução após a falha.
                manager.close()
                lease = json.loads(
                    manager.store.book.metadata[LEASE_ID]["metadataValue"]
                )
                lease["expires"] = 1
                manager.store.book.metadata[LEASE_ID]["metadataValue"] = json.dumps(
                    lease
                )
                index = ContinuationIndex.parse(
                    manager.sheet.get_all_values(),
                    hub="dashboard",
                    segment="FARMA",
                    roots=roots_for(manager.store),
                )
                resumed = RolloverManager(
                    manager.store,
                    manager.sheet,
                    index,
                    provisioner_factory=lambda provider=provider: provider,
                )
                manager.store._continuity = resumed
                snapshot = resumed._create_part("Historico_Pedidos", ["chave", "valor"])
                self.assertEqual(snapshot.worksheet.values, [["chave", "valor"]])
                self.assertEqual(provider.creations, 1)
                self.assertEqual(provider.create.call_count, 1)
                self.assertEqual(len(resumed.index.parts), 1)
                self.assertEqual(resumed.index.intents, {})
                self.assertEqual(len(candidate.book.sheets), 1)
                resumed.close()

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
