"""Projeções da página de produtos sobre uma única leitura da BI_Itens FARMA."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from concurrent.futures import Future
from datetime import date
from decimal import Decimal
from threading import Lock
from typing import Generic, TypeVar

from psycopg import sql

from ds_backend.contract import StorageError
from integrations.datastudio.read_catalog import PRODUCT_FIELDS as FIELDS

# A tabela física já resolve exclusões, vigência, cancelamentos, e a origem
# dos itens para a venda inteira. O filtro do usuário é aplicado aos itens:
# um SKU pode mudar de nome durante o período e um nome pode designar vários SKUs.
BASE = """
WITH itens AS MATERIALIZED (
 SELECT produto_codigo COLLATE "C" AS produto_codigo, produto_nome COLLATE "C" AS produto_nome,
        sku_informado,quantidade,receita_item,item_chave
 FROM farma.ds_bi_itens
 WHERE data BETWEEN %(inicio)s AND %(fim)s
   AND (%(nomes)s::text[] IS NULL OR produto_nome COLLATE "C" = ANY(%(nomes)s::text[]))
), skus AS (
 SELECT produto_codigo,max(produto_nome) AS produto_nome,
        sum(quantidade) AS quantidade,sum(receita_item) AS receita_item,
        count(item_chave) AS registros
 FROM itens GROUP BY produto_codigo
), ranking AS MATERIALIZED (
 SELECT s.*,
    row_number() OVER receita AS posicao_receita_top5,
    row_number() OVER (ORDER BY quantidade DESC, receita_item DESC, produto_codigo ASC NULLS LAST)
      AS posicao_unidades_top5,
    sum(receita_item) OVER (receita ROWS UNBOUNDED PRECEDING)
       / nullif(sum(receita_item) OVER (),0) AS participacao_acumulada
 FROM skus s WINDOW receita AS (ORDER BY receita_item DESC,produto_codigo ASC NULLS LAST)
), nomes AS MATERIALIZED (
 SELECT produto_nome,count(item_chave) AS registros FROM itens GROUP BY produto_nome
), resumo AS (
 SELECT count(DISTINCT produto_codigo) FILTER (WHERE sku_informado=1) AS produtos_distintos_periodo,
        coalesce(sum(quantidade),0) AS quantidade,coalesce(sum(receita_item),0) AS receita_item,
        count(item_chave) AS registros,
        count(*) = count(DISTINCT btrim(item_chave)) AND
        NOT EXISTS (SELECT 1 FROM itens WHERE nullif(btrim(item_chave),'') IS NULL
          OR quantidade IS NULL OR quantidade <= 0 OR receita_item IS NULL OR receita_item < 0
          OR quantidade::text IN ('NaN','Infinity','-Infinity')
          OR receita_item::text IN ('NaN','Infinity','-Infinity')) AS completo
 FROM itens
)
"""

# Um catálogo de tamanho habitual cabe no leitor. Os cartões e Top 5 continuam
# disponíveis para catálogos grandes. A lista inteira, quando pedida com poucas
# colunas, ainda pode caber no limite de resposta: medir a projeção solicitada.
BUNDLE = (
    BASE
    + """
, tamanho AS (
 SELECT (SELECT count(*) FROM ranking) AS skus, (SELECT count(*) FROM nomes) AS nomes,
   (SELECT coalesce(sum(octet_length(to_jsonb(r)::text)),0) FROM ranking r) AS bytes_ranking,
   (SELECT coalesce(sum(octet_length(to_jsonb(r)::text)),0) FROM ranking r
      WHERE r.posicao_receita_top5<=5 OR r.posicao_unidades_top5<=5) AS bytes_tops,
   (SELECT coalesce(sum(octet_length(to_jsonb(n)::text)),0) FROM nomes n) AS bytes_nomes
)
SELECT 'resumo' AS parte,to_jsonb(s)::text AS dados FROM resumo s
UNION ALL SELECT 'tamanho',to_jsonb(t)::text FROM tamanho t
UNION ALL SELECT 'produto',to_jsonb(r)::text FROM ranking r CROSS JOIN tamanho t
  WHERE (t.skus<=%(linhas)s AND t.bytes_ranking<=%(bytes)s)
     OR (t.bytes_tops<=%(bytes)s AND (r.posicao_receita_top5<=5 OR r.posicao_unidades_top5<=5))
