"""O preflight operacional não executa testes de instaladores opcionais."""

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import run_checkup_tests
import run_noturno


class OperationalCheckupTests(unittest.TestCase):
    def test_noturno_checks_real_preflight_in_both_profiles_and_load_modes(self):
        root = Path(run_checkup_tests.__file__).resolve().parents[1]
        for profile in ("FARMA", "PET"):
            for full in (False, True):
                with (
                    self.subTest(profile=profile, full=full),
                    tempfile.TemporaryDirectory() as directory,
                    patch.dict(os.environ, {"NEXOFLOW_PERFIL": profile}),
                    redirect_stdout(io.StringIO()),
                    patch(
                        "run_checkup_tests.development_tests",
                        side_effect=AssertionError("testes opcionais"),
                    ),
                ):
                    calls = []

                    def runner(arguments, *, recorded=calls, **kwargs):
                        recorded.append(arguments)
                        if arguments == ["app/run_checkup_tests.py"]:
                            return run_checkup_tests.operational_checkup(root)
                        return 0  # Demais APIs/aplicações são simuladas.

                    work = Path(directory)
                    self.assertEqual(
                        run_noturno.execute(work, full=full, runner=runner), 0
                    )
                    self.assertEqual(len(calls), 11)
                    report = json.loads(
                        next(work.rglob("resultado.json")).read_text(encoding="utf-8")
                    )
                    self.assertTrue(report["fluxo_completo"])
                    self.assertEqual(os.environ["NEXOFLOW_PERFIL"], profile)

    def test_default_checkup_does_not_load_unsigned_optional_scripts_or_change_profile(
        self,
    ):
        output = io.StringIO()
        with (
            patch.dict(os.environ, {"NEXOFLOW_PERFIL": "PET"}),
            patch(
                "run_checkup_tests.unittest.defaultTestLoader.discover",
                side_effect=RuntimeError("PSSecurityException: script não assinado"),
            ) as discover,
            redirect_stdout(output),
        ):
            self.assertEqual(run_checkup_tests.main(), 0)
            self.assertEqual(os.environ["NEXOFLOW_PERFIL"], "PET")
        discover.assert_not_called()
        self.assertIn("PET", output.getvalue())

    def test_missing_runtime_dependency_fails_without_exposing_exception_secrets(self):
        output = io.StringIO()
        with (
            patch(
                "run_checkup_tests.importlib.import_module",
                side_effect=ImportError("https://user:secret@example.invalid"),
            ),
            redirect_stdout(output),
        ):
            self.assertEqual(run_checkup_tests.main([]), 1)
        self.assertIn("dependência", output.getvalue())
        self.assertNotIn("secret", output.getvalue())

    def test_invalid_segment_is_a_blocking_error(self):
        with (
            patch.dict(os.environ, {"NEXOFLOW_PERFIL": "INEXISTENTE"}),
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(run_checkup_tests.main([]), 1)

    def test_damaged_core_source_is_blocking_and_never_prints_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app").mkdir()
            (root / "app/runtime_profile.py").write_text(
                'password = "SECRET_MARKER"\ninvalid syntax!\n', encoding="utf-8"
            )
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(run_checkup_tests.operational_checkup(root), 1)
            self.assertIn("sintaxe", output.getvalue())
            self.assertNotIn("SECRET_MARKER", output.getvalue())

    def test_missing_required_core_file_is_blocking(self):
        with tempfile.TemporaryDirectory() as directory:
            with redirect_stdout(io.StringIO()):
                self.assertEqual(
                    run_checkup_tests.operational_checkup(Path(directory)), 1
                )

    def test_compilation_checks_control_flow_without_executing_or_writing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in run_checkup_tests.REQUIRED_FILES:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    "raise RuntimeError('não executar')\n", encoding="utf-8"
                )
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(run_checkup_tests.operational_checkup(root), 0)
                (root / "app/main.py").write_text("return 5\n", encoding="utf-8")
                self.assertEqual(run_checkup_tests.operational_checkup(root), 1)
            self.assertIn("sintaxe", output.getvalue())
            self.assertEqual(list(root.rglob("*.pyc")), [])

    def test_checkup_does_not_execute_private_config_or_touch_state(self):
        root = Path(run_checkup_tests.__file__).resolve().parents[1]
        with (
            patch("socket.socket.connect", side_effect=AssertionError("rede")),
            patch("subprocess.Popen", side_effect=AssertionError("subprocesso")),
            patch(
                "project_paths.load_private_settings",
                side_effect=AssertionError("config"),
            ),
            patch("pathlib.Path.write_text", side_effect=AssertionError("estado")),
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(run_checkup_tests.operational_checkup(root), 0)
