"""Conferência da página de produtos no PostgreSQL descartável."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier, Lock

import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from ds_backend.contract import StorageError, record_key
from integrations.datastudio.admin import grants
from integrations.datastudio.api import create_app
from integrations.datastudio.products_reader import ProductPeriods
from integrations.datastudio.reader import Reader
from tests.datastudio.test_contract import row
from tests.datastudio.test_ds_database import DSN, begin, finish
from tests.datastudio.test_ds_database import store as store

pytestmark = pytest.mark.skipif(not DSN, reason="PostgreSQL descartável")

START = "2026-11-08"
END = "2026-11-09"
RANK_FIELDS = [
    "produto_codigo",
    "produto_nome",
    "quantidade",
    "receita_item",
    "registros",
    "participacao_acumulada",
]
SUMMARY_FIELDS = [
    "produtos_distintos_periodo",
    "quantidade",
    "receita_item",
    "registros",
]


@pytest.fixture
def catalog(store):
    finish(store, begin(store))
    # Mesmo SKU com nome novo, e mesmo nome aplicado a SKUs distintos.
    # O nome exibido tem de vir de MAX no filtro corrente, e o último dia
    # fora do recorte não deve mudar o nome, os totais nem a participação.
    example = [
        (START, "001", "Zeta", "2", "7.00", 1),
        (END, "001", "Alfa", "1", "3.01", 1),
        (END, "002", "Alfa", "3", "9.01", 1),
        (END, "003", "Terceiro", "3", "9.01", 1),
        (END, "004", "Quarto", "5", "0.05", 1),
        (START, "005", "Quinto", "4.25", "0.02", 1),
        (END, "1", "Sem zeros à esquerda", "3", "0.04", 1),
        (START, None, "Ausente A", "1.5", "0.01", 0),
        (END, None, "Ausente B", "1", "0.02", 0),
        (END, "NA", "Zero", "1", "0.00", 0),
        ("2026-11-10", "001", "ZZZ fora do período", "1000", "2000.00", 1),
    ]
    with store.connect() as conn:
        with conn.cursor().copy(
            "COPY farma.nf_atuais(tabela,chave,registro) FROM STDIN"
        ) as copy:
            for i, (day, sku, name, quantity, revenue, known_sku) in enumerate(example):
                item = row(
                    "BI_Itens",
                    item_chave=f"item-{i}",
                    venda_chave=f"venda-{i}",
                    data=day,
                    produto_codigo=sku,
                    produto_nome=name,
                    quantidade=quantity,
                    receita_item=revenue,
                    sku_informado=known_sku,
                )
                copy.write_row(("BI_Itens", record_key("BI_Itens", item), Jsonb(item)))
    return Reader(DSN, "homologacao", "FARMA")


def projected(reader, mode, fields, *, start=START, end=END, names=None):
    result = reader.products(mode, fields, start, end, names=names)
    assert result["fields"] == fields
    assert result["complete"] is True
    assert result["version"] == 1
    return [dict(zip(fields, values, strict=True)) for values in result["rows"]]


def assert_ratio(value, numerator, denominator):
    difference = Decimal(str(value)) - Decimal(numerator) / Decimal(denominator)
    assert abs(difference) < Decimal("0.000000000001")


def test_ranking_and_tops_preserve_sku_grain_order_and_period_denominator(catalog):
    ranking = projected(catalog, "ranking", RANK_FIELDS)
    revenue = projected(catalog, "receita", RANK_FIELDS)
    units = projected(catalog, "unidades", RANK_FIELDS)
    assert len(ranking) == 8
    assert revenue == ranking[:5]
    assert [r["produto_codigo"] for r in revenue] == ["001", "002", "003", "004", "1"]
    assert [r["produto_codigo"] for r in units] == ["004", "005", "001", "002", "003"]
    assert revenue[0]["produto_nome"] == "Zeta"
    assert Decimal(revenue[0]["receita_item"]) == Decimal("10.01")
    assert Decimal(revenue[0]["registros"]) == 2
    assert Decimal(units[1]["quantidade"]) == Decimal("4.25")
    missing = [r for r in ranking if r["produto_codigo"] in (None, "")]
    assert len(missing) == 1
    assert Decimal(missing[0]["registros"]) == 2
    assert Decimal(missing[0]["receita_item"]) == Decimal("0.03")
    # Os dois SKUs empatados seguem o desempate por código. Cada linha
    # acumula apenas os anteriores, incluindo-os no denominador do período.
    cumulative_cents = [1001, 1902, 2803, 2808, 2812]
    for product, cents in zip(revenue, cumulative_cents, strict=True):
        assert_ratio(product["participacao_acumulada"], cents, 2817)
    assert Decimal(ranking[-1]["participacao_acumulada"]) == 1

    (summary,) = projected(catalog, "resumo", SUMMARY_FIELDS)
    assert [Decimal(summary[f]) for f in SUMMARY_FIELDS] == [
        6,
        Decimal("24.75"),
        Decimal("28.17"),
        10,
    ]


def test_name_filter_precedes_grouping_distinct_count_and_shares(catalog):
    names = projected(catalog, "nomes", ["produto_nome", "registros"])
    expected_counts = {
        "Zeta": 1,
        "Alfa": 2,
        "Terceiro": 1,
        "Quarto": 1,
        "Quinto": 1,
        "Sem zeros à esquerda": 1,
        "Ausente A": 1,
        "Ausente B": 1,
        "Zero": 1,
    }
    assert len(names) == len(expected_counts)
    assert {
        r["produto_nome"]: Decimal(r["registros"]) for r in names
    } == expected_counts

    ranked = projected(catalog, "ranking", RANK_FIELDS, names=["Alfa"])
    assert [r["produto_codigo"] for r in ranked] == ["002", "001"]
    assert [r["produto_nome"] for r in ranked] == ["Alfa", "Alfa"]
    assert [Decimal(r["receita_item"]) for r in ranked] == [
        Decimal("9.01"),
        Decimal("3.01"),
    ]
    assert_ratio(ranked[0]["participacao_acumulada"], 901, 1202)
    assert Decimal(ranked[1]["participacao_acumulada"]) == 1

    # Uma seleção de duas grafias do mesmo SKU não pode contar o SKU duas vezes.
    (summary,) = projected(catalog, "resumo", SUMMARY_FIELDS, names=["Alfa", "Zeta"])
    assert [Decimal(summary[f]) for f in SUMMARY_FIELDS] == [2, 6, Decimal("19.02"), 3]
    (single,) = projected(catalog, "receita", RANK_FIELDS, names=["Zeta"])
    assert Decimal(single["participacao_acumulada"]) == 1
    (zero,) = projected(catalog, "receita", RANK_FIELDS, names=["Zero"])
    assert Decimal(zero["receita_item"]) == 0 and zero["participacao_acumulada"] is None


def test_empty_period_or_selection_has_one_zero_summary_and_no_detail(catalog):
    for options in (
        {"start": "2026-11-11", "end": "2026-11-11"},
        {"names": ["Nome inexistente"]},
        {"names": []},
    ):
        (summary,) = projected(catalog, "resumo", SUMMARY_FIELDS, **options)
        assert all(Decimal(summary[f]) == 0 for f in SUMMARY_FIELDS)
        for mode in ("ranking", "receita", "unidades"):
            assert projected(catalog, mode, ["produto_codigo"], **options) == []
        assert (
            projected(catalog, "nomes", ["produto_nome", "registros"], **options) == []
        )


def test_60003_skus_return_bounded_tops_and_summary_without_truncating_detail(store):
    finish(store, begin(store))
    with store.connect() as conn:
        conn.execute(
            """INSERT INTO farma.nf_atuais(tabela,chave,registro)
               SELECT 'BI_Itens','i'||n,jsonb_build_object(
                   'item_chave','i'||n,'venda_chave','s'||n,'data',%s::text,
                   'produto_codigo',lpad(n::text,6,'0'),'produto_nome','Nome compartilhado',
                   'quantidade','1','receita_item','0.10','sku_informado','1')
                 FROM generate_series(1,60003) AS serie(n)""",
            (END,),
        )
    reader = Reader(DSN, "homologacao", "FARMA")
    (summary,) = projected(reader, "resumo", SUMMARY_FIELDS)
    assert [Decimal(summary[f]) for f in SUMMARY_FIELDS] == [
        60003,
        60003,
        Decimal("6000.30"),
        60003,
    ]
    for mode in ("receita", "unidades"):
        top = projected(reader, mode, ["produto_codigo", "participacao_acumulada"])
        assert [r["produto_codigo"] for r in top] == [
            "000001",
            "000002",
            "000003",
            "000004",
            "000005",
        ]
        assert_ratio(top[-1]["participacao_acumulada"], 5, 60003)
    with pytest.raises(StorageError, match="EXCEDE_LIMITE"):
        reader.products("ranking", ["produto_codigo"], START, END)
    (name,) = projected(reader, "nomes", ["produto_nome", "registros"])
    assert (
        name["produto_nome"] == "Nome compartilhado"
        and Decimal(name["registros"]) == 60003
    )


def test_seven_components_share_scan_only_with_the_same_visible_rows(
    catalog, store, monkeypatch
):
    charts = [
        ("resumo", ["produtos_distintos_periodo"]),
        ("resumo", ["quantidade"]),
        ("resumo", ["receita_item"]),
        ("ranking", ["produto_codigo", "receita_item"]),
        ("receita", ["produto_codigo", "participacao_acumulada"]),
        ("unidades", ["produto_codigo", "quantidade"]),
        ("nomes", ["produto_nome", "registros"]),
    ]
    barrier, lock = Barrier(len(charts)), Lock()
    scans = 0
    load = ProductPeriods.load

    def counted(conn, params):
        nonlocal scans
        with lock:
            scans += 1
        return load(conn, params)

    monkeypatch.setattr(ProductPeriods, "load", staticmethod(counted))

    def render(chart):
        barrier.wait(timeout=10)
        return projected(catalog, *chart)

    with ThreadPoolExecutor(max_workers=len(charts)) as pool:
        cards, quantity, revenue, ranking, by_revenue, by_quantity, names = pool.map(
            render, charts
        )
    assert Decimal(cards[0]["produtos_distintos_periodo"]) == 6
    assert Decimal(quantity[0]["quantidade"]) == Decimal("24.75")
    assert Decimal(revenue[0]["receita_item"]) == Decimal("28.17")
    assert tuple(map(len, [ranking, by_revenue, by_quantity, names])) == (8, 5, 5, 9)
    assert scans == 1
    assert projected(
        catalog, "nomes", ["produto_nome"], names=["Zeta", "Alfa"]
    ) == projected(catalog, "nomes", ["produto_nome"], names=["Alfa", "Zeta", "Alfa"])
    assert scans == 2
    with store.connect() as conn:
        conn.execute(
            "UPDATE farma.nf_atuais SET registro=registro || jsonb_build_object('produto_nome','Nova grafia') "
            "WHERE tabela='BI_Itens' AND registro->>'produto_nome'='Zeta'"
        )
    assert projected(catalog, "nomes", ["produto_nome"], names=["Alfa", "Zeta"]) == [
        {"produto_nome": "Alfa"}
    ]
    assert scans == 3


def test_failed_scan_is_retried_and_respects_public_byte_limit(
    catalog, store, monkeypatch
):
    from integrations.datastudio import reader

    monkeypatch.setattr(reader, "MAX_RESULT_BYTES", 1300)
    with store.connect() as conn:
        conn.execute(
            "UPDATE farma.nf_atuais SET registro=registro || jsonb_build_object('quantidade', '-1') "
            "WHERE tabela='BI_Itens' AND registro->>'produto_nome'='Zeta'"
        )
    with pytest.raises(StorageError, match="DS_PRODUTOS_BASE_INVALIDA"):
        projected(catalog, "resumo", ["receita_item"])
    assert catalog.product_periods.last is None and not catalog.product_periods.pending
    with store.connect() as conn:
        conn.execute(
            "UPDATE farma.nf_atuais SET registro=registro || "
            "jsonb_build_object('quantidade','2','produto_nome',repeat('ç',3000)) "
            "WHERE tabela='BI_Itens' AND registro->>'produto_nome'='Zeta'"
        )
    assert len(projected(catalog, "ranking", ["produto_codigo", "periodo_inicio"])) == 8
    assert len(projected(catalog, "nomes", ["registros"])) == 9
    assert len(projected(catalog, "receita", ["produto_codigo"])) == 5
    assert len(projected(catalog, "unidades", ["posicao_unidades_top5"])) == 5
    with pytest.raises(StorageError, match="DS_RESPOSTA_EXCEDE_LIMITE"):
        projected(catalog, "ranking", ["produto_nome"])
    with pytest.raises(StorageError, match="DS_RESPOSTA_EXCEDE_LIMITE"):
        projected(catalog, "receita", ["produto_nome"])
    # Nem o perfil excessivo nem a falha anterior contaminam os cartões.
    assert projected(catalog, "resumo", ["receita_item"]) == [{"receita_item": "28.17"}]


def test_read_api_validates_scope_ready_and_fails_closed_on_duplicate_items(
    catalog, store
):
    with store.connect() as conn:
        grants(conn, "FARMA")
    reader = Reader(
        DSN + "&options=-c%20role%3Dnf_ds_farma_read",
        "homologacao",
        "FARMA",
        require_dedicated_role=True,
    )
    token = "synthetic-only-token-not-used-elsewhere-12345"
    client = TestClient(create_app(reader, token, reader=True))
    url = "/v1/produtos"
    headers = {"Authorization": "Bearer " + token}
    body = dict(
        mode="resumo", fields=["receita_item"], start=START, end=END, names=None
    )
    assert client.post(url, json=body).status_code == 401
    assert (
        TestClient(create_app(store, token))
        .post(url, json=body, headers=headers)
        .status_code
        == 404
    )
    success = client.post(url, json=body, headers=headers)
    assert success.status_code == 200
    assert success.json()["version"] == 1 and success.json()["rows"] == [["28.17"]]
    for change, error in [
        ({"fields": ["cliente_id"]}, "DS_CAMPOS_NAO_AUTORIZADOS"),
        ({"names": ["x"] * 101}, "DS_FILTRO_INVALIDO"),
        ({"start": "20261108"}, "DS_PERIODO_INVALIDO"),
        ({"segment": "PET"}, "DS_PARAMETROS_INVALIDOS"),
    ]:
        rejected = client.post(url, json={**body, **change}, headers=headers)
        assert rejected.status_code == 409 and rejected.json() == {"error": error}
    with pytest.raises(StorageError, match="DS_TABELA_NAO_AUTORIZADA"):
        Reader(DSN, "homologacao", "PET").products(**body)
    with store.connect() as conn:
        conn.execute(
            "UPDATE farma.nf_atuais SET registro=registro || jsonb_build_object('item_chave',' item-0 ') "
            "WHERE tabela='BI_Itens' AND registro->>'item_chave'='item-1'"
        )
    rejected = client.post(url, json=body, headers=headers)
    assert rejected.status_code == 409 and rejected.json() == {
        "error": "DS_PRODUTOS_BASE_INVALIDA"
    }


def test_ready_required_and_visible_pointer_change_is_not_reused(store):
    reader = Reader(DSN, "homologacao", "FARMA")
    args = "resumo", ["registros"], START, END
    with pytest.raises(StorageError, match="DS_SEM_PUBLICACAO_CONFIRMADA"):
        reader.products(*args)
    finish(store, begin(store))
    assert reader.products(*args)["version"] == 1
    writing = begin(store)
    assert reader.products(*args)["version"] == 1
    finish(store, writing)
    assert reader.products(*args)["version"] == 2
