"""O resumo distingue gravações e cursores independentes com fontes sintéticas."""

import logging
import os
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, patch

import main
from ds_backend import runtime


class AnalyticsResultSummaryTests(unittest.TestCase):
    def run_pipeline(
        self,
        *,
        client_errors=0,
        order_errors=0,
        meta=None,
        historical=None,
        bi_pending=False,
        postgres=False,
        stage_error=None,
    ):
        sheets, farm, weni = Mock(), Mock(), Mock()
        sheets._continuity = None
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
        if stage_error is not None:
            from ds_backend.adapter import PostgresStore
            sheets.__class__ = PostgresStore
            sheets._owns_analytics_revision = True
            sheets._finalization_started = False
            sheets.revision = "synthetic"
            sheets.client.call.return_value = {"state": "ABORTADA", "facts_preserved": True}
            sheets.abort_after_fatal_error.side_effect = lambda exc: PostgresStore.abort_after_fatal_error(sheets, exc)
            sheets.upsert_pharmacy_orders.side_effect = stage_error
        with ExitStack() as stack:
            stack.enter_context(
                patch.dict(os.environ, {"FORCE_FULL_SYNC": "", "FULL_SYNC_QUARTER": ""})
            )
            if postgres:
                stack.enter_context(patch("ds_backend.client.enabled", return_value=True))
                stack.enter_context(patch.object(runtime, "open_store", return_value=sheets))
                stack.enter_context(patch("weni_insights.enabled", return_value=False))
                stack.enter_context(patch("order_history_store.analytics_history", return_value=([], [], None)))
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
            if bi_pending:
                from bi_preflight import BIContinuationPending

                stack.enter_context(
                    patch(
                        "main.check_replacements",
                        side_effect=BIContinuationPending("BI_Itens: fonte pendente"),
                        create=True,
                    )
                )
            with self.assertLogs(level=logging.INFO) as captured:
                code = main.main()
        return code, "\n".join(captured.output), controls, sheets

    def test_etapas_e_resumo_identificam_o_destino_do_perfil(self):
        for postgres, label in ((False, "Google Sheets"), (True, "PostgreSQL da VPS")):
            with self.subTest(label=label):
                code, output, _, _ = self.run_pipeline(postgres=postgres)
                self.assertEqual(code, 0, output)
                for stage in range(1, 5):
                    self.assertIn(f"{label}: etapa {stage}/4", output)
                for table in range(1, 8):
                    self.assertIn(f"{label}: BI {table}/7", output)
                self.assertIn(f"{label} | contatos inseridos=", output)
                self.assertNotIn("Google Sheets" if postgres else "PostgreSQL da VPS", output)

    def test_analytics_envia_dias_guardados_no_backend_postgres(self):
        with (
            patch("ds_backend.client.enabled", return_value=True),
            patch("weni_insights.enabled", return_value=True),
            patch("weni_insights.publish_configured", return_value=2) as publish,
            patch("ds_backend.runtime.open_store") as open_store,
        ):
            # Interrompe o restante da rotina sintética após observar o envio.
            open_store.return_value.get_control.side_effect = RuntimeError(
                "fim do teste"
            )
            self.run_pipeline()
            publish.assert_called_once_with(
                main.secrets, open_store.return_value.client
            )

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
        self.assertIn("Meta Ads: estrutura pendente em Google Sheets", output)
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
            "Meta Ads gravado em tabelas concluídas: novas linhas=2; atualizadas=3", output
        )
        self.assertIn("linhas confirmadas em tabelas ainda pendentes=5", output)
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

    def test_etapa_2_aborta_erro_impeditivo_e_preserva_revisao_incerta(self):
        from ds_backend.contract import StorageError
        for error, expected in (("DS_OPERACAO_SHEETS_NAO_PERMITIDA", 1),
                                ("DS_RESPOSTA_NAO_CONFIRMADA_RETOMAR", 3)):
            code, output, controls, sheets = self.run_pipeline(
                postgres=True, stage_error=StorageError(error)
            )
            self.assertEqual(code, expected)
            if expected == 1:
                sheets.client.call.assert_called_once_with(
                    "/v1/analytics/abortar-incompleta", {"revision": "synthetic"})
                self.assertIn("ABORTADA", output)
            else:
                sheets.client.call.assert_not_called()
                self.assertIn("confirmação pendente", output)
            self.assertEqual(controls["ultima_sincronizacao_sucesso_utc"], "2026-10-01T12:00:00+00:00")

    def test_storage_failure_stays_critical_without_success_summary(self):
        with patch("main.build_looker_tables", side_effect=RuntimeError("synthetic")):
            code, output, controls, _ = self.run_pipeline()
        self.assertEqual(code, 1)
        self.assertEqual(controls["ultima_execucao_status"], "erro")
        self.assertNotIn("Resumo final Analytics", output)

    def test_bi_source_pending_stops_before_large_replacements_and_success_cursor(self):
        code, output, controls, sheets = self.run_pipeline(bi_pending=True)
        self.assertEqual(code, 3)
        self.assertEqual(controls["ultima_execucao_status"], "parcial")
        self.assertEqual(
            controls["ultima_sincronizacao_sucesso_utc"], "2026-10-01T12:00:00+00:00"
        )
        sheets.replace_bi_sales.assert_not_called()
        sheets.replace_bi_ads.assert_not_called()
        sheets.replace_bi_orders.assert_not_called()
        sheets.replace_looker_tables.assert_not_called()
        sheets.refresh_delivery_bi.assert_not_called()
        sheets.replace_bi_status.assert_not_called()
        self.assertIn("[PENDÊNCIA] BI_Itens", output)
        self.assertNotIn("Traceback", output)
        self.assertIn("Checkpoint de sucesso mantido", output)
        sheets.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
