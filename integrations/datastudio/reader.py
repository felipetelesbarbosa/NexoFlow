"""SQL parametrizado sobre visões autorizadas; nunca devolve resposta truncada."""

from __future__ import annotations

import json
import sys
from collections import OrderedDict
from concurrent.futures import Future
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from threading import BoundedSemaphore, Lock
from typing import Any

from psycopg import sql
from psycopg.errors import CardinalityViolation
from psycopg.rows import dict_row

from ds_backend.contract import (
    PROTOCOL,
    SCHEMA_HASH,
    StorageError,
)
from integrations.datastudio import meta_destinations
from integrations.datastudio.products_reader import (
    ProductPeriods,
    SnapshotPeriod,
    projected,
)
from integrations.datastudio.read_catalog import (
    DERIVED_SQL,
    PUBLIC_SUMMARY,
    READ_REGISTRY,
    read_contract,
)
from integrations.datastudio.store import Store

MAX_RESULT_ROWS = 50_000
MAX_RESULT_BYTES = 7_000_000
# O papel de leitura na VPS aceita seis conexões. Dois lugares ficam livres
# para o healthcheck e para a conferência com outro processo.
MAX_READER_CONNECTIONS = 4


def view_name(name):
    return "ds_" + name.lower()


def ranking_fits_cache(rows):
    """Limita retenção entre chamadas. Campos pedidos têm seu próprio limite HTTP."""
    size = sys.getsizeof(rows)
    for row in rows:
        size += sys.getsizeof(row) + sum(sys.getsizeof(value) for value in row.values())
        if size > MAX_RESULT_BYTES:
            return False
    return True


class SalesPeriods(SnapshotPeriod[list[dict]]):
    @staticmethod
    def load(conn, params):
        conn.execute("SET LOCAL enable_nestloop=off")
        columns = sql.SQL(",").join(
            sql.Identifier(field) for field in READ_REGISTRY["BI_Vendas"]["columns"]
        )
        return conn.execute(
            sql.SQL(
                "SELECT {} FROM farma.ds_bi_vendas WHERE data BETWEEN %(inicio)s "
                "AND %(fim)s LIMIT %(limite)s"
            ).format(columns),
            params,
        ).fetchall()


