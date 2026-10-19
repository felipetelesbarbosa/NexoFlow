"""Rota e transporte coerentes mesmo após espera na fila; sem rede real."""

import os
import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch

from farmalider_client import FarmaliderClient, RequestPermit

PROXY = "http://usuario:senha-sintetica@proxy.example.invalid:8080"


class FarmaliderRouteSnapshotTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ)
        environment.start()
        self.addCleanup(environment.stop)
        for key in list(os.environ):
            if key.lower() in {"http_proxy", "https_proxy", "all_proxy", "no_proxy"}:
                os.environ.pop(key)
        os.environ["WENI_PROXY_ACTIVE"] = "0"
        os.environ["NO_PROXY"] = "*"
        self.client = FarmaliderClient("token-sintetico")
        self.addCleanup(self.client.close)

    def activate_proxy(self):
        os.environ["WENI_PROXY_ACTIVE"] = "1"
        os.environ["HTTPS_PROXY"] = PROXY
        os.environ["NO_PROXY"] = "localhost"

    @contextmanager
    def switch_while_queued(self, endpoint):
        self.activate_proxy()
        yield RequestPermit(0, 1)

    def assert_queued_switch(self, *, preflight):
        with (
            patch.object(self.client, "_request_slot", self.switch_while_queued),
            patch.object(
                self.client.session, "get", return_value=Mock(status_code=404)
            ) as get,
        ):
            if preflight:
                self.assertTrue(self.client.test_connection()["ok"])
            else:
                self.assertIsNone(self.client.get_cliente_by_cpf("52998224725"))
        self.assertTrue(
            get.call_args.args[0].startswith(
                "https://api.farmalider.net.br/farmalider/"
            )
        )
        self.assertNotIn(":3200", get.call_args.args[0])

    def test_waiting_customer_query_uses_route_current_at_admission(self):
        self.assert_queued_switch(preflight=False)

    def test_waiting_preflight_uses_route_current_at_admission(self):
        self.assert_queued_switch(preflight=True)

    def assert_transport_survives_later_change(self, *, initially_proxy):
        import requests

        if initially_proxy:
            self.activate_proxy()
        session = self.client.session
        real_get = session.get
        response = requests.Response()
        response.status_code = 404

        def change_after_snapshot(url, **kwargs):
            if initially_proxy:
                os.environ["WENI_PROXY_ACTIVE"] = "0"
                os.environ.pop("HTTPS_PROXY", None)
                os.environ["NO_PROXY"] = "*"
            else:
                self.activate_proxy()
            return real_get(url, **kwargs)

        with (
            patch.object(session, "get", side_effect=change_after_snapshot),
            patch.object(session, "send", return_value=response) as send,
        ):
            self.assertIsNone(self.client.get_cliente_by_cpf("52998224725"))
        request = send.call_args.args[0]
        proxies = send.call_args.kwargs["proxies"]
        if initially_proxy:
            self.assertNotIn(":3200", request.url)
            self.assertEqual(proxies["https"], PROXY)
        else:
            self.assertIn(":3200/farmalider", request.url)
            self.assertFalse(proxies.get("https"))
            self.assertFalse(proxies.get("http"))
            self.assertFalse(proxies.get("all"))

    def test_captured_proxy_is_not_removed_by_later_direct_detection(self):
        self.assert_transport_survives_later_change(initially_proxy=True)

    def test_captured_direct_route_does_not_inherit_later_proxy(self):
        self.assert_transport_survives_later_change(initially_proxy=False)

    def test_proxy_denial_names_only_destination_and_is_not_retried(self):
        import requests

        from farmalider_client import FarmaliderError

        self.activate_proxy()
        error = requests.exceptions.ProxyError(
            "Tunnel connection failed: 403 Forbidden; "
            + PROXY
            + "; token-sintetico; 52998224725"
        )
        for preflight in (False, True):
            with (
                self.subTest(preflight=preflight),
                patch.object(self.client.session, "get", side_effect=error) as get,
                patch.object(self.client, "_refresh_network_route") as refresh,
            ):
                with self.assertRaises(FarmaliderError) as caught:
                    if preflight:
                        self.client.test_connection()
                    else:
                        self.client.get_cliente_by_cpf("52998224725")
                message = str(caught.exception)
                self.assertIn("PROXY_ACESSO_NEGADO", message)
                self.assertIn("Destino=api.farmalider.net.br:443; rota=proxy", message)
                for private in (
                    PROXY,
                    "senha-sintetica",
                    "token-sintetico",
                    "52998224725",
                ):
                    self.assertNotIn(private, message)
                get.assert_called_once()
                refresh.assert_not_called()