UNION ALL SELECT 'nome',to_jsonb(n)::text FROM nomes n CROSS JOIN tamanho t
  WHERE t.nomes<=%(linhas)s AND t.bytes_nomes<=%(bytes)s
"""
)


def request(mode, fields, start, end, names):
    if not isinstance(mode, str) or mode not in FIELDS:
        raise StorageError("DS_TABELA_NAO_AUTORIZADA")
    if (
        not isinstance(fields, list)
        or not fields
        or not all(isinstance(f, str) for f in fields)
        or len(set(fields)) != len(fields)
        or set(fields) - FIELDS[mode] - {"periodo_inicio"}
    ):
        raise StorageError("DS_CAMPOS_NAO_AUTORIZADOS")
    try:
        begin, finish = date.fromisoformat(start), date.fromisoformat(end)
        if begin > finish or start != begin.isoformat() or end != finish.isoformat():
            raise ValueError
    except (TypeError, ValueError):
        raise StorageError("DS_PERIODO_INVALIDO") from None
    if names is not None and (
        not isinstance(names, list)
        or len(names) > 100
        or not all(isinstance(name, str) and "\x00" not in name for name in names)
    ):
        raise StorageError("DS_FILTRO_INVALIDO")
    return {
        "inicio": begin,
        "fim": finish,
        "nomes": None if names is None else sorted(set(names)),
    }


PeriodData = TypeVar("PeriodData")


class SnapshotPeriod(ABC, Generic[PeriodData]):
    """Compartilha uma leitura entre gráficos no mesmo snapshot PostgreSQL."""

    def __init__(self):
        self.lock = Lock()
        self.pending: dict[tuple, Future[PeriodData]] = {}
        self.last_key: tuple | None = None
        self.last: PeriodData | None = None

    @staticmethod
    @abstractmethod
    def load(conn, params) -> PeriodData:
        raise NotImplementedError

    @staticmethod
    def identity(reader, conn, params):
        # A chave inclui a visibilidade da transação para invalidar até uma
        # reinstalação das visões sem troca de READY. O cache pertence ao leitor.
        state = conn.execute(
            "SELECT versao,execucao,current_user AS papel,pg_postmaster_start_time() AS boot,"
            "pg_current_snapshot()::text AS snapshot FROM controle.nf_publicacoes "
            "WHERE segmento=%s AND versao>0 AND execucao IS NOT NULL",
            (reader.segment,),
        ).fetchone()
        if not state:
            raise StorageError("DS_SEM_PUBLICACAO_CONFIRMADA")
        names = params.get("nomes")
        return (
            state["versao"],
            state["execucao"],
            state["papel"],
            state["boot"],
            state["snapshot"],
            params["inicio"],
            params["fim"],
            None if names is None else tuple(names),
        )

    def get(self, reader, params):
        leader = False
        try:
            with reader.connect(readonly=True) as conn:
                key = self.identity(reader, conn, params)
                with self.lock:
                    if key == self.last_key and self.last is not None:
                        return key, self.last
                    future = self.pending.get(key)
                    if future is None:
                        future = self.pending[key] = Future()
                        leader = True
                if leader:
                    data = self.load(conn, params)
        except BaseException as exc:
            if leader:
                with self.lock:
                    self.pending.pop(key).set_exception(exc)
            raise
        if leader:
            with self.lock:
                self.last_key, self.last = key, data
                self.pending.pop(key).set_result(data)
            return key, data
        # Participantes liberam suas conexões antes de aguardar o responsável.
        try:
            return key, future.result(timeout=45)
        except TimeoutError:
            raise StorageError("DS_CONSULTA_TEMPO_LIMITE") from None


class ProductPeriods(SnapshotPeriod[dict]):
    @staticmethod
    def load(conn, params):
        conn.execute("SET LOCAL enable_nestloop=off")
        data: dict = {"produto": [], "nome": []}
        for part in conn.execute(BUNDLE, params):
            section = part["parte"]
            row = json.loads(part["dados"], parse_float=Decimal)
            if section in ("produto", "nome"):
                data[section].append(row)
            else:
                data[section] = row
        if not data["resumo"].pop("completo"):
            raise StorageError("DS_PRODUTOS_BASE_INVALIDA")
        if abs(data["resumo"]["receita_item"]) * 100 > 2**53 - 1:
            raise StorageError("DS_ABC_PRECISAO_EXCEDIDA")
        data["produto"].sort(key=lambda row: row["posicao_receita_top5"])
        data["nome"].sort(
            key=lambda row: (row["produto_nome"] is None, row["produto_nome"] or "")
        )
        return data


def read_columns(reader, key, params, mode, fields, byte_limit):
    """Mede somente as colunas pedidas quando o perfil completo não coube no cache."""
    select = [
        sql.Identifier(field)
        if field != "periodo_inicio"
        else sql.SQL("%(inicio)s::date AS periodo_inicio")
        for field in fields
    ]
    ordered = {
        "ranking": sql.SQL(" FROM ranking ORDER BY posicao_receita_top5"),
        "nomes": sql.SQL(" FROM nomes ORDER BY produto_nome"),
        "receita": sql.SQL(" FROM ranking ORDER BY posicao_receita_top5 LIMIT 5"),
        "unidades": sql.SQL(" FROM ranking ORDER BY posicao_unidades_top5 LIMIT 5"),
    }
    with reader.connect(readonly=True) as conn:
        if reader.product_periods.identity(reader, conn, params) != key:
            raise StorageError("DS_REVISAO_ALTERADA")
        conn.execute("SET LOCAL enable_nestloop=off")
        statement = (
            sql.SQL(BASE + " SELECT ") + sql.SQL(",").join(select) + ordered[mode]
        )
        rows = []
        size_so_far = 0
        # O cursor limita a leitura em memória mesmo se a resposta final for excessiva.
        with conn.cursor(name="nf_produtos_periodo") as cursor:
            cursor.itersize = 64
            cursor.execute(statement, params)
            for row in cursor:
                size_so_far += len(
                    json.dumps(
                        list(row.values()), default=str, ensure_ascii=False
                    ).encode()
                )
                if size_so_far > byte_limit:
                    raise StorageError("DS_RESPOSTA_EXCEDE_LIMITE_USE_RESUMO")
                rows.append(row)
    return rows


def projected(reader, mode, fields, start, end, names, row_limit, byte_limit):
    if reader.segment != "FARMA":
        raise StorageError("DS_TABELA_NAO_AUTORIZADA")
    params = request(mode, fields, start, end, names)
    params.update(linhas=row_limit, bytes=byte_limit // 2)
    key, data = reader.product_periods.get(reader, params)
    size = data["tamanho"]
    if mode == "resumo":
        rows = [data["resumo"]]
    elif mode in ("receita", "unidades"):
        if size["bytes_tops"] > params["bytes"]:
            rows = read_columns(reader, key, params, mode, fields, byte_limit)
        elif mode == "receita":
            rows = data["produto"][:5]
        else:
            rows = sorted(
                (row for row in data["produto"] if row["posicao_unidades_top5"] <= 5),
                key=lambda row: row["posicao_unidades_top5"],
            )
    else:
        names_mode = mode == "nomes"
        if size["nomes" if names_mode else "skus"] > row_limit:
            raise StorageError("DS_CONSULTA_EXCEDE_LIMITE_USE_RESUMO_OU_PERIODO")
        if size["bytes_nomes" if names_mode else "bytes_ranking"] > params["bytes"]:
            rows = read_columns(reader, key, params, mode, fields, byte_limit)
        else:
            rows = data["nome" if names_mode else "produto"]
    if "periodo_inicio" in fields:
        rows = [dict(row, periodo_inicio=start) for row in rows]
    return reader.result(key[0], fields, rows)
