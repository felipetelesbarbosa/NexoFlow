import json
import sqlite3
import unittest
from copy import deepcopy
from unittest.mock import Mock

from order_history import (
    HistoryError,
    HistoryQuery,
    IdentityIndex,
    canonical,
    ltv,
    normalize_order,
)
from order_history_store import HistoryStore, collect

NOW = "2026-11-06T20:00:00-03:00"


def order(oid=1, amount=80, segment="PET", owner=10, status=2, day="2026-11-03"):
    return {
        "capa": {
            "id": oid,
            "codCliente": owner,
            "segmento": segment,
            "emissao": day + "T10:15:00",
            "status": status,
            "formaPagamento": 5,
            "frete": 0,
        },
        "itens": [
            {
                "id": "item-" + str(oid),
                "codPedido": oid,
                "codProduto": 8,
                "descricao": "Produto sintético",
                "quantidade": 1,
                "valor": amount,
                "total": amount,
                "desconto": 0,
            }
        ],
    }


class Source:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def get_pedidos_history(self, q, page):
        self.calls.append((q.segment, q.start, q.end, q.limit, page))
        return {
            "pagina": page,
            "limite": q.limit,
            "totalRegistros": len(self.rows),
            "totalPaginas": (len(self.rows) + q.limit - 1) // q.limit,
            "pedidos": self.rows[(page - 1) * q.limit : page * q.limit],
        }


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.store = HistoryStore(self.db, "PET")
        self.query = HistoryQuery("PET", "2026-11-01", "2026-11-06", 100)

    def run_source(self, source, **kw):
        return collect(source, self.store, self.query, now=NOW, **kw)

    def test_limits_1200_and_single_page(self):
        for limit, expected in ((400, [1, 2, 3]), (500, [1, 2, 3])):
            q = HistoryQuery("PET", "2026-11-03", "2026-11-03", limit)
            source = Source([order(i) for i in range(1, 1201)])
            first = collect(source, self.store, q, now=NOW, max_pages=1)
            self.assertEqual(first["received"], limit)
            self.assertEqual(first["status"], "incompleta")
            last = collect(source, self.store, q, now=NOW)
            self.assertEqual([r[-1] for r in source.calls], expected)
            self.assertTrue(
                all(
                    r[:4] == ("PET", "2026-11-03", "2026-11-03", limit)
                    for r in source.calls
                )
            )
            self.assertEqual(last["received"], 1200)
            self.assertEqual(last["pedidos_validos"], 1200)
            self.assertEqual(last["faturamento_centavos"], 9600000)

    def test_205_resume_atomic_rollback_and_repeat(self):
        source = Source([order(i) for i in range(1, 206)])
        result = self.run_source(source, max_pages=2)
        self.assertEqual((result["received"], result["next_page"]), (200, 3))
        with self.assertRaises(RuntimeError):
            self.store.commit_page(
                self.query,
                3,
                source.get_pedidos_history(self.query, 3),
                now=NOW,
                interrupt=Mock(side_effect=RuntimeError()),
            )
        self.assertEqual(self.store.state(self.query)["received"], 200)
        result = self.run_source(source)
        self.assertEqual((result["received"], result["status"]), (205, "extraida"))
        self.run_source(source)
        self.assertEqual(self.store.totals()["pedidos_validos"], 205)

    def test_zero_exact_limit_and_size_change(self):
        result = self.run_source(Source([]))
        self.assertEqual(result["status"], "extraida")
        self.run_source(Source([order(i) for i in range(1, 201)]), restart=True)
        q = HistoryQuery("PET", self.query.start, self.query.end, 500)
        result = collect(
            Source([order(i) for i in range(1, 201)]), self.store, q, now=NOW
        )
        self.assertEqual(result["received"], 200)
        self.assertEqual(result["pages_this_run"], 1)

    def test_short_repeated_unstable_and_missing_pages(self):
        source = Source([order(i) for i in range(1, 206)])
        self.run_source(source, max_pages=1)
        payload = source.get_pedidos_history(self.query, 2)
        for change in (
            {"totalRegistros": 204},
            {"pedidos": []},
            {"pedidos": [order(1)]},
            {"pagina": 1},
        ):
            with self.assertRaises(HistoryError):
                self.store.commit_page(self.query, 2, dict(payload, **change), now=NOW)
        self.assertEqual(self.store.state(self.query)["received"], 100)

    def test_ltv_month_cancelled_and_old_closing(self):
        rows = [order(1, 80, day="2026-10-01"), order(2, 50), order(3, 30, status=3)]
        self.query = HistoryQuery("PET", "2026-10-01", "2026-11-06")
        result = self.run_source(Source(rows))
        self.assertEqual(
            (result["faturamento_centavos"], result["pedidos_validos"]), (13000, 2)
        )
        self.assertEqual(ltv(self.store.records())[0]["average"], "65.00")
        self.assertEqual(
            sum(
                r["revenue_cents"]
                for r in self.store.records()
                if r["date"].startswith("2026-11") and r["state"] == "valido"
            ),
            5000,
        )
        rows[0]["capa"]["status"] = 3
        self.run_source(Source(rows), restart=True)
        self.assertEqual(self.store.totals()["faturamento_centavos"], 13000)
        self.run_source(Source(rows), restart=True, mode="reconciliacao")
        self.assertEqual(self.store.totals()["faturamento_centavos"], 5000)

    def test_money_and_absent_items(self):
        r = order()
        r["capa"]["frete"] = 8
        r["itens"].append(
            dict(
                r["itens"][0],
                id="freight",
                codProduto=0,
                descricao="",
                valor=8,
                total=8,
            )
        )
        result = normalize_order(r, "PET", NOW)
        self.assertEqual(result["revenue_cents"], 8800)
        self.assertEqual(result["products_cents"], 8000)
        r["itens"][1]["total"] = 7
        self.assertEqual(normalize_order(r, "PET", NOW)["state"], "pendente")
        for bad in (None, "", {}, False):
            r = order()
            r["itens"] = bad
            self.assertEqual(normalize_order(r, "PET", NOW)["state"], "pendente")
        r = order()
        del r["itens"]
        self.assertEqual(normalize_order(r, "PET", NOW)["state"], "pendente")
        r["itens"] = []
        self.assertEqual(normalize_order(r, "PET", NOW)["state"], "cancelado")
        r = order()
        r["itens"][0]["desconto"] = 1
        self.assertEqual(normalize_order(r, "PET", NOW)["state"], "pendente")

    def test_status_and_analytics_parity(self):
        from analytics import _order_revenue_parts, _sales_order_is_valid

        for status in (-2, -1, 0, 4, 1, 2, 3):
            record = normalize_order(order(status=status), "PET", NOW)
            self.assertEqual(record["state"] == "valido", status != 3)
            self.assertEqual(_sales_order_is_valid(canonical(record)), status != 3)
            if status != 3:
                self.assertEqual(
                    _order_revenue_parts(canonical(record))[2] * 100,
                    record["revenue_cents"],
                )
        r = order()
        r["capa"]["formaPagamento"] = 0
        self.assertEqual(normalize_order(r, "PET", NOW)["state"], "cancelado")

    def test_owner_conflict_preserves_prior_and_no_pii_stored(self):
        self.run_source(Source([order()]))
        self.run_source(Source([order(owner=999)]), restart=True)
        self.assertEqual(next(self.store.records())["owner"], "10")
        self.assertEqual(self.store.totals()["pendencias"], 1)
        r = order()
        r["capa"]["obs"] = "PRIVATE"
        r["capa"]["logradouro"] = "PRIVATE"
        self.assertNotIn("PRIVATE", json.dumps(normalize_order(r, "PET", NOW)))

    def test_identity_valid_invalid_and_ambiguity(self):
        c = {
            "uuid": "u",
            "name": "Pessoa Sintética",
            "urns": ["whatsapp:5591999998888"],
            "fields": {"cpf": "12345678901", "email": "fixture@example.invalid"},
        }
        customer = {
            "cpf": "12345678901",
            "nome": "Pessoa Sintética",
            "celular": "91999998888",
            "email": "",
        }
        self.assertEqual(IdentityIndex([c]).match(customer)[0], "u")
        self.assertEqual(
            IdentityIndex([c]).match(dict(customer, nome="Outra Pessoa"))[0], ""
        )
        self.assertEqual(
            IdentityIndex([c]).match(
                dict(customer, celular="", email="fixture@example.invalid")
            )[0],
            "u",
        )
        self.assertEqual(IdentityIndex([c, dict(c, uuid="v")]).match(customer)[0], "")
        valid = deepcopy(c)
        valid["fields"]["cpf"] = "52998224725"
        self.assertEqual(
            IdentityIndex([valid]).match(dict(customer, cpf="52998224725"))[0], "u"
        )

    def test_dates_and_cross_segment(self):
        q = HistoryQuery(
            "PET", "2026-11-01T00:00:00-03:00", "2026-11-01T23:59:59-03:00"
        )
        self.assertTrue(q.contains("2026-11-02T02:59:59Z"))
        self.assertFalse(q.contains("2026-11-02T03:00:00Z"))
        self.assertEqual(normalize_order(order(), "FARMA", NOW)["state"], "ignorado")
        with self.assertRaises(HistoryError):
            self.store.begin(HistoryQuery("FARMA", q.start, q.end))


