"""Progresso deve medir resultados confirmados, inclusive durante API lenta."""

import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

from farmalider_client import FarmaliderUnavailableError
from google_sheets import GoogleSheetsStore
from main import build_orders
from task_progress import TaskProgress


class AnalyticsProgressTests(unittest.TestCase):
    def test_legacy_cpf_eta_rounds_up_until_completion(self):
        from main import _format_duration

        self.assertEqual(_format_duration(0.15), "1s")
        self.assertEqual(_format_duration(0), "0s")

    def setUp(self):
        self.now = 0.0
        self.logs = []
        self.progress = []
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(
            patch(
                "task_progress.logging.info",
                side_effect=lambda fmt, *args: self.logs.append(fmt % args),
            )
        )

    def factory(self, *args, **kwargs):
        progress = TaskProgress(*args, **kwargs, interval=3600, clock=lambda: self.now)
        self.progress.append(progress)
        return progress

    def test_orders_include_skipped_contacts_and_waiting_api_without_private_data(self):
        self.stack.enter_context(patch("main.TaskProgress", side_effect=self.factory))
        contacts = [
            {"uuid": "private-customer-1", "fields": {}},
            {"uuid": "private-customer-2", "fields": {}},
        ]

        def resolve(*args, **kwargs):
            self.now += 2
            self.progress[-1].report()
            return None, []

        self.stack.enter_context(
            patch("main.resolve_contact_order", side_effect=resolve)
        )
        orders, items, _ = build_orders(
            contacts,
            rows_by_uuid={},
            farm_client=Mock(),
            sync_time="2026-10-11T20:00:00-03:00",
        )
        self.assertEqual((orders, items), ([], []))
        self.assertEqual(self.progress[0].completed, 2)
        self.assertTrue(
            any(
                "50%" in line and "restante estimado=00:00:04" in line
                for line in self.logs
            )
        )
        self.assertTrue(any("aguardando API: FarmaLíder" in line for line in self.logs))
        self.assertIn("100%", self.logs[-1])
        self.assertFalse(any("private-customer" in line for line in self.logs))

    def test_orders_interrupted_by_unavailable_api_never_show_completion(self):
        self.stack.enter_context(patch("main.TaskProgress", side_effect=self.factory))
        self.stack.enter_context(
            patch(
                "main.resolve_contact_order",
                side_effect=FarmaliderUnavailableError("Indisponível"),
            )
        )
        with self.assertRaises(FarmaliderUnavailableError):
            build_orders(
                [{"uuid": "synthetic", "fields": {}}],
                rows_by_uuid={},
                farm_client=Mock(),
                sync_time="synthetic",
            )
        self.assertEqual(self.progress[0].completed, 0)
        self.assertIn("interrompido", self.logs[-1])
        self.assertFalse(any("100%" in line for line in self.logs))

    def test_sheets_only_counts_acknowledged_changes_and_history_rows(self):
        self.stack.enter_context(
            patch("google_sheets.TaskProgress", side_effect=self.factory)
        )
        self.stack.enter_context(
            patch("google_sheets.GOOGLE_SHEETS_WRITE_DELAY_SECONDS", 0)
        )
        store = GoogleSheetsStore.__new__(GoogleSheetsStore)
        store._last_write_started_at = 0
        ws = Mock(title="Base_Contatos", row_count=1000)
        ws.title = "Base_Contatos"

        def waiting(*args, **kwargs):
            self.now += 2
            self.progress[-1].report()

        ws.batch_update.side_effect = waiting
        store._append_keyed_batch = Mock(side_effect=waiting)
        result = store._upsert_records_detailed(
            ws,
            [
                {"contact_uuid": "one", "nome": "novo"},
                {"contact_uuid": "two", "nome": "igual"},
                {"contact_uuid": "three", "nome": "inserido"},
            ],
            "contact_uuid",
            existing_values=[
                ["contact_uuid", "nome"],
                ["one", "antigo"],
                ["two", "igual"],
            ],
        )
        self.assertEqual((result.updated, result.inserted, result.unchanged), (1, 1, 1))
        self.assertEqual(self.progress[0].completed, 2)
        self.assertTrue(
            any(
                "0/2 linhas" in line and "aguardando API:" in line for line in self.logs
            )
        )
        self.assertTrue(
            any("1/2 linhas" in line and "50%" in line for line in self.logs)
        )
        self.assertTrue(
            any("100%" in line and "2/2 linhas" in line for line in self.logs)
        )
        store.history = Mock(row_count=1000)
        store.history.col_values.return_value = ["acao"]
        store._append_history_batch = Mock(side_effect=waiting)
        store.append_history(result.changed_records, {"one", "two"})
        self.assertEqual(self.progress[-1].completed, 2)

    def test_table_cleanup_failure_remains_incomplete_after_confirmed_writes(self):
        self.stack.enter_context(
            patch("google_sheets.TaskProgress", side_effect=self.factory)
        )
        self.stack.enter_context(
            patch("google_sheets.GOOGLE_SHEETS_WRITE_DELAY_SECONDS", 0)
        )
        store = GoogleSheetsStore.__new__(GoogleSheetsStore)
        store._last_write_started_at = 0
        ws = Mock(title="BI_Vendas", row_count=10, col_count=1)
        ws.title = "BI_Vendas"
        ws.get_all_values.return_value = [["a"], ["old"], ["obsolete"]]
        ws.batch_clear.side_effect = ValueError("Limpeza não confirmada")
        with self.assertRaises(ValueError):
            store._replace_table(ws, ["a"], [["new"]])
        write_logs = [line for line in self.logs if "gravação confirmada" in line]
        self.assertIn("2/2 linhas", write_logs[-1])
        self.assertIn("interrompido", write_logs[-1])
        self.assertFalse(any("100%" in line for line in write_logs))
