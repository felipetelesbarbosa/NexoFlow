"""O resumo distingue gravações e cursores independentes com fontes sintéticas."""

import logging
import os
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, patch

import main


class AnalyticsResultSummaryTests(unittest.TestCase):
    def run_pipeline(
        self, *, client_errors=0, order_errors=0, meta=None, historical=None
    ):
        sheets, farm, weni = Mock(), Mock(), Mock()
        farm.metrics_snapshot.return_value = {}
        weni.list_contacts.return_value = []
        sheets.load_base_snapshot.return_value = ([], [], set())
        sheets.load_order_records.return_value = []
        sheets.load_order_item_records.return_value = []
        sheets.request_stats.return_value = {"reads": 2, "writes": 3, "total": 5}
        controls = {"ultima_sincronizacao_sucesso_utc": "2026-10-01T12:00:00+00:00"}
        sheets.get_control.side_effect = lambda key: controls.get(key, "")
        sheets.set_controls.side_effect = controls.update
        sheets.upsert_contacts_detailed.return_value = SimpleNamespace(
            inserted=4, updated=2, unchanged=7, changed_records=[], final_records=[]
        )
        sheets.upsert_pharmacy_orders.return_value = (
            SimpleNamespace(inserted=3, updated=1, final_records=[]),
            SimpleNamespace(inserted=5, updated=2, final_records=[]),
        )
        sheets.reconcile_pharmacy_scope.return_value = SimpleNamespace(
            contacts=[], orders=[], items=[]
        )
        with ExitStack() as stack:
            stack.enter_context(
                patch.dict(os.environ, {"FORCE_FULL_SYNC": "", "FULL_SYNC_QUARTER": ""})
            )
            for target, value in (
                ("configure_logging", None),
                ("validate_configuration", None),
                ("open_farmalider_client", farm),
                ("GoogleSheetsStore", sheets),
                ("WeniClient", weni),
                ("prepare_customers", None),
                ("directory_for", None),
                (
                    "validate_contacts",
                    main.ClienteValidationStats(api_errors=client_errors),
                ),
                ("build_orders", ([], [], main.OrderStats(api_errors=order_errors))),
                ("_sync_optional_native_meta", meta or {"status": "desativado"}),
            ):
                stack.enter_context(patch("main." + target, return_value=value))
            stack.enter_context(patch("customer_observations.acknowledge"))
            stack.enter_context(
                patch(
                    "analytics_history_sync.run",
                    return_value=historical
                    or {"status": "desativado", "partial": False},
                )
            )
            with self.assertLogs(level=logging.INFO) as captured:
                code = main.main()
        return code, "\n".join(captured.output), controls, sheets

    def test_meta_schema_pending_keeps_successful_primary_counts_and_cursor(self):
        code, output, controls, _ = self.run_pipeline(
            meta={
                "status": "schema_pendente",
                "partial": True,
                "applied": False,
                "counts": {"Meta_Ads_Diario": 1000},
            }
        )
        self.assertEqual(code, 3)
        self.assertEqual(controls["ultima_execucao_status"], "sucesso")
        self.assertNotEqual(
            controls["ultima_sincronizacao_sucesso_utc"], "2026-10-01T12:00:00+00:00"
        )
        self.assertIn(
            "Contatos gravados: novos=4; atualizados=2; sem mudança=7", output
        )
        self.assertIn("Pedidos gravados: novos=3; atualizados=1", output)
        self.assertIn("Itens gravados: novos=5; atualizados=2", output)
        self.assertIn("Checkpoint principal: avançado", output)
        self.assertIn("Meta Ads: estrutura da planilha pendente", output)
        self.assertIn("cursor próprio", output)
        self.assertNotIn("0 erro(s) em consulta", output)
        self.assertNotIn("marco incremental anterior foi mantido", output)
        self.assertNotIn("1000", output)

    def test_farma_pending_preserves_primary_cursor_and_confirmed_writes(self):
        code, output, controls, sheets = self.run_pipeline(
            client_errors=2, order_errors=1
        )
        self.assertEqual(code, 3)
        self.assertEqual(controls["ultima_execucao_status"], "parcial")
        self.assertEqual(
            controls["ultima_sincronizacao_sucesso_utc"], "2026-10-01T12:00:00+00:00"
        )
        self.assertTrue(sheets.replace_looker_tables.called)
        self.assertIn(
            "FarmaLíder para revalidar: consultas de clientes=2; pedidos=1", output
        )
        self.assertIn("Checkpoint principal: mantido para a próxima carga", output)
        self.assertIn("Contatos gravados: novos=4; atualizados=2", output)

    def test_meta_only_reports_confirmed_rows_and_leaves_pending_rows_for_retry(self):
        code, output, _, _ = self.run_pipeline(
            meta={
                "status": "parcial",
                "partial": True,
                "counts": {"Meta_Ads_Diario": 1000},
                "summary": {
                    "inserted": 2,
                    "updated": 3,
                    "unchanged": 4,
                    "tables": {
                        "Meta_Ads_Diario": {"pending": True, "confirmed_rows": 5}
                    },
                },
            }
        )
        self.assertEqual(code, 3)
        self.assertIn(
            "Meta Ads gravado em abas concluídas: novas linhas=2; atualizadas=3", output
        )
        self.assertIn("linhas confirmadas em abas ainda pendentes=5", output)
        self.assertNotIn("1000", output)

    def test_history_pending_preserves_checkpoint_and_other_tables(self):
        code, output, controls, sheets = self.run_pipeline(
            historical={"status": "pendente", "partial": True}
        )
        self.assertEqual(code, 3)
        self.assertEqual(controls["ultima_execucao_status"], "parcial")
        self.assertEqual(
            controls["ultima_sincronizacao_sucesso_utc"], "2026-10-01T12:00:00+00:00"
        )
        self.assertTrue(sheets.replace_looker_tables.called)
        self.assertIn("Cinco fontes históricas: publicação pendente", output)

    def test_history_confirmed_allows_primary_checkpoint(self):
        code, output, controls, sheets = self.run_pipeline(
            historical={"status": "conferida", "partial": False}
        )
        self.assertEqual(code, 0)
        self.assertEqual(controls["ultima_execucao_status"], "sucesso")
        self.assertTrue(sheets.replace_bi_orders.called)
        self.assertIn(
            "Cinco fontes históricas: publicação e conferência concluídas", output
        )

    def test_storage_failure_stays_critical_without_success_summary(self):
        with patch("main.build_looker_tables", side_effect=RuntimeError("synthetic")):
            code, output, controls, _ = self.run_pipeline()
        self.assertEqual(code, 1)
        self.assertEqual(controls["ultima_execucao_status"], "erro")
        self.assertNotIn("Resumo final Analytics", output)


if __name__ == "__main__":
    unittest.main()
