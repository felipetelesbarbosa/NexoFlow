import errno
import socket
import unittest
from unittest.mock import Mock, patch

import requests
from urllib3.exceptions import MaxRetryError, ProxyError

from network_diagnostics import classify_network_failure
from weni_client import WeniClient, WeniError


class NetworkDiagnosticTests(unittest.TestCase):
    def test_nested_proxy_codes_are_classified_without_disclosing_exception_text(self):
        for code, category in (
            (407, "PROXY_AUTENTICACAO"),
            (403, "PROXY_ACESSO_NEGADO"),
            (502, "PROXY_CONEXAO"),
        ):
            with self.subTest(code=code):
                secret = "SENSITIVE_TEST_MARKER"
                inner = ProxyError(
                    "Unable to connect to proxy",
                    OSError(f"Tunnel connection failed: {code} {secret}"),
                )
                error = requests.exceptions.ProxyError(
                    MaxRetryError(
                        None,
                        f"https://user:{secret}@test.invalid/?token={secret}",
                        inner,
                    )
                )
                result = classify_network_failure(error)
                self.assertEqual(result.category, category)
                self.assertEqual(result.status, code)
                self.assertNotIn(secret, result.summary)
                self.assertNotIn("test.invalid", result.summary)
                self.assertEqual(result.retryable, code == 502)

    def test_tls_timeout_dns_and_refused_connections_are_distinct(self):
        for error, category in (
            (
                requests.exceptions.SSLError("secret certificate verify failed"),
                "TLS_CERTIFICADO",
            ),
            (requests.exceptions.ConnectTimeout("secret"), "TIMEOUT"),
            (requests.exceptions.ReadTimeout("secret"), "TIMEOUT"),
            (requests.exceptions.ConnectionError(socket.gaierror(-2, "secret")), "DNS"),
            (
                requests.exceptions.ProxyError(
                    ConnectionRefusedError(errno.ECONNREFUSED, "secret")
                ),
                "CONEXAO_RECUSADA",
            ),
            (requests.exceptions.ProxyError("secret"), "PROXY_CONEXAO"),
            (requests.exceptions.ConnectionError("secret"), "REDE"),
        ):
            with self.subTest(category=category):
                result = classify_network_failure(error)
                self.assertEqual(result.category, category)
                self.assertNotIn("secret", result.summary)

    def test_exception_cycles_do_not_loop(self):
        error = requests.exceptions.ConnectionError("secret")
        error.__cause__ = error
        self.assertEqual(classify_network_failure(error).category, "REDE")

    def test_explicit_proxy_auth_failure_is_not_retried(self):
        client = WeniClient("synthetic-token")
        self.addCleanup(client.close)
        error = requests.exceptions.ProxyError(
            OSError("Tunnel connection failed: 407 private-password")
        )
        with (
            patch.object(client.session, "request", side_effect=error) as request,
            patch("weni_client.time.sleep") as sleep,
        ):
            with self.assertRaisesRegex(WeniError, "PROXY_AUTENTICACAO") as caught:
                client._get_json("https://test.invalid")
        self.assertEqual(request.call_count, 1)
        sleep.assert_not_called()
        self.assertNotIn("private-password", str(caught.exception))
        self.assertTrue(caught.exception.__suppress_context__)

    def test_transient_proxy_failure_retries_then_recovers(self):
        client = WeniClient("synthetic-token")
        self.addCleanup(client.close)
        response = Mock(status_code=200, content=b"{}")
        response.json.return_value = {"results": []}
        with (
            patch.object(
                client.session,
                "request",
                side_effect=[requests.exceptions.ProxyError("secret"), response],
            ) as request,
            patch("weni_client.time.sleep") as sleep,
        ):
            self.assertEqual(client._get_json("https://test.invalid"), {"results": []})
        self.assertEqual(request.call_count, 2)
        sleep.assert_called_once()

    def test_diagnostic_does_not_echo_uncontrolled_exception_text(self):
        from diagnostico import safe_failure

        for error in (
            RuntimeError("sensitive-marker"),
            ValueError("sensitive-marker"),
            requests.exceptions.ProxyError("sensitive-marker"),
        ):
            self.assertNotIn("sensitive-marker", safe_failure(error))

    def test_farmalider_400_is_reported_as_unconfirmed_authentication(self):
        import diagnostico

        with (
            patch.object(
                diagnostico.secrets, "WENI_API_TOKEN", "synthetic-token", create=True
            ),
            patch.object(
                diagnostico.secrets,
                "GOOGLE_SPREADSHEET_ID",
                "synthetic-sheet",
                create=True,
            ),
            patch.object(
                diagnostico.secrets,
                "FARMALIDER_API_TOKEN",
                "synthetic-token",
                create=True,
            ),
            patch.object(
                diagnostico.secrets, "FARMALIDER_API_ENABLED", True, create=True
            ),
            patch.object(
                diagnostico,
                "GOOGLE_CREDENTIALS_FILE",
                Mock(**{"exists.return_value": True}),
            ),
            patch.object(diagnostico, "WeniClient") as weni,
            patch.object(diagnostico, "FarmaliderClient") as farm,
            patch.object(diagnostico, "GoogleSheetsStore"),
            patch("builtins.print") as output,
        ):
            weni.return_value.test_connection.return_value = {"sample_count": 0}
            farm.return_value.test_connection.return_value = {
                "status_code": 400,
                "environment": "producao",
                "base_url": "https://test.invalid",
            }
            self.assertEqual(diagnostico.main(), 0)
        printed = "\n".join(
            str(call.args[0]) for call in output.call_args_list if call.args
        )
        self.assertIn("autenticação não confirmada", printed)
        self.assertIn("[AVISO] FarmaLíder", printed)
