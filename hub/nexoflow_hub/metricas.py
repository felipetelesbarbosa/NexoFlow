"""Leitura da revisão de vendas FARMA publicada para o Looker Studio."""

from datetime import date
from decimal import Decimal
from uuid import UUID

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
from pydantic import BaseModel

DATABASE = "nexoflow_datastudio"
ROLE = "nf_metricas_farma_leitor"
MAX_PERIOD_DAYS = 366
MAX_SAFE_INTEGER = 2**53 - 1


class SourceUnavailable(ValueError):
    pass


class RevisionChanged(ValueError):
    pass


class SalesTotals(BaseModel):
    pedidos: int = 0
    produtos_centavos: int = 0
    frete_centavos: int = 0
    faturamento_centavos: int = 0


class SalesDay(SalesTotals):
    data: date


class SalesReport(BaseModel):
    segmento: str = "FARMA"
    fonte: str = "data_studio_producao"
    revisao: UUID
    versao: int
    inicio: date
    fim: date
    totais: SalesTotals
    dias: list[SalesDay]


def validate_source(dsn: str) -> None:
    try:
        info = conninfo_to_dict(dsn)
    except psycopg.ProgrammingError:
        raise ValueError("DSN_METRICAS_INVALIDO") from None
    if info.get("dbname") != DATABASE or info.get("user") != ROLE:
        raise ValueError("DESTINO_METRICAS_FARMA_INVALIDO")


def integer(value: Decimal | None, scale: int = 1) -> int:
    if value is None or not value.is_finite():
        raise SourceUnavailable
    scaled = value * scale
    if abs(scaled) > MAX_SAFE_INTEGER or scaled != scaled.to_integral_value():
        raise SourceUnavailable
    return int(scaled)


def read_sales(
    dsn: str, start: date, end: date, expected: UUID | None = None
) -> SalesReport:
    with (
        psycopg.connect(dsn, connect_timeout=4) as connection,
        connection.cursor(row_factory=dict_row) as db,
    ):
        db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        db.execute("SET LOCAL statement_timeout = '45s'")
        db.execute("SET LOCAL lock_timeout = '1500ms'")
        db.execute("SET LOCAL enable_nestloop = off")
        database = db.execute(
            "SELECT current_database() AS banco, current_user AS papel"
        ).fetchone()
        if database != {"banco": DATABASE, "papel": ROLE}:
            raise SourceUnavailable
        revision = db.execute(
            "SELECT revisao, versao FROM farma.ds_metricas_publicacao"
        ).fetchone()
        if not revision:
            raise SourceUnavailable
        if expected is not None and revision["revisao"] != expected:
            raise RevisionChanged
        rows = db.execute(
            """SELECT data, pedidos, faturamento_produtos, faturamento_frete, faturamento_total
               FROM farma.ds_bi_vendas WHERE data BETWEEN %s AND %s ORDER BY data
               LIMIT %s""",
            (start, end, MAX_PERIOD_DAYS + 1),
        ).fetchall()

    if len(rows) > MAX_PERIOD_DAYS:
        raise SourceUnavailable
    days: list[SalesDay] = []
    for row in rows:
        day = SalesDay(
            data=row["data"],
            pedidos=integer(row["pedidos"]),
            produtos_centavos=integer(row["faturamento_produtos"], 100),
            frete_centavos=integer(row["faturamento_frete"], 100),
            faturamento_centavos=integer(row["faturamento_total"], 100),
        )
        if (
            day.pedidos < 0
            or day.produtos_centavos + day.frete_centavos != day.faturamento_centavos
            or (days and days[-1].data == day.data)
        ):
            raise SourceUnavailable
        days.append(day)
    totals = SalesTotals(
        pedidos=sum(day.pedidos for day in days),
        produtos_centavos=sum(day.produtos_centavos for day in days),
        frete_centavos=sum(day.frete_centavos for day in days),
        faturamento_centavos=sum(day.faturamento_centavos for day in days),
    )
    if any(abs(value) > MAX_SAFE_INTEGER for value in totals.model_dump().values()):
        raise SourceUnavailable
    return SalesReport(
        revisao=revision["revisao"],
        versao=revision["versao"],
        inicio=start,
        fim=end,
        totais=totals,
        dias=days,
    )
