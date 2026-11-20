"""Conferência dos gráficos de Vendas que pedem o mesmo recorte."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from threading import Barrier, Event

import pytest
from psycopg.errors import QueryCanceled

from ds_backend.contract import StorageError
from integrations.datastudio import products_reader
from integrations.datastudio.reader import Reader

FIRST = "2026-11-01"
LAST = "2026-11-20"


class SnapshotConnection:
    def __init__(self):
        self.revision = 2
        self.snapshot = "100:100:"

    def execute(self, statement, params):
        assert "pg_current_snapshot()" in statement
        assert params == ("FARMA",)
        return self

    def fetchone(self):
        return {
            "versao": self.revision,
            "execucao": f"rev-{self.revision}",
            "papel": "nf_ds_farma_read",
            "boot": "boot",
            "snapshot": self.snapshot,
        }


@pytest.fixture
def sales_reader(monkeypatch):
    reader = Reader("synthetic", "homologacao", "FARMA")
    conn = SnapshotConnection()

    @contextmanager
    def readonly_connection(*, readonly):
        assert readonly is True
        yield conn

    monkeypatch.setattr(reader, "connect", readonly_connection)
    return reader, conn


def sales(reader, fields, first=FIRST, last=LAST):
    return reader.query("BI_Vendas", fields, first, last, [], {})


def test_sales_page_shares_read_and_uses_the_requested_columns_and_period(
    sales_reader, monkeypatch
):
    reader, conn = sales_reader
    calls = []

    def load(connection, params):
        assert connection is conn
        calls.append((params["inicio"], params["fim"], conn.revision, conn.snapshot))
        if params["inicio"] > date(2026, 11, 3):
            return []
        return [
            {
                "data": date(2026, 11, 3),
                "faturamento": Decimal("84.10") * conn.revision,
                "pedidos": 2,
                "unidades_vendidas": None,
            }
        ]

    monkeypatch.setattr(reader.sales_periods, "load", load)
    projections = [["faturamento"], ["pedidos"], ["data", "faturamento"]] * 2
    start = Barrier(len(projections))

    def chart(fields):
        start.wait(timeout=5)
        return sales(reader, fields)

    with ThreadPoolExecutor(max_workers=len(projections)) as pool:
        results = list(pool.map(chart, projections))

    assert len(calls) == 1
    assert [r["fields"] for r in results] == projections
    assert [r["rows"] for r in results] == [
        [["168.20"]],
        [[2]],
        [["2026-11-03", "168.20"]],
    ] * 2
    assert all(r["complete"] and r["version"] == 2 for r in results)
    with pytest.raises(StorageError, match="DS_BI_VENDAS_INCOMPLETA"):
        sales(reader, ["unidades_vendidas"])
    assert len(calls) == 1

    conn.revision = 3
    assert sales(reader, ["faturamento"])["rows"] == [["252.30"]]
    conn.snapshot = "101:101:"
    assert sales(reader, ["faturamento"])["version"] == 3
    assert sales(reader, ["faturamento"], "2026-11-04")["rows"] == []
    assert len(calls) == 4


def test_failed_sales_read_releases_waiter_and_can_be_retried(
    sales_reader, monkeypatch
):
    reader, _ = sales_reader
    started, waiting = Event(), Event()
    original_future = products_reader.Future
    attempts = 0

    class ObservedFuture(original_future):
        def result(self, timeout=None):
            waiting.set()
            return super().result(timeout)

    def load(conn, params):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            started.set()
            assert waiting.wait(5)
            raise QueryCanceled("synthetic statement timeout")
        return [{"pedidos": 2}]

    monkeypatch.setattr(products_reader, "Future", ObservedFuture)
    monkeypatch.setattr(reader.sales_periods, "load", load)
    with ThreadPoolExecutor(max_workers=2) as pool:
        leader = pool.submit(sales, reader, ["pedidos"])
        assert started.wait(5)
        follower = pool.submit(sales, reader, ["pedidos"])
        for request in (leader, follower):
            with pytest.raises(QueryCanceled):
                request.result(timeout=5)

    assert attempts == 1
    assert sales(reader, ["pedidos"])["rows"] == [[2]]
    assert attempts == 2
