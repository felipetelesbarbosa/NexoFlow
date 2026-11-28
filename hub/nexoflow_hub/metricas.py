"""Leitura da revisão de vendas FARMA publicada para o Looker Studio."""

from contextlib import contextmanager
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal
from uuid import UUID

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
from pydantic import BaseModel

DATABASE = "nexoflow_datastudio"
ROLE = "nf_metricas_farma_leitor"
MAX_PERIOD_DAYS = 366
MAX_SAFE_INTEGER = 2**53 - 1
PRODUCT_LIMIT = 50


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


class ProductRow(BaseModel):
    codigo: str | None
    nome: str
    unidades: Decimal
    receita_centavos: int


class ProductsReport(BaseModel):
    segmento: str = "FARMA"
    fonte: str = "data_studio_producao"
    revisao: UUID
    versao: int
    inicio: date
    fim: date
    produtos_com_codigo: int = 0
    itens_sem_codigo: int = 0
    itens_incompletos: int = 0
    unidades: Decimal = Decimal(0)
    receita_centavos: int = 0
    ranking: list[ProductRow]


class AdsRow(BaseModel):
    conta: str
    moeda: str
    fuso: str
    atribuicao: str
    anuncio: str | None
    campanha: str | None
    investimento: Decimal | None
    conversas: Decimal | None
    conversas_parciais: bool
    pedidos: int | None
    receita_centavos: int | None
    primeiras_compras: int | None
    cpa_centavos: int | None
    roas: Decimal | None
    cac_centavos: int | None
    cobertura_parcial: bool


class AdsReport(BaseModel):
    segmento: str = "FARMA"
    fonte: str = "data_studio_producao"
    revisao: UUID
    versao: int
    inicio: date
    fim: date
    totais: list[AdsRow]
    anuncios: list[AdsRow]
    anuncios_limitados: bool


class AdOrder(BaseModel):
    anuncio: str
    campanha: str | None
    conversa: date
    emissao: date
    vinculo: Literal["direto", "posterior", "sem_vinculo_conversa"]
    receita_centavos: int


class AdOrdersReport(BaseModel):
    segmento: str = "FARMA"
    fonte: str = "data_studio_producao"
    revisao: UUID
    versao: int
    inicio: date
    fim: date
    encontrado: bool
    cobertura: Literal["sem_evidencia", "parcial", "completa"]
    limitado: bool
    pedidos: list[AdOrder]


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


@contextmanager
def published_snapshot(dsn: str, expected: UUID | None):
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
        yield db, revision


def read_sales(
    dsn: str, start: date, end: date, expected: UUID | None = None
) -> SalesReport:
    with published_snapshot(dsn, expected) as (db, revision):
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


def read_products(
    dsn: str, start: date, end: date, expected: UUID | None = None
) -> ProductsReport:
    with published_snapshot(dsn, expected) as (db, revision):
        rows = db.execute(
            """WITH itens AS (
                 SELECT nullif(btrim(produto_codigo), '') AS codigo,
                        nullif(btrim(produto_nome), '') AS nome,
                        quantidade, receita_item,
                        coalesce(quantidade > 0 AND receita_item >= 0, false) AS completo
                 FROM farma.ds_bi_itens
                 WHERE data BETWEEN %s AND %s
               ), produtos AS (
                 SELECT codigo, coalesce(min(nome), 'Produto não identificado') AS nome,
                        sum(quantidade) FILTER (WHERE completo) AS unidades,
                        sum(receita_item) FILTER (WHERE completo) AS receita,
                        count(*) FILTER (WHERE NOT completo) AS incompletos,
                        count(*) AS itens
                 FROM itens
                 GROUP BY codigo, CASE WHEN codigo IS NULL THEN lower(nome) END
               )
               SELECT codigo, nome, unidades, receita,
                      count(codigo) FILTER (WHERE unidades IS NOT NULL) OVER () AS produtos_com_codigo,
                      sum(itens) FILTER (WHERE codigo IS NULL) OVER () AS itens_sem_codigo,
                      sum(incompletos) OVER () AS itens_incompletos,
                      sum(unidades) OVER () AS total_unidades,
                      sum(receita) OVER () AS total_receita
               FROM produtos
               ORDER BY unidades DESC NULLS LAST, receita DESC NULLS LAST, codigo, nome
               LIMIT %s""",
            (start, end, PRODUCT_LIMIT),
        ).fetchall()
    summary = rows[0] if rows else {}
    ranking = [
        ProductRow(
            codigo=row["codigo"],
            nome=row["nome"],
            unidades=row["unidades"],
            receita_centavos=integer(row["receita"], 100),
        )
        for row in rows
        if row["unidades"] is not None
    ]
    return ProductsReport(
        revisao=revision["revisao"],
        versao=revision["versao"],
        inicio=start,
        fim=end,
        produtos_com_codigo=summary.get("produtos_com_codigo", 0),
        itens_sem_codigo=int(summary.get("itens_sem_codigo") or 0),
        itens_incompletos=int(summary.get("itens_incompletos") or 0),
        unidades=summary.get("total_unidades") or Decimal(0),
        receita_centavos=integer(summary.get("total_receita") or Decimal(0), 100),
        ranking=ranking,
    )


