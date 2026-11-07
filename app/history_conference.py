"""Conferência agregada privada; não publica identificadores individuais."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from decimal import Decimal
from tempfile import TemporaryDirectory
from typing import Any

from order_history import HistoryError, digest
from pedido_utils import business_order_datetime

FORMAT = "historico_conferencia_v1"


def summarize(
    records, segment, *, context=None, tolerate_financial=False
) -> dict[str, Any]:
    """Deduplica em disco. TOTAL conta clientes diretamente, sem somar meses.

    Itens são linhas de produto (frete técnico excluído); unidades são Decimal.
    Bases monetárias consideram apenas compras válidas, em centavos inteiros.
    """
    with TemporaryDirectory(prefix="nexoflow-conferencia-") as directory:
        with closing(sqlite3.connect(directory + "/indices.sqlite")) as db:
            db.executescript("""PRAGMA cache_size=-8192;
            CREATE TABLE seen(k TEXT PRIMARY KEY,hash TEXT);
            CREATE TABLE buyers(period TEXT,owner TEXT,PRIMARY KEY(period,owner));""")
            groups = {}
            first_day = last_day = None

            def group(key):
                return groups.setdefault(
                    key,
                    dict(
                        recorte=key,
                        pedidos=0,
                        validos=0,
                        cancelados=0,
                        pendentes=0,
                        outros=0,
                        itens_linhas_observadas=0,
                        itens_linhas_validas=0,
                        unidades_validas="0",
                        produtos_centavos=0,
                        frete_centavos=0,
                        faturamento_centavos=0,
                    ),
                )

            group("TOTAL")
            for row in records:
                if row["segment"] != segment:
                    raise HistoryError("CONFERENCIA_DE_OUTRO_SEGMENTO")
                key = row["id"]
                checksum = digest(row)
                found = db.execute("SELECT hash FROM seen WHERE k=?", (key,)).fetchone()
                if found:
                    if found[0] != checksum:
                        raise HistoryError("PEDIDO_DIVERGENTE_NA_CONFERENCIA")
                    continue
                db.execute("INSERT INTO seen VALUES(?,?)", (key, checksum))
                day = business_order_datetime(row["date"])
                if day:
                    civil_day = day.date().isoformat()
                    first_day = min(first_day, civil_day) if first_day else civil_day
                    last_day = max(last_day, civil_day) if last_day else civil_day
                period = day.strftime("%Y-%m") if day else "SEM_EMISSAO"
                valid = row["state"] == "valido"
                if valid and (not day or not row["owner"]):
                    raise HistoryError("COMPRA_VALIDA_SEM_DATA_OU_CLIENTE")
                products = [i for i in row["items"] if not i["freight"]]
                for label in (period, "TOTAL"):
                    g = group(label)
                    g["pedidos"] += 1
                    state = {
                        "valido": "validos",
                        "cancelado": "cancelados",
                        "pendente": "pendentes",
                    }.get(row["state"], "outros")
                    g[state] += 1
                    g["itens_linhas_observadas"] += len(products)
                    if valid:
                        db.execute(
                            "INSERT OR IGNORE INTO buyers VALUES(?,?)",
                            (label, row["owner"]),
                        )
                        g["itens_linhas_validas"] += len(products)
                        units = sum(
                            (Decimal(str(i["quantity"])) for i in products), Decimal(0)
                        )
                        g["unidades_validas"] = str(
                            Decimal(g["unidades_validas"]) + units
                        )
                        for target, source in (
                            ("produtos_centavos", "products_cents"),
                            ("frete_centavos", "freight_cents"),
                            ("faturamento_centavos", "revenue_cents"),
                        ):
                            value = row[source]
                            if type(value) is not int:
                                raise HistoryError("CENTAVOS_NAO_INTEIROS")
                            g[target] += value
            for period, g in groups.items():
                g["clientes_com_compra_valida"] = db.execute(
                    "SELECT count(*) FROM buyers WHERE period=?", (period,)
                ).fetchone()[0]
                if (
                    g["produtos_centavos"] + g["frete_centavos"]
                    != g["faturamento_centavos"]
                ):
                    if not tolerate_financial:
                        raise HistoryError("BASES_FINANCEIRAS_DIVERGENTES")
                    g["inconsistencia_base_centavos"] = (
                        g["faturamento_centavos"]
                        - g["produtos_centavos"]
                        - g["frete_centavos"]
                    )
            result = dict(
                formato=FORMAT,
                segmento=segment,
                conferido_em=datetime.now(UTC).isoformat(),
                contexto=context or {},
                periodo_emissao=dict(
                    inicio=first_day, fim=last_day, fuso="America/Belem"
                ),
                cobertura="LIMITES_DA_API_NAO_HOMOLOGADOS",
                criterio_itens="linhas de produto; exclui lançamentos técnicos de frete",
                criterio_financeiro="compras válidas; produtos + frete oficial; centavos",
                recebimentos_brutos_por_mes=None,
                motivo_recebimentos="Não reconstruir recebimentos brutos mensais a partir de fatos únicos atualizados.",
                recortes=[groups[k] for k in sorted(groups) if k != "TOTAL"]
                + [groups["TOTAL"]],
            )
            return result


def receipts(store):
    """Cobertura de extração não é prova de recebimentos brutos por emissão."""
    names = {
        r[0]
        for r in store.db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    windows = []
    if {"history_windows", "history_seen"} <= names:
        for key, start, end, total, status in store.db.execute(
            "SELECT key,start,end,total,status FROM history_windows WHERE segment=? ORDER BY start,key",
            (store.segment,),
        ):
            unique = store.db.execute(
                "SELECT count(*) FROM history_seen WHERE window_key=?", (key,)
            ).fetchone()[0]
            windows.append(
                dict(
                    inicio=start,
                    fim=end,
                    declarados=total,
                    ids_unicos_observados=unique,
                    extracao=status,
                )
            )
    executions = []
    if "history_run_receipts" in names:
        for run, occurrences, unique in store.db.execute(
            "SELECT run,sum(occurrences),count(*) FROM history_run_receipts WHERE segment=? GROUP BY run",
            (store.segment,),
        ):
            executions.append(
                dict(execucao=run, recebimentos_brutos=occurrences, ids_unicos=unique)
            )
    return dict(janelas=windows, execucoes=executions)


def from_published(db, table="observed"):
    """Mesma semântica a partir das quatro tabelas relidas, sem joins de receita por item."""
    if table not in ("incoming", "observed", "pilot_expected", "pilot_observed"):
        raise HistoryError("FONTE_DE_CONFERENCIA_INVALIDA")
    db.execute(
        f"CREATE INDEX IF NOT EXISTS {table}_pedido ON {table}(t,json_extract(v,'$.pedido_id'),json_extract(v,'$.segmento'))"
    )

    def cents(value):
        number = Decimal(str(value)) * 100
        if not number.is_finite() or number != number.to_integral_value():
            raise HistoryError("VALOR_PUBLICADO_FORA_DE_CENTAVOS")
        return int(number)

    for (raw,) in db.execute(
        f"SELECT v FROM {table} WHERE t='Historico_Pedidos' ORDER BY k"
    ):
        row = json.loads(raw)
        if row["vigente"] != "Sim":
            continue
        items = []
        for (encoded,) in db.execute(
            f"SELECT v FROM {table} WHERE t='Historico_Itens' AND json_extract(v,'$.pedido_id')=? AND json_extract(v,'$.segmento')=? ORDER BY k",
            (row["pedido_id"], row["segmento"]),
        ):
            item = json.loads(encoded)
            if item["vigente"] == "Sim":
                items.append(
                    dict(freight=item["frete"] == "Sim", quantity=item["quantidade"])
                )
        yield dict(
            segment=row["segmento"],
            id=row["pedido_id"],
            owner=row["cliente_id"],
            date=row["data"],
            state=row["estado"],
            items=items,
            products_cents=cents(row["produtos"]),
            freight_cents=cents(row["frete"]),
            revenue_cents=cents(row["faturamento"]),
        )


def compare(expected, observed) -> dict[str, Any]:
    if expected["segmento"] != observed["segmento"]:
        raise HistoryError("COMPARACAO_ENTRE_SEGMENTOS")
    left = {r["recorte"]: r for r in expected["recortes"]}
    right = {r["recorte"]: r for r in observed["recortes"]}
    differences = []
    for period in sorted(left.keys() | right.keys()):
        for key in sorted(
            (left.get(period, {}) | right.get(period, {})).keys() - {"recorte"}
        ):
            a = left.get(period, {}).get(key, 0)
            b = right.get(period, {}).get(key, 0)
            if Decimal(str(a)) != Decimal(str(b)):
                differences.append(
                    dict(
                        recorte=period,
                        indicador=key,
                        esperado=a,
                        observado=b,
                        diferenca=str(Decimal(str(b)) - Decimal(str(a))),
                    )
                )
    return dict(
        formato=FORMAT,
        segmento=expected["segmento"],
        conferido_em=observed["conferido_em"],
        esperado=expected,
        observado=observed,
        diferencas=differences,
        estado="conferido" if not differences else "divergente",
    )
