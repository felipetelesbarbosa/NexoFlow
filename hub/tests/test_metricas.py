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
