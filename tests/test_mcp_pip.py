"""Rede da instalação MCP: somente dados sintéticos e processos simulados."""

import contextlib
import importlib
import io
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
        return code, runner, sleep, output.getvalue()

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
