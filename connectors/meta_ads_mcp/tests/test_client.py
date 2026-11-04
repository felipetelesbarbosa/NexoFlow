"""Regressões com dados sintéticos, sem acesso à internet nem token real."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from connectors.meta_ads_mcp.client import MetaAdsClient, MetaReadError
from connectors.meta_ads_mcp.settings import MetaSettings, SettingsError, load_settings


class FakeResponse:
    def __init__(self, data=None, code=200):
        self._data = data if data is not None else {"data": []}
        self.status_code = code

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, responses):
        self.responses = [
            FakeResponse({"data": [{"permission": "ads_read", "status": "granted"}]})
        ] + list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


class MetaAdsClientTests(unittest.TestCase):
    def setUp(self):
        self.settings = MetaSettings("TOKEN_FICTICIO", "v26.0", ("898435729140540",))

    def test_allowlist_blocks_before_http(self):
        sess = FakeSession([])
        cli = MetaAdsClient(self.settings, sess)
        with self.assertRaises(MetaReadError):
            cli.campaigns("111111111111111")
        self.assertEqual(sess.calls, [])

    def test_read_only_get_and_bearer_header(self):
        sess = FakeSession(
            [FakeResponse({"id": "act_898435729140540", "name": "Teste"})]
        )
        item = MetaAdsClient(self.settings, sess).account_details("act_898435729140540")
        self.assertEqual(item["name"], "Teste")
        url, kw = sess.calls[1]
        self.assertEqual(url, "https://graph.facebook.com/v26.0/act_898435729140540")
        self.assertEqual(kw["headers"]["Authorization"], "Bearer TOKEN_FICTICIO")
        self.assertFalse(kw["allow_redirects"])
        self.assertNotIn("access_token", kw["params"])
        self.assertNotIn("TOKEN_FICTICIO", url)

    def test_pagination_only_uses_cursor_not_next_url(self):
        sess = FakeSession(
            [
                FakeResponse(
                    {
                        "data": [{"id": "1"}],
                        "paging": {
                            "cursors": {"after": "CURSOR_1"},
                            "next": "https://unsafe.invalid?access_token=TOKEN_FICTICIO",
                        },
                    }
                ),
                FakeResponse({"data": [{"id": "2"}]}),
            ]
        )
        result = MetaAdsClient(self.settings, sess).campaigns("898435729140540", 1, 2)
        self.assertEqual(result["total_retornado"], 2)
        self.assertEqual(sess.calls[2][1]["params"]["after"], "CURSOR_1")
        self.assertEqual(sess.calls[1][0], sess.calls[2][0])

    def test_rejects_invalid_level_and_date_without_http(self):
        sess = FakeSession([])
        cli = MetaAdsClient(self.settings, sess)
        for level in ("write", "campaigns"):
            with self.assertRaises(MetaReadError):
                cli.insights("898435729140540", "2026-10-01", "2026-10-31", level)
        with self.assertRaises(MetaReadError):
            cli.insights("898435729140540", "2026-09-01", "2026-01-01")
        self.assertFalse(sess.calls)

    def test_error_does_not_echo_response_token(self):
        sess = FakeSession(
            [FakeResponse({"error": {"message": "TOKEN_FICTICIO"}}, 403)]
        )
        with self.assertRaises(MetaReadError) as err:
            MetaAdsClient(self.settings, sess).account_details("898435729140540")
        self.assertNotIn("TOKEN_FICTICIO", str(err.exception))

    def test_truncation_flag(self):
        sess = FakeSession(
            [
                FakeResponse(
                    {
                        "data": [{"id": "1"}],
                        "paging": {
                            "cursors": {"after": "CURSOR_1"},
                            "next": "https://ignored.invalid",
                        },
                    }
                )
            ]
        )
        result = MetaAdsClient(self.settings, sess).ads("898435729140540", 1, 1)
        self.assertTrue(result["parcial"])

    def test_load_settings_and_duplicate_normalization(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "credentials.json"
            path.write_text(
                json.dumps(
                    {
                        "access_token": "TOKEN_FICTICIO",
                        "api_version": "v26.0",
                        "allowed_ad_account_ids": [
                            "act_898435729140540",
                            "898435729140540",
                        ],
                    }
                ),
                encoding="utf-8",
            )
            settings = load_settings(path)
            self.assertEqual(settings.allowed_account_ids, ("898435729140540",))

    def test_missing_credentials_gives_safe_error(self):
        with self.assertRaises(SettingsError):
            load_settings(Path("__arquivo_inexistente__"))


if __name__ == "__main__":
    unittest.main()
