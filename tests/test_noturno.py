"""Sequência noturna com processos sintéticos; sem APIs ou confirmação gráfica."""

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import run_noturno as nightly
from recompra_lock import execution_file_lock


class NoturnoTests(unittest.TestCase):
    def run_flow(self, root, codes=None, *, full=False):
        calls = []
        codes = codes or {}

        def runner(arguments, **kwargs):
            calls.append(arguments)
            return codes.get(len(calls), 0)

        with contextlib.redirect_stdout(io.StringIO()):
            code = nightly.execute(root, runner=runner, full=full)
        report = next((root / "logs/noturno").glob("*/resultado.json"))
        return code, calls, json.loads(report.read_text(encoding="utf-8"))

    def test_sequence_uses_its_own_reviews_and_never_forces_full_load(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            code, calls, result = self.run_flow(root)
            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "concluido")
            self.assertEqual(len(calls), 11)
            self.assertEqual(calls[5], ["app/run_main.py"])
            self.assertEqual(calls[-1], ["app/run_main.py"])
            self.assertIn("--require-complete", calls[7])
            for dry_index, apply_index in ((3, 4), (7, 9)):
                dry, apply = calls[dry_index], calls[apply_index]
                review = dry[dry.index("--review-out") + 1]
                self.assertEqual(review, apply[apply.index("--require-review") + 1])
                self.assertTrue(Path(review).is_relative_to(root / "logs/noturno"))
            self.assertFalse(any("--full" in args for args in calls))

    def test_full_mode_uses_complete_weni_and_analytics_but_final_sync_is_incremental(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            recorded = []

            def runner(arguments, **kwargs):
                recorded.append((arguments, kwargs["full_sync"]))
                return 0

            with contextlib.redirect_stdout(io.StringIO()):
                code = nightly.execute(root, full=True, runner=runner)
            self.assertEqual(code, 0)
            self.assertIn("--full", recorded[3][0])
            self.assertIn("--full", recorded[4][0])
            self.assertIn("--full", recorded[7][0])
            self.assertEqual(
                [index for index, (_, full_sync) in enumerate(recorded) if full_sync],
                [5],
            )
            self.assertEqual(recorded[-1], (["app/run_main.py"], False))

    def test_complete_sync_sets_flag_and_clears_inherited_quarter(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            script = root / "synthetic.py"
            script.write_text(
                "import os\nassert os.environ['FORCE_FULL_SYNC'] == '1'\nassert 'FULL_SYNC_QUARTER' not in os.environ\n",
                encoding="utf-8",
            )
            with (
                patch.dict(os.environ, FULL_SYNC_QUARTER="4"),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                code = nightly.run_step(
                    [str(script)], root=root, log=root / "execucao.log", full_sync=True
                )
            self.assertEqual(code, 0)

    def test_failure_or_partial_stops_every_following_stage(self):
        for stage in range(1, 12):
            for failure in (1, 3):
                with (
                    self.subTest(stage=stage, failure=failure),
                    tempfile.TemporaryDirectory() as temp,
                ):
                    code, calls, result = self.run_flow(Path(temp), {stage: failure})
                    self.assertEqual(code, failure)
                    self.assertEqual(len(calls), stage)
                    self.assertEqual(result["codigo"], failure)
                    self.assertEqual(
                        result["status"], "parcial" if failure == 3 else "interrompido"
                    )

    def test_expired_review_is_regenerated_once_with_a_different_path(self):
        for expiry in (8, 9, 10):
            with self.subTest(expiry=expiry), tempfile.TemporaryDirectory() as temp:
                code, calls, _ = self.run_flow(Path(temp), {expiry: 4})
                self.assertEqual(code, 0)
                dry_runs = [
                    args
                    for args in calls
                    if args[:2] == ["app/run_recompra.py", "--dry-run"]
                ]
                self.assertEqual(len(dry_runs), 2)
                self.assertNotEqual(dry_runs[0][-1], dry_runs[1][-1])

    def test_repeated_expiry_stops_without_an_infinite_loop(self):
        with tempfile.TemporaryDirectory() as temp:
            code, calls, _ = self.run_flow(Path(temp), {8: 4, 9: 4})
            self.assertEqual(code, 4)
            self.assertEqual(len(calls), 9)
            self.assertFalse(
                any(
                    "--apply" in args and args[0].endswith("run_recompra.py")
                    for args in calls
                )
            )

    def test_runs_preserve_separate_reports(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.run_flow(root)
            self.run_flow(root)
            self.assertEqual(
                len(list((root / "logs/noturno").glob("*/resultado.json"))), 2
            )

    def test_second_execution_cannot_run_while_locked(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with execution_file_lock(
                root / "logs/noturno.lock",
                protocol="nexoflow-noturno-v1",
                operation="Teste",
            ):
                code, calls, result = self.run_flow(root)
            self.assertEqual(code, 1)
            self.assertEqual(calls, [])
            self.assertEqual(result["status"], "interrompido")

    def test_process_has_no_input_and_does_not_inherit_full_load_flags(self):
        with tempfile.TemporaryDirectory(prefix="noturno teste ") as temp:
            root = Path(temp)
            script = root / "sintetico.py"
            script.write_text(
                "import os,sys\n"
                "assert sys.stdin.read() == ''\n"
                "assert 'FORCE_FULL_SYNC' not in os.environ\n"
                "assert 'FULL_SYNC_QUARTER' not in os.environ\n"
                "print('Execução sintética concluída')\n"
                "raise SystemExit(3)\n",
                encoding="utf-8",
            )
            log = root / "execucao.log"
            with (
                patch.dict(os.environ, FORCE_FULL_SYNC="1", FULL_SYNC_QUARTER="2"),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                code = nightly.run_step([str(script)], root=root, log=log)
            self.assertEqual(code, 3)
            self.assertIn(
                "Execução sintética concluída", log.read_text(encoding="utf-8")
            )

    def test_runner_error_is_reported_without_retrying_application(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with (
                patch.object(nightly, "run_step", side_effect=OSError),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                code = nightly.execute(root, runner=nightly.run_step)
            self.assertEqual(code, 1)
            report = next((root / "logs/noturno").glob("*/resultado.json"))
            self.assertEqual(
                json.loads(report.read_text(encoding="utf-8"))["status"], "interrompido"
            )


if __name__ == "__main__":
    unittest.main()
