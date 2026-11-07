"""404 específico de ausência: janela vazia, nunca erro de rota ou página faltante."""

import json
import sqlite3
import unittest
from contextlib import closing
from unittest.mock import Mock, patch

import requests

from farmalider_client import FarmaliderClient, FarmaliderError
from order_history import HistoryQuery, empty_history_envelope
from order_history_store import HistoryStore, collect_windows
from tests.test_order_history import NOW, Source, order

EMPTY_MESSAGE = "Nenhum pedido encontrado para o segmento e período informados."


class EmptyWindowTests(unittest.TestCase):
    def test_only_the_official_message_in_text_or_json_is_empty(self):
        for message in (
            EMPTY_MESSAGE,
            json.dumps(EMPTY_MESSAGE),
            json.dumps(EMPTY_MESSAGE, ensure_ascii=False),
        ):
            with self.subTest(message=message):
                self.assertIsNotNone(empty_history_envelope(404, message, 1, 500))
                for status, page in ((200, 1), (401, 1), (403, 1), (500, 1), (404, 2)):
                    self.assertIsNone(empty_history_envelope(status, message, page, 500))
        for message in (
            None,
            {},
            "",
            "Not Found",
            json.dumps("Not Found"),
            json.dumps({"message": EMPTY_MESSAGE}),
            json.dumps([EMPTY_MESSAGE]),
            json.dumps(EMPTY_MESSAGE)[:-1],
            json.dumps(json.dumps(EMPTY_MESSAGE)),
            f"<html>{EMPTY_MESSAGE}</html>",
        ):
            with self.subTest(message=message):
                self.assertIsNone(empty_history_envelope(404, message, 1, 500))

    def test_json_string_empty_response_with_the_client_accept_header(self):
        client = FarmaliderClient("TOKEN_SINTETICO")
        self.addCleanup(client.close)
        self.assertEqual(client.session.headers["Accept"], "application/json")
        response = requests.Response()
        response.status_code = 404
        response.headers["Content-Type"] = "application/json; charset=utf-8"
        session = Mock()
        session.get.return_value = response
        query = HistoryQuery("FARMA", "2000-01-01", "2000-02-01")
        for ascii_only in (False, True):
            with (
                self.subTest(ascii_only=ascii_only),
                patch.object(client, "_get_session", return_value=session),
                patch.object(
                    client, "_request_route", return_value=("https://example.invalid", {})
                ),
            ):
                response._content = json.dumps(
                    EMPTY_MESSAGE, ensure_ascii=ascii_only
                ).encode("utf-8")
                result = client.get_pedidos_history(query, 1)
                self.assertEqual(result["pedidos"], [])
                self.assertEqual(result["totalRegistros"], 0)
                with self.assertRaises(FarmaliderError):
                    client.get_pedidos_history(query, 2)

    def test_exact_empty_response_becomes_zero_envelope_on_first_page_only(self):
        client = FarmaliderClient("TOKEN_SINTETICO")
        self.addCleanup(client.close)
        response = requests.Response()
        response.status_code = 404
        response._content = EMPTY_MESSAGE.encode()
        response.encoding = "utf-8"
        session = Mock()
        session.get.return_value = response
        q = HistoryQuery("FARMA", "2000-01-01", "2000-02-01")
        with (
            patch.object(client, "_get_session", return_value=session),
            patch.object(
                client, "_request_route", return_value=("https://example.invalid", {})
            ),
        ):
            result = client.get_pedidos_history(q, 1)
            self.assertEqual(
                result,
                {
                    "pedidos": [],
                    "pagina": 1,
                    "limite": 500,
                    "totalRegistros": 0,
                    "totalPaginas": 0,
                },
            )
            self.assertEqual(session.get.call_count, 1)
            with self.assertRaises(FarmaliderError):
                client.get_pedidos_history(q, 2)
            for body in (b"Not Found", b"", b"Route not found"):
                response._content = body
                with self.assertRaises(FarmaliderError):
                    client.get_pedidos_history(q, 1)

    def test_empty_windows_advance_then_paginate_and_resume_without_duplicates(self):
        with closing(sqlite3.connect(":memory:")) as db:
            store = HistoryStore(db, "PET")
            calls = []

            class Windows:
                def get_pedidos_history(_, q, page):
                    calls.append((q.start, page))
                    rows = (
                        []
                        if q.start < "2026-03-04"
                        else [order(i, day=q.start) for i in (1, 2, 3)]
                    )
                    return Source(rows).get_pedidos_history(q, page)

            q = HistoryQuery("PET", "2026-01-01", "2026-03-05", 2)
            first = collect_windows(Windows(), store, q, now=NOW, max_pages=3)
            self.assertEqual(
                calls, [("2026-01-01", 1), ("2026-02-01", 1), ("2026-03-04", 1)]
            )
            self.assertEqual(first["pedidos_validos"], 2)
            again = collect_windows(Windows(), store, q, now=NOW)
            self.assertEqual(calls[-1], ("2026-03-04", 2))
            self.assertEqual(again["pedidos_validos"], 3)
            self.assertEqual(again["incomplete_windows"], 0)
            self.assertEqual(again["faturamento_centavos"], 24000)

    def test_http_json_empty_windows_continue_and_resume_real_collector(self):
        client = FarmaliderClient("TOKEN_SINTETICO")
        self.addCleanup(client.close)
        calls = []

        def get(url, *, params, **kwargs):
            calls.append((params["dataInicio"], params["pagina"]))
            response = requests.Response()
            response.headers["Content-Type"] = "application/json; charset=utf-8"
            if params["dataInicio"] < "2026-03-04":
                response.status_code = 404
                payload = EMPTY_MESSAGE
            else:
                response.status_code = 200
                payload = Source(
                    [order(i, day=params["dataInicio"], segment="FARMA") for i in (1, 2, 3)]
                ).get_pedidos_history(query, params["pagina"])
            response._content = json.dumps(payload).encode("utf-8")
            return response

        session = Mock()
        session.get.side_effect = get
        with (
            closing(sqlite3.connect(":memory:")) as db,
            patch.object(client, "_get_session", return_value=session),
            patch.object(
                client, "_request_route", return_value=("https://example.invalid", {})
            ),
        ):
            store = HistoryStore(db, "FARMA")
            query = HistoryQuery("FARMA", "2026-01-01", "2026-03-05", 2)
            first = collect_windows(client, store, query, now=NOW, max_pages=3)
            self.assertEqual(
                calls, [("2026-01-01", 1), ("2026-02-01", 1), ("2026-03-04", 1)]
            )
            self.assertEqual(first["pedidos_validos"], 2)
            self.assertEqual(first["incomplete_windows"], 1)
            again = collect_windows(client, store, query, now=NOW)
            self.assertEqual(calls[-1], ("2026-03-04", 2))
            self.assertEqual(len(calls), 4)
            self.assertEqual(again["pedidos_validos"], 3)
            self.assertEqual(again["incomplete_windows"], 0)
            self.assertEqual(again["faturamento_centavos"], 24000)

    def test_missing_later_page_keeps_partial_checkpoint(self):
        from order_history_store import collect

        with closing(sqlite3.connect(":memory:")) as db:
            store = HistoryStore(db, "FARMA")
            q = HistoryQuery("FARMA", "2026-11-03", "2026-11-03", 2)
            collect(
                Source([order(i, segment="FARMA") for i in (1, 2, 3)]),
                store,
                q,
                now=NOW,
                max_pages=1,
            )
            client = FarmaliderClient("TOKEN_SINTETICO")
            self.addCleanup(client.close)
            response = requests.Response()
            response.status_code = 404
            response._content = EMPTY_MESSAGE.encode()
            session = Mock()
            session.get.return_value = response
            with (
                patch.object(client, "_get_session", return_value=session),
                patch.object(
                    client,
                    "_request_route",
                    return_value=("https://example.invalid", {}),
                ),
                self.assertRaises(FarmaliderError),
            ):
                collect(client, store, q, now=NOW)
            self.assertEqual(store.state(q)["next_page"], 2)
            self.assertEqual(store.state(q)["received"], 2)
            self.assertEqual(store.totals()["pedidos_validos"], 2)

    def test_empty_window_progress_has_no_page_one_of_zero(self):
        import io
        from contextlib import redirect_stdout

        from run_order_history import print_progress

        with redirect_stdout(io.StringIO()) as output:
            print_progress(
                dict(
                    next_page=2,
                    pages=0,
                    received=0,
                    total=0,
                    status="extraida",
                    window=1,
                    windows=2,
                )
            )
        self.assertIn("sem pedidos nesta janela", output.getvalue())
        self.assertNotIn("1/0", output.getvalue())
