"""Proteções HTTP e configuração; nenhum serviço ou token real."""

import json
import tempfile
import unittest
from pathlib import Path

import requests

from connectors.meta_ads_mcp.client import MetaAdsClient, MetaReadError
from connectors.meta_ads_mcp.settings import MetaSettings, SettingsError, load_settings
from connectors.meta_ads_mcp.tests.test_client import FakeResponse, FakeSession

ACCOUNT = "898435729140540"
TOKEN = "TOKEN_FICTICIO"


class SecurityTests(unittest.TestCase):
    def client(self, responses):
        return MetaAdsClient(
            MetaSettings(TOKEN, "v26.0", (ACCOUNT,)),
            FakeSession(responses),
            sleep_fn=lambda _: None,
        )

    def test_missing_or_management_permission_blocks_before_account(self):
        for scopes in ([], ["ads_management"], ["ads_read", "ads_management"]):
            cli = self.client([])
            cli.session.responses = [
                FakeResponse(
                    {"data": [{"permission": s, "status": "granted"} for s in scopes]}
                )
            ]
            with self.assertRaises(MetaReadError):
                cli.account_details(ACCOUNT)
            self.assertEqual(len(cli.session.calls), 1)

    def test_errors_sanitized_for_each_status_and_200_error(self):
        for code in (400, 401, 403, 429, 500, 302, 399):
            cli = self.client([FakeResponse({"error": {"message": TOKEN}}, code)] * 3)
            with self.assertRaises(MetaReadError) as err:
                cli.ads(ACCOUNT)
            self.assertNotIn(TOKEN, str(err.exception))
        with self.assertRaises(MetaReadError):
            self.client([FakeResponse({"error": {"message": TOKEN}})]).ads(ACCOUNT)

    def test_timeout_does_not_echo_url(self):
        cli = self.client([])

        def timeout(*args, **kw):
            raise requests.Timeout("https://graph.facebook.com?access_token=" + TOKEN)

        cli.session.get = timeout
        with self.assertRaises(MetaReadError) as err:
            cli.account_details(ACCOUNT)
        self.assertNotIn(TOKEN, str(err.exception))

    def test_constructor_rejects_injected_version_and_token_repr(self):
        for version in ("https://evil.invalid", "v26.0/../../me", "v26.0?token=x"):
            with self.assertRaises(SettingsError):
                MetaSettings(TOKEN, version, (ACCOUNT,))
        self.assertNotIn(TOKEN, repr(MetaSettings(TOKEN, "v26.0", (ACCOUNT,))))
        for token in ("", "COLE_TOKEN", "synthetic\r\nInjected:yes"):
            with self.assertRaises(SettingsError):
                MetaSettings(token, "v26.0", (ACCOUNT,))

    def test_settings_missing_token_invalid_json_and_empty_allowlist(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / "test.json"
            for data in (
                {},
                [],
                {"access_token": TOKEN, "allowed_ad_account_ids": []},
                "invalid",
            ):
                p.write_text(json.dumps(data) if data != "invalid" else "{")
                with self.assertRaises(SettingsError):
                    load_settings(p)

    def test_invalid_page_shapes_limits_and_empty_data(self):
        for data in ({}, {"data": None}, {"data": [None]}, {"data": [{}, {}]}):
            with self.assertRaises(MetaReadError):
                self.client([FakeResponse(data)]).ads(ACCOUNT, 1)
        self.assertEqual(
            self.client([FakeResponse({"data": []})]).ads(ACCOUNT)["dados"], []
        )
        for limit, pages in ((0, 1), (101, 1), (True, 1), (1, 0), (1, 11)):
            with self.assertRaises(MetaReadError):
                self.client([]).ads(ACCOUNT, limit, pages)

    def test_missing_cursor_and_cycles_fail(self):
        with self.assertRaises(MetaReadError):
            self.client(
                [FakeResponse({"data": [], "paging": {"next": "https://evil.invalid"}})]
            ).ads(ACCOUNT)

        def page(c):
            return FakeResponse(
                {
                    "data": [],
                    "paging": {"next": "https://evil.invalid", "cursors": {"after": c}},
                }
            )

        with self.assertRaises(MetaReadError):
            self.client([page("A"), page("B"), page("A")]).ads(ACCOUNT, 1, 4)

    def test_no_arbitrary_paths_and_output_hides_token_and_page_links(self):
        cli = self.client([])
        for path in (
            "me",
            "act_11111",
            "act_" + ACCOUNT + "/delete",
            "https://evil.invalid",
        ):
            with self.assertRaises(MetaReadError):
                cli._get(path, {})
        self.assertEqual(cli.session.calls, [])
        result = self.client(
            [
                FakeResponse(
                    {
                        "id": "act_" + ACCOUNT,
                        "name": TOKEN,
                        "access_token": TOKEN,
                        "paging": {
                            "next": "https://evil.invalid?access_token=" + TOKEN
                        },
                    }
                )
            ]
        ).account_details(ACCOUNT)
        rendered = json.dumps(result)
        self.assertNotIn(TOKEN, rendered)
        self.assertNotIn("evil.invalid", rendered)

    def test_strict_dates_before_http(self):
        cli = self.client([])
        for start, end in (
            ("20261101", "2026-11-02"),
            ("2026-11-03", "2026-11-01"),
            ("2026-01-01", "2026-12-31"),
            ("n/a", "2026-11-02"),
        ):
            with self.assertRaises(MetaReadError):
                cli.insights(ACCOUNT, start, end)
        self.assertEqual(cli.session.calls, [])
