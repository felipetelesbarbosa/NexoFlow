import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import requests

from config import WENI_CONTACTS_API_URL
from weni_client import WeniClient


class WeniClientTests(unittest.TestCase):
    @staticmethod
    def response(payload):
        response = Mock(status_code=200, content=b"{}")
        response.json.return_value = payload
        return response

    def test_preflight_confirms_org_then_recovers_slow_read_for_each_segment(self):
        for segment, org in (
            ("FARMA", "Delivery FarmaLíder"),
            ("PET", "Delivery Pets Líder"),
        ):
            with (
                self.subTest(segment=segment),
                patch.dict(os.environ, {"NEXOFLOW_PERFIL": segment}),
            ):
                client = WeniClient("synthetic-token")
                self.addCleanup(client.close)
                with (
                    patch.object(
                        client.session,
                        "request",
                        side_effect=[
                            self.response({"name": org}),
                            requests.exceptions.ReadTimeout("private-marker"),
                            self.response({"results": []}),
                            self.response({"results": [{"id": "synthetic-message"}]}),
                            self.response(
                                {"results": [{"name": "Opt-Out LGPD", "uuid": "group"}]}
                            ),
                        ],
                    ) as request,
                    patch("weni_client.refresh_network_route") as refresh,
                    patch("weni_client.time.sleep"),
                ):
                    result = client.test_update_access("Opt-Out LGPD")
                self.assertTrue(result["ok"])
                self.assertTrue(result["opt_out_group_found"])
                self.assertEqual(result["sample_messages"], 1)
                self.assertTrue(request.call_args_list[0].args[1].endswith("/org.json"))
                self.assertEqual(request.call_args_list[3].kwargs["params"]["limit"], 1)
                self.assertEqual(request.call_count, 5)
                refresh.assert_called_once()
                for call in request.call_args_list:
                    self.assertEqual(call.args[0], "GET")
                    self.assertEqual(call.kwargs["timeout"], (10, 90))
                    self.assertFalse(call.kwargs["allow_redirects"])
                    self.assertIsNot(call.kwargs.get("verify", True), False)

    def test_preflight_rejects_wrong_org_before_reading_contacts(self):
        for segment, wrong_org in (
            ("FARMA", "Delivery Pets Líder"),
            ("PET", "Delivery FarmaLíder"),
        ):
            with (
                self.subTest(segment=segment),
                patch.dict(os.environ, {"NEXOFLOW_PERFIL": segment}),
            ):
                client = WeniClient("synthetic-token")
                self.addCleanup(client.close)
                with patch.object(
                    client.session,
                    "request",
                    return_value=self.response({"name": wrong_org}),
                ) as request:
                    from weni_client import WeniError

                    with self.assertRaisesRegex(WeniError, "Perfil selecionado"):
                        client.test_update_access("Opt-Out LGPD")
                request.assert_called_once()
                self.assertTrue(request.call_args.args[1].endswith("/org.json"))

    def test_single_attempt_post_does_not_repeat_after_read_timeout(self):
        from weni_client import WeniError

        client = WeniClient("synthetic-token", retry_mutations=False)
        self.addCleanup(client.close)
        with (
            patch.object(
                client.session,
                "request",
                side_effect=requests.exceptions.ReadTimeout("private-marker"),
            ) as request,
            patch("weni_client.refresh_network_route") as refresh,
            patch("weni_client.time.sleep") as sleep,
        ):
            with self.assertRaises(WeniError) as caught:
                client._post_json(
                    WENI_CONTACTS_API_URL + "?token=private-marker",
                    json_body={"fields": {"synthetic": "value"}},
                )
        self.assertEqual(request.call_count, 1)
        self.assertEqual(request.call_args.kwargs["timeout"], (10, 90))
        refresh.assert_not_called()
        sleep.assert_not_called()
        message = str(caught.exception)
        self.assertIn("POST /api/v2/contacts.json", message)
        self.assertIn("fase=resposta", message)
        self.assertNotIn("private-marker", message)

    def test_connection_timeouts_are_bounded_and_identify_the_read_operation(self):
        from weni_client import WeniError

        client = WeniClient("synthetic-token")
        self.addCleanup(client.close)
        with (
            patch.object(
                client.session,
                "request",
                side_effect=requests.exceptions.ConnectTimeout("private-marker"),
            ) as request,
            patch("weni_client.refresh_network_route") as refresh,
            patch("weni_client.time.sleep") as sleep,
        ):
            with self.assertRaises(WeniError) as caught:
                client._get_json(WENI_CONTACTS_API_URL)
        self.assertEqual(request.call_count, 4)
        self.assertEqual(refresh.call_count, 3)
        self.assertEqual(sleep.call_count, 3)
        message = str(caught.exception)
        self.assertIn("GET /api/v2/contacts.json", message)
        self.assertIn("fase=conexao", message)
        self.assertIn("conexão=10s", message)
        self.assertNotIn("private-marker", message)

    def test_paginated_logs_are_consolidated_without_claiming_a_known_total(self):
        from task_progress import TaskProgress

        client = WeniClient("token-sintetico")
        self.addCleanup(client.close)
        pages = [
            {
                "results": [{"uuid": f"synthetic-{i}-{j}"} for j in range(100)],
                "next": f"?page={i + 2}" if i < 10 else None,
            }
            for i in range(11)
        ]
        for streaming in (False, True):
            with (
                self.subTest(streaming=streaming),
                patch.object(client, "_get_json", side_effect=pages) as get,
                patch(
                    "weni_client.TaskProgress",
                    side_effect=lambda *args, **kwargs: TaskProgress(
                        *args, **kwargs, clock=lambda: 0.0
                    ),
                ),
                patch("weni_client.logging.info") as info,
                patch("weni_client.logging.debug") as debug,
            ):
                contacts = (
                    list(client.iter_contacts())
                    if streaming
                    else client.list_contacts()
                )
            lines = [call.args[0] % call.args[1:] for call in info.call_args_list]
            self.assertEqual(len(contacts), 1100)
            self.assertEqual(get.call_count, 11)
            self.assertEqual(debug.call_count, 11)
            self.assertEqual(len(lines), 3)
            self.assertIn("1000 registros", lines[1])
            self.assertIn("lotes concluídos=1", lines[1])
            self.assertIn("1100 registros", lines[-1])
            self.assertFalse(any("página" in line or "%" in line for line in lines))

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

    def test_iter_contacts_loads_pages_only_as_they_are_consumed(self) -> None:
        client = WeniClient("token")
        self.addCleanup(client.close)
        with patch.object(
            client,
            "_get_json",
            side_effect=[
                {
                    "results": [{"uuid": "1"}, {"uuid": "2"}],
                    "next": "?page=2",
                },
                {"results": [{"uuid": "3"}], "next": None},
            ],
        ) as get:
            contacts = client.iter_contacts(limit=2)
            get.assert_not_called()
            self.assertEqual(next(contacts), {"uuid": "1"})
            self.assertEqual(get.call_count, 1)
            self.assertEqual(next(contacts), {"uuid": "2"})
            self.assertEqual(get.call_count, 1)
            self.assertEqual(next(contacts), {"uuid": "3"})
            self.assertEqual(get.call_count, 2)
            self.assertEqual(
                get.call_args.args[0],
                WENI_CONTACTS_API_URL + "?page=2",
            )
            self.assertIsNone(get.call_args.kwargs["params"])
            self.assertEqual(list(contacts), [])

    def test_iter_contacts_passes_filter_and_after_on_first_request(self) -> None:
        client = WeniClient("token")
        self.addCleanup(client.close)
        after = datetime(2026, 10, 9, 21, 0, tzinfo=timezone(timedelta(hours=-3)))
        with patch.object(
            client,
            "_get_json",
            return_value={"results": [], "next": None},
        ) as get:
            self.assertEqual(list(client.iter_contacts(after=after, limit=50)), [])
        get.assert_called_once_with(
            WENI_CONTACTS_API_URL,
            params={
                "deleted": "false",
                "order_by": "modified_on",
                "limit": 50,
                "after": "2026-10-10T00:00:00.000Z",
            },
        )

    def test_list_contacts_preserves_complete_list_and_filters_records(self) -> None:
        client = WeniClient("token")
        self.addCleanup(client.close)
        with patch.object(
            client,
            "_get_json",
            side_effect=[
                {"results": [{"uuid": "1"}, None, "invalid"], "next": "?page=2"},
                [{"uuid": "2"}],
            ],
        ) as get:
            self.assertEqual(
                client.list_contacts(),
                [{"uuid": "1"}, {"uuid": "2"}],
            )
            self.assertEqual(get.call_count, 2)

    def test_paginated_limit_does_not_request_page_after_exact_boundary(self) -> None:
        client = WeniClient("token")
        self.addCleanup(client.close)
        with patch.object(
            client,
            "_get_json",
            side_effect=[
                {"results": [{"uuid": "1"}], "next": "?page=2"},
                {"results": [{"uuid": "2"}], "next": "?page=3"},
            ],
        ) as get:
            results = client._list_paginated(
                WENI_CONTACTS_API_URL,
                item_label="contatos",
                max_results=2,
            )
            self.assertEqual(results, [{"uuid": "1"}, {"uuid": "2"}])
            self.assertEqual(get.call_count, 2)

    def test_paginated_zero_limit_does_not_request_any_page(self) -> None:
        client = WeniClient("token")
        self.addCleanup(client.close)
        with patch.object(client, "_get_json") as get:
            self.assertEqual(
                client._list_paginated(
                    WENI_CONTACTS_API_URL,
                    item_label="contatos",
                    max_results=0,
                ),
                [],
            )
            get.assert_not_called()

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
