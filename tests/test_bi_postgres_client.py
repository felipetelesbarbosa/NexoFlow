"""Contrato e integração Analytics/Windows sem serviços comerciais."""

import copy
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from analytics import _item_key
from bi_postgres_client import batches, open_publisher, sales_scope
from bi_postgres_contract import PublicationError, normalize_rows
from looker_bi import SCHEMAS, build_looker_tables, opaque_key
from tests import test_analytics_result_summary as harness
from tests.test_looker_bi import item, order


class BiPostgresClientTests(unittest.TestCase):
    def built(self, orders, items):
        return build_looker_tables(
            [],
            orders,
            items,
            snapshot_date="2026-11-12",
            updated_at="2026-11-12T10:00:00-03:00",
        )

    def test_same_official_builder_rows_keys_and_corrected_positions(self):
        old_items = [item(1, "0001", position=1), item(1, "0002", position=2)]
        # O parser oficial cria identidade pela posição, não SKU nem ID do produto.
        for n, r in enumerate(old_items, 1):
            r["item_chave"] = _item_key(r["pedido_chave"], n)
        initial = self.built([order(1)], old_items)["BI_Itens"]
        changed = copy.deepcopy(old_items[0])
        changed["produto_codigo"] = "0009"
        corrected = self.built([order(1)], [changed])["BI_Itens"]
        self.assertEqual(initial[0][0], corrected[0][0])
        self.assertNotEqual(initial[0][4], corrected[0][4])
        self.assertEqual(initial[1][0], opaque_key("item", old_items[1]["item_chave"]))
        self.assertEqual(len(normalize_rows(corrected)), 1)
        self.assertEqual(normalize_rows(corrected)[0]["produto_codigo"], "0009")
        cancelled = self.built([order(1, status="3")], old_items)["BI_Itens"]
        self.assertEqual(cancelled, [])
        self.assertEqual(sales_scope([order(1)], initial), [initial[0][1]])
        cancel = order(1, status="3")
        cancel["status_confirmacao"] = "CANCELADO_API"
        self.assertEqual(sales_scope([cancel]), [initial[0][1]])

    def test_sale_omitted_by_builder_does_not_authorize_removal(self):
        future = order(1)
        future["data_hora"] = "2099-01-01T10:00:00-03:00"
        rows = self.built([future], [item(1)])["BI_Itens"]
        self.assertEqual(rows, [])
        self.assertEqual(sales_scope([future]), [])
        self.assertEqual(sales_scope([future], rows), [])

    def test_batches_keep_whole_sale_and_partial_does_not_authorize_removal(self):
        rows = self.built(
            [order(1), order(2)], [item(1, position=1), item(1, position=2), item(2)]
        )["BI_Itens"]
        from uuid import uuid4

        parts = batches(
            rows,
            sales_scope([order(1), order(2)], rows),
            str(uuid4()),
            False,
            target_rows=1,
        )
        self.assertEqual(sorted(len(p["rows"]) for p in parts), [1, 2])
        self.assertTrue(all(p["complete"] is False for p in parts))
        self.assertEqual(len({k for p in parts for k in p["sales"]}), 2)
        empty = batches([], [], str(uuid4()), False)
        self.assertEqual(len(empty), 1)  # Mesmo vazio exige recibo do servidor.
        self.assertEqual(empty[0]["rows"], [])

    def test_local_outbox_lock_blocks_analytics_and_terminal_competition(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from bi_postgres_client import Publisher

        credentials = dict(
            endpoint="https://publicador.example.test",
            publish_token="sintetico-" * 8,
            access_client_id="sintetico",
            access_client_secret="sintetico",
        )
        with TemporaryDirectory() as folder:
            path = Path(folder) / "outbox.json"
            first = Publisher(credentials, path, transport=Mock())
            second = Publisher(credentials, path, transport=Mock())
            other_profile = Publisher(
                credentials, Path(folder) / "PET/outbox.json", transport=Mock()
            )
            try:
                first._lock()
                with self.assertRaisesRegex(PublicationError, "BI_PG_OUTBOX_EM_USO"):
                    second._lock()
                second.http.request.assert_not_called()
                other_profile._lock()  # Caminho independente não compete com FARMA.
                first.close()
                second._lock()
                self.assertTrue(path.with_suffix(".lock").exists())
            finally:
                first.close()
                second.close()
                other_profile.close()

    def test_destination_opt_in_and_pet_isolation(self):
        self.assertIsNone(open_publisher(SimpleNamespace()))
        for destination in ("postgres", "outro"):
            with patch.dict(os.environ, {"NEXOFLOW_PERFIL": "PET"}):
                with self.assertRaises(PublicationError):
                    open_publisher(SimpleNamespace(BI_ITENS_DESTINO=destination))

    def run_pg(self, *, simulate=False, fail=False, errors=0):
        pg = Mock()
        pg.publish.return_value = {"simulated": simulate, "receipts": []}
        if fail:
            pg.publish.side_effect = PublicationError("BI_PG_RESPOSTA_INCERTA")
        from bi_postgres_client import publish_other_looker_tables
        from google_sheets import GoogleSheetsStore

        def routed(store, tables):
            store._typed_bi_rows.side_effect = GoogleSheetsStore._typed_bi_rows
            return publish_other_looker_tables(store, tables)

        with (
            patch("main.open_publisher", return_value=pg),
            patch("main.publish_other_looker_tables", side_effect=routed),
        ):
            result = harness.AnalyticsResultSummaryTests().run_pipeline(
                client_errors=errors
            )
        return pg, result

    def test_actual_pipeline_routes_only_bi_itens_and_preserves_other_tables(self):
        pg, (code, _, controls, sheets) = self.run_pg()
        self.assertEqual(code, 0)
        pg.start.assert_called_once()
        pg.publish.assert_called_once()
        self.assertEqual(pg.publish.call_args.args[0], [])
        self.assertTrue(pg.publish.call_args.kwargs["complete"])
        sheets.replace_looker_tables.assert_not_called()
        self.assertEqual(sheets._replace_table.call_count, len(SCHEMAS) - 1)
        sheets.replace_bi_sales.assert_called_once()
        sheets.replace_bi_ads.assert_called_once()
        self.assertEqual(controls["ultima_execucao_status"], "sucesso")
        pg.close.assert_called_once()

    def test_actual_pipeline_simulation_or_failure_preserves_success_cursor(self):
        for simulate, fail in ((True, False), (False, True)):
            pg, (code, output, controls, sheets) = self.run_pg(
                simulate=simulate, fail=fail
            )
            self.assertEqual(code, 3)
            self.assertEqual(
                controls["ultima_sincronizacao_sucesso_utc"],
                "2026-10-01T12:00:00+00:00",
            )
            self.assertNotIn("Traceback", output)
            if fail:
                sheets.replace_bi_sales.assert_not_called()
            pg.close.assert_called_once()

    def test_actual_pipeline_errors_force_partial_order_scope(self):
        pg, (code, _, _, _) = self.run_pg(errors=1)
        self.assertEqual(code, 3)
        self.assertFalse(pg.publish.call_args.kwargs["complete"])

    def test_real_terminal_command_status_does_not_collect_or_open_sheets(self):
        import nexo_cli

        with (
            patch("proxy_config.configure_proxy"),
            patch(
                "project_paths.load_private_settings", return_value=SimpleNamespace()
            ),
            patch("builtins.print") as output,
        ):
            self.assertEqual(nexo_cli.run(["bi-itens-postgres", "status"]), 0)
        self.assertIn("desabilitado", str(output.call_args))


if __name__ == "__main__":
    unittest.main()
