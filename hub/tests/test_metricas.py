"""Vendas FARMA depende de uma revisão READY e de valores exatos."""

from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from nexoflow_hub import metricas

REVISION = UUID("e28b3606-c8b1-4840-86d2-08c16d6fab89")
DAY = date(2026, 11, 1)


@pytest.fixture
def source(monkeypatch):
    data = {
        "ready": {"revisao": REVISION, "versao": 14},
        "rows": [],
        "statements": [],
        "papel": metricas.ROLE,
    }

    class DB:
        @contextmanager
        def cursor(self, **_kwargs):
            yield self

        def execute(self, sql, params=None):
            data["statements"].append((sql.strip(), params))
            return self

        def fetchone(self):
            if "current_database" in data["statements"][-1][0]:
                return {"banco": metricas.DATABASE, "papel": data["papel"]}
            return data["ready"]

        def fetchall(self):
            return data["rows"]

    @contextmanager
    def connect(*_args, **_kwargs):
        yield DB()

    monkeypatch.setattr(metricas.psycopg, "connect", connect)
    return data


def test_ready_sales_and_empty_period(source):
    empty = metricas.read_sales("", DAY, DAY, REVISION)
    assert empty.totais.model_dump() == {
        "pedidos": 0,
        "produtos_centavos": 0,
        "frete_centavos": 0,
        "faturamento_centavos": 0,
    }
    assert empty.dias == []
    assert empty.revisao == REVISION
    assert (
        source["statements"][0][0]
        == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
    )
    assert source["statements"][-1][1] == (DAY, DAY, 367)
    source["rows"].append(
        {
            "data": DAY,
            "pedidos": Decimal("2"),
            "faturamento_produtos": Decimal("996.42"),
            "faturamento_frete": Decimal("12.30"),
            "faturamento_total": Decimal("1008.72"),
        }
    )
    match = metricas.read_sales("", DAY, DAY)
    assert match.totais.faturamento_centavos == 100872
    assert match.dias[0].produtos_centavos == 99642


def test_products_keep_source_totals_separate_from_limited_ranking(source):
    source["rows"] = [{
        "codigo": "510", "nome": "Produto teste", "unidades": Decimal("2.500"),
        "receita": Decimal("10.20"), "produtos_com_codigo": 54, "itens_sem_codigo": 7,
        "itens_incompletos": 1, "total_unidades": Decimal("91.500"), "total_receita": Decimal("146.20"),
    }]
    report = metricas.read_products("", DAY, DAY, REVISION)
    assert report.ranking[0].receita_centavos == 1020
    assert report.ranking[0].unidades == Decimal("2.5")
    assert report.unidades == Decimal("91.5")
    assert report.receita_centavos == 14620
    assert report.produtos_com_codigo == 54
    assert report.itens_sem_codigo == 7
    assert report.itens_incompletos == 1
    assert source["statements"][-1][1] == (DAY, DAY, 50)


def test_ads_calculates_ratios_on_brl_facts_and_preserves_unknown(source):
    row = {
        "conta_id": "123", "moeda": "BRL", "fuso": "America/Belem",
        "politica_atribuicao": "teste", "anuncio_id": "456", "campanha_nome": "Campanha teste",
        "investimento_original": Decimal("251.02"), "conversas": Decimal("70"),
        "fatos_sem_metrica_meta": 1, "pedidos": Decimal(3), "receita": Decimal("461.20"),
        "primeiros": Decimal(2), "parciais": 1,
    }
    source["rows"] = [row]
    report = metricas.read_ads("", DAY, DAY, REVISION)
    total = report.totais[0]
    assert (total.cpa_centavos, total.roas, total.cac_centavos) == (8367, Decimal("1.84"), 12551)
    assert total.conversas == Decimal("70") and total.conversas_parciais
    assert total.cobertura_parcial
    assert report.anuncios[0].anuncio == "456"

    source["rows"] = [dict(row, pedidos=None, receita=None, primeiros=None, parciais=None)]
    pending = metricas.read_ads("", DAY, DAY).totais[0]
    assert pending.cpa_centavos is pending.roas is pending.cac_centavos is None
    assert pending.cobertura_parcial
    source["rows"] = [dict(row, pedidos=Decimal(0), receita=Decimal(0), primeiros=Decimal(0), parciais=0)]
    empty = metricas.read_ads("", DAY, DAY).totais[0]
    assert empty.pedidos == empty.receita_centavos == 0
    assert empty.cpa_centavos is empty.cac_centavos is None
    assert empty.roas == 0 and not empty.cobertura_parcial


def test_ad_order_search_preserves_partial_evidence_and_accepts_typed_identifier(source):
    source["rows"] = [
        {"anuncio": "123", "campanha": "Campanha teste", "presente": True,
         "completa": False, "conversa": DAY, "emissao": DAY, "vinculo": "posterior",
         "receita": Decimal("62.10")},
        {"anuncio": "321", "campanha": "Campanha teste", "presente": False,
         "completa": False, "conversa": None, "emissao": None, "vinculo": None,
         "receita": None},
    ]
    report = metricas.read_ad_orders("", DAY, DAY, "campanha", "900", REVISION)
    assert report.revisao == REVISION and report.encontrado
    assert report.cobertura == "parcial"
    assert [row.receita_centavos for row in report.pedidos] == [6210]
    assert source["statements"][-1][1] == (DAY, DAY, "campanha", "900")


def test_wrong_revision_absent_ready_wrong_role_and_missing_amount(source):
    with pytest.raises(metricas.RevisionChanged):
        metricas.read_sales("", DAY, DAY, UUID(int=0))
    assert "ds_bi_vendas" not in source["statements"][-1][0]
    source["ready"] = None
    with pytest.raises(metricas.SourceUnavailable):
        metricas.read_sales("", DAY, DAY)
    source["ready"] = {"revisao": REVISION, "versao": 14}
    source["papel"] = "nf_ds_farma_publish"
    with pytest.raises(metricas.SourceUnavailable):
        metricas.read_sales("", DAY, DAY)
    source["papel"] = metricas.ROLE
    source["rows"].append(
        {
            "data": DAY,
            "pedidos": Decimal("1"),
            "faturamento_produtos": None,
            "faturamento_frete": Decimal("0"),
            "faturamento_total": Decimal("11.00"),
        }
    )
    with pytest.raises(metricas.SourceUnavailable):
        metricas.read_sales("", DAY, DAY)
