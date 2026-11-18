"""Conferência das chamadas dos cartões à mesma linha do resumo ABC."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock

import pytest

from integrations.datastudio import abc_reader
from integrations.datastudio.reader import Reader
from tests.datastudio.test_abc_reader import seed
from tests.datastudio.test_ds_database import DSN
from tests.datastudio.test_ds_database import store as store

pytestmark = pytest.mark.skipif(not DSN, reason="PostgreSQL descartável")

CARDS = [
    ["produtos_classe_a"],
    ["produtos_classe_b"],
    ["produtos_classe_c"],
    ["receita_classe_a"],
    ["receita_classe_b"],
    ["receita_classe_c"],
    [
        "periodo_rotulo",
        "skus_distintos",
        "participacao_top5_receita",
        "faturamento_produtos",
        "produtos_classe_a",
    ],
]


def test_seven_summary_cards_share_only_the_same_complete_snapshot(store, monkeypatch):
    seed(store, 6)
    reader = Reader(DSN, "homologacao", "FARMA")
    day = "2026-11-09"
    with store.connect() as conn:
        conn.execute(
            "UPDATE farma.nf_atuais SET registro=registro||jsonb_build_object('data', %s::text) "
            "WHERE tabela IN ('BI_Itens', 'BI_Clientes_Vendas')",
            (day,),
        )
    fields = list(dict.fromkeys(name for fields in CARDS for name in fields))
    reference = Reader(DSN, "homologacao", "FARMA").abc("resumo", fields, day, day)
    expected = dict(zip(fields, reference["rows"][0], strict=True))
    original = abc_reader.aggregates
    barrier, lock = Barrier(7), Lock()
    calls = 0

    def tracked(*args, **kwargs):
        nonlocal calls
        with lock:
            calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(abc_reader, "aggregates", tracked)

    def card(fields):
        barrier.wait(timeout=10)
        return reader.abc("resumo", fields, day, day)

    with ThreadPoolExecutor(max_workers=7) as pool:
        results = list(pool.map(card, CARDS))
    for projection, response in zip(CARDS, results, strict=True):
        assert response["fields"] == projection
        assert response["rows"] == [[expected[name] for name in projection]]
    assert all(r["complete"] and r["version"] == reference["version"] for r in results)
    assert calls == 1
    assert (
        reader.abc("resumo", fields[::-1], day, day)["rows"][0]
        == reference["rows"][0][::-1]
    )
    assert calls == 1
    empty = reader.abc("resumo", ["skus_distintos"], "2026-11-10", "2026-11-10")
    assert empty["rows"] == [[0]] and calls == 2
    # Até uma manutenção de visão ou escrita na mesma versão deve invalidar o snapshot.
    with store.connect() as conn:
        conn.execute(
            "UPDATE farma.nf_atuais SET registro=registro||jsonb_build_object('produto_codigo','novo') "
            "WHERE tabela='BI_Itens'"
        )
    assert reader.abc("resumo", ["skus_distintos"], day, day)["rows"] == [[1]]
    assert calls == 3


@pytest.mark.parametrize("failure", ["timeout", "incomplete", "wait_timeout"])
@pytest.mark.parametrize(
    "mode,field", [("resumo", "skus_distintos"), ("abc", "produto_codigo")]
)
def test_failed_abc_releases_waiters_without_caching_a_partial_row(
    store, monkeypatch, failure, mode, field
):
    from concurrent.futures import Future

    from psycopg.errors import QueryCanceled

    from ds_backend.contract import StorageError

    seed(store, 6)
    reader = Reader(DSN, "homologacao", "FARMA")
    owner, waiting = Event(), Event()

    class ObservedFuture(Future):
        def result(self, timeout=None):
            assert 0 < timeout <= 45
            waiting.set()
            if failure == "wait_timeout":
                raise TimeoutError
            return super().result(timeout)

    monkeypatch.setattr("integrations.datastudio.reader.Future", ObservedFuture)
    original = abc_reader.aggregates
    calls = 0

    def first(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            owner.set()
            assert waiting.wait(10)
            if failure == "timeout":
                raise QueryCanceled("synthetic timeout")
            if failure == "incomplete":
                raise StorageError("DS_ABC_BASE_INCOMPLETA")
        return original(*args, **kwargs)

    monkeypatch.setattr(abc_reader, "aggregates", first)
    args = (mode, [field], "2026-11-01", "2026-11-02")
    expected = [[2]] if mode == "resumo" else [["001"], ["002"]]
    with ThreadPoolExecutor(max_workers=2) as pool:
        leader = pool.submit(reader.abc, *args)
        assert owner.wait(10)
        follower = pool.submit(reader.abc, *args)
        if failure == "wait_timeout":
            with pytest.raises(StorageError, match="DS_CONSULTA_TEMPO_LIMITE"):
                follower.result(10)
            assert leader.result(10)["rows"] == expected
        else:
            error = QueryCanceled if failure == "timeout" else StorageError
            for task in (leader, follower):
                with pytest.raises(error):
                    task.result(10)
    assert calls == 1
    assert reader.abc(*args)["rows"] == expected
    assert calls == (1 if failure == "wait_timeout" else 2)


def test_chart_requests_wait_for_reader_connections_instead_of_exhausting_role(
    store, monkeypatch
):
    from contextlib import contextmanager
    from time import sleep

    from psycopg.errors import TooManyConnections

    from integrations.datastudio.store import Store

    seed(store, 6)
    original = Store.connect
    lock = Lock()
    barrier = Barrier(7)
    in_use = 0

    @contextmanager
    def constrained(self, **options):
        nonlocal in_use
        with lock:
            if in_use == 4:
                raise TooManyConnections()
            in_use += 1
        try:
            # Emula as duas conexões usadas por outros processos no mesmo papel.
            sleep(0.10)
            with original(self, **options) as conn:
                yield conn
        finally:
            with lock:
                in_use -= 1

    monkeypatch.setattr(Store, "connect", constrained)
    reader = Reader(DSN, "homologacao", "FARMA")

    def card(fields):
        barrier.wait(timeout=10)
        return reader.abc("resumo", fields, "2026-11-09", "2026-11-09")

    with ThreadPoolExecutor(max_workers=7) as pool:
        results = list(pool.map(card, CARDS))

    assert all(r["complete"] for r in results)
    assert [r["fields"] for r in results] == CARDS
    assert in_use == 0