class HistoryTransportTests(unittest.TestCase):
    def test_query_route_redirect_and_reserved_token(self):
        from unittest.mock import patch
        from urllib.parse import parse_qs, urlsplit

        import requests

        from farmalider_client import FarmaliderClient, FarmaliderError

        client = FarmaliderClient("fixture+/&=?% token")
        self.addCleanup(client.close)
        q = HistoryQuery("FARMA", "2026-11-01", "2026-11-06", 500)
        response = requests.Response()
        response.status_code = 200
        response._content = b'{"pedidos":[]}'
        session = Mock()
        session.get.return_value = response
        with (
            patch.object(client, "_get_session", return_value=session),
            patch.object(
                client,
                "_request_route",
                return_value=("https://example.invalid/api/Delivery/pedidos/farma", {}),
            ),
        ):
            client.get_pedidos_history(q, 1)
            call = session.get.call_args
            prepared = requests.Request(
                "GET", call.args[0], params=call.kwargs["params"]
            ).prepare()
            self.assertEqual(
                parse_qs(urlsplit(prepared.url).query)["token"], ["fixture+/&=?% token"]
            )
            self.assertFalse(call.kwargs["allow_redirects"])
            self.assertEqual(call.kwargs["params"]["dataFim"], "2026-11-06T23:59:59.999999")
            response.status_code = 302
            with self.assertRaisesRegex(FarmaliderError, "Redirecionamento"):
                client.get_pedidos_history(q, 1)
        with self.assertRaises(ValueError):
            client._request_json("/api/Delivery/pedido/1", query={"token": "forbidden"})

    def test_history_400_explains_rejected_parameters_without_retry_or_cursor_advance(
        self,
    ):
        from contextlib import closing
        from unittest.mock import patch

        import requests

        from farmalider_client import FarmaliderBadRequestError, FarmaliderClient

        client = FarmaliderClient("TOKEN_PRIVADO_SINTETICO")
        self.addCleanup(client.close)
        q = HistoryQuery("FARMA", "2026-11-01", "2026-11-06", 500)
        response = requests.Response()
        response.status_code = 400
        response._content = b'{"error":"DADO_PRIVADO_NAO_EXIBIR"}'
        session = Mock()
        session.get.return_value = response
        with closing(sqlite3.connect(":memory:")) as db:
            store = HistoryStore(db, "FARMA")
            with (
                patch.object(client, "_get_session", return_value=session),
                patch.object(
                    client,
                    "_request_route",
                    return_value=("https://example.invalid", {}),
                ),
                self.assertRaises(FarmaliderBadRequestError) as error,
            ):
                collect(client, store, q, now=NOW)
            message = str(error.exception)
            self.assertIn("limite=500", message)
            self.assertIn("500", message)
            self.assertIn("não confirma", message)
            self.assertNotIn("TOKEN_PRIVADO", message)
            self.assertNotIn("DADO_PRIVADO", message)
            self.assertEqual(session.get.call_count, 1)
            self.assertEqual(store.state(q)["next_page"], 1)
            self.assertEqual(list(store.records()), [])

    def test_timeout_429_retry_and_failure_preserves_cursor(self):
        from unittest.mock import patch

        import requests

        from farmalider_client import FarmaliderClient, FarmaliderError

        client = FarmaliderClient("fixture-token")
        self.addCleanup(client.close)
        q = HistoryQuery("FARMA", "2026-11-01", "2026-11-06")
        limited = requests.Response()
        limited.status_code = 429
        limited.headers["Retry-After"] = "0"
        good = requests.Response()
        good.status_code = 200
        good._content = b'{"pedidos":[]}'
        session = Mock()
        session.get.side_effect = [requests.Timeout("secret-query"), limited, good]
        with (
            patch.object(client, "_get_session", return_value=session),
            patch.object(
                client, "_request_route", return_value=("https://example.invalid", {})
            ),
            patch.object(client, "_protect_after_failure"),
            patch.object(client, "_refresh_network_route"),
            patch.object(client, "_sleep_before_retry"),
        ):
            client.get_pedidos_history(q, 1)
            self.assertEqual(session.get.call_count, 3)
            session.get.side_effect = requests.exceptions.SSLError("secret-query")
            with self.assertRaises(FarmaliderError) as error:
                client.get_pedidos_history(q, 1)
            self.assertNotIn("secret-query", str(error.exception))


