"""Entrada em script: menus, identidade de perfil e resultado sem APIs."""

import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import run_noturno_console as console


class NoturnoConsoleTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ)
        environment.start()
        self.addCleanup(environment.stop)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        for name in (".venv/Scripts/python.exe", "app/run_noturno.py"):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture", encoding="utf-8")
        self.runner = Mock(return_value=SimpleNamespace(returncode=0))

    def test_selects_segment_before_child_and_preserves_full_mode(self):
        choices = iter(["errado", "2", "errado", "2"])
        with (
            patch.dict(os.environ, NEXOFLOW_PERFIL=""),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            code = console.run(
                [],
                root=self.root,
                runner=self.runner,
                lock=contextlib.nullcontext,
                input_fn=lambda _: next(choices),
            )
        self.assertEqual(code, 0)
        args, kwargs = self.runner.call_args
        self.assertEqual(args[0][-1], "--full")
        self.assertEqual(kwargs["env"]["NEXOFLOW_PERFIL"], "PET")
        self.assertEqual(kwargs["env"]["NEXOFLOW_UNATTENDED"], "1")
        self.assertTrue(kwargs["cwd"].samefile(self.root))
        self.assertFalse(kwargs["check"])

    def test_modes_profiles_and_partial_exit_are_preserved(self):
        for profile in ("FARMA", "PET"):
            for mode in ("--incremental", "--full"):
                for code in (0, 3, 7):
                    with (
                        self.subTest(profile=profile, mode=mode, code=code),
                        contextlib.redirect_stdout(io.StringIO()),
                    ):
                        self.runner.return_value.returncode = code
                        result = console.run(
                            [mode, "--perfil", profile],
                            root=self.root,
                            runner=self.runner,
                            lock=contextlib.nullcontext,
                            input_fn=Mock(
                                side_effect=AssertionError("Menu inesperado")
                            ),
                        )
                        self.assertEqual(result, code)
                        self.assertEqual(
                            self.runner.call_args.kwargs["env"]["NEXOFLOW_PERFIL"],
                            profile,
                        )

    def test_cancel_and_missing_environment_never_start_child(self):
        with (
            patch.dict(os.environ, NEXOFLOW_PERFIL="FARMA"),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertIsNone(
                console.run(
                    [], root=self.root, runner=self.runner, input_fn=lambda _: "0"
                )
            )
            (self.root / ".venv/Scripts/python.exe").unlink()
            with self.assertRaises(FileNotFoundError):
                console.run(["--full"], root=self.root, runner=self.runner)
        self.runner.assert_not_called()

    def test_lock_conflict_never_starts_child(self):
        @contextlib.contextmanager
        def busy():
            raise RuntimeError("Rotina em andamento")
            yield

        with (
            patch.dict(os.environ, NEXOFLOW_PERFIL="FARMA"),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            with self.assertRaisesRegex(RuntimeError, "em andamento"):
                console.run(["--full"], root=self.root, runner=self.runner, lock=busy)
        self.runner.assert_not_called()

    def test_main_keeps_result_visible_on_success_partial_failure_and_invalid_input(
        self,
    ):
        for outcome, expected in (
            (0, 0),
            (3, 3),
            (7, 7),
            (FileNotFoundError("Ambiente ausente"), 2),
            (SystemExit(2), 2),
        ):
            with (
                self.subTest(outcome=outcome),
                contextlib.redirect_stdout(io.StringIO()) as output,
            ):
                with (
                    patch.object(
                        console,
                        "run",
                        side_effect=outcome
                        if isinstance(outcome, BaseException)
                        else None,
                        return_value=outcome,
                    ),
                    patch.object(console, "wait_console") as wait,
                ):
                    self.assertEqual(console.main(), expected)
                wait.assert_called_once_with()
                self.assertIn(f"Código de saída: {expected}", output.getvalue())

    def test_operation_lock_is_released_before_final_console_wait(self):
        active = []

        @contextlib.contextmanager
        def lock():
            active.append(True)
            try:
                yield
            finally:
                active.clear()

        with (
            patch.dict(os.environ, NEXOFLOW_PERFIL="FARMA"),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            console.run(
                ["--incremental"], root=self.root, runner=self.runner, lock=lock
            )
        self.assertFalse(active)
