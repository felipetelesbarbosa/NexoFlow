"""SQL parametrizado sobre visões autorizadas; nunca devolve resposta truncada."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

from psycopg import sql
from psycopg.rows import dict_row

from ds_backend.contract import (
    PROTOCOL,
    SCHEMA_HASH,
    StorageError,
)
from integrations.datastudio.read_catalog import (
    DERIVED_SQL,
    READ_REGISTRY,
    read_contract,
)
from integrations.datastudio.store import Store

MAX_RESULT_ROWS = 50_000
MAX_RESULT_BYTES = 7_000_000


def view_name(name):
    return "ds_" + name.lower()


class Reader(Store):
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
        expressions = []
        for field in fields:
            column = sql.Identifier(field)
            if field in aggregation:
                operation = aggregation[field]
                if operation == "count_distinct":
                    expr = sql.SQL("COUNT(DISTINCT {})").format(column)
                else:
                    expr = sql.SQL("{}({})").format(sql.SQL(operation.upper()), column)
                expressions.append(sql.SQL("{} AS {}").format(expr, column))
            else:
                expressions.append(column)
        statement = sql.SQL("SELECT {} FROM {}.{}").format(
            sql.SQL(",").join(expressions),
            sql.Identifier(self.schema),
            sql.Identifier(view_name(table)),
        )
        if clauses:
            statement += sql.SQL(" WHERE ") + sql.SQL(" AND ").join(clauses)
        dimensions = [sql.Identifier(f) for f in fields if f not in aggregation]
        if aggregation and dimensions:
            statement += sql.SQL(" GROUP BY ") + sql.SQL(",").join(dimensions)
        with self.connect(readonly=True) as conn:
            version = self.active(conn)
            if not version:
                raise StorageError("DS_SEM_PUBLICACAO_CONFIRMADA")
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
            rows = conn.execute(
                statement + sql.SQL(" LIMIT %s"), [*params, MAX_RESULT_ROWS + 1]
            ).fetchall()
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
