import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from task_progress import TaskProgress, request_progress


class TaskProgressTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.bytes = 0
        self.logs = []
        self.logger = patch(
            "task_progress.logging.info",
            side_effect=lambda fmt, *args: self.logs.append(fmt % args),
        )
        self.logger.start()
        self.addCleanup(self.logger.stop)

    def progress(self, total, **kwargs):
        return TaskProgress(
            "Teste", total, clock=lambda: self.now, interval=3600, **kwargs
        )

    def test_actual_counts_bytes_and_eta(self):
        self.bytes = 500  # Conteúdo de uma execução anterior não entra na medição.
        with self.progress(100, byte_count=lambda: self.bytes) as progress:
            self.assertIn("  0%", self.logs[0])
            self.assertIn("restante estimado=calculando", self.logs[0])
            self.now = 2
            self.bytes += 200_000
            progress.advance(20)
            progress.report()
            self.assertIn(" 20%", self.logs[-1])
            self.assertIn("10.0 contatos/s", self.logs[-1])
            self.assertIn("100.0 KB/s", self.logs[-1])
            self.assertIn("restante estimado=00:00:08", self.logs[-1])
            self.now = 10
            progress.advance(80)
        self.assertIn("100%", self.logs[-1])
        self.assertIn("concluído", self.logs[-1])

    def test_continue_is_counted_and_failure_never_finishes(self):
        with self.assertRaises(RuntimeError):
            with self.progress(3) as progress:
                for item in progress.track(range(3)):
                    self.now += 1
                    if item == 0:
                        continue
                    if item == 2:
                        raise RuntimeError("API falhou")
        self.assertEqual(progress.completed, 2)
        self.assertIn("interrompido", self.logs[-1])
        self.assertNotIn("100%", self.logs[-1])
        self.assertFalse(progress._thread.is_alive())

    def test_no_total_does_not_invent_percent_or_eta(self):
        with self.progress(None, unit="registros") as progress:
            progress.advance(5)
            self.now = 1
            progress.report()
            self.assertIn("5.0 registros/s", self.logs[-1])
            self.assertIn("restante estimado=indisponível", self.logs[-1])
            self.assertNotIn("%", self.logs[-1])

    def test_empty_stage_starts_at_zero_and_finishes_at_100(self):
        with self.progress(0):
            pass
        self.assertIn("  0%", self.logs[0])
        self.assertIn("100%", self.logs[-1])

    def test_stalled_stage_rate_falls_to_zero(self):
        with self.progress(100) as progress:
            self.now = 2
            progress.advance(10)
            progress.report()
            self.now = 12
            progress.report()
            self.assertIn("0.0 contatos/s", self.logs[-1])
            self.assertIn("restante estimado=00:01:48", self.logs[-1])

    def test_heartbeat_reports_while_worker_waits(self):
        seen = threading.Event()
        with patch("task_progress.logging.info", side_effect=lambda *args: seen.set()):
            with TaskProgress("API lenta", 10, interval=0.01) as progress:
                seen.clear()
                self.assertTrue(seen.wait(1))
                self.assertEqual(progress.completed, 0)
        self.assertFalse(progress._thread.is_alive())

    def test_jsonl_counter_matches_utf8_file_growth(self):
        import weni_update

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "audit.jsonl"
            before = weni_update._AUDIT_BYTES_WRITTEN
            try:
                weni_update._append_audit({"nome": "João", "status": "planned"}, path)
                weni_update._append_audit(
                    {"nome": "Conceição", "status": "applied"}, path
                )
                self.assertEqual(
                    weni_update._AUDIT_BYTES_WRITTEN - before, path.stat().st_size
                )
                self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()), 2)
            finally:
                weni_update._close_audit_handles()

    def test_nested_contact_queries_keep_only_parent_bar(self):
        with self.progress(2) as parent:
            for _item in parent.track(range(2)):
                with TaskProgress("Consulta de contato", None) as child:
                    child.advance(10)
                    self.assertIsNone(child._thread)
        self.assertEqual(parent.completed, 2)
        self.assertFalse(any("Consulta de contato" in line for line in self.logs))
        with self.progress(0):
            pass
        self.assertIn("100%", self.logs[-1])

    def test_requests_show_activity_without_inflating_parent_counts(self):
        with self.progress(10) as parent:
            with request_progress("Sheets: lote"):
                self.now = 3
                parent.report()
                self.assertIn("aguardando API: Sheets: lote", self.logs[-1])
                self.assertIn("0/10", self.logs[-1])
                self.assertNotIn("100%", self.logs[-1])
            self.assertEqual(parent.activity, "")
            self.assertEqual(parent.completed, 0)

    def test_weighted_batches_count_only_acknowledged_rows(self):
        with self.assertRaises(RuntimeError):
            with self.progress(5, unit="linhas") as progress:
                for index, _batch in enumerate(
                    progress.track([[1, 2], [3, 4, 5]], weight=len)
                ):
                    self.now += 2
                    if index == 1:
                        raise RuntimeError("Escrita não confirmada")
        self.assertEqual(progress.completed, 2)
        self.assertIn("2/5 linhas", self.logs[-1])
        self.assertNotIn("100%", self.logs[-1])

    def test_cleanup_failure_never_reports_100_percent(self):
        with self.assertRaises(RuntimeError):
            with self.progress(2) as progress:
                progress.advance(2)
                progress.report()
                self.assertIn("restante estimado=finalizando", self.logs[-1])
                raise RuntimeError("Limpeza falhou")
        self.assertIn("interrompido", self.logs[-1])
        self.assertFalse(any("100%" in line for line in self.logs))

    def test_standalone_request_heartbeat_and_failure(self):
        seen = threading.Event()
        original = TaskProgress

        def capture(fmt, *args):
            line = fmt % args
            self.logs.append(line)
            if "aguardando resposta da API" in line:
                seen.set()

        with (
            patch("task_progress.logging.info", side_effect=capture),
            patch(
                "task_progress.TaskProgress",
                side_effect=lambda *args, **kwargs: original(
                    *args, **kwargs, interval=0.01
                ),
            ),
        ):
            with self.assertRaises(RuntimeError):
                with request_progress("Google Sheets: teste"):
                    self.assertTrue(seen.wait(1))
                    raise RuntimeError("API falhou")
        self.assertIn("interrompido", self.logs[-1])
        self.assertFalse(any("100%" in line for line in self.logs))

    def test_resumed_progress_uses_only_new_work_for_speed_and_eta(self):
        with self.progress(100, initial_completed=60) as progress:
            self.assertIn(" 60%", self.logs[-1])
            self.assertIn("restante estimado=calculando", self.logs[-1])
            self.now = 2
            progress.advance(10)
            progress.report()
            self.assertIn("5.0 contatos/s", self.logs[-1])
            self.assertIn("restante estimado=00:00:06", self.logs[-1])
            self.now = 8
            progress.advance(30)
        self.assertIn("100%", self.logs[-1])

    def test_invalid_resume_count_is_rejected(self):
        for count in (-1, 101):
            with self.assertRaises(ValueError):
                self.progress(100, initial_completed=count)

    def test_batch_progress_emits_only_completed_lots_and_final_partial(self):
        with self.progress(2501, batch_size=1000) as progress:
            for _item in progress.track(range(2501)):
                self.now += 0.001
        self.assertEqual(len(self.logs), 4)
        self.assertIn("0/2501", self.logs[0])
        self.assertIn("lotes=0/3", self.logs[0])
        self.assertIn("1000/2501", self.logs[1])
        self.assertIn("lotes=1/3", self.logs[1])
        self.assertIn("2000/2501", self.logs[2])
        self.assertIn("lotes=2/3", self.logs[2])
        self.assertIn("100%", self.logs[-1])
        self.assertIn("2501/2501", self.logs[-1])
        self.assertIn("lotes=3/3", self.logs[-1])

    def test_batch_heartbeat_is_throttled_and_reports_stalled_api(self):
        with TaskProgress(
            "Teste", 3000, batch_size=1000, interval=15, clock=lambda: self.now
        ) as progress:
            progress.advance(1000)
            self.now = 2
            progress.report()
            self.assertEqual(len(self.logs), 2)
            self.now = 15
            progress.set_activity("aguardando API: Weni")
            progress.report()
            self.assertEqual(len(self.logs), 3)
            self.assertIn("1000/3000", self.logs[-1])
            self.assertIn("aguardando API: Weni", self.logs[-1])
            self.assertNotIn("100%", self.logs[-1])
            self.assertIn("0.0 contatos/s", self.logs[-1])

    def test_interrupted_batch_never_reports_partial_lot_as_completed(self):
        with self.assertRaises(RuntimeError):
            with self.progress(2500, batch_size=1000) as progress:
                progress.advance(1200)
                raise RuntimeError("API falhou")
        self.assertIn("1200/2500", self.logs[-1])
        self.assertIn("lotes=1/3", self.logs[-1])
        self.assertIn("interrompido", self.logs[-1])
        self.assertFalse(any("100%" in line for line in self.logs))

    def test_unknown_total_never_invents_batch_total_or_percent(self):
        with self.progress(None, batch_size=1000) as progress:
            progress.advance(1000)
        self.assertIn("lotes concluídos=1", self.logs[-1])
        self.assertNotIn("%", self.logs[-1])
        self.assertNotIn("lotes=", self.logs[-1])

    def test_invalid_batch_size_is_rejected(self):
        for size in (0, -1, 1.5, True):
            with self.subTest(size=size), self.assertRaises(ValueError):
                self.progress(100, batch_size=size)

    def test_explicit_substage_pauses_parent_and_resumes_without_advancing_it(self):
        with self.progress(1) as parent:
            with TaskProgress("BI", 8000, show_nested=True, interval=3600) as child:
                before = len(self.logs)
                parent.report()
                self.assertEqual(len(self.logs), before)
                child.advance(4000)
                child.report()
                self.assertIn("50%", self.logs[-1])
                with request_progress("leitura BI"):
                    self.assertEqual(child.activity, "aguardando API: leitura BI")
                    self.assertEqual(parent.activity, "")
                child.advance(4000)
            self.assertEqual(parent.completed, 0)
            self.assertIn("BI", self.logs[-1])
            self.assertIn("100%", self.logs[-1])
            parent.report()
            self.assertIn("0/1", self.logs[-1])
            parent.advance()
        self.assertIn("100%", self.logs[-1])
        self.assertFalse(child._thread.is_alive())

    def test_substage_failure_and_interruption_always_restore_parent(self):
        for error in (RuntimeError("API sintética"), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__), self.progress(1) as parent:
                with self.assertRaises(type(error)):
                    with TaskProgress(
                        "BI", 2, show_nested=True, interval=3600
                    ) as child:
                        child.advance()
                        raise error
                self.assertIn("interrompido", self.logs[-1])
                self.assertNotIn("100%", self.logs[-1])
                parent.report()
                self.assertIn("0/1", self.logs[-1])
                self.assertEqual(parent._suspended, 0)
                self.assertFalse(child._thread.is_alive())

    def test_substage_initialization_failure_does_not_hide_parent(self):
        def broken_counter():
            raise OSError("contador indisponível")

        with self.progress(1) as parent:
            with self.assertRaises(OSError):
                with TaskProgress("BI", 2, show_nested=True, byte_count=broken_counter):
                    self.fail("O contador deveria falhar antes de iniciar.")
            self.assertEqual(parent._suspended, 0)
            parent.report()
            self.assertIn("0/1", self.logs[-1])

    def test_three_substage_levels_resume_only_the_immediate_parent(self):
        with self.progress(1) as root:
            with TaskProgress("Fontes", 1, show_nested=True, interval=3600) as middle:
                with TaskProgress("Linhas", 1, show_nested=True, interval=3600) as leaf:
                    before = len(self.logs)
                    root.report()
                    middle.report()
                    self.assertEqual(len(self.logs), before)
                    leaf.advance()
                middle.report()
                self.assertTrue(self.logs[-1].startswith("Fontes"))
                before = len(self.logs)
                root.report()
                self.assertEqual(len(self.logs), before)
            root.report()
            self.assertTrue(self.logs[-1].startswith("Teste"))


if __name__ == "__main__":
    unittest.main()
