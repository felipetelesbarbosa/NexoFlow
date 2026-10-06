import unittest

from urn_utils import native_contact_urns, resolve_contact_urns, urn_channel


class UrnUtilsTests(unittest.TestCase):
    def test_classifies_supported_channels_without_using_ad_origin(self):
        self.assertEqual(urn_channel("whatsapp:5591999999999"), "whatsapp")
        self.assertEqual(urn_channel("instagram:123456"), "instagram")
        self.assertEqual(urn_channel("facebook:abc"), "facebook")
        self.assertEqual(urn_channel("messenger:abc"), "facebook")
        self.assertEqual(urn_channel("tel:+5591999999999"), "other")

    def test_native_urns_are_deduplicated_and_keep_weni_order(self):
        contact = {
            "urns": ["instagram:2", "instagram:2", "whatsapp:1"],
            "urn": "facebook:3",
        }
        self.assertEqual(
            native_contact_urns(contact),
            ("instagram:2", "whatsapp:1", "facebook:3"),
        )

    def test_multichannel_principal_prefers_whatsapp(self):
        contact = {
            "urns": ["instagram:2", "facebook:3", "whatsapp:1"],
            "fields": {},
        }
        resolved = resolve_contact_urns(contact)
        self.assertEqual(resolved.principal_urn, "whatsapp:1")
        self.assertEqual(resolved.principal_channel, "whatsapp")
        self.assertEqual(resolved.channel_urns["instagram"], "instagram:2")
        self.assertEqual(resolved.channel_urns["facebook"], "facebook:3")

    def test_instagram_only_becomes_principal(self):
        resolved = resolve_contact_urns({"urns": ["instagram:999"], "fields": {}})
        self.assertEqual(resolved.principal_urn, "instagram:999")
        self.assertEqual(resolved.principal_channel, "instagram")
        self.assertEqual(resolved.channel_urns["instagram"], "instagram:999")
        self.assertEqual(resolved.channel_urns["whatsapp"], "")

    def test_facebook_only_accepts_messenger_scheme(self):
        resolved = resolve_contact_urns({"urns": ["messenger:abc"], "fields": {}})
        self.assertEqual(resolved.principal_urn, "messenger:abc")
        self.assertEqual(resolved.principal_channel, "facebook")
        self.assertEqual(resolved.channel_urns["facebook"], "messenger:abc")

    def test_existing_channel_urn_is_kept_when_still_native(self):
        contact = {
            "urns": ["whatsapp:new", "whatsapp:old"],
            "fields": {"contact_urn_whatsapp": "whatsapp:old"},
        }
        resolved = resolve_contact_urns(contact)
        self.assertEqual(resolved.channel_urns["whatsapp"], "whatsapp:old")
        self.assertEqual(resolved.principal_urn, "whatsapp:old")

    def test_no_native_urn_falls_back_to_existing_without_invention(self):
        contact = {
            "urns": [],
            "fields": {"contact_urn": "instagram:777"},
        }
        resolved = resolve_contact_urns(contact)
        self.assertEqual(resolved.principal_urn, "instagram:777")
        self.assertEqual(resolved.principal_channel, "instagram")

    def test_unrecognized_native_scheme_is_preserved_as_other(self):
        resolved = resolve_contact_urns({"urns": ["ext:abc"], "fields": {}})
        self.assertEqual(resolved.principal_urn, "ext:abc")
        self.assertEqual(resolved.principal_channel, "outro")
        self.assertFalse(any(resolved.channel_urns.values()))


if __name__ == "__main__":
    unittest.main()