def _ads_rows(db, start, end, summary, limit):
    rows = db.execute(
        """SELECT m.conta_id, m.moeda, m.fuso, m.politica_atribuicao,
                  m.anuncio_id, m.campanha_nome, m.investimento_original,
                  coalesce(m.conversas_meta, m.conversas_meta_informadas) AS conversas,
                  m.fatos_sem_metrica_meta, a.pedidos, a.receita, a.primeiros, a.parciais
           FROM farma.ds_veiculacao_meta_v4(%s,%s,%s) m
           LEFT JOIN farma.ds_atribuicao_periodo_v1(%s,%s,%s) a
             ON (m.conta_id,m.moeda,m.fuso,m.politica_atribuicao)
              = (a.conta_id,a.moeda,a.fuso,a.politica_atribuicao)
            AND m.anuncio_id IS NOT DISTINCT FROM a.ad
           ORDER BY m.investimento_original DESC NULLS LAST, m.conta_id,
                    m.moeda, m.fuso, m.politica_atribuicao, m.anuncio_id
           LIMIT %s""",
        (start, end, summary, start, end, summary, limit + 1),
    ).fetchall()
    return [_ads_row(row) for row in rows[:limit]], len(rows) > limit


def _ads_row(row) -> AdsRow:
    spend, revenue = row["investimento_original"], row["receita"]
    orders, buyers = row["pedidos"], row["primeiros"]
    comparable = row["moeda"] == "BRL" and spend is not None

    def cost(count):
        if not comparable or not count:
            return None
        return integer((spend / count).quantize(Decimal(".01"), rounding=ROUND_HALF_UP), 100)

    return AdsRow(
        conta=row["conta_id"], moeda=row["moeda"], fuso=row["fuso"],
        atribuicao=row["politica_atribuicao"], anuncio=row["anuncio_id"],
        campanha=row["campanha_nome"], investimento=spend, conversas=row["conversas"],
        conversas_parciais=bool(row["fatos_sem_metrica_meta"]) or row["conversas"] is None,
        pedidos=integer(orders) if orders is not None else None,
        receita_centavos=integer(revenue, 100) if revenue is not None else None,
        primeiras_compras=integer(buyers) if buyers is not None else None,
        cpa_centavos=cost(orders), cac_centavos=cost(buyers),
        roas=(revenue / spend).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
        if comparable and spend and revenue is not None else None,
        cobertura_parcial=row["parciais"] != 0 or orders is None or revenue is None,
    )


def read_ads(
    dsn: str, start: date, end: date, expected: UUID | None = None
) -> AdsReport:
    with published_snapshot(dsn, expected) as (db, revision):
        db.execute("SET LOCAL statement_timeout = '22s'")
        totals, limited = _ads_rows(db, start, end, True, 50)
        if limited:
            raise SourceUnavailable
        ads, ads_limited = _ads_rows(db, start, end, False, 100) if totals else ([], False)
    return AdsReport(
        revisao=revision["revisao"], versao=revision["versao"], inicio=start, fim=end,
        totais=totals, anuncios=ads, anuncios_limitados=ads_limited,
    )


def read_ad_orders(
    dsn: str, start: date, end: date, kind: str, identifier: str,
    expected: UUID | None = None,
) -> AdOrdersReport:
    with published_snapshot(dsn, expected) as (db, revision):
        rows = db.execute(
            """SELECT anuncio, campanha, presente, completa, conversa, emissao, vinculo, receita
               FROM farma.ds_metricas_pedidos_anuncios(%s,%s,%s,%s)""",
            (start, end, kind, identifier),
        ).fetchall()
    limited = len(rows) > 100
    if not any(row["presente"] for row in rows):
        coverage = "sem_evidencia"
    elif limited or any(not row["completa"] for row in rows):
        coverage = "parcial"
    else:
        coverage = "completa"
    return AdOrdersReport(
        revisao=revision["revisao"], versao=revision["versao"], inicio=start, fim=end,
        encontrado=bool(rows), cobertura=coverage, limitado=limited,
        pedidos=[
            AdOrder(
                anuncio=row["anuncio"], campanha=row["campanha"],
                conversa=row["conversa"], emissao=row["emissao"], vinculo=row["vinculo"],
                receita_centavos=integer(row["receita"], 100),
            )
            for row in rows[:100] if row["emissao"] is not None
        ],
    )