class Reader(Store):
    def __init__(self, dsn, environment, segment, *, require_dedicated_role=False):
        super().__init__(
            dsn, environment, segment, require_dedicated_role=require_dedicated_role
        )
        self._abc_lock = Lock()
        self._abc_pending: dict[tuple, Future] = {}
        self._abc_ready: dict[str, OrderedDict[tuple, list]] = {
            "resumo": OrderedDict(),
            "abc": OrderedDict(),
        }
        self.product_periods = ProductPeriods()
        self.sales_periods = SalesPeriods()
        self._db_slots = BoundedSemaphore(MAX_READER_CONNECTIONS)

    @contextmanager
    def connect(self, *, readonly=False):
        if not self._db_slots.acquire(timeout=45):
            raise StorageError("DS_CONSULTA_TEMPO_LIMITE")
        try:
            with super().connect(readonly=readonly) as conn:
                yield conn
        finally:
            self._db_slots.release()

    def products(self, mode, fields, start, end, names=None):
        return projected(
            self, mode, fields, start, end, names, MAX_RESULT_ROWS, MAX_RESULT_BYTES
        )

    def pairs(self, fields, start, end, top):
        if type(top) is not int or not 1 <= top <= 1000:
            raise StorageError("DS_TOP_PARES_INVALIDO")
        return self._abc("juntos", fields, start, end, top=top)

    def abc(self, mode, fields, start, end):
        return self._abc(mode, fields, start, end)

    def _abc(self, mode, fields, start, end, *, top=None):
        from integrations.datastudio.abc_reader import FIELDS, aggregates, calculate

        if not isinstance(mode, str) or mode not in FIELDS:
            raise StorageError("DS_TABELA_NAO_AUTORIZADA")
        if (
            not isinstance(fields, list)
            or not fields
            or any(not isinstance(f, str) for f in fields)
            or len(fields) != len(set(fields))
            or set(fields) - set(FIELDS[mode])
        ):
            raise StorageError("DS_CAMPOS_NAO_AUTORIZADOS")
        try:
            if date.fromisoformat(start) > date.fromisoformat(end):
                raise ValueError
        except (TypeError, ValueError):
            raise StorageError("DS_PERIODO_INVALIDO") from None
        if mode in ("abc", "resumo") and self.segment == "FARMA":
            return self._shared_abc(mode, fields, start, end)
        with self.connect(readonly=True) as conn:
            version = self.active(conn)
            if not version:
                raise StorageError("DS_SEM_PUBLICACAO_CONFIRMADA")
            # Preserva o hotfix bba86d0 também no caminho ABC. A mesma transação
            # REPEATABLE READ contém versão, itens, vendas e validações.
            conn.execute("SET LOCAL enable_nestloop=off")
            records = aggregates(
                conn, self.schema, start, end, mode, MAX_RESULT_ROWS, top=top
            )
        universe = None
        if top is not None:
            records, universe = records
        rows = calculate(records, start, end, mode)
        if top is not None:
            for row in rows:
                row["periodo_rotulo"] += f" | Top {len(rows)} de {universe} pares"
        result: dict[str, Any] = self.result(version, fields, rows)
        if top is not None:
            result["scope"] = dict(
                kind="TOP_PARES",
                requested=top,
                universe_pairs=universe,
                selected_pairs=len(rows),
                all_pairs_returned=universe == len(rows),
            )
        return result

    def _shared_abc(self, mode, fields, start, end):
        from integrations.datastudio.abc_reader import FIELDS, aggregates, calculate

        # Cada requisição confirma contrato, usuário, READY e visibilidade MVCC.
        # Uma escrita ou troca de visão invalida o reuso mesmo sob o mesmo UUID.
        leader = False
        try:
            with self.connect(readonly=True) as conn:
                version = self.active(conn)
                if not version:
                    raise StorageError("DS_SEM_PUBLICACAO_CONFIRMADA")
                identity = conn.execute(
                    "SELECT execucao, current_user AS role, pg_postmaster_start_time() AS boot, "
                    "pg_current_snapshot()::text AS snapshot FROM controle.nf_publicacoes "
                    "WHERE segmento=%s AND versao=%s AND execucao IS NOT NULL",
                    (self.segment, version),
                ).fetchone()
                if not identity:
                    raise StorageError("DS_SEM_PUBLICACAO_CONFIRMADA")
                key = (
                    self.target,
                    mode,
                    version,
                    identity["execucao"],
                    identity["role"],
                    identity["boot"],
                    identity["snapshot"],
                    start,
                    end,
                )
                ready = self._abc_ready[mode]
                with self._abc_lock:
                    complete = ready.get(key)
                    if complete is not None:
                        ready.move_to_end(key)
                    else:
                        pending = self._abc_pending.get(key)
                        if pending is None:
                            pending = Future()
                            self._abc_pending[key] = pending
                            leader = True
                if leader:
                    conn.execute("SET LOCAL enable_nestloop=off")
                    records = aggregates(
                        conn, self.schema, start, end, mode, MAX_RESULT_ROWS
                    )
                    complete = calculate(records, start, end, mode)
                    if mode == "resumo":
                        self.result(version, FIELDS[mode], complete)
                    retain = mode == "resumo" or ranking_fits_cache(complete)
            # Uma consulta participante libera a conexão antes de esperar.
            # O responsável disponibiliza a linha só após o êxito da transação.
        except BaseException as error:
            if leader:
                with self._abc_lock:
                    self._abc_pending.pop(key).set_exception(error)
            raise

        if leader:
            with self._abc_lock:
                if retain:
                    ready[key] = complete
                    if len(ready) > (32 if mode == "resumo" else 1):
                        ready.popitem(last=False)
                self._abc_pending.pop(key).set_result(complete)
        elif complete is None:
            try:
                complete = pending.result(timeout=45)
            except TimeoutError:
                raise StorageError("DS_CONSULTA_TEMPO_LIMITE") from None
        # Validar cada projeção por si: a tabela pode exceder o limite de bytes
        # enquanto o seletor de classes do mesmo ranking continua válido.
        return self.result(version, fields, complete)

    def info(self):
        with self.connect() as conn:
            version = self.active(conn)
        return dict(
            protocol=PROTOCOL,
            target=self.target,
            segment=self.segment,
            environment=self.environment,
            schema_hash=SCHEMA_HASH,
            version=version,
        )

    def query(self, table, fields, start, end, filters, aggregation):
        spec = read_contract(table)
        if spec.get("segment", self.segment) != self.segment:
            raise StorageError(
                "DS_INSIGHTS_SEGMENTO"
                if table == "BI_Weni_Conversas_Diarias"
                else "DS_TABELA_NAO_AUTORIZADA"
            )
        allowed = spec.get("read_columns", spec["columns"])
        if (
            not spec["public"]
            or not isinstance(fields, list)
            or not fields
            or len(fields) != len(set(fields))
            or set(fields) - set(allowed)
        ):
            raise StorageError("DS_CAMPOS_NAO_AUTORIZADOS")
        if (
            not isinstance(filters, list)
            or len(filters) > 16
            or not isinstance(aggregation, dict)
        ):
            raise StorageError("DS_FILTRO_INVALIDO")
        if set(aggregation) - set(fields) or any(
            v not in ("sum", "count_distinct", "count", "min", "max")
            for v in aggregation.values()
        ):
            raise StorageError("DS_AGREGACAO_INVALIDA")
        if table == PUBLIC_SUMMARY and aggregation:
            # Os grupos conjuntos permitem que a página aplique dimensões e
            # fórmulas legadas, mesmo quando o Looker não encaminha os filtros.
            raise StorageError("DS_PUBLICO_AGREGACAO_INVALIDA")
        for field, operation in aggregation.items():
            if operation == "sum" and spec["types"][field] != "number":
                raise StorageError("DS_AGREGACAO_TIPO")
        if table == "BI_Historico_Resumo":
            grains = [
                f.get("values")
                for f in filters
                if isinstance(f, dict) and f.get("field") == "tipo_recorte"
            ]
            if len(grains) != 1 or grains[0] not in (
                ["MES"],
                ["ANO"],
                ["TOTAL"],
                ["SEM_EMISSAO"],
            ):
                raise StorageError("DS_RESUMO_EXIGE_GRAO")
            if grains[0][0] in ("TOTAL", "SEM_EMISSAO") and (start or end):
                raise StorageError("DS_RESUMO_TOTAL_NAO_APLICA_DATA")
            if aggregation.get("clientes") == "sum":
                raise StorageError("DS_COMPRADORES_NAO_SOMAVEIS_ENTRE_MESES")
        clauses: list[sql.Composable] = []
        params = []
        summary = table == "BI_Historico_Resumo"
        if summary:
            clauses.append(sql.SQL("vigente='Sim'"))
        if bool(start) != bool(end):
            raise StorageError("DS_PERIODO_INVALIDO")
        if table == "BI_Weni_Conversas_Diarias" and not start:
            raise StorageError("DS_INSIGHTS_PERIODO_OBRIGATORIO")
        if start:
            try:
                first, last = date.fromisoformat(start), date.fromisoformat(end)
                if first > last:
                    raise ValueError
            except (ValueError, TypeError):
                raise StorageError("DS_PERIODO_INVALIDO") from None
            if spec["period"] is None:
                raise StorageError("DS_PERIODO_NAO_APLICAVEL")
            if summary:
                # Selecionar sobreposição, mas recusar cortes parciais antes de
                # devolver dados. BETWEEN só no início perdia meses ou os somava
                # integralmente a um intervalo de poucos dias.
                clauses.append(sql.SQL("periodo_fim >= %s AND periodo_inicio <= %s"))
                params.extend((first, last))
            else:
                clauses.append(
                    sql.SQL("{} BETWEEN %s AND %s").format(
                        sql.Identifier(spec["period"])
                    )
                )
                params.extend((first, last))
        for item in filters:
            if (
                not isinstance(item, dict)
                or set(item) != {"field", "values"}
                or item["field"] not in allowed
                or not isinstance(item["values"], list)
                or not 1 <= len(item["values"]) <= 100
            ):
                raise StorageError("DS_FILTRO_INVALIDO")
            if any(not isinstance(v, (str, int, float)) for v in item["values"]):
                raise StorageError("DS_FILTRO_INVALIDO")
            clauses.append(
                sql.SQL("{}::text=ANY(%s)").format(sql.Identifier(item["field"]))
            )
            params.append([str(v) for v in item["values"]])
        period_customer_revenue = (
            self.segment == "FARMA"
            and table == "BI_Clientes_Vendas"
            and bool(start)
            and fields == ["faturamento"]
            and aggregation == {"faturamento": "sum"}
        )
        expressions = []
        for field in fields:
            column = sql.Identifier(field)
            if field in aggregation:
                operation = aggregation[field]
                if operation == "count_distinct":
                    expr = sql.SQL("COUNT(DISTINCT {})").format(column)
                else:
                    expr = sql.SQL("{}({})").format(sql.SQL(operation.upper()), column)
                if period_customer_revenue:
                    expr = sql.SQL("coalesce({},0::numeric)").format(expr)
                expressions.append(sql.SQL("{} AS {}").format(expr, column))
            else:
                expressions.append(column)
        daily_metrics = (
            [f for f in fields if spec["types"][f] == "number"]
            if table == "BI_Vendas" and self.segment == "FARMA"
            else []
        )
        if (
            table == "BI_Vendas"
            and self.segment == "FARMA"
            and start
            and not filters
            and not aggregation
        ):
            key, rows = self.sales_periods.get(
                self, {"inicio": first, "fim": last, "limite": MAX_RESULT_ROWS + 1}
            )
            # Um gráfico pode pedir somente medidas com cobertura. Cada projeção
            # conserva o mesmo bloqueio por nulo da consulta SQL individual.
            if any(row[field] is None for row in rows for field in daily_metrics):
                raise StorageError("DS_BI_VENDAS_INCOMPLETA")
            return self.result(key[0], fields, rows)
        if daily_metrics:
            # SUM no SQL e a reagregação do Looker ignoram NULL. Conferir a
            # cobertura dos campos pedidos no mesmo snapshot e na mesma leitura.
            incomplete = sql.SQL(" OR ").join(
                sql.SQL("{} IS NULL").format(sql.Identifier(f)) for f in daily_metrics
            )
            if aggregation:
                incomplete = sql.SQL("bool_or({})").format(incomplete)
            expressions.append(sql.SQL("({}) AS nf_incompleto").format(incomplete))
        if period_customer_revenue:
            expressions.append(
                sql.SQL("count(*) <> count(faturamento) AS nf_incompleto")
            )
        statement = sql.SQL("SELECT {} FROM {}.{}").format(
            sql.SQL(",").join(expressions),
            sql.Identifier(self.schema),
            sql.Identifier(view_name(table)),
        )
        period_ads = table in meta_destinations.PERIOD
        commercial_ads = period_ads and bool(
            meta_destinations.COMMERCIAL_METRICS.keys()
            & (set(fields) | {f["field"] for f in filters})
        )
        ads_function = (
            "ds_veiculacao_meta_v4" if commercial_ads else "ds_veiculacao_meta_v3"
        )
        if period_ads:
            if not start or aggregation:
                raise StorageError("DS_ANUNCIOS_PERIODO_OU_AGREGACAO")
            statement = sql.SQL("SELECT {} FROM farma.{}(%s,%s,%s)").format(
                sql.SQL(",").join(expressions), sql.Identifier(ads_function)
            )
            params = [start, end, table == meta_destinations.PERIOD[1], *params]
        if clauses:
            statement += sql.SQL(" WHERE ") + sql.SQL(" AND ").join(clauses)
        dimensions = [sql.Identifier(f) for f in fields if f not in aggregation]
        if aggregation and dimensions:
            statement += sql.SQL(" GROUP BY ") + sql.SQL(",").join(dimensions)
        with self.connect(readonly=True) as conn:
            version = self.active(conn)
            if not version:
                raise StorageError("DS_SEM_PUBLICACAO_CONFIRMADA")
            if (
                spec.get("optional") and not period_ads
            ) or table == "BI_Weni_Conversas_Diarias":
                if (
                    conn.execute(
                        "SELECT to_regclass(%s) AS relation",
                        (f"{self.schema}.{view_name(table)}",),
                    ).fetchone()["relation"]
                    is None
                ):
                    raise StorageError(
                        "DS_INSIGHTS_VISAO_AUSENTE"
                        if table == "BI_Weni_Conversas_Diarias"
                        else "DS_DESTINOS_VISAO_AUSENTE"
                        if table
                        in (meta_destinations.DETAIL, meta_destinations.CATALOG)
                        else "DS_PUBLICO_VISAO_AUSENTE"
                    )
            if (
                period_ads
                and not conn.execute(
                    "SELECT to_regprocedure(%s) AS f",
                    (f"farma.{ads_function}(date,date,boolean)",),
                ).fetchone()["f"]
            ):
                raise StorageError("DS_DESTINOS_VISAO_AUSENTE")
            if table == "BI_Weni_Conversas_Diarias":
                coverage = conn.execute(
                    "SELECT count(*) AS linhas,count(DISTINCT data) AS dias "
                    "FROM farma.ds_bi_weni_conversas_diarias WHERE data BETWEEN %s AND %s",
                    (start, end),
                ).fetchone()
                if (
                    coverage["linhas"] != coverage["dias"]
                    or coverage["dias"]
                    != (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
                ):
                    raise StorageError("DS_INSIGHTS_COBERTURA_INCOMPLETA")
            if summary:
                with conn.cursor(row_factory=dict_row) as cursor:
                    bounds = cursor.execute(
                        sql.SQL(
                            "SELECT min(periodo_inicio) AS first,max(periodo_fim) AS last,count(*) AS n FROM {}.{} WHERE {}"
                        ).format(
                            sql.Identifier(self.schema),
                            sql.Identifier(view_name(table)),
                            sql.SQL(" AND ").join(clauses),
                        ),
                        params,
                    ).fetchone()
                if bounds is None:
                    raise StorageError("DS_RESUMO_NAO_CONFIRMADO")
                if (
                    start
                    and bounds["n"]
                    and (bounds["first"] < first or bounds["last"] > last)
                ):
                    raise StorageError("DS_FILTRO_CORTA_RECORTE_USE_DETALHE")
                if (
                    "clientes" in fields
                    and bounds["n"] > 1
                    and ("competencia" not in fields or "competencia" in aggregation)
                ):
                    raise StorageError(
                        "DS_COMPRADORES_EXIGEM_COMPETENCIA_OU_RECORTE_UNICO"
                    )
            if table == "BI_Itens" or (
                self.segment == "FARMA" and table in ("BI_Pedidos", "BI_Vendas")
            ):
                # As visões históricas sobre JSONB subestimam a cardinalidade
                # dos itens por venda e podem escolher laços quadráticos.
                conn.execute("SET LOCAL enable_nestloop=off")
            try:
                with conn.cursor(row_factory=dict_row) as cursor:
                    rows = cursor.execute(
                        statement + sql.SQL(" LIMIT %s"), [*params, MAX_RESULT_ROWS + 1]
                    ).fetchall()
            except CardinalityViolation:
                if table == "BI_Pedidos" and self.segment == "FARMA":
                    raise StorageError("DS_BI_PEDIDO_OPERACIONAL_AMBIGUO") from None
                raise
            if (daily_metrics or period_customer_revenue) and any(
                row["nf_incompleto"] for row in rows
            ):
                raise StorageError("DS_BI_VENDAS_INCOMPLETA")
        return self.result(version, fields, rows)

    def result(self, version, fields, rows):
        if len(rows) > MAX_RESULT_ROWS:
            raise StorageError("DS_CONSULTA_EXCEDE_LIMITE_USE_RESUMO_OU_PERIODO")

        def scalar(value):
            if isinstance(value, Decimal):
                return str(value)
            if isinstance(value, date):
                return value.isoformat()
            return value

        output = [[scalar(r[f]) for f in fields] for r in rows]
        result = dict(
            protocol=PROTOCOL,
            target=self.target,
            segment=self.segment,
            environment=self.environment,
            schema_hash=SCHEMA_HASH,
            version=version,
            fields=fields,
            rows=output,
            complete=True,
        )
        if len(json.dumps(result, ensure_ascii=False).encode()) > MAX_RESULT_BYTES:
            raise StorageError("DS_RESPOSTA_EXCEDE_LIMITE_USE_RESUMO")
        return result


def create_views(conn):
    for segment in ("FARMA", "PET"):
        schema = segment.lower()
        for name, spec in READ_REGISTRY.items():
            if name == "BI_Weni_Conversas_Diarias" or spec.get("optional"):
                continue  # Visões de homologação têm instalação própria.
            if not spec["public"] and name != "Exclusoes_Publicacao":
                continue
            columns = []
            for field in spec.get("read_columns", spec["columns"]):
                value = (
                    sql.SQL(DERIVED_SQL[name, field])
                    if (name, field) in DERIVED_SQL
                    else sql.SQL("registro ->> {}").format(sql.Literal(field))
                )
                kind = spec["types"][field]
                if kind in ("number", "date"):
                    value = (
                        sql.SQL("NULLIF({},'')::numeric").format(value)
                        if kind == "number"
                        else sql.SQL("controle.nf_data({})").format(value)
                    )
                columns.append(sql.SQL("{} AS {}").format(value, sql.Identifier(field)))
            output_name = view_name(name) + (
                "_operacional"
                if name
                in ("BI_Itens", "BI_Clientes", "BI_Clientes_Vendas", "BI_Pedidos")
                else ""
            )
            query = sql.SQL(
                "CREATE OR REPLACE VIEW {}.{} WITH(security_barrier=true) AS SELECT {} FROM {}.nf_atuais WHERE tabela={}"
            ).format(
                sql.Identifier(schema),
                sql.Identifier(output_name),
                sql.SQL(",").join(columns),
                sql.Identifier(schema),
                sql.Literal(name),
            )
            # Datas e vínculos frequentes têm índices da projeção ativa. O arquivo
            # de versões continua sendo a evidência e a fonte do rollback.
            import hashlib

            fields = [f for f, k in spec["types"].items() if k == "date"]
            fields += [
                f
                for f in ("pedido_id", "venda_chave", "cliente_id")
                if f in spec["columns"]
            ]
            for field in fields:
                index = (
                    "nf_ds_"
                    + hashlib.sha256((name + ":" + field).encode()).hexdigest()[:16]
                )
                expression = sql.SQL("registro ->> {}").format(sql.Literal(field))
                if spec["types"][field] == "date":
                    expression = sql.SQL("controle.nf_data({})").format(expression)
                conn.execute(
                    sql.SQL(
                        "CREATE INDEX IF NOT EXISTS {} ON {}.nf_atuais (({})) WHERE tabela={}"
                    ).format(
                        sql.Identifier(index),
                        sql.Identifier(schema),
                        expression,
                        sql.Literal(name),
                    )
                )
            conn.execute(query)
    from integrations.datastudio.financial_views import create_financial_views

    create_financial_views(conn)


def create_farma_public_summary(conn):
    conn.execute("""CREATE OR REPLACE VIEW farma.ds_bi_publico_resumo
        WITH (security_barrier=true) AS
        SELECT nullif(btrim(cidade),'') AS cidade,canal,idade,idade_informada,
          count(*) AS contatos,
          coalesce(sum(compra_identificada),0)::bigint AS compra_identificada,
          count(*) - coalesce(sum(compra_identificada),0)::bigint AS sem_compra_identificada,
          count(*) FILTER (WHERE idade_informada=1) AS contatos_idade_informada,
          count(*) FILTER (WHERE nullif(btrim(cidade),'') IS NULL
            OR btrim(cidade)='Não informado') AS contatos_sem_cidade
        FROM farma.ds_bi_publico GROUP BY 1,2,3,4""")
    conn.execute("GRANT SELECT ON farma.ds_bi_publico_resumo TO nf_ds_farma_read")
