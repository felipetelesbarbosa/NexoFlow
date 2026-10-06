import unittest
from unittest.mock import Mock, patch

from weni_client import WeniClient


class WeniClientTests(unittest.TestCase):
    def test_extracts_paginated_results(self) -> None:
        payload = {
            "results": [{"uuid": "1"}, {"uuid": "2"}],
            "next": "https://flows.weni.ai/api/v2/contacts.json?page=2",
        }
        results, next_url = WeniClient.extract_results(payload)
        self.assertEqual(len(results), 2)
        self.assertIsNotNone(next_url)
        assert next_url is not None
        self.assertTrue(next_url.endswith("page=2"))

    def test_extracts_list_response(self) -> None:
        results, next_url = WeniClient.extract_results([{"uuid": "1"}])
        self.assertEqual(len(results), 1)
        self.assertIsNone(next_url)

    def test_update_contact_fields_posts_only_fields(self) -> None:
        client = WeniClient("token")
        try:
            with patch.object(client, "_post_json", return_value={"ok": True}) as post:
                client.update_contact_fields(
                    "contact-1",
                    {"idade": 30, "maior_de_18_anos": "sim"},
                )
            kwargs = post.call_args.kwargs
            self.assertEqual(kwargs["params"], {"uuid": "contact-1"})
            self.assertEqual(
                kwargs["json_body"],
                {"fields": {"idade": 30, "maior_de_18_anos": "sim"}},
            )
        finally:
            client.close()

    def test_contact_group_action_uses_contact_actions_api(self) -> None:
        client = WeniClient("token")
        try:
            with patch.object(client, "_post_json", return_value={"ok": True}) as post:
                client.contact_group_action(
                    "contact-1",
                    action="add",
                    group="group-1",
                )
            self.assertEqual(
                post.call_args.kwargs["json_body"],
                {
                    "contacts": ["contact-1"],
                    "action": "add",
                    "group": "group-1",
                },
            )
        finally:
            client.close()

    def test_request_retries_server_error(self) -> None:
        client = WeniClient("token")
        response_500 = Mock()
        response_500.status_code = 500
        response_500.raise_for_status.side_effect = RuntimeError("server")
        response_ok = Mock()
        response_ok.status_code = 200
        response_ok.content = b"{}"
        response_ok.json.return_value = {"results": []}
        try:
            with (
                patch.object(
                    client.session,
                    "request",
                    side_effect=[response_500, response_ok],
                ),
                patch("weni_client.time.sleep"),
            ):
                payload = client._request_json("GET", "https://example.test")
            self.assertEqual(payload, {"results": []})
        finally:
            client.close()

    def test_list_fields_uses_fields_api(self) -> None:
        client = WeniClient("token")
        try:
            with patch.object(
                client,
                "_list_paginated",
                return_value=[{"key": "contact_urn_whatsapp"}],
            ) as listing:
                result = client.list_fields()
            self.assertEqual(result, [{"key": "contact_urn_whatsapp"}])
            self.assertIn("/api/v2/fields.json", listing.call_args.args[0])
            self.assertEqual(listing.call_args.kwargs["item_label"], "campos")
        finally:
            client.close()

    def test_list_messages_can_stop_at_requested_limit(self) -> None:
        client = WeniClient("token")
        try:
            with patch.object(
                client,
                "_get_json",
                return_value={
                    "results": [{"uuid": str(i)} for i in range(10)],
                    "next": "https://flows.weni.ai/api/v2/messages.json?page=2",
                },
            ) as get:
                result = client.list_messages(contact="contact-1", limit=3)
            self.assertEqual(len(result), 3)
            self.assertEqual(get.call_count, 1)
        finally:
            client.close()


if __name__ == "__main__":
    unittest.main()
