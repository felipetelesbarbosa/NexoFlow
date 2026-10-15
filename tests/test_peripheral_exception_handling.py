"""Falhas esperadas dos launchers e da detecção de rede, sem chamadas reais."""

import io
import subprocess
import unittest
from contextlib import redirect_stderr, redirect_stdout
from http.client import HTTPException
from unittest.mock import Mock, patch
from urllib.error import URLError


class PeripheralExceptionHandlingTests(unittest.TestCase):
    def test_direct_probe_returns_false_for_network_and_http_failures(self):
        import proxy_config

        for error in (
            OSError("Falha fictícia de rede"),
            URLError("Destino fictício indisponível"),
            TimeoutError("Timeout fictício"),
            HTTPException("Resposta HTTP fictícia inválida"),
        ):
            with self.subTest(error=type(error).__name__):
                opener = Mock()
                opener.open.side_effect = error
                with patch.object(
                    proxy_config.urllib.request, "build_opener", return_value=opener
                ):
                    self.assertFalse(proxy_config._direct_internet_available(0.1))

    def test_direct_probe_does_not_hide_programming_errors_as_network_failure(self):
        import proxy_config

        with patch.object(
            proxy_config.urllib.request,
            "build_opener",
            side_effect=AttributeError("Erro fictício de programação"),
        ):
            with self.assertRaises(AttributeError):
                proxy_config._direct_internet_available(0.1)

    def test_terminal_reports_missing_shell_and_invalid_proxy_configuration(self):
        import run_terminal

        for error in (
            OSError("Executável fictício indisponível"),
            RuntimeError("PowerShell não foi encontrado neste Windows."),
            ValueError("Configuração fictícia inválida"),
        ):
            with self.subTest(error=type(error).__name__):
                with (
                    patch.object(
                        run_terminal, "_prepare_environment", side_effect=error
                    ),
                    patch.object(run_terminal.subprocess, "run") as runner,
                    redirect_stderr(io.StringIO()) as output,
                ):
                    self.assertEqual(run_terminal.main(), 1)
                runner.assert_not_called()
                self.assertIn("[ERRO]", output.getvalue())

    def test_terminal_preserves_subprocess_exit_code(self):
        import run_terminal

        with (
            patch.object(run_terminal, "_prepare_environment", return_value={}),
            patch.object(run_terminal, "_powershell_executable", return_value="pwsh"),
            patch.object(
                run_terminal.subprocess,
                "run",
                return_value=subprocess.CompletedProcess(["pwsh"], 7),
            ),
        ):
            self.assertEqual(run_terminal.main(), 7)

    def test_proxy_configuration_failures_block_pip_before_subprocess(self):
        import run_pip

        for error in (
            ImportError("Dependência fictícia ausente"),
            SyntaxError("Configuração fictícia com sintaxe inválida"),
            OSError("Configuração fictícia inacessível"),
            ValueError("Configuração fictícia inválida"),
        ):
            with self.subTest(error=type(error).__name__):
                with (
                    patch.object(run_pip.sys, "argv", ["app/run_pip.py", "--version"]),
                    patch.object(run_pip, "_configure_proxy", side_effect=error),
                    patch.object(run_pip.subprocess, "run") as runner,
                    redirect_stdout(io.StringIO()) as output,
                ):
                    self.assertEqual(run_pip.main(), 1)
                runner.assert_not_called()
                self.assertIn("[ERRO]", output.getvalue())

    def test_proxy_configuration_failures_stop_diagnostic_before_api_import(self):
        import run_diagnostico

        for error in (
            ValueError("Configuração fictícia inválida"),
            OSError("Falha fictícia"),
        ):
            with self.subTest(error=type(error).__name__):
                with (
                    patch.object(run_diagnostico, "configure_proxy", side_effect=error),
                    redirect_stdout(io.StringIO()) as output,
                ):
                    self.assertEqual(run_diagnostico.run(), 1)
                self.assertIn("Configuração de proxy inválida", output.getvalue())
