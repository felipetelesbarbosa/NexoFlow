"""Fontes aditivas; revisão de destino/schema/conteúdo e backup antes de escrever."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path

from order_history import HistoryError

SCHEMAS = {
    "Historico_Pedidos": [
        "chave",
        "segmento",
        "pedido_id",
        "cliente_id",
        "contato_weni",
        "vinculo",
        "data",
        "estado",
        "motivo",
        "produtos",
        "frete",
        "faturamento",
        "origem",
        "base_financeira",
        "vigente",
    ],
    "Historico_Itens": [
        "chave",
        "segmento",
        "pedido_id",
        "item_id",
        "sku",
        "produto",
        "quantidade",
        "valor",
        "frete",
        "estado",
        "vigente",
    ],
    "BI_LTV_Clientes": [
        "chave",
        "segmento",
        "cliente_id",
        "pedidos",
        "ltv_observado",
        "ticket_medio",
        "primeira_compra",
        "ultima_compra",
        "cobertura",
        "vigente",
    ],
    "BI_Cobertura_Historica": [
        "chave",
        "segmento",
        "inicio",
        "fim",
        "limite",
        "proxima_pagina",
        "total_declarado",
        "paginas",
        "extracao",
        "motivo",
        "atualizado",
        "calendario",
        "pendencias",
        "vigente",
    ],
}


SCHEMAS["BI_Historico_Resumo"] = [
    "chave",
    "segmento",
    "tipo_recorte",
    "competencia",
    "periodo_inicio",
    "periodo_fim",
    "pedidos",
    "validos",
    "cancelados",
    "pendentes",
    "outros",
    "clientes",
    "itens",
    "unidades",
    "produtos",
    "frete",
    "faturamento",
    "cobertura",
    "vigente",
]


NUMERIC = {
    "validos",
    "cancelados",
    "pendentes",
    "outros",
    "clientes",
    "itens",
    "unidades",
    "produtos",
    "frete",
    "faturamento",
    "quantidade",
    "valor",
    "pedidos",
    "ltv_observado",
    "ticket_medio",
    "limite",
    "proxima_pagina",
    "total_declarado",
    "paginas",
    "pendencias",
}


def normalized_cells(row):
    result = {}
    for key, value in row.items():
        text = str(value)
        if key in NUMERIC and text not in ("", "Sim", "Não"):
            try:
                number = Decimal(text)
            except InvalidOperation:
                raise HistoryError("NUMERO_INVALIDO") from None
            if not number.is_finite():
                raise HistoryError("NUMERO_INVALIDO")
            text = format(number.normalize(), "f")
        result[key] = text
    return result


def typed_cells(row):
    return {
        k: float(v) if k in NUMERIC and v not in ("", "Sim", "Não") else v
        for k, v in row.items()
    }


def iter_tables(store):
    """Linhas em fluxo; agregação LTV em SQLite, sem lista de pedidos em RAM."""

    def amount(cents):
        return str(Decimal(cents) / 100)

    from pedido_utils import business_order_datetime

    item_summary = {}
    for row in store.records():
        day = business_order_datetime(row["date"])
        periods = [
            ("MES", day.strftime("%Y-%m") if day else None),
            ("ANO", day.strftime("%Y") if day else None),
            ("TOTAL", "TOTAL"),
        ]
        key = row["segment"] + ":" + row["id"]
        yield (
            "Historico_Pedidos",
            dict(
                zip(
                    SCHEMAS["Historico_Pedidos"],
                    [
                        key,
                        row["segment"],
                        row["id"],
                        row["owner"],
                        row["contact_uuid"],
                        row["link_state"],
                        row["date"],
                        row["state"],
                        row["reason"],
                        amount(row["products_cents"]),
                        amount(row["freight_cents"]),
                        amount(row["revenue_cents"]),
                        row["source"],
                        row["policy"],
                        "Sim",
                    ],
                    strict=True,
                )
            ),
        )
        for item in row["items"]:
            if row["state"] == "valido" and not item["freight"]:
                for scope in periods:
                    count, units = item_summary.get(scope, (0, Decimal(0)))
                    item_summary[scope] = (
                        count + 1,
                        units + Decimal(str(item["quantity"])),
                    )
            yield (
                "Historico_Itens",
                dict(
                    zip(
                        SCHEMAS["Historico_Itens"],
                        [
                            key + ":" + item["id"],
                            row["segment"],
                            row["id"],
                            item["id"],
                            item["sku"],
                            item["name"],
                            item["quantity"],
                            amount(item["total_cents"]),
                            "Sim" if item["freight"] else "Não",
                            row["state"],
                            "Sim",
                        ],
                        strict=True,
                    )
                ),
            )
    for owner, count, revenue, first, last in store.db.execute(
        "SELECT owner,count(*),sum(json_extract(record,'$.revenue_cents')),min(json_extract(record,'$.date')),max(json_extract(record,'$.date')) FROM history_orders WHERE segment=? AND json_extract(record,'$.state')='valido' GROUP BY owner ORDER BY owner",
        (store.segment,),
    ):
        average = str((Decimal(revenue) / 100 / count).quantize(Decimal("0.01")))
        yield (
            "BI_LTV_Clientes",
            dict(
                zip(
                    SCHEMAS["BI_LTV_Clientes"],
                    [
                        store.segment + ":" + owner,
                        store.segment,
                        owner,
                        str(count),
                        amount(revenue),
                        average,
                        first,
                        last,
                        "LTV_OBSERVADO",
                        "Sim",
                    ],
                    strict=True,
                )
            ),
        )
    pending = store.db.execute(
        "SELECT count(*) FROM history_issues WHERE segment=?", (store.segment,)
    ).fetchone()[0]
    for row in store.db.execute(
        "SELECT key,segment,start,end,page_limit,next_page,total,pages,status,reason,updated FROM history_windows WHERE segment=? ORDER BY key",
        (store.segment,),
    ):
        yield (
            "BI_Cobertura_Historica",
            dict(
                zip(
                    SCHEMAS["BI_Cobertura_Historica"],
                    [
                        *[str(v) if v is not None else "" for v in row],
                        "LIMITES_API_NAO_HOMOLOGADOS",
                        str(pending),
                        "Sim",
                    ],
                    strict=True,
                )
            ),
        )

    # Resumo pequeno para o leitor anual, com clientes distintos calculados
    # diretamente em cada grão. Nunca somar clientes mensais para obter o ano.
    raw_date = "json_extract(record,'$.date')"
    date_expr = f"CASE WHEN length({raw_date})=10 THEN {raw_date}||'T00:00:00-03:00' WHEN instr(substr({raw_date},11),'+')=0 AND instr(substr({raw_date},11),'-')=0 AND upper(substr({raw_date},-1))!='Z' THEN {raw_date}||'-03:00' ELSE {raw_date} END"
    expressions = [
        ("MES", f"strftime('%Y-%m',{date_expr},'-3 hours')"),
        ("ANO", f"strftime('%Y',{date_expr},'-3 hours')"),
        ("TOTAL", "'TOTAL'"),
    ]
    for kind, period in expressions:
        sql = f"""SELECT {period} AS competence,
             min(date({date_expr},'-3 hours')),max(date({date_expr},'-3 hours')),
             count(*),sum(json_extract(record,'$.state')='valido'),
             sum(json_extract(record,'$.state')='cancelado'),sum(json_extract(record,'$.state')='pendente'),
             sum(json_extract(record,'$.state') NOT IN ('valido','cancelado','pendente')),
             count(DISTINCT CASE WHEN json_extract(record,'$.state')='valido' THEN owner END),
             coalesce(sum(CASE WHEN json_extract(record,'$.state')='valido' THEN json_extract(record,'$.products_cents') ELSE 0 END),0),
             coalesce(sum(CASE WHEN json_extract(record,'$.state')='valido' THEN json_extract(record,'$.freight_cents') ELSE 0 END),0),
             coalesce(sum(CASE WHEN json_extract(record,'$.state')='valido' THEN json_extract(record,'$.revenue_cents') ELSE 0 END),0)
             FROM history_orders WHERE segment=? GROUP BY competence ORDER BY competence"""
        for (
            period_id,
            first,
            last,
            count,
            valid,
            cancel,
            pending,
            other,
            buyers,
            products,
            freight,
            revenue,
        ) in store.db.execute(sql, (store.segment,)):
            if period_id is None and kind == "ANO":
                continue
            type_id = kind if period_id is not None else "SEM_EMISSAO"
            period_id = period_id or "SEM_EMISSAO"
            lines, units = item_summary.get(
                (kind, None if type_id == "SEM_EMISSAO" else period_id), (0, Decimal(0))
            )
            yield (
                "BI_Historico_Resumo",
                dict(
                    zip(
                        SCHEMAS["BI_Historico_Resumo"],
                        [
                            store.segment + ":" + type_id + ":" + period_id,
                            store.segment,
                            type_id,
                            period_id,
                            first or "",
                            last or "",
                            str(count),
                            str(valid or 0),
                            str(cancel or 0),
                            str(pending or 0),
                            str(other or 0),
                            str(buyers),
                            str(lines),
                            str(units),
                            amount(products),
                            amount(freight),
                            amount(revenue),
                            "OBSERVADO; LIMITES_API_NAO_HOMOLOGADOS",
                            "Sim",
                        ],
                        strict=True,
                    )
                ),
            )


def tables(store):
    """Compatibilidade para consumidores pequenos; publicação usa iter_tables."""
    result = {name: [] for name in SCHEMAS}
    for title, row in iter_tables(store):
        result[title].append(row)
    return result


def google_store_type():
    from google_sheets import GoogleSheetsStore

    class HistoryGoogleStore(GoogleSheetsStore):
        @staticmethod
        def _native_meta_headers(title, headers):
            if title not in SCHEMAS or headers != SCHEMAS[title]:
                raise HistoryError("SCHEMA_HISTORICO_INVALIDO")

    return HistoryGoogleStore


class HistorySheets:
    """Fachada compatível do publicador; todos os caminhos usam o protocolo v2."""

    def __init__(self, store, segment, backup_dir: Path):
        from history_publication import Publication
        from history_sheets_transport import SheetsTransport

        remote = store if hasattr(store, "describe") else SheetsTransport(store)
        self.engine = Publication(remote, segment, backup_dir)
        self.last_result = {}

    def plan(self, data, *, evidence=None):
        if isinstance(data, dict) and set(data) != set(SCHEMAS):
            raise HistoryError("TABELAS_INCOMPLETAS")
        rows = (
            ((title, row) for title, records in data.items() for row in records)
            if isinstance(data, dict)
            else data
        )
        return self.engine.prepare(rows, evidence=evidence)

    def apply(self, data, review, *, max_batches=None):
        if data is not None:
            rows = (
                ((title, row) for title, records in data.items() for row in records)
                if isinstance(data, dict)
                else data
            )
            self.engine.verify_input(rows, review)
        self.last_result = self.engine.apply(review, max_batches=max_batches)
        return self.last_result["applied_rows"]

    def check(self, review):
        return self.engine.check(review)

    def rollback(self, review, batch):
        return self.engine.rollback(review, batch)
