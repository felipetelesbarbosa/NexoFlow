"""Rede da instalação MCP: somente dados sintéticos e processos simulados."""

import contextlib
import importlib
import io
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import run_mcp_pip as mcp


class McpPipTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        root = patch.object(mcp, "ROOT", self.root)
        root.start()
        self.addCleanup(root.stop)
        route = patch.dict(os.environ, {"NEXOFLOW_NETWORK_MODE": "auto"})
        route.start()
        self.addCleanup(route.stop)
        guard = patch("pip_network.preflight")
        guard.start()
        self.addCleanup(guard.stop)

    def status(self, active=True, credentials=True):
        return types.SimpleNamespace(active=active, has_credentials=credentials)

    def test_shared_configuration_overrides_stale_pip_proxy_and_inherits_ca(self):
        for profile in ("FARMA", "PET"):
            for active in (False, True):
                with tempfile.NamedTemporaryFile() as ca:
                    env = {
                        "NEXOFLOW_PERFIL": profile,
                        "REQUESTS_CA_BUNDLE": ca.name,
                        "HTTPS_PROXY": "http://u:p%40ss@proxy.invalid:8020",
                        "PIP_PROXY": "http://stale.invalid",
                        "PIP_TRUSTED_HOST": "unsafe.invalid",
                    }

                    def configure(profile=profile, active=active):
                        self.assertEqual(os.environ["NEXOFLOW_PERFIL"], profile)
                        return self.status(active)

                    module = types.SimpleNamespace(configure_proxy=configure)
                    with (
                        patch.dict(os.environ, env),
                        patch.dict("sys.modules", {"proxy_config": module}),
                    ):
                        result = mcp.dependency_environment()
                        self.assertEqual(
                            result["PIP_PROXY"], env["HTTPS_PROXY"] if active else ""
                        )
                        self.assertEqual(result["PIP_CERT"], ca.name)
                        self.assertEqual(result["REQUESTS_CA_BUNDLE"], ca.name)
                        self.assertEqual(result["PIP_CONFIG_FILE"], os.devnull)
                        self.assertEqual(result["PIP_TRUSTED_HOST"], "")
                        self.assertEqual(os.environ["PIP_PROXY"], env["PIP_PROXY"])

    def test_real_proxy_configuration_reaches_child_with_encoded_credentials(self):
        settings = types.SimpleNamespace(
            PROXY_MODE="on",
            PROXY_HOST="proxy.invalid",
            PROXY_PORT=8020,
            PROXY_USER="synthetic",
            PROXY_PASSWORD="a@b:c/",
            PROXY_BYPASS="localhost",
        )
        output = io.StringIO()
        with (
            patch.dict(os.environ),
            patch.dict(sys.modules),
            patch("project_paths.load_private_settings", return_value=settings),
            contextlib.redirect_stdout(output),
        ):
            sys.modules.pop("proxy_config", None)
            config = importlib.import_module("proxy_config")
            with patch.object(config, "_is_reachable", return_value=True):
                runner = Mock(return_value=types.SimpleNamespace(returncode=0))
                self.assertEqual(mcp.install(Path("synthetic-python"), run=runner), 0)
            child = runner.call_args.kwargs["env"]
            self.assertEqual(
                child["PIP_PROXY"], "http://synthetic:a%40b%3Ac%2F@proxy.invalid:8020"
            )
            self.assertEqual(child["HTTPS_PROXY"], child["PIP_PROXY"])
        self.assertNotIn("a@b:c/", output.getvalue())
        self.assertNotIn("a%40b", output.getvalue())

    def execute(self, results):
        runner = Mock(side_effect=results)
        sleep = Mock()
        output = io.StringIO()
        with (
            patch.object(
                mcp, "dependency_environment", return_value={"HTTPS_PROXY": "secret"}
            ),
            contextlib.redirect_stdout(output),
        ):
            code = mcp.install(Path("synthetic-python"), run=runner, sleep=sleep)
        self.assertNotIn("SENSITIVE_MARKER", output.getvalue())
        self.assertNotIn("private.invalid", output.getvalue())
        report = self.report()
        serialized = json.dumps(report)
        self.assertNotIn("SENSITIVE_MARKER", serialized)
        self.assertNotIn("private.invalid", serialized)
        self.assertNotIn("secret", serialized)
        return code, runner, sleep, output.getvalue()

    def report(self):
        return json.loads(
            (self.root / "logs/meta_ads_mcp_dependencias.json").read_text(
                encoding="utf-8"
            )
        )

    def test_permission_failure_is_specific_and_reported_without_private_output(self):
        code, run, sleep, output = self.execute(
            [
                types.SimpleNamespace(
                    returncode=1,
                    stdout="Installing collected packages: mcp\nERROR: Could not install packages due to an OSError: [WinError 5] Access is denied: 'SENSITIVE_MARKER' https://private.invalid/secret",
                )
            ]
        )
        self.assertEqual(code, 1)
        run.assert_called_once()
        sleep.assert_not_called()
        self.assertIn("PIP_PERMISSAO", output)
        report = self.report()
        self.assertEqual(report["status"], "falha")
        self.assertEqual(report["preflight_https"], "aprovado")
        self.assertEqual(report["tentativas"][0]["codigo_saida"], 1)
        self.assertEqual(report["tentativas"][0]["categoria"], "PIP_PERMISSAO")
        self.assertEqual(
            report["tentativas"][0]["ultima_etapa_reportada"], "instalacao"
        )

    def test_unknown_failure_preserves_exit_code_without_claiming_proxy_cause(self):
        _, _, _, output = self.execute(
            [types.SimpleNamespace(returncode=1073741845, stdout="SENSITIVE_MARKER")]
        )
        report = self.report()
        self.assertEqual(report["tentativas"][0]["codigo_saida"], 1073741845)
        self.assertEqual(report["tentativas"][0]["categoria"], "PIP_INSTALACAO")
        self.assertEqual(
            report["tentativas"][0]["ultima_etapa_reportada"], "indeterminada"
        )
        self.assertNotIn("PROXY_AUTENTICACAO", output)

    def test_download_http_failure_is_not_misreported_as_no_distribution(self):
        bad = types.SimpleNamespace(
            returncode=1,
            stdout="ERROR: HTTP error 503 while getting https://private.invalid/SENSITIVE_MARKER\nNo matching distribution found",
        )
        code, run, _, output = self.execute([bad, bad, bad])
        self.assertEqual(code, 1)
        self.assertEqual(run.call_count, 3)
        self.assertIn("PIP_HTTP", output)
        self.assertEqual(self.report()["tentativas"][-1]["http"], 503)

    def test_local_failure_patterns_are_differentiated_without_raw_messages(self):
        cases = (
            (
                "ERROR: Package 'private' requires a different Python: 3.11 not in '>=3.14'",
                "PIP_PYTHON",
            ),
            (
                "ERROR: ResolutionImpossible: SENSITIVE_MARKER",
                "PIP_CONFLITO_DEPENDENCIAS",
            ),
            ("ERROR: Failed building wheel for SENSITIVE_MARKER", "PIP_COMPILACAO"),
            (
                "ERROR: [Errno 28] No space left on device SENSITIVE_MARKER",
                "PIP_ESPACO",
            ),
            ("python.exe: No module named pip SENSITIVE_MARKER", "PIP_AUSENTE"),
            (
                "ERROR: [WinError 32] The process cannot access the file SENSITIVE_MARKER",
                "PIP_ARQUIVO_EM_USO",
            ),
        )
        for message, category in cases:
            with self.subTest(category=category):
                code, run, sleep, output = self.execute(
                    [types.SimpleNamespace(returncode=1, stdout=message)]
                )
                self.assertEqual(code, 1)
                run.assert_called_once()
                sleep.assert_not_called()
                self.assertIn(category, output)

    def test_previous_failure_is_replaced_and_retry_history_is_kept(self):
        self.execute([types.SimpleNamespace(returncode=1, stdout="SENSITIVE_MARKER")])
        bad = types.SimpleNamespace(
            returncode=1, stdout="Tunnel connection failed: 503"
        )
        self.execute([bad, types.SimpleNamespace(returncode=0)])
        report = self.report()
        self.assertEqual(report["status"], "sucesso")
        self.assertEqual(len(report["tentativas"]), 2)
        self.assertEqual(report["tentativas"][0]["categoria"], "PROXY_CONEXAO")
        self.assertEqual(report["tentativas"][1]["codigo_saida"], 0)
        self.assertEqual(report["tentativas"][1]["categoria"], "OK")

    def test_report_write_failure_does_not_hide_pip_result_or_expose_path(self):
        with patch.object(
            Path, "mkdir", side_effect=PermissionError("SENSITIVE_MARKER")
        ):
            result = types.SimpleNamespace(
                returncode=1, stdout="CERTIFICATE_VERIFY_FAILED"
            )
            runner = Mock(return_value=result)
            output = io.StringIO()
            with (
                patch.object(mcp, "dependency_environment", return_value={}),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(mcp.install(Path("python"), run=runner), 1)
        self.assertIn("TLS_CERTIFICADO", output.getvalue())
        self.assertIn("DIAGNOSTICO_MCP_GRAVACAO", output.getvalue())
        self.assertNotIn("SENSITIVE_MARKER", output.getvalue())

    def test_preflight_error_keeps_safe_category_and_never_launches_pip(self):
        for prefix, category, status in (
            ("PROXY_CONNECT_407", "PROXY_AUTENTICACAO", 407),
            ("PROXY_CONNECT_503", "PROXY_CONEXAO", 503),
            ("REDE_PIP_HTTP_403", "PIP_HTTP", 403),
            ("TLS_CERTIFICADO", "TLS_CERTIFICADO", None),
            ("REDE_AMBIGUA", "REDE_AMBIGUA", None),
            ("PROXY_INDISPONIVEL", "PROXY_INDISPONIVEL", None),
            ("REDE_PIP_INDISPONIVEL", "REDE_PIP_INDISPONIVEL", None),
        ):
            with self.subTest(prefix=prefix):
                run = Mock()
                output = io.StringIO()
                with (
                    patch.object(
                        mcp,
                        "dependency_environment",
                        side_effect=ValueError(f"{prefix}: SENSITIVE_MARKER"),
                    ),
                    contextlib.redirect_stdout(output),
                ):
                    self.assertEqual(mcp.install(Path("python"), run=run), 2)
                run.assert_not_called()
                self.assertIn(category, output.getvalue())
                report = self.report()
                self.assertEqual(report["categoria_rede"], category)
                self.assertEqual(report["http_rede"], status)
                self.assertEqual(report["preflight_https"], "nao_aprovado")
                self.assertEqual(report["tentativas"], [])
                self.assertNotIn("SENSITIVE_MARKER", json.dumps(report))

    def test_permanent_connect_error_does_not_retry(self):
        for status in (400, 401, 403, 404, 407):
            with self.subTest(status=status):
                code, run, sleep, _ = self.execute(
                    [
                        types.SimpleNamespace(
                            returncode=1, stdout=f"Tunnel connection failed: {status}"
                        )
                    ]
                )
                self.assertEqual(code, 1)
                run.assert_called_once()
                sleep.assert_not_called()

    def test_package_named_timeout_does_not_hide_file_permission_error(self):
        code, run, sleep, output = self.execute(
            [
                types.SimpleNamespace(
                    returncode=1,
                    stdout="Collecting pytest-timeout\nERROR: [WinError 5] SENSITIVE_MARKER",
                )
            ]
        )
        self.assertEqual(code, 1)
        self.assertIn("PIP_PERMISSAO", output)
        run.assert_called_once()
        sleep.assert_not_called()

    def test_real_child_output_is_captured_and_only_safe_diagnostic_survives(self):
        fixture = self.root / "pip.py"
        fixture.write_text(
            "print('ERROR: HTTP error 403 while getting https://u:SENSITIVE_MARKER@private.invalid/')\nraise SystemExit(1)\n",
            encoding="utf-8",
        )
        output = io.StringIO()
        with (
            patch.object(mcp, "dependency_environment", return_value=dict(os.environ)),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(mcp.install(Path(sys.executable)), 1)
        report = self.report()
        self.assertEqual(report["tentativas"][0]["codigo_saida"], 1)
        self.assertEqual(report["tentativas"][0]["http"], 403)
        for text in (output.getvalue(), json.dumps(report)):
            self.assertNotIn("SENSITIVE_MARKER", text)
            self.assertNotIn("private.invalid", text)
        self.assertIn("PIP_HTTP", output.getvalue())

    def test_report_profile_and_route_are_explicit_without_environment_dump(self):
        for profile in ("FARMA", "PET"):
            with patch.dict(
                os.environ,
                {"NEXOFLOW_PERFIL": profile, "PRIVATE_TEST": "SENSITIVE_MARKER"},
            ):
                self.execute([types.SimpleNamespace(returncode=0)])
                report = self.report()
                self.assertEqual(report["perfil"], profile)
                self.assertEqual(report["rota"], "proxy")
                self.assertEqual(report["status"], "sucesso")

    def test_407_is_terminal_and_not_misreported_as_missing_package(self):
        result = types.SimpleNamespace(
            returncode=1,
            stdout="Tunnel connection failed: 407 Proxy Authentication Required https://u:SENSITIVE_MARKER@private.invalid No matching distribution found for mcp",
        )
        code, run, sleep, output = self.execute([result])
        self.assertEqual(code, 1)
        run.assert_called_once()
        sleep.assert_not_called()
        self.assertIn("PROXY_AUTENTICACAO", output)
        self.assertNotIn("No matching", output)
        self.assertEqual(run.call_args.kwargs["env"]["HTTPS_PROXY"], "secret")
        self.assertNotIn("secret", run.call_args.args[0])
        self.assertIn("0", run.call_args.args[0])

    def test_connect_503_retries_bounded_then_recovers(self):
        bad = types.SimpleNamespace(
            returncode=1, stdout="Tunnel connection failed: 503 SENSITIVE_MARKER"
        )
        code, run, sleep, output = self.execute(
            [bad, types.SimpleNamespace(returncode=0)]
        )
        self.assertEqual(code, 0)
        self.assertEqual(run.call_count, 2)
        sleep.assert_called_once_with(1)
        self.assertIn("HTTP=503", output)
        code, run, sleep, _ = self.execute([bad, bad, bad])
        self.assertEqual(code, 1)
        self.assertEqual(run.call_count, 3)

    def test_tls_error_does_not_retry_or_expose_output(self):
        bad = types.SimpleNamespace(
            returncode=1,
            stdout="CERTIFICATE_VERIFY_FAILED https://private.invalid/SENSITIVE_MARKER",
        )
        code, run, sleep, output = self.execute([bad])
        self.assertEqual(code, 1)
        run.assert_called_once()
        sleep.assert_not_called()
        self.assertIn("TLS_CERTIFICADO", output)

    def test_timeout_retry_and_unknown_error_fail_safely(self):
        code, run, _, _ = self.execute(
            [
                subprocess.TimeoutExpired(["private.invalid"], 600),
                types.SimpleNamespace(returncode=0),
            ]
        )
        self.assertEqual(code, 0)
        self.assertEqual(run.call_count, 2)
        code, run, sleep, output = self.execute(
            [
                types.SimpleNamespace(
                    returncode=1, stdout="SENSITIVE_MARKER No matching distribution"
                )
            ]
        )
        self.assertEqual(code, 1)
        run.assert_called_once()
        sleep.assert_not_called()
        self.assertIn("não comprova ausência", output)

    def test_missing_network_configuration_never_starts_pip(self):
        run = Mock()
        output = io.StringIO()
        with (
            patch.object(
                mcp,
                "dependency_environment",
                side_effect=ValueError("SENSITIVE_MARKER"),
            ),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(mcp.install(Path("python"), run=run), 2)
        run.assert_not_called()
        self.assertNotIn("SENSITIVE_MARKER", output.getvalue())
