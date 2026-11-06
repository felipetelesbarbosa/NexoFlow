"""Persistência Meta com store real e planilhas em memória; nenhuma API externa."""

import os
import re
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch

from gspread.exceptions import WorksheetNotFound

from google_sheets import GoogleSheetsStore
from meta_ads_model import SCHEMAS
from meta_ads_sheets import NativeMetaSchemaError, NativeMetaSheets
from sheets_storage import SheetsStorage

ACCOUNT = "12345678901234567"
AD = "120250505038200073"


def row(title="Meta_Ads_Diario", key="opaque-key", **changes):
    result = {name: "" for name in SCHEMAS[title]}
    result.update(chave=key, segmento="FARMA", conta_id=ACCOUNT)
    if "anuncio_id" in result:
        result["anuncio_id"] = AD
    result.update(changes)
    return result


class MemoryWorksheet:
    def __init__(self, title, book, values=()):
        self.title, self.book = title, book
        self.values = deepcopy(list(values))
        self.id = len(book.tabs) + 1
        self.row_count, self.col_count = (
            1000,
            max((len(r) for r in values), default=26),
        )

    def get_all_values(self, **kwargs):
        return deepcopy(self.values)

    def batch_get(self, ranges, **kwargs):
        result = []
        for cell_range in ranges:
            start, end = [int(x) for x in re.findall(r"\d+", cell_range)]
            result.append(deepcopy(self.values[start - 1 : end]))
        return result

    def update(self, *, range_name, values, value_input_option):
        if self.title in self.book.store.fail_titles:
            raise RuntimeError("simulated API failure")
        last_col = re.findall(r"[A-Z]+", range_name)[-1]
        column = 0
        for letter in last_col:
            column = column * 26 + ord(letter) - ord("A") + 1
        if (
            column > self.col_count
            or max(map(int, re.findall(r"\d+", range_name))) > self.row_count
        ):
            raise RuntimeError("Range exceeds grid limits")
        self.book.store.options.append(value_input_option)
        self.book.store.writes += 1
        start = int(re.match(r"[A-Z]+(\d+)", range_name).group(1)) - 1
        while len(self.values) < start + len(values):
            self.values.append([])
        for i, r in enumerate(values, start):
            self.values[i] = deepcopy(r)

    def batch_update(self, changes, *, value_input_option):
        for change in changes:
            self.update(
                range_name=change["range"],
                values=change["values"],
                value_input_option=value_input_option,
            )

    def resize(self, rows=None, cols=None):
        self.book.store.writes += 1
        if rows:
            self.row_count = rows
        if cols:
            self.col_count = cols


class MemoryBook:
    def __init__(self, book_id, store):
        self.id, self.store, self.tabs = book_id, store, {}

    def worksheet(self, title):
        if title not in self.tabs:
            raise WorksheetNotFound(title)
        return self.tabs[title]

    def add_worksheet(self, *, title, rows, cols):
        if title in self.store.fail_titles:
            raise RuntimeError("simulated create failure")
        self.store.writes += 1
        ws = MemoryWorksheet(title, self)
        ws.row_count, ws.col_count = rows, cols
        self.tabs[title] = ws
        return ws


class MemoryStore(GoogleSheetsStore):
    def __init__(self):
        self.writes = 0
        self.options = []
        self.fail_titles = set()
        self._continuity = None
        self._headers_cache = {}
        self._storage_layout = SheetsStorage("dash", "ops", "hist")
        self._storage_books = {
            book_id: MemoryBook(book_id, self) for book_id in ("dash", "ops", "hist")
        }
        self.book = self._storage_books["dash"]
        self._hub_id = "dash"
        self.profile = "FARMA"

    def native_meta_context(self):
        return {
            "segment": self.profile,
            "dashboard": "dash",
            "operations": "ops",
            "history": "hist",
        }

    def _read_with_retry(self, description, func):
        return func()

    def _write_with_retry(self, description, func):
        return func()

    def put(self, title, records=None, headers=None):
        book = self._storage_books[self._storage_layout.destination(title)]
        schema = (
            headers if headers is not None else SCHEMAS.get(title, ["legacy", "value"])
        )
        values = [schema, *[[r.get(k, "") for k in schema] for r in records or []]]
        ws = MemoryWorksheet(title, book, values)
        book.tabs[title] = ws
        return ws


