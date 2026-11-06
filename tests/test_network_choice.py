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

    def test_ambiguity_repeats_invalid_answers_until_explicit_choice(self):
        for answer, expected in (("1", "personal"), ("2", "corporate"), ("0", None)):
            with self.subTest(answer=answer):
                module = self.load_module(PROXY_ALLOW_DIRECT_FALLBACK=False)
                with (
                    patch.dict(module.os.environ, {"NEXOFLOW_NETWORK_MODE": "auto"}),
                    patch.object(
                        module, "_is_reachable", side_effect=[False, False, False, True]
                    ) as tcp,
                    patch.object(module, "_direct_internet_available") as direct,
                    patch.object(module.sys.stdin, "isatty", return_value=True),
                    patch(
                        "builtins.input", side_effect=["3", "", "texto", "12", answer]
                    ) as ask,
                    patch("builtins.print") as output,
                    patch.object(module.time, "sleep"),
                ):
                    if expected is None:
                        with self.assertRaisesRegex(ValueError, "cancelada"):
                            module.configure_proxy()
                        self.assertEqual(
                            module.os.environ["NEXOFLOW_NETWORK_MODE"], "auto"
                        )
                    else:
                        self.assertEqual(
                            module.configure_proxy().active, expected == "corporate"
                        )
                        self.assertEqual(
                            module.os.environ["NEXOFLOW_NETWORK_MODE"], expected
                        )
                    self.assertEqual(ask.call_count, 5)
                    self.assertEqual(output.call_count, 4)
                    for warning in output.call_args_list:
                        self.assertIn("Opção inválida", warning.args[0])
                    self.assertEqual(
                        tcp.call_count, 4 if expected == "corporate" else 3
                    )
                    direct.assert_not_called()

    def test_eof_ends_ambiguity_without_authorizing_a_route(self):
        module = self.load_module(PROXY_ALLOW_DIRECT_FALLBACK=False)
        with (
            patch.object(module, "_is_reachable", return_value=False) as tcp,
            patch.object(module, "_direct_internet_available") as direct,
            patch.object(module.sys.stdin, "isatty", return_value=True),
            patch("builtins.input", side_effect=["", EOFError]) as ask,
            patch("builtins.print") as output,
            patch.object(module.time, "sleep"),
        ):
            with self.assertRaisesRegex(ValueError, "Entrada de rede encerrada"):
                module.configure_proxy()
            self.assertEqual(module.os.environ["NEXOFLOW_NETWORK_MODE"], "auto")
            self.assertEqual(ask.call_count, 2)
            self.assertEqual(output.call_count, 1)
            self.assertEqual(tcp.call_count, 3)
            direct.assert_not_called()

    def test_headless_ambiguity_and_corporate_failure_do_not_read_input(self):
        for mode, category in (
            ("auto", "REDE_AMBIGUA"),
            ("corporate", "PROXY_INDISPONIVEL"),
        ):
            with self.subTest(mode=mode):
                module = self.load_module(PROXY_ALLOW_DIRECT_FALLBACK=False)
                with (
                    patch.dict(module.os.environ, {"NEXOFLOW_NETWORK_MODE": mode}),
                    patch.object(module, "_is_reachable", return_value=False) as tcp,
                    patch.object(module, "_direct_internet_available") as direct,
                    patch.object(module.sys.stdin, "isatty", return_value=False),
                    patch("builtins.input") as ask,
                    patch.object(module.time, "sleep"),
                ):
                    with self.assertRaisesRegex(ValueError, category):
                        module.configure_proxy()
                    self.assertEqual(tcp.call_count, 3)
                    ask.assert_not_called()
                    direct.assert_not_called()


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
