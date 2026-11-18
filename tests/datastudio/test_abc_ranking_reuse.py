"""As duas projeções da página Curva ABC compartilham apenas o cálculo validado."""

from concurrent.futures import Future, ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier, Event, Lock

import pytest
from psycopg.types.json import Jsonb

from ds_backend.contract import StorageError, record_key
from integrations.datastudio import abc_reader
from integrations.datastudio.reader import Reader
from tests.datastudio.test_contract import row
from tests.datastudio.test_ds_database import DSN, begin, finish
from tests.datastudio.test_ds_database import store as store

pytestmark = pytest.mark.skipif(not DSN, reason="PostgreSQL descartável")

DAY = "2026-11-09"
RANKING = [
    "classe_abc",
    "produto_codigo",
    "produto_nome",
    "unidades",
    "receita_produtos",
    "participacao_receita",
    "participacao_acumulada",
]
SELECTOR = ["classe_abc", "unidades"]


def seed_rank(store):
    finish(store, begin(store))
    items = [
        row(
            "BI_Itens",
            item_chave=f"i{i}",
            venda_chave="v",
            data=DAY,
            produto_codigo=f"{i % 151:04d}",
            produto_nome=f"Produto {i % 151}",
            categoria="Genérica",
            quantidade="1",
            receita_item="0.10",
            sku_informado="1",
        )
        for i in range(254)
    ]
    sales = [
        row(
            "BI_Clientes_Vendas",
            venda_chave="v",
            data=DAY,
            faturamento_produtos="25.40",
            frete="3.00",
            faturamento="28.40",
        )
    ]
    with (
        store.connect() as conn,
        conn.cursor().copy(
            "COPY farma.nf_atuais(tabela,chave,registro) FROM STDIN"
        ) as copy,
    ):
        for table, rows in (("BI_Itens", items), ("BI_Clientes_Vendas", sales)):
            for r in rows:
                copy.write_row((table, record_key(table, r), Jsonb(r)))


def test_one_ranking_then_two_components(store, monkeypatch):
    seed_rank(store)
    calls = 0
    original = abc_reader.aggregates
    lock = Lock()

    def tracked(*args, **kw):
        nonlocal calls
        with lock:
            calls += 1
        return original(*args, **kw)

    monkeypatch.setattr(abc_reader, "aggregates", tracked)

    def single(reader, fields):
        return reader.abc("abc", fields, DAY, DAY)

    # Medida de controle independente dos caches do leitor da página.
    alone = single(Reader(DSN, "homologacao", "FARMA"), RANKING)
    assert calls == 1 and len(alone["rows"]) == 151
    assert sum(Decimal(r[3]) for r in alone["rows"]) == 254
    assert sum(Decimal(r[4]) for r in alone["rows"]) == Decimal("25.40")
    assert all(r[5] is not None and r[6] is not None for r in alone["rows"])
    calls = 0
    reader = Reader(DSN, "homologacao", "FARMA")
    barrier = Barrier(2)

    def component(fields):
        barrier.wait(10)
        return single(reader, fields)

    with ThreadPoolExecutor(max_workers=2) as pool:
        ranking, selector = pool.map(component, [RANKING, SELECTOR])
    assert ranking == alone
    assert selector["fields"] == SELECTOR
    assert selector["rows"] == [[r[0], r[3]] for r in alone["rows"]]
    assert selector["complete"] and ranking["version"] == selector["version"]
    assert calls == 1

    # Nenhum resultado de ranking é elegível para outra data ou para o modo de pares.
    assert reader.abc("abc", SELECTOR, "2026-11-10", "2026-11-10")["rows"] == []
    pairs = reader.pairs(["pedidos_juntos"], DAY, DAY, 1)
    assert pairs["scope"]["universe_pairs"] == 151 * 150 // 2


def test_wide_ranking_failure_does_not_poison_narrow_follower_or_retain_large_result(
    store, monkeypatch
):
    seed_rank(store)
    with store.connect() as conn:
        conn.execute(
            "UPDATE farma.nf_atuais SET registro=registro || "
            "jsonb_build_object('produto_nome',repeat('界',30000)) WHERE tabela='BI_Itens'"
        )
    reader = Reader(DSN, "homologacao", "FARMA")
    owner, follower = Event(), Event()
    calls = 0
    original = abc_reader.aggregates

    class ObservedFuture(Future):
        def result(self, timeout=None):
            follower.set()
            return super().result(timeout)

    def tracked(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            owner.set()
            assert follower.wait(10)
        return original(*args, **kwargs)

    monkeypatch.setattr("integrations.datastudio.reader.Future", ObservedFuture)
    monkeypatch.setattr(abc_reader, "aggregates", tracked)
    with ThreadPoolExecutor(max_workers=2) as pool:
        wide = pool.submit(reader.abc, "abc", RANKING, DAY, DAY)
        assert owner.wait(10)
        narrow = pool.submit(reader.abc, "abc", SELECTOR, DAY, DAY)
        with pytest.raises(StorageError, match="DS_RESPOSTA_EXCEDE_LIMITE_USE_RESUMO"):
            wide.result(10)
        result = narrow.result(10)
    assert calls == 1 and result["complete"] and len(result["rows"]) == 151
    assert sum(Decimal(r[1]) for r in result["rows"]) == 254
    assert reader.abc("abc", SELECTOR, DAY, DAY) == result
    assert calls == 2


def test_two_fields_fit_individually_when_whole_ranking_exceeds_http_budget(store):
    seed_rank(store)
    reader = Reader(DSN, "homologacao", "FARMA")
    with store.connect() as conn:
        conn.execute(
            "UPDATE farma.nf_atuais SET registro=registro || jsonb_build_object("
            "'produto_nome',repeat('a',27000),'categoria',repeat('b',27000)) "
            "WHERE tabela='BI_Itens'"
        )
    with pytest.raises(StorageError, match="DS_RESPOSTA_EXCEDE_LIMITE_USE_RESUMO"):
        reader.abc("abc", abc_reader.FIELDS["abc"], DAY, DAY)
    for field, char in (("produto_nome", "a"), ("categoria", "b")):
        result = reader.abc("abc", [field], DAY, DAY)
        assert result["complete"] and len(result["rows"]) == 151
        assert all(row == [char * 27000] for row in result["rows"])
    with store.connect() as conn:
        conn.execute(
            "UPDATE controle.nf_publicacoes SET execucao=NULL WHERE segmento='FARMA'"
        )
    with pytest.raises(StorageError, match="DS_SEM_PUBLICACAO_CONFIRMADA"):
        reader.abc("abc", SELECTOR, DAY, DAY)
