"""Atualiza histórico acumulado sem substituir a base por um SQLite parcial."""

from __future__ import annotations

import json
from contextlib import closing

from ds_backend.contract import StorageError, normalize


def synchronize_postgres(settings, storage):
    if storage is None:
        raise StorageError("DS_HISTORICO_EXIGE_MESMA_REVISAO")
    enabled = getattr(
        settings,
        "FARMALIDER_HISTORY_STORAGE_ENABLED",
        getattr(settings, "FARMALIDER_HISTORY_ENABLED", False),
    )
    if not enabled:
        return dict(status="desativado", partial=False)
    from customer_observations import connect
    from order_history_sheets import iter_tables
    from order_history_store import HistoryStore

    # O cache vem do PostgreSQL. A conexão não toca o SQLite comercial original.
    with connect() as db:
        history = HistoryStore(db, storage.client.config["segment"])
        if db.execute(
            "SELECT 1 FROM history_windows WHERE segment=? AND status!='extraida' LIMIT 1",
            (history.segment,),
        ).fetchone():
            return dict(status="pendente", partial=True, error="DS_JANELA_INCOMPLETA")
        tables = {
            n: []
            for n in ("Historico_Pedidos", "Historico_Itens", "BI_Cobertura_Historica")
        }
        for name, row in iter_tables(history):
            if name in tables:
                tables[name].append(row)
        tables, quality_issues = protect_published(storage, tables)
        for issue in quality_issues:
            db.execute(
                "INSERT OR REPLACE INTO history_issues VALUES(?,?,?)",
                (history.segment, issue["id"], issue["reason"]),
            )
        for name, records in tables.items():
            if not records:
                continue
            # Atualizações são exclusivamente os fatos oficiais acumulados nesse cache.
            storage._upsert_records_detailed(
                storage._known_sheets[name], records, "chave"
            )
        # Não inativar itens ausentes de uma coleta parcial. Um pedido completo
        # normalizado informa o conjunto vigente de itens daquele pedido.
        incoming = {r["pedido_id"] for r in tables["Historico_Pedidos"]}
        keys = {r["chave"] for r in tables["Historico_Itens"]}
        obsolete = []
        for row in storage.records("Historico_Itens"):
            if (
                row["pedido_id"] in incoming
                and row["chave"] not in keys
                and row["vigente"] == "Sim"
            ):
                obsolete.append(dict(row, vigente="Não"))
        if obsolete:
            storage._upsert_records_detailed(
                storage._known_sheets["Historico_Itens"], obsolete, "chave"
            )
        # Reutiliza a agregação oficial em TODA a base financeira remota,
        # inclusive os fatos do corte inicial sem payload bruto conservado.
        regenerate(storage)
    return dict(
        status="preparada",
        partial=False,
        applied_rows=sum(map(len, tables.values())),
        remaining_batches=0,
        quality_issues=len(quality_issues),
    )


def regenerate(storage):
    import sqlite3
    import tempfile
    from decimal import Decimal

    from order_history_sheets import iter_tables
    from order_history_store import HistoryStore

    def cents(value):
        amount = Decimal(str(value)) * 100
        if not amount.is_finite() or amount != amount.to_integral_value():
            raise StorageError("DS_CENTAVOS_INVALIDOS")
        return int(amount)

    with tempfile.TemporaryDirectory(prefix="nexoflow-ltv-pg-") as directory:
        with closing(sqlite3.connect(directory + "/resumo.sqlite")) as db:
            history = HistoryStore(db, storage.client.config["segment"])
            items = {}
            for item in storage.records("Historico_Itens"):
                if item["vigente"] == "Sim":
                    items.setdefault(item["pedido_id"], []).append(
                        dict(
                            id=item["item_id"],
                            sku=item["sku"],
                            name=item["produto"],
                            quantity=item["quantidade"],
                            total_cents=cents(item["valor"]),
                            freight=item["frete"] == "Sim",
                        )
                    )
            for row in storage.records("Historico_Pedidos"):
                if row["vigente"] != "Sim":
                    continue
                record = dict(
                    segment=row["segmento"],
                    id=row["pedido_id"],
                    owner=row["cliente_id"],
                    contact_uuid=row["contato_weni"],
                    link_state=row["vinculo"],
                    date=row["data"],
                    state=row["estado"],
                    reason=row["motivo"],
                    products_cents=cents(row["produtos"]),
                    freight_cents=cents(row["frete"]),
                    revenue_cents=cents(row["faturamento"]),
                    source=row["origem"],
                    policy=row["base_financeira"],
                    items=items.get(row["pedido_id"], []),
                )
                db.execute(
                    "INSERT INTO history_orders VALUES(?,?,?,?,?,?)",
                    (
                        history.segment,
                        row["pedido_id"],
                        row["cliente_id"],
                        json.dumps(record),
                        "",
                        "",
                    ),
                )
            tables = {n: [] for n in ("BI_LTV_Clientes", "BI_Historico_Resumo")}
            for name, record in iter_tables(history):
                if name in tables:
                    tables[name].append(record)
            total_orders = db.execute(
                "SELECT coalesce(sum(json_extract(record,'$.revenue_cents')),0) FROM history_orders WHERE json_extract(record,'$.state')='valido'"
            ).fetchone()[0]
            total_ltv = sum(
                cents(r["ltv_observado"]) for r in tables["BI_LTV_Clientes"]
            )
            if total_orders != total_ltv:
                raise StorageError("DS_LTV_DIVERGENTE")
            # Tombstones são proibidos para essas tabelas financeiras. Marcar
            # somente chaves antigas derivadas como não vigentes após cálculo global.
            for name, records in tables.items():
                present = {r["chave"] for r in records}
                records.extend(
                    dict(r, vigente="Não")
                    for r in storage.records(name)
                    if r["chave"] not in present and r["vigente"] == "Sim"
                )
                storage._upsert_records_detailed(
                    storage._known_sheets[name], records, "chave"
                )


