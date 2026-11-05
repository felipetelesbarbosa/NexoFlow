"""Contrato diário nativo e retentativas limitadas, com Meta simulada."""

import json
import unittest
from unittest.mock import Mock

import requests

from connectors.meta_ads_mcp.client import MetaAdsClient, MetaReadError
from connectors.meta_ads_mcp.settings import MetaSettings
from connectors.meta_ads_mcp.tests.test_client import FakeResponse, FakeSession

ACCOUNT = "898435729140540"


class Transport(FakeSession):
    def get(self, *args, **kwargs):
        result = super().get(*args, **kwargs)
        if isinstance(result, Exception):
            raise result
        return result


class NativeClientTests(unittest.TestCase):
    def client(self, responses):
        sleep = Mock()
        cli = MetaAdsClient(
            MetaSettings("TOKEN_FICTICIO", "v26.0", (ACCOUNT,)),
            Transport(responses),
            sleep_fn=sleep,
        )
        return cli, sleep

    def test_native_catalog_exhausts_more_than_ten_pages(self):
        responses = [
            FakeResponse({"data": [{"id": str(i)}], "paging": {
                "next": "https://graph.facebook.com/ignored",
                "cursors": {"after": str(i + 1)},
            }}) for i in range(12)
        ]
        responses.append(FakeResponse({"data": [{"id": "last"}]}))
        cli, _ = self.client(responses)
        result = cli.campaigns(ACCOUNT, pages=None)
        self.assertFalse(result["parcial"])
        self.assertEqual(result["total_retornado"], 13)

    def test_daily_ad_contract_fields_attribution_and_missing_values(self):
        data = {
            "date_start": "2026-11-01",
            "date_stop": "2026-11-01",
            "account_id": ACCOUNT,
            "ad_id": "123",
            "spend": "10.50",
            "impressions": "100",
            "actions": [{"action_type": "purchase", "value": "2"}],
        }
        cli, _ = self.client([FakeResponse({"data": [data]})])
        result = cli.daily_insights(ACCOUNT, "2026-11-01", "2026-11-01")
        self.assertEqual(result["dados"], [data])
        self.assertNotIn("reach", result["dados"][0])
        self.assertEqual(result["time_increment"], 1)
        self.assertEqual(result["nivel"], "ad")
        self.assertEqual(result["attribution"]["mode"], "explicit_windows")
        query = cli.session.calls[1][1]["params"]
        self.assertEqual(query["time_increment"], 1)
        self.assertEqual(query["level"], "ad")
        self.assertEqual(
            json.loads(query["action_attribution_windows"]), ["7d_click", "1d_view"]
        )
        for field in (
            "inline_link_clicks",
            "cost_per_action_type",
            "purchase_roas",
            "action_values",
        ):
            self.assertIn(field, query["fields"])
        self.assertEqual(query["action_report_time"], "impression")

    def test_legacy_insights_is_still_aggregated_and_account_settings_are_explicit(
        self,
    ):
        cli, _ = self.client([FakeResponse({"data": []}), FakeResponse({"data": []})])
        result = cli.insights(ACCOUNT, "2026-11-01", "2026-11-02")
        self.assertIsNone(result["time_increment"])
        self.assertNotIn("time_increment", cli.session.calls[1][1]["params"])
        result = cli.daily_insights(
            ACCOUNT,
            "2026-11-01",
            "2026-11-02",
            use_account_attribution_setting=True,
            action_attribution_windows=None,
        )
        self.assertEqual(result["attribution"]["mode"], "account_setting")
        self.assertEqual(
            cli.session.calls[2][1]["params"]["use_account_attribution_setting"], "true"
        )
        self.assertNotIn(
            "action_attribution_windows", cli.session.calls[2][1]["params"]
        )

    def test_rate_limit_and_server_retry_use_only_same_get(self):
        limited = FakeResponse(code=429)
        limited.headers = {"Retry-After": "2"}
        cli, sleep = self.client(
            [limited, FakeResponse(code=503), FakeResponse({"data": []})]
        )
        self.assertEqual(cli.ads(ACCOUNT)["dados"], [])
        self.assertEqual(sleep.call_count, 2)
        sleep.assert_any_call(2)
        self.assertEqual(len({url for url, _ in cli.session.calls[1:]}), 1)
        for _, kwargs in cli.session.calls:
            self.assertFalse(kwargs["allow_redirects"])
            self.assertNotIn("access_token", kwargs["params"])

    def test_long_retry_after_defers_instead_of_retrying_early(self):
        limited = FakeResponse(code=429)
        limited.headers = {"Retry-After": "120"}
        cli, sleep = self.client([limited])
        with self.assertRaises(MetaReadError) as caught:
            cli.ads(ACCOUNT)
        self.assertTrue(caught.exception.retryable)
        self.assertFalse(caught.exception.critical)
        self.assertEqual(caught.exception.status_code, 429)
        sleep.assert_not_called()
        self.assertEqual(len(cli.session.calls), 2)

    def test_auth_errors_never_retry_and_expired_token_is_critical_even_http400(self):
        for status in (400, 401, 403):
            cli, sleep = self.client(
                [
                    FakeResponse(
                        {"error": {"code": 190, "message": "TOKEN_FICTICIO"}}, status
                    )
                ]
            )
            with self.assertRaises(MetaReadError) as caught:
                cli.ads(ACCOUNT)
            self.assertTrue(caught.exception.critical)
            self.assertFalse(caught.exception.retryable)
            self.assertNotIn("TOKEN_FICTICIO", str(caught.exception))
            sleep.assert_not_called()
            self.assertEqual(len(cli.session.calls), 2)

    def test_timeout_retries_then_raises_sanitized_retryable_error(self):
        cli, sleep = self.client([requests.Timeout("TOKEN_FICTICIO")] * 3)
        with self.assertRaises(MetaReadError) as caught:
            cli.ads(ACCOUNT)
        self.assertTrue(caught.exception.retryable)
        self.assertIsNone(caught.exception.status_code)
        self.assertEqual(sleep.call_count, 2)
        self.assertEqual(len(cli.session.calls), 4)
        self.assertNotIn("TOKEN_FICTICIO", str(caught.exception))

    def test_daily_truncation_retains_rows_and_marks_partial(self):
        row = {"ad_id": "123", "date_start": "2026-11-01", "date_stop": "2026-11-01"}
        cli, _ = self.client(
            [
                FakeResponse(
                    {
                        "data": [row],
                        "paging": {
                            "next": "https://bad.invalid",
                            "cursors": {"after": "cursor"},
                        },
                    }
                )
            ]
        )
        result = cli.daily_insights(ACCOUNT, "2026-11-01", "2026-11-01", pages=1)
        self.assertTrue(result["parcial"])
        self.assertEqual(result["dados"], [row])

    def test_bad_attribution_does_not_contact_meta(self):
        for kwargs in (
            {"action_report_time": "unknown"},
            {"time_increment": 2},
            {"action_attribution_windows": (["bad"],)},
            {"action_attribution_windows": ("28d_click",)},
            {
                "action_attribution_windows": ("7d_click",),
                "use_account_attribution_setting": True,
            },
        ):
            cli, _ = self.client([])
            with self.assertRaises(MetaReadError):
                cli.insights(ACCOUNT, "2026-11-01", "2026-11-01", **kwargs)
            self.assertEqual(cli.session.calls, [])
