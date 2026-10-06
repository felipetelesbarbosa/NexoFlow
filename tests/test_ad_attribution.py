import unittest

from ad_attribution import GOOGLE_ADS_ORIGIN, extract_google_ads_attribution


class GoogleAdsAttributionTests(unittest.TestCase):
    def test_gclid_in_nested_source_url_is_google_ads(self):
        message = {
            "id": "m1",
            "created_on": "2026-10-03T12:00:00Z",
            "direction": "in",
            "urn": "whatsapp:5591999999999",
            "metadata": {
                "source_url": (
                    "https://example.com/?utm_source=google&utm_medium=cpc"
                    "&utm_campaign_type=performance_max&gclid=ABC123"
                )
            },
        }
        result = extract_google_ads_attribution(message)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.click_id, "ABC123")
        self.assertEqual(result.click_id_type, "gclid")
        self.assertEqual(result.campaign_type, "Performance Max")
        self.assertEqual(result.destination_channel, "whatsapp")
        self.assertIn("gclid", result.reason)

    def test_search_detected_only_from_explicit_paid_search_medium(self):
        message = {
            "id": "m2",
            "created_on": "2026-10-03T12:00:00Z",
            "direction": "in",
            "urn": "messenger:abc",
            "metadata": {"source_url": "https://example.com/?utm_source=google&utm_medium=paid_search&gclid=G-2"},
        }
        result = extract_google_ads_attribution(message)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.campaign_type, "Search")
        self.assertEqual(result.destination_channel, "facebook")

    def test_display_detected_from_explicit_medium(self):
        message = {
            "id": "m3",
            "created_on": "2026-10-03T12:00:00Z",
            "direction": "in",
            "urn": "instagram:abc",
            "metadata": {"source_url": "https://example.com/?utm_source=google&utm_medium=display&gbraid=BR123"},
        }
        result = extract_google_ads_attribution(message)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.click_id_type, "gbraid")
        self.assertEqual(result.campaign_type, "Display/Banner")
        self.assertEqual(result.destination_channel, "instagram")

    def test_youtube_detected_from_explicit_source_and_video_medium(self):
        message = {
            "id": "m4",
            "created_on": "2026-10-03T12:00:00Z",
            "direction": "in",
            "urn": "whatsapp:1",
            "metadata": {
                "utm_source": "youtube ads",
                "utm_medium": "video",
                "wbraid": "WB123",
            },
        }
        result = extract_google_ads_attribution(message)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.campaign_type, "YouTube")
        self.assertEqual(result.click_id_type, "wbraid")

    def test_cpc_alone_does_not_guess_search_or_performance_max(self):
        message = {
            "id": "m5",
            "created_on": "2026-10-03T12:00:00Z",
            "direction": "in",
            "urn": "whatsapp:1",
            "metadata": {"source_url": "https://example.com/?utm_source=google&utm_medium=cpc&gclid=G5"},
        }
        result = extract_google_ads_attribution(message)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.campaign_type, "")

    def test_plain_google_url_is_not_treated_as_ad(self):
        message = {
            "id": "m6",
            "created_on": "2026-10-03T12:00:00Z",
            "direction": "in",
            "urn": "whatsapp:1",
            "text": "https://www.google.com/search?q=farmacia",
        }
        self.assertIsNone(extract_google_ads_attribution(message))

    def test_outgoing_message_is_not_used_as_ad_evidence(self):
        message = {
            "id": "m7",
            "created_on": "2026-10-03T12:00:00Z",
            "direction": "out",
            "urn": "whatsapp:1",
            "metadata": {"source_url": "https://example.com/?gclid=SHOULD_NOT_COUNT"},
        }
        self.assertIsNone(extract_google_ads_attribution(message))


    def test_customer_pasting_gclid_url_in_free_text_is_not_attribution(self):
        message = {
            "id": "m8",
            "created_on": "2026-10-03T12:00:00Z",
            "direction": "in",
            "urn": "whatsapp:1",
            "text": "olha esse link https://example.com/?gclid=PASTED_BY_CUSTOMER&utm_source=google&utm_medium=cpc",
        }
        self.assertIsNone(extract_google_ads_attribution(message))

    def test_constant_origin_label(self):
        self.assertEqual(GOOGLE_ADS_ORIGIN, "Google Ads")


if __name__ == "__main__":
    unittest.main()
