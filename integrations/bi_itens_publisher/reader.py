"""Consultas somente leitura à visão FARMA, com grão solicitado e limites explícitos."""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal

import psycopg
from psycopg import IsolationLevel, sql
from psycopg.rows import dict_row

from bi_postgres_contract import COLUMNS, PublicationError

READ_TARGET = "nexoflow_datastudio_piloto.farma.produtos_itens_datastudio"
READ_PROTOCOL = "bi_itens_farma_leitura_1"
METRICS = {"quantidade", "valor_unitario", "receita_item"}
DISTINCT = "produtos_distintos_periodo"
OPTIONAL_TEXT = {"produto_codigo", "produto_nome", "categoria", "atualizado_em"}


def dimension(name):
    return (
        sql.SQL("coalesce({}::text,'')").format(sql.Identifier(name))
        if name in OPTIONAL_TEXT
        else sql.Identifier(name)
    )


class Reader:
    def __init__(self, dsn):
        self.dsn = dsn

    def connect(self):
        conn = psycopg.connect(
            self.dsn,
            row_factory=dict_row,
            connect_timeout=8,
            options="-c statement_timeout=20000 -c lock_timeout=5000",
        )
        conn.isolation_level = IsolationLevel.REPEATABLE_READ
        conn.read_only = True
        return conn

    def check(self, conn, *, require_ready=True):
        if (
            conn.execute("SELECT current_database() AS db").fetchone()["db"]
            != "nexoflow_datastudio_piloto"
        ):
            raise PublicationError("BI_PG_BANCO_DIVERGENTE")
        role = conn.execute(
            "SELECT rolname,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=current_user"
        ).fetchone()
        if role["rolname"] != "nf_bi_itens_reader" or any(
            role[k]
            for k in (
                "rolsuper",
                "rolcreatedb",
                "rolcreaterole",
                "rolreplication",
                "rolbypassrls",
            )
        ):
            raise PublicationError("BI_PG_LEITOR_PRIVILEGIOS")
        columns = conn.execute(
            "SELECT column_name,data_type FROM information_schema.columns WHERE table_schema='farma' AND table_name='produtos_itens_datastudio'"
        ).fetchall()
        types = {r["column_name"]: r["data_type"] for r in columns}
        if (
            not set(COLUMNS).issubset(types)
            or any(types[c] != "numeric" for c in METRICS)
            or types["data"] != "date"
            or any(
                types[c] not in {"text", "character varying"}
                for c in (
                    "item_chave",
                    "venda_chave",
                    "cliente_chave",
                    "produto_codigo",
                    "produto_nome",
                    "categoria",
                )
            )
        ):
            raise PublicationError("BI_PG_VISAO_SCHEMA_DIVERGENTE")
        lineage = conn.execute("""SELECT DISTINCT n.nspname,c.relname FROM pg_rewrite r
          JOIN pg_depend d ON d.classid='pg_rewrite'::regclass AND d.objid=r.oid AND d.refclassid='pg_class'::regclass
          JOIN pg_class c ON c.oid=d.refobjid JOIN pg_namespace n ON n.oid=c.relnamespace
          WHERE r.ev_class='farma.produtos_itens_datastudio'::regclass AND d.refobjid<>r.ev_class""").fetchall()
        if {(r["nspname"], r["relname"]) for r in lineage} != {("farma", "bi_itens")}:
            raise PublicationError("BI_PG_VISAO_LINHAGEM_NAO_CONFIRMADA")
        custom = conn.execute("""SELECT 1 FROM pg_rewrite r JOIN pg_depend d
          ON d.classid='pg_rewrite'::regclass AND d.objid=r.oid AND d.refclassid='pg_proc'::regclass
          JOIN pg_proc p ON p.oid=d.refobjid JOIN pg_namespace n ON n.oid=p.pronamespace
          WHERE r.ev_class='farma.produtos_itens_datastudio'::regclass AND n.nspname<>'pg_catalog' LIMIT 1""").fetchone()
        if (
            custom
            or conn.execute(
                "SELECT 1 FROM pg_class WHERE oid='farma.bi_itens'::regclass AND (relrowsecurity OR relforcerowsecurity)"
            ).fetchone()
        ):
            raise PublicationError("BI_PG_VISAO_LINHAGEM_NAO_CONFIRMADA")
        state = conn.execute(
            "SELECT state,revision FROM nexoflow_publicacao.estado_leitura"
        ).fetchone()
        if require_ready and state["state"] not in {"READY", "LEGADO"}:
            raise PublicationError("BI_PG_LEITURA_PUBLICACAO_PENDENTE")
        return state

    def query(self, request):
        if not isinstance(request, dict) or set(request) != {
            "protocol",
            "target",
            "segment",
            "fields",
            "start",
            "end",
            "filters",
        }:
            raise PublicationError("BI_PG_CONSULTA_INVALIDA")
        if (request["protocol"], request["target"], request["segment"]) != (
            READ_PROTOCOL,
            READ_TARGET,
            "FARMA",
        ):
            raise PublicationError("BI_PG_DESTINO_DIVERGENTE")
        fields = request["fields"]
        if (
            not isinstance(fields, list)
            or not fields
            or len(fields) > 13
            or any(
                not isinstance(f, str) or f not in (*COLUMNS, DISTINCT) for f in fields
            )
            or len(set(fields)) != len(fields)
        ):
            raise PublicationError("BI_PG_CAMPOS_INVALIDOS")
        try:
            start, end = (
                date.fromisoformat(request["start"]),
                date.fromisoformat(request["end"]),
            )
            if (
                start.isoformat() != request["start"]
                or end.isoformat() != request["end"]
                or start > end
            ):
                raise ValueError
        except (ValueError, TypeError):
            raise PublicationError("BI_PG_PERIODO_INVALIDO") from None
        groups = request["filters"]
        if not isinstance(groups, list) or len(groups) > 25:
            raise PublicationError("BI_PG_FILTRO_NAO_SUPORTADO")
        conditions = []
        arguments = [start, end]
        for group in groups:
            if not isinstance(group, list) or not group or len(group) > 25:
                raise PublicationError("BI_PG_FILTRO_NAO_SUPORTADO")
            atoms = []
            for f in group:
                if not isinstance(f, dict) or set(f) != {
                    "fieldName",
                    "values",
                    "type",
                    "operator",
                }:
                    raise PublicationError("BI_PG_FILTRO_NAO_SUPORTADO")
                name, values = f["fieldName"], f["values"]
                if name == "sku_informado" and isinstance(values, list):
                    values = [
                        str(v) if type(v) is int and v in (0, 1) else v for v in values
                    ]
                if (
                    not isinstance(name, str)
                    or name not in COLUMNS
                    or name in METRICS
                    or f["type"] not in {"INCLUDE", "EXCLUDE"}
                    or not isinstance(values, list)
                    or not values
                    or len(values) > 100
                    or any(not isinstance(v, str) or len(v) > 512 for v in values)
                ):
                    raise PublicationError("BI_PG_FILTRO_NAO_SUPORTADO")
                column = dimension(name)
                if name == "sku_informado":
                    if any(v not in {"0", "1"} for v in values):
                        raise PublicationError("BI_PG_FILTRO_NAO_SUPORTADO")
                    values = [int(v) for v in values]
                if name == "data":
                    try:
                        values = [
                            datetime.strptime(v, "%Y%m%d").date()
                            if len(v) == 8
                            else date.fromisoformat(v)
                            for v in values
                        ]
                    except (ValueError, TypeError):
                        raise PublicationError("BI_PG_FILTRO_NAO_SUPORTADO") from None
                if f["operator"] in {"EQUALS", "IN_LIST"}:
                    if f["operator"] == "EQUALS" and len(values) != 1:
                        raise PublicationError("BI_PG_FILTRO_NAO_SUPORTADO")
                    atom = sql.SQL("{}=ANY(%s)").format(column)
                    arguments.append(values)
                elif (
                    f["operator"] == "CONTAINS"
                    and len(values) == 1
                    and name not in {"data", "sku_informado"}
                ):
                    atom = sql.SQL("strpos({}::text,%s)>0").format(column)
                    arguments.append(values[0])
                else:
                    raise PublicationError("BI_PG_FILTRO_NAO_SUPORTADO")
                atoms.append(
                    sql.SQL("NOT ({})").format(atom) if f["type"] == "EXCLUDE" else atom
                )
            conditions.append(sql.SQL("({})").format(sql.SQL(" OR ").join(atoms)))
        where = sql.SQL("data BETWEEN %s AND %s")
        if conditions:
            where += sql.SQL(" AND ") + sql.SQL(" AND ").join(conditions)
        if DISTINCT in fields and fields != [DISTINCT]:
            raise PublicationError("BI_PG_CARTAO_EXATO_SEPARADO")
        with self.connect() as conn:
            state = self.check(conn)
            # Validar o grão original antes de filtros; nunca esconder duplicação na agregação.
            checked = conn.execute(
                """SELECT count(*) AS n,count(DISTINCT item_chave) AS keys,
                count(*) FILTER(WHERE data IS NULL OR item_chave IS NULL
                OR item_chave !~ '^[0-9a-f]{32}$' OR venda_chave !~ '^[0-9a-f]{32}$' OR cliente_chave !~ '^[0-9a-f]{32}$'  OR venda_chave IS NULL OR cliente_chave IS NULL
                OR quantidade IS NULL OR quantidade<=0 OR receita_item IS NULL OR receita_item<0
                OR valor_unitario IS NULL OR valor_unitario<0 OR sku_informado IS NULL OR sku_informado NOT IN(0,1)
                OR quantidade::text IN ('NaN','Infinity','-Infinity')
                OR receita_item::text IN ('NaN','Infinity','-Infinity')
                OR valor_unitario::text IN ('NaN','Infinity','-Infinity')) AS invalid
                FROM farma.produtos_itens_datastudio WHERE data IS NULL OR data BETWEEN %s AND %s""",
                (start, end),
            ).fetchone()
            if checked["n"] != checked["keys"] or checked["invalid"]:
                raise PublicationError("BI_PG_VISAO_GRAO_INVALIDO")
            dimensions = [f for f in fields if f not in METRICS and f != DISTINCT]
            if fields == [DISTINCT]:
                expressions = [
                    sql.SQL(
                        "count(DISTINCT nullif(produto_codigo,'')) FILTER(WHERE sku_informado=1) AS produtos_distintos_periodo"
                    )
                ]
            else:
                expressions = [
                    sql.SQL("sum({}) AS {}").format(
                        sql.Identifier(f), sql.Identifier(f)
                    )
                    if f in METRICS
                    else sql.SQL("{} AS {}").format(dimension(f), sql.Identifier(f))
                    for f in fields
                ]
            statement = sql.SQL(
                "SELECT {},count(*) AS _nf_count FROM farma.produtos_itens_datastudio WHERE {}"
            ).format(sql.SQL(",").join(expressions), where)
            if dimensions:
                identifiers = sql.SQL(",").join(map(dimension, dimensions))
                statement += sql.SQL(" GROUP BY {} ORDER BY {}").format(
                    identifiers, identifiers
                )
            statement += sql.SQL(" LIMIT 200001")
            records = conn.execute(statement, arguments).fetchall()
            if len(records) > 200000:
                raise PublicationError("BI_PG_LEITURA_LIMITE; reduza o período")
            rows = []
            for record in records:
                if (
                    not record["_nf_count"]
                    or fields == [DISTINCT]
                    and not record[DISTINCT]
                ):
                    continue
                values = []
                for field in fields:
                    value = record[field]
                    if isinstance(value, Decimal):
                        if not value.is_finite():
                            raise PublicationError("BI_PG_VISAO_GRAO_INVALIDO")
                        value = str(value)
                    elif field == "data":
                        value = value.strftime("%Y%m%d")
                    elif isinstance(value, (date, datetime)):
                        value = value.isoformat()
                    values.append(value)
                rows.append({"values": values})
            cut = (
                conn.execute("SELECT transaction_timestamp() AS cut")
                .fetchone()["cut"]
                .isoformat()
            )
            response = {
                "protocol": READ_PROTOCOL,
                "target": READ_TARGET,
                "fields": fields,
                "rows": rows,
                "filtersApplied": True,
                "revision": state["revision"],
                "state": state["state"],
                "cut_at": cut,
            }
            if len(json.dumps(response, ensure_ascii=False).encode()) > 12_000_000:
                raise PublicationError("BI_PG_LEITURA_LIMITE; reduza o período")
            return response
