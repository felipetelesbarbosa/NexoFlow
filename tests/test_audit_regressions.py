"""Regressões da auditoria: falhas sintéticas, sem rede ou dados privados."""

import copy
import unittest
from datetime import date
from unittest.mock import Mock, patch

from requests.exceptions import Timeout

from analytics import (
    BI_ADS_COLUMNS,
    BI_SALES_COLUMNS,
    BI_STATUS_COLUMNS,
    build_bi_conversion_records,
)
from google_sheets import GoogleSheetsStore
from looker_bi import SCHEMAS, build_looker_tables
from tests.test_looker_bi import item, order, records
from weni_client import WeniClient, WeniError


def store_and_sheet(values):
    stored = copy.deepcopy(values)
    ws = Mock(title="Tabela", row_count=100, col_count=20)
    ws.get_all_values.side_effect = lambda: copy.deepcopy(stored)
    store = GoogleSheetsStore.__new__(GoogleSheetsStore)
    store._last_write_started_at = 0.0
    store._read_requests = store._write_requests = 0
    store._read_with_retry = Mock(
        side_effect=lambda description, operation: operation()
    )
    store._wait_before_write = Mock()
    return store, ws, stored


class SheetAuditTests(unittest.TestCase):
    def test_committed_append_with_timeout_is_not_duplicated(self):
        for committed_count in (0, 1, 2):
            with self.subTest(committed=committed_count):
                store, ws, stored = store_and_sheet([["id", "nome"]])
                batch = [["a", "Ágata"], ["b", "João"]]
                calls = 0

                def append(
                    rows, stored=stored, committed_count=committed_count, **kwargs
                ):
                    nonlocal calls
                    calls += 1
                    if calls == 1:
                        stored.extend(copy.deepcopy(rows[:committed_count]))
                        raise Timeout("Resposta perdida depois da inclusão")
                    stored.extend(copy.deepcopy(rows))

                def update(updates, stored=stored, **kwargs):
                    for change in updates:
                        position = int(change["range"].split(":")[0][1:])
                        stored[position - 1] = change["values"][0]

                ws.append_rows.side_effect = append
                ws.batch_update.side_effect = update
                with (
                    patch("google_sheets.time.sleep"),
                    patch("google_sheets.refresh_network_route"),
                ):
                    store._append_keyed_batch(ws, batch, ["id", "nome"], "id", "RAW")
                self.assertEqual(stored, [["id", "nome"], *batch])
                self.assertEqual(ws.append_rows.call_args.kwargs["table_range"], "A1:B")
                self.assertEqual(
                    ws.append_rows.call_count, 1 if committed_count == 2 else 2
                )

    def test_history_append_timeout_preserves_distinct_actions_without_duplicates(self):
        headers = ["acao", "sincronizado_em", "contact_uuid"]
        store, ws, stored = store_and_sheet([headers])
        store.history = ws
        batch = [["Inserido", "2026-10-11", "a"], ["Atualizado", "2026-10-11", "a"]]

        def append(rows, **kwargs):
            stored.extend(copy.deepcopy(rows))
            raise Timeout("Resposta perdida")

        ws.append_rows.side_effect = append
        with (
            patch("google_sheets.time.sleep"),
            patch("google_sheets.refresh_network_route"),
        ):
            store._append_history_batch(batch)
        self.assertEqual(stored, [headers, *batch])
        ws.append_rows.assert_called_once()
        self.assertEqual(ws.append_rows.call_args.kwargs["table_range"], "A1:BF")

    def test_schema_change_during_append_retry_blocks_further_inclusion(self):
        store, ws, stored = store_and_sheet([["outra_coluna"]])
        ws.append_rows.side_effect = Timeout("Resposta perdida")
        with (
            patch("google_sheets.time.sleep"),
            patch("google_sheets.refresh_network_route"),
        ):
            with self.assertRaisesRegex(RuntimeError, "Schema mudou"):
                store._append_keyed_batch(ws, [["a"]], ["id"], "id", "RAW")
        ws.append_rows.assert_called_once()
        self.assertEqual(stored, [["outra_coluna"]])

    def test_initial_replacement_failure_keeps_previous_table(self):
        store, ws, stored = store_and_sheet([["id"], ["anterior"]])
        store._write_with_retry = Mock(
            side_effect=lambda description, operation: operation()
        )
        ws.update.side_effect = RuntimeError("Falha antes da escrita")
        with self.assertRaises(RuntimeError):
            store._replace_table(ws, ["id"], [["nova"]])
        self.assertEqual(stored, [["id"], ["anterior"]])
        ws.clear.assert_not_called()
        ws.batch_clear.assert_not_called()

    def test_obsolete_cells_are_cleared_only_after_successful_replacement(self):
        store, ws, _ = store_and_sheet([["id", "extra"], ["a", "x"], ["b", "y"]])
        store._write_with_retry = Mock(
            side_effect=lambda description, operation: operation()
        )
        operations = []
        ws.update.side_effect = lambda **kwargs: operations.append("update")
        ws.batch_clear.side_effect = lambda ranges: operations.append("clear")
        store._replace_table(ws, ["id"], [["nova"]])
        self.assertEqual(operations, ["update", "clear"])
        self.assertEqual(ws.batch_clear.call_args.args[0], ["A3:T3", "B1:B2"])
        ws.clear.assert_not_called()

    def test_numeric_comparison_accepts_formatted_equivalents(self):
        self.assertFalse(
            GoogleSheetsStore._record_changed(["50,25"], [50.25], ["taxa"])
        )
        self.assertFalse(GoogleSheetsStore._record_changed(["50"], [50.0], ["taxa"]))
        self.assertTrue(GoogleSheetsStore._record_changed(["50"], [50.25], ["taxa"]))

    def test_channel_and_conversion_upserts_preserve_numbers(self):
        store = GoogleSheetsStore.__new__(GoogleSheetsStore)
        store.bi_channels = store.bi_conversion = Mock()
        store._upsert_records_detailed = Mock()
        for operation in (store.upsert_bi_channels, store.upsert_bi_conversion):
            operation([{"chave": "dia", "taxa": 50.25}])
            self.assertTrue(
                store._upsert_records_detailed.call_args.kwargs["preserve_types"]
            )

    def test_old_bi_tables_use_literal_text_native_numbers_and_typed_dates(self):
        store = GoogleSheetsStore.__new__(GoogleSheetsStore)
        store._replace_table = Mock()
        store._format_bi_columns = Mock()
        store.bi_sales = store.bi_ads = store.bi_status = Mock()
        for headers, operation, data in (
            (
                BI_SALES_COLUMNS,
                store.replace_bi_sales,
                {"data": "2026-10-11", "faturamento": 1170.06},
            ),
            (
                BI_ADS_COLUMNS,
                store.replace_bi_ads,
                {
                    "data_snapshot": "2026-10-11",
                    "anuncio_titulo": "=1+1",
                    "anuncio_id": "001",
                    "faturamento": 1170.06,
                },
            ),
        ):
            operation([[data.get(header, "") for header in headers]])
            written = dict(
                zip(headers, store._replace_table.call_args.args[2][0], strict=True)
            )
            self.assertEqual(
                written[headers[0]], (date(2026, 10, 11) - date(1899, 12, 30)).days
            )
            self.assertEqual(written["faturamento"], 1170.06)
            if "anuncio_id" in written:
                self.assertEqual(written["anuncio_id"], "001")
                self.assertEqual(written["anuncio_titulo"], "=1+1")
            self.assertNotIn(
                "value_input_option", store._replace_table.call_args.kwargs
            )
        store.replace_bi_status(
            ["agora", "1.0", "sucesso", "manual", *([0] * (len(BI_STATUS_COLUMNS) - 4))]
        )
        self.assertEqual(store._replace_table.call_args.args[2][0][1], "1.0")

    def test_all_looker_rows_are_validated_before_first_write(self):
        store = GoogleSheetsStore.__new__(GoogleSheetsStore)
        store._replace_table = Mock()
        tables = {title: [] for title in SCHEMAS}
        tables["BI_Qualidade"] = [["incompleta"]]
        with self.assertRaises(ValueError):
            store.replace_looker_tables(tables)
        store._replace_table.assert_not_called()

    def test_nonfinite_measure_is_rejected_before_sheets(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                GoogleSheetsStore._typed_bi_rows(["receita_item"], [[value]])

    def test_summary_migration_commits_values_and_formats_in_single_request(self):
        store, ws, _ = store_and_sheet([])
        ws.id = 42
        store.bi_summary = ws
        store.book = Mock()
        store._write_with_retry = Mock(
            side_effect=lambda description, operation: operation()
        )
        store._replace_summary_atomically(
            ["data", "faturamento_dia", "campo_extra"], [[46178, 1170.06, "preservado"]]
        )
        store.book.batch_update.assert_called_once()
        requests = store.book.batch_update.call_args.args[0]["requests"]
        update = next(r["updateCells"] for r in requests if "updateCells" in r)
        self.assertEqual(
            update["rows"][1]["values"][1],
            {"userEnteredValue": {"numberValue": 1170.06}},
        )
        formats = [r["repeatCell"] for r in requests if "repeatCell" in r]
        self.assertEqual(
            [f["cell"]["userEnteredFormat"]["numberFormat"]["type"] for f in formats],
            ["DATE", "NUMBER"],
        )
        self.assertEqual(len(formats), 2)
        ws.clear.assert_not_called()

    def test_failed_summary_migration_does_not_advance_revision(self):
        store, ws, _ = store_and_sheet(
            [["data", "faturamento_dia"], ["2026-10-11", "1170.06"]]
        )
        store.bi_summary = ws
        store._headers_cache = {}
        store.get_control = Mock(return_value="")
        store.set_controls = Mock()
        store._replace_summary_atomically = Mock(
            side_effect=RuntimeError("Falha transitória")
        )
        with self.assertRaises(RuntimeError):
            store.migrate_bi_summary_numbers()
        store.set_controls.assert_not_called()

    def test_conversion_counts_buyers_only_in_current_contact_base(self):
        base = [
            {
                "contact_uuid": "atual",
                "farmalider_cliente_status": "CPF_CONFIRMADO",
                "farmalider_cliente_id": "10",
            }
        ]
        rows = build_bi_conversion_records(
            base,
            [order(1, uuid="historico"), order(2, customer="20", uuid="excluido")],
            snapshot_date="2026-10-11",
            updated_at="agora",
        )
        self.assertEqual(rows[-1]["quantidade"], 1)
        self.assertEqual(rows[-1]["taxa_base_pct"], 100)


class ItemCoverageAuditTests(unittest.TestCase):
    def build(self, orders, items):
        return build_looker_tables(
            [],
            orders,
            items,
            snapshot_date="2026-10-11",
            updated_at="agora",
            period_start="2026-10-01",
            period_end="2026-10-11",
        )

    def test_missing_order_items_disable_abc_and_top5(self):
        tables = self.build([order(1), order(2)], [item(1)])
        self.assertEqual(records(tables, "BI_Qualidade")[0]["pedidos_sem_itens"], 1)
        self.assertEqual(records(tables, "BI_Produtos_ABC")[0]["abc_disponivel"], 0)
        self.assertEqual(records(tables, "BI_Produtos_ABC")[0]["classe_abc"], "")
        self.assertEqual(
            records(tables, "BI_KPIs_Periodo")[0]["participacao_top5_receita_pct"], ""
        )
        self.assertEqual(records(tables, "BI_KPIs_Periodo")[0]["faturamento"], 200)

    def test_divergent_item_totals_disable_abc(self):
        tables = self.build([order(1)], [item(1, revenue="50")])
        quality = records(tables, "BI_Qualidade")[0]
        self.assertEqual(quality["pedidos_com_itens_divergentes"], 1)
        self.assertEqual(quality["abc_periodo_disponivel"], 0)

    def test_missing_items_outside_period_do_not_disable_period_abc(self):
        tables = self.build([order(1, day="2026-09-01"), order(2)], [item(2)])
        quality = records(tables, "BI_Qualidade")[0]
        self.assertEqual(quality["pedidos_sem_itens"], 1)
        self.assertEqual(quality["abc_periodo_disponivel"], 1)

    def test_item_total_rounding_tolerance_is_one_cent(self):
        tables = self.build([order(1)], [item(1, revenue="99.99")])
        self.assertEqual(
            records(tables, "BI_Qualidade")[0]["abc_periodo_disponivel"], 1
        )


class PaginationAuditTests(unittest.TestCase):
    def test_unexpected_pagination_destination_is_blocked_before_second_request(self):
        for destination in (
            "https://other.example.invalid/contacts.json",
            "http://flows.weni.ai/api/v2/contacts.json",
            "/api/v2/groups.json",
            "https://user@flows.weni.ai/api/v2/contacts.json",
        ):
            with self.subTest(destination=destination):
                client = WeniClient("TOKEN_SINTETICO")
                self.addCleanup(client.close)
                with patch.object(
                    client,
                    "_get_json",
                    return_value={"results": [{"uuid": "a"}], "next": destination},
                ) as request:
                    with self.assertRaises(WeniError):
                        client.list_contacts()
                request.assert_called_once()

    def test_repeated_page_is_blocked_without_infinite_loop(self):
        from config import WENI_CONTACTS_API_URL

        client = WeniClient("TOKEN_SINTETICO")
        self.addCleanup(client.close)
        with patch.object(
            client,
            "_get_json",
            return_value={"results": [], "next": WENI_CONTACTS_API_URL},
        ) as request:
            with self.assertRaisesRegex(WeniError, "repetiu"):
                client.list_contacts()
        request.assert_called_once()

    def test_http_redirect_is_rejected_without_following_it(self):
        client = WeniClient("TOKEN_SINTETICO")
        self.addCleanup(client.close)
        with patch.object(
            client.session, "request", return_value=Mock(status_code=302)
        ) as request:
            with self.assertRaisesRegex(WeniError, "redirecionamento"):
                client._request_json("GET", "https://example.invalid")
        request.assert_called_once()
        self.assertFalse(request.call_args.kwargs["allow_redirects"])
