"""Escolha explícita, ambiguidade e transporte sem acesso a redes reais."""

import ssl
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

import pip_network
from tests import test_proxy_config as proxy_tests


class NetworkChoiceTests(unittest.TestCase):
    setUp = proxy_tests.ProxyConfigTests.setUp
    tearDown = proxy_tests.ProxyConfigTests.tearDown
    _restore_modules = proxy_tests.ProxyConfigTests._restore_modules
    load_module = proxy_tests.ProxyConfigTests.load_module

    def test_personal_choice_keeps_private_settings_and_skips_proxy_probe(self):
        module = self.load_module(PROXY_ALLOW_DIRECT_FALLBACK=False)
        with (
            patch.dict(module.os.environ, {"NEXOFLOW_NETWORK_MODE": "personal"}),
            patch.object(module, "_is_reachable") as tcp,
        ):
            result = module.configure_proxy()
            self.assertFalse(result.active)
            tcp.assert_not_called()
            self.assertEqual(module.secrets.PROXY_HOST, "proxy.test.invalid")

    def test_corporate_choice_unavailable_is_fast_without_direct_probe(self):
        module = self.load_module()
        with (
            patch.dict(module.os.environ, {"NEXOFLOW_NETWORK_MODE": "corporate"}),
            patch.object(module, "_is_reachable", return_value=False),
            patch.object(module, "_direct_internet_available") as direct,
            patch.object(module.time, "sleep"),
        ):
            with self.assertRaisesRegex(ValueError, "PROXY_INDISPONIVEL"):
                module.configure_proxy(detection_attempts=1)
            direct.assert_not_called()

    def test_interactive_ambiguity_requires_choice_and_remembers_session(self):
        module = self.load_module(PROXY_ALLOW_DIRECT_FALLBACK=False)
        with (
            patch.object(module, "_is_reachable", return_value=False),
            patch.object(module.sys.stdin, "isatty", return_value=True),
            patch("builtins.input", return_value="1"),
            patch.object(module.time, "sleep"),
        ):
            self.assertFalse(module.configure_proxy().active)
            self.assertEqual(module.os.environ["NEXOFLOW_NETWORK_MODE"], "personal")


class PipPreflightTests(unittest.TestCase):
    def test_direct_and_proxy_use_explicit_handler_tls_and_timeout(self):
        for proxy in ("", "http://synthetic:secret@proxy.invalid:8020"):
            opener = MagicMock()
            with patch(
                "pip_network.urllib.request.build_opener", return_value=opener
            ) as build:
                pip_network.preflight({"PIP_PROXY": proxy})
                self.assertEqual(
                    build.call_args.args[1].proxies, {"https": proxy} if proxy else {}
                )
                self.assertEqual(opener.open.call_args.kwargs["timeout"], 10)
                self.assertEqual(
                    build.call_args.args[2]._context.verify_mode, ssl.CERT_REQUIRED
                )

    def test_connect_tls_and_timeout_fail_before_packages_without_secrets(self):
        for failure, category in (
            (
                urllib.error.URLError(OSError("Tunnel connection failed: 407 SECRET")),
                "CONNECT_407",
            ),
            (
                urllib.error.URLError(OSError("Tunnel connection failed: 503 SECRET")),
                "CONNECT_503",
            ),
            (
                urllib.error.URLError(ssl.SSLError("certificate verify failed SECRET")),
                "TLS_CERTIFICADO",
            ),
            (TimeoutError("SECRET"), "REDE_PIP_INDISPONIVEL"),
        ):
            with patch("pip_network.urllib.request.build_opener") as build:
                build.return_value.open.side_effect = failure
                with self.assertRaisesRegex(ValueError, category) as caught:
                    pip_network.preflight({})
                self.assertNotIn("SECRET", str(caught.exception))
                self.assertEqual(build.return_value.open.call_count, 1)


class PipPolicyTests(unittest.TestCase):
    def test_bootstrap_never_upgrades_pip_automatically(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        text = (root / "instalar.bat").read_text(encoding="utf-8")
        self.assertNotIn("install --upgrade pip", text)
        self.assertIn("setuptools>=77", text)
