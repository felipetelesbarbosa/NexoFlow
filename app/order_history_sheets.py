"""Fontes aditivas; revisão de destino/schema/conteúdo e backup antes de escrever."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from order_history import HistoryError, digest, ltv

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


NUMERIC = {
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
            number = Decimal(text)
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


def tables(store):
    result = {name: [] for name in SCHEMAS}

    def add(title, values):
        result[title].append(dict(zip(SCHEMAS[title], values, strict=True)))

    def amount(cents):
        return str(Decimal(cents) / 100)

    for row in store.records():
        key = row["segment"] + ":" + row["id"]
        add(
            "Historico_Pedidos",
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
        )
        for item in row["items"]:
            add(
                "Historico_Itens",
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
            )
    for row in ltv(store.records()):
        add(
            "BI_LTV_Clientes",
            [
                row["segment"] + ":" + row["owner"],
                row["segment"],
                row["owner"],
                str(row["orders"]),
                amount(row["revenue_cents"]),
                row["average"],
                row["first"],
                row["last"],
                row["coverage"],
                "Sim",
            ],
        )
    for row in store.db.execute(
        "SELECT key,segment,start,end,page_limit,next_page,total,pages,status,reason,updated FROM history_windows WHERE segment=?",
        (store.segment,),
    ):
        add(
            "BI_Cobertura_Historica",
            [
                *[str(v) if v is not None else "" for v in row],
                "LIMITES_API_NAO_HOMOLOGADOS",
                str(store.totals()["pendencias"]),
                "Sim",
            ],
        )
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
    def __init__(self, store, segment, backup_dir: Path):
        self.store, self.segment, self.backup_dir = store, segment, backup_dir

    def plan(self, data):
        if set(data) != set(SCHEMAS):
            raise HistoryError("TABELAS_INCOMPLETAS")
        context = self.store.native_meta_context()
        if (
            context["segment"] != self.segment
            or len({context[k] for k in ("history", "operations", "dashboard")}) != 3
        ):
            raise HistoryError("DESTINOS_INVALIDOS")
        snapshots, changes = {}, {}
        for title, headers in SCHEMAS.items():
            snapshot = self.store.native_meta_read(title, headers)
            expected_book = context[
                "history" if title.startswith("Historico_") else "dashboard"
            ]
            if snapshot["book_id"] != expected_book:
                raise HistoryError("DESTINO_DIVERGENTE")
            values = snapshot["values"]
            if values and values[0] != headers:
                raise HistoryError("CABECALHO_DIVERGENTE")
            old = {}
            for cells in values[1:]:
                if not cells or not any(cells):
                    continue
                if len(cells) > len(headers) or cells[0] in old:
                    raise HistoryError("LINHA_DUPLICADA_OU_INVALIDA")
                row = dict(
                    zip(
                        headers, cells + [""] * (len(headers) - len(cells)), strict=True
                    )
                )
                if row["segmento"] != self.segment:
                    raise HistoryError("SEGMENTO_DIVERGENTE")
                old[row["chave"]] = normalized_cells(row)
            incoming = {}
            for row in data[title]:
                if (
                    set(row) != set(headers)
                    or row["segmento"] != self.segment
                    or not row["chave"]
                    or row["chave"] in incoming
                ):
                    raise HistoryError("REGISTRO_INVALIDO")
                incoming[row["chave"]] = normalized_cells(row)
            # Ausência local não autoriza apagar/inativar uma compra remota.
            missing = old.keys() - incoming.keys()
            if title == "Historico_Pedidos" and any(
                old[k].get("vigente") != "Não" for k in missing
            ):
                raise HistoryError("BASE_LOCAL_INCOMPLETA_RECONCILIAR")
            for key in missing:
                # Itens/LTV derivados só ficam inativos após conhecer todos os
                # pedidos remotos no preflight da primeira tabela.
                incoming[key] = dict(old[key], vigente="Não")
            changes[title] = [r for k, r in incoming.items() if r != old.get(k)]
            snapshots[title] = snapshot
        return {
            "segment": self.segment,
            "context": context,
            "data_digest": digest(data),
            "snapshots": snapshots,
            "changes": changes,
        }

    def apply(self, data, review):
        plan = self.plan(data)
        if plan != review:
            raise HistoryError("REVISAO_OU_DESTINO_ALTERADO")
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        count = 0
        for title, changes in plan["changes"].items():
            for offset in range(0, len(changes), 200):
                batch = changes[offset : offset + 200]
                snapshot = self.store.native_meta_read(title, SCHEMAS[title])
                # Conferir novamente antes da primeira gravação de cada tabela.
                if offset == 0 and snapshot != plan["snapshots"][title]:
                    raise HistoryError("PLANILHA_ALTERADA_APOS_REVISAO")
                path = self.backup_dir / (uuid4().hex + ".json")
                path.write_text(
                    json.dumps(
                        {"title": title, "snapshot": snapshot, "batch": batch},
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                path.chmod(0o600)
                self.store.native_meta_upsert_chunk(
                    title,
                    SCHEMAS[title],
                    [typed_cells(r) for r in batch],
                    expected_snapshot=snapshot,
                )
                checked = self.store.native_meta_read(title, SCHEMAS[title])["values"]
                observed = {
                    str(r[0]): dict(
                        zip(
                            SCHEMAS[title],
                            [str(v) for v in r] + [""] * (len(SCHEMAS[title]) - len(r)),
                            strict=True,
                        )
                    )
                    for r in checked[1:]
                    if r
                }
                if any(
                    normalized_cells(observed.get(r["chave"], {})) != r for r in batch
                ):
                    raise HistoryError("GRAVACAO_NAO_CONFIRMADA")
                count += len(batch)
        return count