class NativeMetaSheetsTests(unittest.TestCase):
    def setUp(self):
        root = tempfile.TemporaryDirectory(prefix="native_meta_sheets_")
        self.addCleanup(root.cleanup)
        self.backup = Path(root.name)
        for patcher in (
            patch("meta_ads_sheets.PRIVATE_ROOT", self.backup),
            patch.dict(os.environ, NEXOFLOW_PERFIL="FARMA"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.store = MemoryStore()
        self.native = NativeMetaSheets(self.store, "FARMA", account_ids=(ACCOUNT,))

    def apply(self, tables):
        plan = self.native.plan_tables(tables)
        return self.native.apply_tables(
            tables, expected_manifest=plan["schema_manifest"]
        )

    def test_constructor_load_and_plan_do_not_write_or_create_tabs(self):
        self.assertEqual(self.store.writes, 0)
        self.assertEqual(set(self.native.load_tables()), set(SCHEMAS))
        plan = self.native.plan_tables({"Meta_Ads_Diario": [row()]})
        self.assertEqual(plan["tables"]["Meta_Ads_Diario"]["inserted"], 1)
        self.assertEqual(self.store.writes, 0)
        self.assertFalse(list(self.backup.iterdir()))

    def test_apply_creates_five_native_tabs_in_correct_files_and_repeats_no_writes(
        self,
    ):
        tables = {name: [] for name in SCHEMAS}
        tables["Meta_Ads_Diario"] = [
            row(
                investimento_original="10.00",
                impressoes=100,
                anuncio_nome='=IMPORTXML("url")',
            )
        ]
        self.assertTrue(self.apply(tables)["applied"])
        self.assertEqual(
            set(self.store._storage_books["ops"].tabs),
            {x for x in SCHEMAS if not x.startswith("BI_")},
        )
        self.assertEqual(
            set(self.store.book.tabs), {x for x in SCHEMAS if x.startswith("BI_")}
        )
        before = self.store.writes
        self.assertTrue(self.apply(tables)["applied"])
        self.assertEqual(self.store.writes, before)
        self.assertEqual(set(self.store.options), {"RAW"})
        loaded = self.native.load_tables()["Meta_Ads_Diario"][0]
        self.assertEqual(loaded["anuncio_id"], AD)
        self.assertIsInstance(loaded["anuncio_id"], str)
        self.assertEqual(loaded["investimento_original"], 10)
        self.assertEqual(loaded["anuncio_nome"], '=IMPORTXML("url")')
        self.assertEqual(len(list(self.backup.glob("*.json"))), 5)

    def test_preserves_history_not_returned_and_legacy_money(self):
        self.store.put(
            "Meta_Ads_Diario", [row(key="old", investimento_original="50.25")]
        )
        legacy = self.store.put(
            "Campanhas_Meta", [{"legacy": "paid", "value": "999.99"}]
        )
        baseline = deepcopy(legacy.values)
        result = self.apply(
            {"Meta_Ads_Diario": [row(key="new", investimento_original="10.00")]}
        )
        self.assertEqual(result["tables"]["Meta_Ads_Diario"]["preserved"], 1)
        self.assertEqual(
            {x["chave"] for x in self.native.load_tables()["Meta_Ads_Diario"]},
            {"old", "new"},
        )
        self.assertEqual(legacy.values, baseline)

    def test_apply_adopts_only_empty_native_tabs_and_replay_does_not_write(self):
        title = "Meta_Ads_Diario"
        book = self.store._storage_books["ops"]
        sheet = MemoryWorksheet(title, book, [[], [""]])
        book.tabs[title] = sheet
        before_id = sheet.id
        self.assertTrue(self.apply({title: [row()]})["applied"])
        self.assertEqual(book.tabs[title].id, before_id)
        self.assertEqual(len(self.native.load_tables()[title]), 1)
        writes = self.store.writes
        self.assertTrue(self.apply({title: [row()]})["applied"])
        self.assertEqual(self.store.writes, writes)

    def test_empty_default_grid_expands_before_header_and_never_shrinks(self):
        for title in ("Meta_Ads_Diario", "BI_Meta_Resultados"):
            for columns in (26, len(SCHEMAS[title]) + 10):
                with self.subTest(title=title, columns=columns):
                    store = MemoryStore()
                    native = NativeMetaSheets(store, "FARMA", account_ids=(ACCOUNT,))
                    book = store._storage_books[
                        store._storage_layout.destination(title)
                    ]
                    sheet = MemoryWorksheet(title, book)
                    sheet.row_count, sheet.col_count = 1000, columns
                    book.tabs[title] = sheet
                    tables = {title: []}
                    plan = native.plan_tables(tables)
                    result = native.apply_tables(
                        tables, expected_manifest=plan["schema_manifest"]
                    )
                    self.assertTrue(result["applied"], result)
                    self.assertEqual(sheet.col_count, max(columns, len(SCHEMAS[title])))
                    self.assertEqual(sheet.row_count, 1000)
                    writes = store.writes
                    plan = native.plan_tables(tables)
                    self.assertTrue(
                        native.apply_tables(
                            tables, expected_manifest=plan["schema_manifest"]
                        )["applied"]
                    )
                    self.assertEqual(store.writes, writes)

    def test_formula_rendering_preserves_empty_result_formula_without_bootstrap(self):
        title = "Meta_Ads_Diario"
        book = self.store._storage_books["ops"]
        sheet = MemoryWorksheet(title, book, [['=""']])
        book.tabs[title] = sheet
        rendered = []

        def read_formula(**kwargs):
            rendered.append(kwargs.get("value_render_option"))
            return (
                deepcopy(sheet.values)
                if kwargs.get("value_render_option") == "FORMULA"
                else [[""]]
            )

        with patch.object(sheet, "get_all_values", side_effect=read_formula):
            result = self.apply({title: []})
        self.assertFalse(result["applied"])
        self.assertEqual(sheet.values, [['=""']])
        self.assertEqual(set(rendered), {"FORMULA"})
        self.assertEqual(self.store.writes, 0)

    def test_content_added_during_grid_expansion_blocks_header_without_data_loss(self):
        title = "Meta_Ads_Diario"
        book = self.store._storage_books["ops"]
        sheet = MemoryWorksheet(title, book)
        sheet.col_count = 26
        book.tabs[title] = sheet
        resize = sheet.resize

        def changed_after_resize(**kwargs):
            resize(**kwargs)
            sheet.values = [["concurrent data"]]

        with patch.object(sheet, "resize", side_effect=changed_after_resize):
            result = self.apply({title: []})
        self.assertFalse(result["applied"])
        self.assertEqual(sheet.values, [["concurrent data"]])
        self.assertEqual(sheet.col_count, len(SCHEMAS[title]))
        self.assertEqual(self.store.writes, 1, "Somente a expansão foi autorizada")

    def test_failed_initial_header_recovers_without_recreating_sheet(self):
        title = "Meta_Ads_Diario"
        book = self.store._storage_books["ops"]
        create = book.add_worksheet

        def create_then_fail_header(**kwargs):
            sheet = create(**kwargs)
            sheet.update = Mock(side_effect=RuntimeError("header write failed"))
            return sheet

        with patch.object(book, "add_worksheet", side_effect=create_then_fail_header):
            first = self.apply({title: [row()]})
        self.assertFalse(first["applied"])
        sheet = book.tabs[title]
        self.assertEqual(sheet.values, [])
        del sheet.update
        with patch.object(
            book, "add_worksheet", side_effect=AssertionError("duplicate")
        ):
            retry = self.apply({title: [row()]})
        self.assertTrue(retry["applied"], retry)
        self.assertEqual(len(self.native.load_tables()[title]), 1)

    def test_lost_create_or_header_response_retries_without_duplicate_creation(self):
        title = "Meta_Ads_Diario"
        for lost in ("create", "header"):
            with self.subTest(lost=lost):
                store = MemoryStore()
                native = NativeMetaSheets(store, "FARMA", account_ids=(ACCOUNT,))
                book = store._storage_books["ops"]
                create = book.add_worksheet
                header_calls = []

                def lost_response_create(
                    create=create, lost=lost, header_calls=header_calls, **kwargs
                ):
                    sheet = create(**kwargs)
                    if lost == "create":
                        raise RuntimeError("creation response lost")
                    update = sheet.update

                    def lost_response_header(**update_kwargs):
                        result = update(**update_kwargs)
                        if update_kwargs["values"] == [SCHEMAS[title]]:
                            header_calls.append(True)
                            raise RuntimeError("header response lost")
                        return result

                    sheet.update = lost_response_header
                    return sheet

                def retry_once(description, func):
                    try:
                        return func()
                    except RuntimeError:
                        return func()

                tables = {title: [row()]}
                plan = native.plan_tables(tables)
                with (
                    patch.object(
                        book, "add_worksheet", side_effect=lost_response_create
                    ) as added,
                    patch.object(store, "_write_with_retry", side_effect=retry_once),
                ):
                    result = native.apply_tables(
                        tables, expected_manifest=plan["schema_manifest"]
                    )
                self.assertTrue(result["applied"], result)
                self.assertEqual(added.call_count, 1)
                self.assertEqual(len(native.load_tables()[title]), 1)
                if lost == "header":
                    self.assertEqual(len(header_calls), 1)

    def test_concurrent_content_before_header_is_preserved(self):
        title = "Meta_Ads_Diario"
        book = self.store._storage_books["ops"]
        sheet = MemoryWorksheet(title, book)
        book.tabs[title] = sheet
        write = self.store._write_with_retry

        def changed_before_header(description, func):
            if description == f"cabeçalho nativo {title}":
                sheet.values = [["concurrent data"]]
            return write(description, func)

        with patch.object(
            self.store, "_write_with_retry", side_effect=changed_before_header
        ):
            result = self.apply({title: [row()]})
        self.assertFalse(result["applied"])
        self.assertEqual(sheet.values, [["concurrent data"]])
        self.assertEqual(self.store.writes, 0)

    def test_empty_tab_changed_after_review_is_never_initialized(self):
        title = "Meta_Ads_Diario"
        book = self.store._storage_books["ops"]
        sheet = MemoryWorksheet(title, book)
        book.tabs[title] = sheet
        tables = {title: [row()]}
        plan = self.native.plan_tables(tables)
        sheet.values = [["preserve this data"]]
        with self.assertRaisesRegex(NativeMetaSchemaError, "mudaram"):
            self.native.apply_tables(tables, expected_manifest=plan["schema_manifest"])
        self.assertEqual(sheet.values, [["preserve this data"]])
        self.assertEqual(self.store.writes, 0)

    def test_schema_mismatch_isolated_and_never_repaired(self):
        bad = self.store.put("Meta_Ads_Diario", headers=["wrong", "header"])
        before = deepcopy(bad.values)
        result = self.apply(
            {
                "Meta_Ads_Diario": [row()],
                "Meta_Ads_Anuncios": [row("Meta_Ads_Anuncios")],
            }
        )
        self.assertFalse(result["applied"])
        self.assertIn("Meta_Ads_Diario", result["pending_tabs"])
        self.assertEqual(bad.values, before)
        self.assertEqual(len(self.native.load_tables()["Meta_Ads_Anuncios"]), 1)

    def test_failure_in_one_table_preserves_confirmed_table_and_retry_is_idempotent(
        self,
    ):
        self.store.fail_titles.add("Meta_Ads_Anuncios")
        tables = {
            "Meta_Ads_Diario": [row()],
            "Meta_Ads_Anuncios": [row("Meta_Ads_Anuncios")],
        }
        failed = self.apply(tables)
        self.assertEqual(failed["inserted"], 1)
        self.assertIn("Meta_Ads_Anuncios", failed["pending_tabs"])
        self.store.fail_titles.clear()
        retry = self.apply(tables)
        self.assertTrue(retry["applied"])
        self.assertEqual(retry["inserted"], 1)
        self.assertEqual(len(self.native.load_tables()["Meta_Ads_Diario"]), 1)

    def test_changed_source_manifest_refuses_all_writes(self):
        tables = {"Meta_Ads_Diario": [row()]}
        plan = self.native.plan_tables(tables)
        self.store.put("Meta_Ads_Diario", [row(key="concurrent")])
        with self.assertRaisesRegex(NativeMetaSchemaError, "mudaram"):
            self.native.apply_tables(tables, expected_manifest=plan["schema_manifest"])
        self.assertEqual(self.store.writes, 0)

    def test_wrong_segment_or_account_never_writes(self):
        for value in (row(segmento="PET"), row(conta_id="999")):
            self.assertFalse(self.apply({"Meta_Ads_Diario": [value]})["applied"])
            self.assertEqual(self.store.writes, 0)
        self.store.profile = "PET"
        with self.assertRaises(NativeMetaSchemaError):
            self.native.load_tables()

    def test_pet_uses_same_contract_without_reusing_farma_profile(self):
        with patch.dict(os.environ, NEXOFLOW_PERFIL="PET"):
            self.store.profile = "PET"
            native = NativeMetaSheets(self.store, "PET", account_ids=(ACCOUNT,))
            tables = {
                "Meta_Ads_Diario": [row(segmento="PET", investimento_original="5.75")]
            }
            plan = native.plan_tables(tables)
            self.assertEqual(plan["schema_manifest"]["segment"], "PET")
            result = native.apply_tables(
                tables, expected_manifest=plan["schema_manifest"]
            )
            self.assertTrue(result["applied"])
            self.assertEqual(
                native.load_tables()["Meta_Ads_Diario"][0]["segmento"], "PET"
            )
            with self.assertRaises(NativeMetaSchemaError):
                self.native.load_tables()

    def test_numeric_id_is_rejected_instead_of_becoming_rounded_text(self):
        self.assertFalse(
            self.apply({"Meta_Ads_Diario": [row(anuncio_id=120250505038200073.0)]})[
                "applied"
            ]
        )
        self.assertEqual(self.store.writes, 0)

    def test_shared_cost_cannot_be_allocated_to_profile(self):
        self.assertFalse(
            self.apply(
                {
                    "Meta_Ads_Diario": [
                        row(
                            segmento="COMPARTILHADO",
                            classificacao="COMPARTILHADO",
                            investimento_atribuivel="10.00",
                        )
                    ]
                }
            )["applied"]
        )
        self.assertEqual(self.store.writes, 0)

    def test_legacy_tab_input_is_rejected(self):
        with self.assertRaises(NativeMetaSchemaError):
            self.native.plan_tables({"BI_Ads": []})
        self.assertEqual(self.store.writes, 0)

    def test_apply_requires_account_allowlist(self):
        native = NativeMetaSheets(self.store, "FARMA")
        with self.assertRaises(NativeMetaSchemaError):
            native.apply_tables({}, expected_manifest=native.schema_manifest())
        self.assertEqual(self.store.writes, 0)

    def test_chunk_failure_preserves_first_chunk_and_resume_does_not_duplicate(self):
        title = "Meta_Ads_Diario"
        self.store.put(title)
        sheet = self.store._storage_books["ops"].tabs[title]
        update = sheet.update

        def fail_second_chunk(**kwargs):
            if kwargs["values"][0][0] == "key-200":
                raise RuntimeError("simulated lost second chunk")
            return update(**kwargs)

        rows = [row(key=f"key-{i:03d}") for i in range(201)]
        with patch.object(sheet, "update", side_effect=fail_second_chunk):
            result = self.apply({title: rows})
        self.assertFalse(result["applied"])
        self.assertEqual(result["tables"][title]["confirmed_rows"], 200)
        self.assertEqual(len(self.native.load_tables()[title]), 200)
        self.assertTrue(self.apply({title: rows})["applied"])
        self.assertEqual(len(self.native.load_tables()[title]), 201)
        self.assertEqual(len(list(self.backup.glob("*.json"))), 3)

    def test_post_without_reread_confirmation_never_reports_success(self):
        title = "Meta_Ads_Diario"
        self.store.put(title)
        with patch.object(self.store, "native_meta_upsert_chunk", return_value=None):
            result = self.apply({title: [row()]})
        self.assertFalse(result["applied"])
        self.assertIn(title, result["pending_tabs"])

    def test_readonly_factory_never_initializes_legacy_or_creates_worksheets(self):
        client = Mock()
        client.open_by_key.side_effect = self.store._storage_books.__getitem__
        context = self.store.native_meta_context()
        self.store.put(
            "Base_Contatos", [{"contact_uuid": "synthetic"}], headers=["contact_uuid"]
        )
        self.store.put(
            "Pedidos_FarmaLider", [{"pedido_id": "42"}], headers=["pedido_id"]
        )
        self.store.put(
            "Itens_Pedidos_FarmaLider", [{"pedido_id": "42"}], headers=["pedido_id"]
        )
        with (
            patch("google_sheets.gspread.service_account", return_value=client),
            patch(
                "sheets_storage.configured_storage",
                return_value=self.store._storage_layout,
            ),
            patch.object(
                GoogleSheetsStore, "native_meta_context", return_value=context
            ),
            patch.object(
                GoogleSheetsStore,
                "_initialize_structure",
                side_effect=AssertionError("legacy write"),
            ),
        ):
            opened = GoogleSheetsStore.open_native_readonly("dash")
            inputs = opened.native_meta_inputs()
            opened.close()
        self.assertEqual(inputs["contacts"], [{"contact_uuid": "synthetic"}])
        self.assertEqual(inputs["orders"], [{"pedido_id": "42"}])
        self.assertEqual(inputs["items"], [{"pedido_id": "42"}])
        self.assertEqual(self.store.writes, 0)