def protect_published(storage, tables):
    """A origem publicada prevalece sobre evidência incompleta do cache novo."""
    from datetime import datetime, timedelta
    from decimal import Decimal
    from zoneinfo import ZoneInfo

    previous = {r["chave"]: r for r in storage.records("Historico_Pedidos")}
    old_items = {}
    for item in storage.records("Historico_Itens"):
        if item["vigente"] == "Sim":
            old_items.setdefault(item["pedido_id"], []).append(item)
    new_items = {}
    for item in tables["Historico_Itens"]:
        new_items.setdefault(item["pedido_id"], []).append(item)

    def item_signature(items):
        return sorted(
            (
                i["item_id"],
                i["sku"],
                i["produto"],
                str(Decimal(i["quantidade"])),
                str(Decimal(i["valor"])),
                i["frete"],
            )
            for i in items
        )

    excluded = {r["pedido_id"] for r in storage.records("Exclusoes_Publicacao")}
    blocked = set()
    issues = []
    today = datetime.now(ZoneInfo("America/Belem")).date()
    for row in tables["Historico_Pedidos"]:
        old = previous.get(row["chave"])
        if row["pedido_id"] in excluded:
            blocked.add(row["pedido_id"])
            issues.append(
                dict(id=row["pedido_id"], reason="EXCLUSAO_REQUER_CONFERENCIA_DO_FATO")
            )
            continue
        if old is None:
            continue
        reason = None
        if old["vigente"] != "Sim":
            reason = "EXCLUSAO_PUBLICADA_PRESERVADA"
        elif row["cliente_id"] != old["cliente_id"]:
            reason = "CLIENTE_OFICIAL_CONFLITANTE"
        else:
            normalized = normalize(
                "Historico_Pedidos", [row], storage.client.config["segment"]
            )[0]
            old_day = old["data"]
            if old_day and normalized["data"] and old_day != normalized["data"]:
                reason = "EMISSAO_CONFLITANTE"
            elif old["estado"] == "valido" and row["estado"] not in (
                "valido",
                "cancelado",
            ):
                reason = "COMPRA_VALIDA_PRESERVADA"
            elif old_day and __import__("datetime").date.fromisoformat(
                old_day
            ) < today - timedelta(days=20):
                financial_changed = old["estado"] != row["estado"] or any(
                    Decimal(old[f]) != Decimal(row[f])
                    for f in ("produtos", "frete", "faturamento")
                )
                if financial_changed or item_signature(
                    old_items.get(row["pedido_id"], [])
                ) != item_signature(new_items.get(row["pedido_id"], [])):
                    reason = "FECHAMENTO_ANTIGO_REQUER_RECONCILIACAO"
        if reason:
            blocked.add(row["pedido_id"])
            issues.append(dict(id=row["pedido_id"], reason=reason))
    result = {
        n: [
            r
            for r in records
            if n == "BI_Cobertura_Historica" or r["pedido_id"] not in blocked
        ]
        for n, records in tables.items()
    }
    return result, issues