class HistorySheetsTests(unittest.TestCase):
    def test_real_store_simulated_sheets_idempotence_and_backup(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from order_history_sheets import HistorySheets, google_store_type, tables
        from tests.test_meta_ads_sheets import MemoryStore

        class Store(MemoryStore):
            _native_meta_headers = staticmethod(
                google_store_type()._native_meta_headers
            )

        store = Store()
        store.profile = "PET"
        db = sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        history = HistoryStore(db, "PET")
        collect(
            Source([order()]),
            history,
            HistoryQuery("PET", "2026-11-01", "2026-11-06"),
            now=NOW,
        )
        with TemporaryDirectory() as tmp:
            adapter = HistorySheets(store, "PET", Path(tmp))
            data = tables(history)
            plan = adapter.plan(data)
            self.assertEqual(store.writes, 0)
            self.assertGreater(adapter.apply(data, plan), 0)
            self.assertTrue(list(Path(tmp).glob("*.json")))
            self.assertEqual(adapter.apply(data, adapter.plan(data)), 0)
            self.assertIn("Historico_Pedidos", store._storage_books["hist"].tabs)
            self.assertIn("BI_LTV_Clientes", store._storage_books["dash"].tabs)
            altered = deepcopy(data)
            altered["Historico_Pedidos"][0]["segmento"] = "FARMA"
            with self.assertRaises(HistoryError):
                adapter.plan(altered)


class HistoryIntegrationTests(unittest.TestCase):
    def test_ads_before_between_after_and_no_recompra(self):
        from order_history import attribute_history

        a = {
            "segment": "PET",
            "contact_uuid": "u",
            "event_id": "a",
            "ad_id": "10",
            "date": "2026-11-01T10:00:00-03:00",
            "official": True,
        }
        b = dict(a, event_id="b", ad_id="20", date="2026-11-04T10:00:00-03:00")
        first = normalize_order(order(), "PET", NOW)
        first["contact_uuid"] = "u"
        second = normalize_order(order(2, day="2026-11-05"), "PET", NOW)
        second["contact_uuid"] = "u"
        self.assertEqual(attribute_history(first, [a, b], window_days=7)["ad_id"], "10")
        self.assertEqual(
            attribute_history(second, [a, b], window_days=7)["ad_id"], "20"
        )
        self.assertIsNone(attribute_history(first, [a, b], window_days=None))
        self.assertIsNone(
            attribute_history(dict(first, contact_uuid=""), [a, b], window_days=7)
        )
        self.assertNotIn("recompra", first)

    def test_canonical_dedup_same_sku_and_cancelled_updates(self):
        from analytics import _item_key
        from order_history_store import merge_canonical

        db = sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        store = HistoryStore(db, "PET")
        q = HistoryQuery("PET", "2026-11-01", "2026-11-06")
        r = order()
        r["itens"].append(dict(r["itens"][0], id="second"))
        collect(Source([r]), store, q, now=NOW)
        orders, items = merge_canonical(
            store, [dict(canonical(normalize_order(r, "PET", NOW)))], []
        )
        self.assertEqual(len(orders), 1)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[1]["item_chave"], _item_key("FARMALIDER:1", 2))
        r["capa"]["status"] = 3
        collect(Source([r]), store, q, now=NOW, restart=True)
        orders, items = merge_canonical(store, orders, items)
        self.assertEqual(orders[0]["status_confirmacao"], "CANCELADO_API")
        self.assertFalse(items)

    def test_operational_cli_parser(self):
        from nexo_cli import build_parser

        args = build_parser().parse_args(
            [
                "historico",
                "--inicio",
                "2026-11-01",
                "--fim",
                "2026-11-06",
                "--limite",
                "500",
                "--max-paginas",
                "1",
            ]
        )
        self.assertEqual(
            (args.command, args.limite, args.max_paginas), ("historico", 500, 1)
        )

    def test_multiwindow_boundaries_and_incremental_resume(self):
        from order_history_store import collect_windows

        db = sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        store = HistoryStore(db, "PET")

        class DailySource(Source):
            def get_pedidos_history(self, q, page):
                self.rows = [order(int(q.start[-2:]), day=q.start)]
                return super().get_pedidos_history(q, page)

        source = DailySource([])
        q = HistoryQuery("PET", "2026-11-01", "2026-11-06")
        result = collect_windows(source, store, q, now=NOW, max_pages=1, window_days=2)
        self.assertEqual(result["incomplete_windows"], 2)
        result = collect_windows(source, store, q, now=NOW, window_days=2)
        self.assertEqual(result["incomplete_windows"], 0)
        self.assertEqual(
            [(c[1], c[2]) for c in source.calls],
            [
                ("2026-11-01", "2026-11-03"),
                ("2026-11-03", "2026-11-05"),
                ("2026-11-05", "2026-11-06"),
            ],
        )

    def test_remote_valid_orders_missing_locally_block_publication(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from order_history_sheets import HistorySheets, google_store_type, tables
        from tests.test_meta_ads_sheets import MemoryStore

        class Store(MemoryStore):
            _native_meta_headers = staticmethod(
                google_store_type()._native_meta_headers
            )

        remote = Store()
        remote.profile = "PET"
        db = sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        local = HistoryStore(db, "PET")
        collect(
            Source([order()]),
            local,
            HistoryQuery("PET", "2026-11-01", "2026-11-06"),
            now=NOW,
        )
        with TemporaryDirectory() as tmp:
            adapter = HistorySheets(remote, "PET", Path(tmp))
            data = tables(local)
            adapter.apply(data, adapter.plan(data))
            empty = {k: [] for k in data}
            with self.assertRaisesRegex(HistoryError, "BASE_LOCAL_INCOMPLETA"):
                adapter.plan(empty)

    def test_history_cache_cannot_undo_newer_confirmation_and_wrong_directory(self):
        from order_history_store import merge_canonical

        db = sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        store = HistoryStore(db, "PET")
        collect(
            Source([order()]),
            store,
            HistoryQuery("PET", "2026-11-01", "2026-11-06"),
            now=NOW,
        )
        current = canonical(normalize_order(order(status=3), "PET", NOW))
        current["farmalider_confirmado_em"] = "2026-11-06T21:00:00-03:00"
        orders, items = merge_canonical(store, [current], [])
        self.assertEqual(orders, [current])
        self.assertEqual(items, [])
        with self.assertRaisesRegex(HistoryError, "CADASTRO_DE_OUTRO_SEGMENTO"):
            store.link(Mock(segment="FARMA"), [])
