"""Recuperação de autenticação Google com transporte simulado, sem credenciais."""

import json
import unittest
from unittest.mock import Mock, patch

import gspread
import requests
from google.auth.credentials import Credentials
from google.auth.exceptions import RefreshError, TransportError
from google.auth.transport.requests import AuthorizedSession

from google_sheets import GoogleSheetsStore


class SyntheticCredentials(Credentials):
    def refresh(self, request):
        request("https://oauth.test.invalid/token", method="POST", body=b"synthetic")
        self.token = "synthetic-access"


def response(payload):
    result = requests.Response()
    result.status_code = 200
    result._content = json.dumps(payload).encode("utf-8")
    return result


def wrapped(error):
    result = TransportError("synthetic-auth-transport")
    result.__cause__ = error
    return result


class GoogleAuthRecoveryTests(unittest.TestCase):
    def auth_session(self):
        session = AuthorizedSession(SyntheticCredentials())
        self.addCleanup(session.close)
        return session

    def test_open_recovers_real_google_auth_wrapped_proxy_timeout(self):
        session = self.auth_session()
        client = gspread.Client(auth=session.credentials, session=session)
        unavailable = requests.exceptions.ProxyError(
            requests.exceptions.ConnectTimeout("private-proxy-marker")
        )
        metadata = response(
            {"spreadsheetId": "synthetic-sheet", "properties": {"title": "Teste"}}
        )
        with (
            patch("google_sheets.GOOGLE_CREDENTIALS_FILE") as credential_path,
            patch("google_sheets.gspread.service_account", return_value=client),
            patch.object(GoogleSheetsStore, "_initialize_structure"),
            patch.object(
                session._auth_request.session,
                "request",
                side_effect=[unavailable, response({})],
            ) as token_request,
            patch.object(session, "send", return_value=metadata) as sheets_request,
            patch("google_sheets.refresh_network_route") as refresh,
            patch("google_sheets.time.sleep") as sleep,
            patch("google_sheets.logging.warning") as warning,
        ):
            credential_path.exists.return_value = True
            store = GoogleSheetsStore("synthetic-sheet")

        self.assertEqual(store.book.title, "Teste")
        self.assertEqual(token_request.call_count, 2)
        sheets_request.assert_called_once()
        refresh.assert_called_once()
        sleep.assert_called_once_with(2)
        messages = "\n".join(
            call.args[0] % call.args[1:] for call in warning.call_args_list
        )
        self.assertNotIn("private-proxy-marker", messages)
        self.assertIn("TIMEOUT", messages)

    def test_token_failure_before_append_does_not_duplicate_the_sheet_post(self):
        session = self.auth_session()
        client = gspread.Client(auth=session.credentials, session=session)
        store = GoogleSheetsStore.__new__(GoogleSheetsStore)
        store._last_write_started_at = 0.0
        with (
            patch.object(
                session._auth_request.session,
                "request",
                side_effect=[
                    requests.exceptions.ConnectTimeout("synthetic"),
                    response({}),
                ],
            ) as token_request,
            patch.object(session, "send", return_value=response({})) as sheets_request,
            patch("google_sheets.refresh_network_route") as refresh,
            patch("google_sheets.time.sleep"),
            patch.object(store, "_wait_before_write"),
        ):
            store._write_with_retry(
                "acrescentar linhas",
                lambda: client.http_client.request(
                    "post",
                    "https://sheets.test.invalid/values:append",
                    json={"values": [["synthetic-row"]]},
                ),
            )

        self.assertEqual(token_request.call_count, 2)
        sheets_request.assert_called_once()
        request = sheets_request.call_args.args[0]
        self.assertEqual(request.method, "POST")
        self.assertEqual(json.loads(request.body), {"values": [["synthetic-row"]]})
        refresh.assert_called_once()

    def test_wrapped_tls_and_proxy_denials_stop_without_route_change(self):
        failures = (
            requests.exceptions.SSLError("certificate verify failed"),
            requests.exceptions.ProxyError(OSError("Tunnel connection failed: 407")),
            requests.exceptions.ProxyError(OSError("Tunnel connection failed: 403")),
        )
        for error in failures:
            for operation_name in ("_read_with_retry", "_write_with_retry"):
                with self.subTest(error=type(error).__name__, operation=operation_name):
                    store = GoogleSheetsStore.__new__(GoogleSheetsStore)
                    operation = Mock(side_effect=wrapped(error))
                    with (
                        patch("google_sheets.refresh_network_route") as refresh,
                        patch("google_sheets.time.sleep") as sleep,
                        patch.object(store, "_wait_before_write"),
                    ):
                        with self.assertRaises(TransportError):
                            getattr(store, operation_name)("teste", operation)
                    operation.assert_called_once()
                    refresh.assert_not_called()
                    sleep.assert_not_called()

    def test_rejected_credentials_are_not_treated_as_network_failure(self):
        for operation_name in ("_read_with_retry", "_write_with_retry"):
            with self.subTest(operation=operation_name):
                store = GoogleSheetsStore.__new__(GoogleSheetsStore)
                operation = Mock(
                    side_effect=RefreshError("invalid_grant", retryable=False)
                )
                with (
                    patch("google_sheets.refresh_network_route") as refresh,
                    patch("google_sheets.time.sleep") as sleep,
                    patch.object(store, "_wait_before_write"),
                ):
                    with self.assertRaises(RefreshError):
                        getattr(store, operation_name)("teste", operation)
                operation.assert_called_once()
                refresh.assert_not_called()
                sleep.assert_not_called()

    def test_persistent_auth_transport_failure_has_bounded_retries(self):
        for operation_name, setting in (
            ("_read_with_retry", "GOOGLE_SHEETS_READ_MAX_RETRIES"),
            ("_write_with_retry", "GOOGLE_SHEETS_WRITE_MAX_RETRIES"),
        ):
            with self.subTest(operation=operation_name):
                store = GoogleSheetsStore.__new__(GoogleSheetsStore)
                operation = Mock(
                    side_effect=wrapped(requests.exceptions.ConnectTimeout())
                )
                with (
                    patch("google_sheets." + setting, 3),
                    patch("google_sheets.refresh_network_route") as refresh,
                    patch("google_sheets.time.sleep") as sleep,
                    patch.object(store, "_wait_before_write"),
                ):
                    with self.assertRaises(TransportError):
                        getattr(store, operation_name)("teste", operation)
                self.assertEqual(operation.call_count, 3)
                self.assertEqual(refresh.call_count, 2)
                self.assertEqual(
                    [call.args[0] for call in sleep.call_args_list], [2, 4]
                )


if __name__ == "__main__":
    unittest.main()
