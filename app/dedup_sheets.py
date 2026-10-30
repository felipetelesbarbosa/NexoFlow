"""Limpeza nativa das fontes dos duplicados; não inicializa nem migra schemas."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import gspread
from gspread.exceptions import APIError
from gspread.utils import ValueRenderOption

from analytics import is_valid_cpf, normalize_cpf
from config import GOOGLE_CREDENTIALS_FILE, WENI_PROGRESS_INTERVAL_SECONDS
from contact_dedup_guard import contact_refusals, customer_phones, native_phones
from dedup_io import DedupHTTPClient, digest, save_private
from farmalider_integration import _positive_id
from google_sheets import GoogleSheetsStore, column_letter
from sheets_storage import STORAGE_SHEET, SheetsStorage, configured_storage
from task_progress import TaskProgress, request_progress

if TYPE_CHECKING:
    from sheets_partitions import RolloverManager


SOURCE_TABS = (
    "Base_Contatos",
    "Pedidos_FarmaLider",
    "Itens_Pedidos_FarmaLider",
    "Tickets_Delivery_Weni",
    "Eventos_Anuncios",
    "Historico_Alteracoes",
)
IDENTITY_COLUMNS = {
    "Pedidos_FarmaLider": {
        "contact_uuid",
        "telefone",
        "cliente",
        "cpf",
        "cpf_normalizado",
        "farmalider_cliente_id",
    },
    "Itens_Pedidos_FarmaLider": {"contact_uuid", "telefone", "cliente"},
}


def plain(cell):
    value = cell.get("userEnteredValue", {})
    for kind in ("formulaValue", "stringValue", "numberValue", "boolValue"):
        if kind in value:
            return str(value[kind])
    return ""


def diagnostic_order(row):
    monetary = {
        h
        for h in row
        if h.startswith(("valor_", "total_", "quantidade_", "diferenca_"))
    } | {"farmalider_frete"}
    return (
        not _positive_id(row.get("pedido_id"))
        and row.get("status_confirmacao")
        in {"CPF_IDENTIDADE_DIVERGENTE", "CPF_REJEITADO_API"}
        and row.get("origem_pedido") == "FARMALIDER_CLIENTE_ULTIMO_PEDIDO"
        and all(not str(row.get(h) or "").strip() for h in monetary)
    )


def record(table, row):
    return dict(zip(table["headers"], (plain(c) for c in row), strict=True))


def cell_request(table, number, name, value):
    col = table["headers"].index(name)
    before = table["cells"][str(number)][col]
    if before.get("dataValidation") or "formulaValue" in before.get(
        "userEnteredValue", {}
    ):
        raise ValueError(
            "Célula de identidade contém fórmula ou validação; exige revisão."
        )
    return {
        "updateCells": {
            "range": {
                "sheetId": table["id"],
                "startRowIndex": int(number) - 1,
                "endRowIndex": int(number),
                "startColumnIndex": col,
                "endColumnIndex": col + 1,
            },
            "rows": [{"values": [{"userEnteredValue": {"stringValue": str(value)}}]}],
            "fields": "userEnteredValue",
        }
    }


def requests_for(tables, pairs, canonicals):
    """Somente identidade H:M/G:I; nenhum pedido/itens financeiros é excluído."""
    pairs = {p["duplicate_uuid"]: p for p in pairs}
    requests = {}
    delivery_keys = set()
    for table_key, table in tables.items():
        title = table.get("source_title", table_key)
        updates, deletions = [], []
        for number, cells in table["cells"].items():
            row = record(table, cells)
            uid = row["contact_uuid"]
            if uid not in pairs:
                if (
                    title == "Base_Contatos"
                    and uid in canonicals
                    and any(p["canonical_uuid"] == uid for p in pairs.values())
                    and contact_refusals(canonicals[uid])["lgpd_refused"]
                ):
                    if row.get("opt_in_lgpd") != "recusado":
                        updates.append(
                            cell_request(table, number, "opt_in_lgpd", "recusado")
                        )
                continue
            pair = pairs[uid]
            can = canonicals[pair["canonical_uuid"]]
            if title in IDENTITY_COLUMNS:
                oid = _positive_id(row.get("pedido_id"))
                if title == "Pedidos_FarmaLider" and diagnostic_order(row):
                    # Um diagnóstico com itens não é um registro descartável.
                    if row.get("pedido_chave") in table.get("item_order_keys", []):
                        raise ValueError(
                            "Diagnóstico sem ID possui itens; exclusão bloqueada."
                        )
                    deletions.append(int(number))
                    continue
                if (
                    title == "Itens_Pedidos_FarmaLider"
                    and table.get("ledger_orders", {}).get(row.get("pedido_chave"))
                    != oid
                ):
                    raise ValueError(
                        "Item não corresponde à chave e ao ID do pedido no histórico operacional."
                    )
                capa = pair["orders"].get(oid, {}).get("capa", {})
                if (
                    not oid
                    or _positive_id(capa.get("id")) != oid
                    or _positive_id(capa.get("codCliente")) != pair["customer_id"]
                ):
                    raise ValueError(
                        "Pedido sem proprietário comprovado; limpeza bloqueada."
                    )
                owners = {
                    _positive_id(row.get(h))
                    for h in ("farmalider_cliente_id", "farmalider_cod_cliente")
                } - {""}
                if owners - {pair["customer_id"]}:
                    raise ValueError(
                        "Pedido já vinculado a outro cliente; limpeza bloqueada."
                    )
                matches = sorted(customer_phones(pair["customer"]) & native_phones(can))
                if not matches:
                    raise ValueError(
                        "Telefone do contato correto não está mais comprovado."
                    )
                changes = {
                    "contact_uuid": pair["canonical_uuid"],
                    "telefone": "+55" + matches[0],
                    "cliente": pair["customer"].get("nome") or can.get("name", ""),
                }
                if title == "Pedidos_FarmaLider":
                    changes.update(
                        cpf=pair["cpf"],
                        cpf_normalizado=pair["cpf"],
                        farmalider_cliente_id=pair["customer_id"],
                    )
                for name, value in changes.items():
                    # Cabeçalho autoritativo; também aceita a ordem canônica dos schemas
                    # em instalações novas, sem assumir uma posição física antiga.
                    if name not in IDENTITY_COLUMNS[title]:
                        raise ValueError("Campo fora da identidade.")
                    if row.get(name) != str(value):
                        updates.append(cell_request(table, number, name, value))
            else:
                if title == "Tickets_Delivery_Weni" and row.get("pedido_chave"):
                    delivery_keys.add(row["pedido_chave"])
                deletions.append(int(number))
        updates.extend(
            {
                "deleteDimension": {
                    "range": {
                        "sheetId": table["id"],
                        "dimension": "ROWS",
                        "startIndex": n - 1,
                        "endIndex": n,
                    }
                }
            }
            for n in sorted(deletions, reverse=True)
        )
        requests[table_key] = updates
    return requests, delivery_keys


def verify_transaction(entry, current, removed):
    """Confirma vínculos por chave, valores preservados e ausências, sem reenviar."""
    if digest(entry["requests"]) != entry["requests_sha256"]:
        raise ValueError("Comprovante de escrita alterado.")
    titles = {v["id"]: title for title, v in entry["backup"].items()}
    for title in entry["backup"]:
        if (
            title not in current
            or current[title]["id"] != entry["backup"][title]["id"]
            or current[title]["headers"] != entry["backup"][title]["headers"]
        ):
            raise ValueError("Aba ou cabeçalho mudou após a transação.")
        if any(
            record(current[title], cells).get("contact_uuid") in removed
            for cells in current[title]["cells"].values()
        ):
            raise RuntimeError(
                "Limpeza anterior sem confirmação; reenvio de índices bloqueado."
            )
    changes = {}
    for req in entry["requests"]:
        if "updateCells" not in req:
            continue
        update = req["updateCells"]
        grid = update["range"]
        title = titles[grid["sheetId"]]
        row = str(grid["startRowIndex"] + 1)
        changes.setdefault((title, row), {})[grid["startColumnIndex"]] = update["rows"][
            0
        ]["values"][0]["userEnteredValue"]
    for (title, row), columns in changes.items():
        old = entry["backup"][title]
        key = {
            "Pedidos_FarmaLider": "pedido_chave",
            "Itens_Pedidos_FarmaLider": "item_chave",
            "Base_Contatos": "contact_uuid",
        }[old.get("source_title", title)]
        before = old["cells"][row]
        identity = record(old, before)[key]
        matches = [
            cells
            for cells in current[title]["cells"].values()
            if record(current[title], cells).get(key) == identity
        ]
        if len(matches) != 1:
            raise RuntimeError("Registro corrigido sem chave única no readback.")
        after = matches[0]
        for col, cell in enumerate(before):
            expected = columns.get(col, cell.get("userEnteredValue", {}))
            if after[col].get("userEnteredValue", {}) != expected:
                raise RuntimeError("Vínculo ou valor original divergiu após a limpeza.")


class DedupSheets:
    continuity: RolloverManager | None = None

    def __init__(self, hub_id: str):
        self.continuity = None
        self.client = gspread.service_account(
            filename=str(GOOGLE_CREDENTIALS_FILE), http_client=DedupHTTPClient
        )
        self.client.set_timeout((10, 120))
        self.hub = self.client.open_by_key(hub_id)
        try:
            tabs = {w.title: w for w in self.hub.worksheets()}
            configured = configured_storage(hub_id)
            self.layout = (
                SheetsStorage.from_values(tabs[STORAGE_SHEET].get("A1:B5"), hub_id)
                if STORAGE_SHEET in tabs
                else configured or SheetsStorage(hub_id, hub_id, hub_id)
            )
            if configured is not None and self.layout != configured:
                raise ValueError("Os IDs locais divergem do mapa NexoFlow_Arquivos.")
            from runtime_profile import validate_sheet_destinations

            validate_sheet_destinations(
                self.layout.dashboard, self.layout.operations, self.layout.history
            )
            self.books: dict[str, Any] = {hub_id: self.hub}
            for key in (self.layout.operations, self.layout.history):
                if key not in self.books:
                    self.books[key] = self.client.open_by_key(key)
            self.handles: dict[str, dict[str, Any]] = {
                key: {w.title: w for w in book.worksheets()}
                for key, book in self.books.items()
            }
            from sheets_continuation import INDEX_TITLE
            from sheets_partitions import RolloverManager

            if INDEX_TITLE in tabs:
                # Contexto sem __init__: ler a auditoria não cria abas nem migra schemas.
                context = GoogleSheetsStore.__new__(GoogleSheetsStore)
                context.book, context.client = self.hub, self.client
                context._hub_id, context._storage_layout = hub_id, self.layout
                context._storage_books = self.books
                context._headers_cache = {}
                context._last_write_started_at = 0.0
                context._read_requests = context._write_requests = 0
                self.continuity = RolloverManager.attach(context, tabs[INDEX_TITLE])
                context._continuity = self.continuity
                assert self.continuity is not None
                self.books = self.continuity.books

        except Exception:
            self.close()
            raise

    def close(self):
        try:
            if self.continuity is not None:
                self.continuity.close()
        finally:
            self.client.http_client.session.close()

    def locations(self, title):
        """Localizadores físicos; a simulação não escreve no índice."""
        manager = self.continuity
        parts = manager.index.table_parts(title) if manager is not None else []
        if parts:
            assert manager is not None
            result = []
            for part in parts:
                ws = self.handles.get(part.book_id, {}).get(title)
                if ws is None or ws.id != part.sheet_id:
                    ws = manager.worksheet(part)
                if part.book_id not in self.handles:
                    self.handles[part.book_id] = {
                        w.title: w for w in self.books[part.book_id].worksheets()
                    }
                result.append((part.book_id, ws, part))
            return result
        book_id = self.layout.destination(title)
        ws = self.handles[book_id].get(title)
        return [(book_id, ws, None)] if ws is not None else []

    def refresh_handles(self):
        self.handles = {
            key: {ws.title: ws for ws in book.worksheets()}
            for key, book in self.books.items()
        }
        if self.continuity is not None:
            self.continuity.handles.clear()

    def scan(self, ws, name, headers):
        letter = column_letter(headers.index(name) + 1)
        result: dict[str, str] = {}
        for first in range(2, ws.row_count + 1, 30000):
            values = ws.get(
                f"{letter}{first}:{letter}{min(first + 29999, ws.row_count)}",
                value_render_option=ValueRenderOption.formula,
            )
            result.update(
                {
                    str(first + i): str(row[0])
                    for i, row in enumerate(values)
                    if row and row[0] not in ("", None)
                }
            )
        if name == "contact_uuid" and any(
            value.startswith("=") for value in result.values()
        ):
            raise ValueError("UUID calculado por fórmula impede uma limpeza segura.")
        return result

    def capture(self, targets):
        """Lê candidatos em todas as partes; preserva linhas e células nativas."""
        from sheets_continuation import fingerprint

        tables, ledger_ids, ledger_orders, item_keys = {}, set(), {}, set()
        with TaskProgress(
            "Weni: fontes da deduplicação",
            len(SOURCE_TABS),
            unit="abas",
            interval=WENI_PROGRESS_INTERVAL_SECONDS,
            show_nested=True,
        ) as progress:
            for title in progress.track(SOURCE_TABS):
                locations = self.locations(title)
                if not locations:
                    if title in ("Eventos_Anuncios", "Tickets_Delivery_Weni"):
                        continue
                    raise ValueError(
                        f"Aba {title} ausente. Execute o Analytics antes da deduplicação."
                    )
                for book_id, ws, part in locations:
                    progress.set_activity(
                        f"aba em conferência: {title}; parte={part.number if part else 0}"
                    )
                    header = ws.get(
                        f"A1:{column_letter(ws.col_count)}1",
                        value_render_option=ValueRenderOption.formula,
                    )
                    headers = list(header[0]) if header else []
                    if (
                        not headers
                        or any(not isinstance(h, str) or not h for h in headers)
                        or len(headers) != len(set(headers))
                        or "contact_uuid" not in headers
                        or (
                            part is not None
                            and (
                                len(headers) != part.width
                                or fingerprint(headers) != part.schema
                            )
                        )
                    ):
                        raise ValueError(f"Cabeçalho inválido em {title}.")
                    if title == "Pedidos_FarmaLider":
                        ids = self.scan(ws, "pedido_id", headers)
                        keys = self.scan(ws, "pedido_chave", headers)
                        if len(keys.values()) != len(set(keys.values())) or set(
                            keys.values()
                        ) & set(ledger_orders):
                            raise ValueError(
                                "Chave de pedido duplicada nas fontes e continuações."
                            )
                        ledger_ids.update(
                            {_positive_id(v) for v in ids.values()} - {""}
                        )
                        ledger_orders.update(
                            {key: _positive_id(ids.get(n)) for n, key in keys.items()}
                        )
                    if title == "Itens_Pedidos_FarmaLider":
                        item_keys.update(
                            self.scan(ws, "pedido_chave", headers).values()
                        )
                    identifiers = self.scan(ws, "contact_uuid", headers)
                    numbers = sorted(
                        int(n) for n, uid in identifiers.items() if uid in targets
                    )
                    cells = {}
                    for start in range(0, len(numbers), 40):
                        ranges = [
                            f"'{title}'!A{n}:{column_letter(len(headers))}{n}"
                            for n in numbers[start : start + 40]
                        ]
                        response = self.books[book_id].fetch_sheet_metadata(
                            params={
                                "includeGridData": True,
                                "ranges": ranges,
                                "fields": "sheets(properties(sheetId),data(startRow,startColumn,rowData(values(userEnteredValue,userEnteredFormat,dataValidation))))",
                            }
                        )
                        for sheet in response.get("sheets", []):
                            if sheet["properties"]["sheetId"] != ws.id:
                                raise ValueError("Leitura nativa retornou outra aba.")
                            for block in sheet.get("data", []):
                                data = block.get("rowData", [])
                                row = data[0].get("values", []) if data else []
                                cells[str(block.get("startRow", 0) + 1)] = row + [
                                    {} for _ in range(len(headers) - len(row))
                                ]
                    if set(cells) != set(map(str, numbers)):
                        raise ValueError("Backup nativo incompleto.")
                    table_key = (
                        title
                        if part is None or part.number == 0
                        else f"{title}::{book_id}::{ws.id}"
                    )
                    tables[table_key] = {
                        "id": ws.id,
                        "book": book_id,
                        "source_title": title,
                        "headers": headers,
                        "cells": cells,
                    }
        for table in tables.values():
            if table["source_title"] == "Pedidos_FarmaLider":
                table["item_order_keys"] = sorted(item_keys)
            if table["source_title"] == "Itens_Pedidos_FarmaLider":
                table["ledger_orders"] = ledger_orders
        return tables, ledger_ids

    @staticmethod
    def context_for(tables, uid, cpf, ledger_ids):
        refs, owners, reasons = set(), set(), []
        for title, table in tables.items():
            for cells in table["cells"].values():
                row = record(table, cells)
                if row["contact_uuid"] != uid:
                    continue
                for h in ("farmalider_cliente_id", "farmalider_cod_cliente"):
                    owner = _positive_id(row.get(h))
                    if owner:
                        owners.add(owner)
                old_cpf = normalize_cpf(row.get("cpf_normalizado") or row.get("cpf"))
                if is_valid_cpf(old_cpf) and old_cpf != cpf:
                    reasons.append("HISTORICO_CPF_DIFERENTE")
                oid = _positive_id(row.get("pedido_id"))
                if oid:
                    refs.add(oid)
                    if (
                        table.get("source_title", title) == "Historico_Alteracoes"
                        and oid not in ledger_ids
                    ):
                        reasons.append("PEDIDO_HISTORICO_SEM_LEDGER")
        return refs, owners, reasons

    def cleanup(self, pairs, canonicals, directory):
        """Backup e transação por arquivo; reenvio de exclusão incerta é bloqueado."""
        if self.continuity is not None:
            self.continuity.require()
            current = self.continuity.sheet.get_all_values()
            from sheets_continuation import ContinuationError, fingerprint

            if fingerprint(current) != self.continuity.persisted_hash:
                raise ContinuationError(
                    "O índice de continuações mudou; gere uma nova auditoria de duplicados."
                )
            if any(
                v.get("pending_history") for v in self.continuity.index.status.values()
            ):
                raise ContinuationError(
                    "Há histórico incompleto; retome o Analytics antes da deduplicação."
                )
        targets = {p[k] for p in pairs for k in ("duplicate_uuid", "canonical_uuid")}
        tables, ledger = self.capture(targets)
        for pair in pairs:
            refs, owners, reasons = self.context_for(
                tables, pair["duplicate_uuid"], pair["cpf"], ledger
            )
            if (
                reasons
                or owners - {pair["customer_id"]}
                or not refs <= set(pair["orders"])
            ):
                raise ValueError(
                    "Fonte mudou após a revisão; limpeza preservada para conferência."
                )
            if (
                sum(
                    record(table, row)["contact_uuid"] == pair["canonical_uuid"]
                    for key, table in tables.items()
                    if table.get("source_title", key) == "Base_Contatos"
                    for row in table["cells"].values()
                )
                != 1
            ):
                raise ValueError("Contato correto não tem uma única linha na Base.")
        requests, keys = requests_for(tables, pairs, canonicals)
        removed = {p["duplicate_uuid"] for p in pairs}
        for book_id in sorted({t["book"] for t in tables.values()}):
            role = (
                "history"
                if book_id == self.layout.history
                and self.layout.history != self.layout.operations
                else "operations"
            )
            suffix = (
                ""
                if book_id in {self.layout.operations, self.layout.history}
                else "-" + digest(book_id)[:12]
            )
            path = Path(directory) / f"{role}{suffix}.json"
            selected = {t: v for t, v in tables.items() if v["book"] == book_id}
            body = [q for t in selected for q in requests[t]]
            previous = (
                json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
            )
            if previous and previous["state"] in ("sending", "uncertain"):
                verify_transaction(previous, tables, removed)
                previous["state"] = "verified_by_readback"
                save_private(path, previous)
                continue
            if previous and previous["state"] == "rejected":
                path.replace(
                    path.with_name(path.stem + "-rejected-" + uuid4().hex + ".json")
                )
                previous = None
            if not body:
                continue
            if len(json.dumps(body, ensure_ascii=False).encode()) > 1_500_000:
                raise ValueError(
                    "Lote de deduplicação maior que 1,5 MB. Nenhuma escrita neste arquivo foi iniciada."
                )
            # O arquivo é imutável depois do primeiro envio; não perder prova de uma retomada.
            if previous:
                raise RuntimeError(
                    "Arquivo já processado contém novamente um contato excluído. Exige nova revisão."
                )
            entry = {
                "state": "sending",
                "book": book_id,
                "backup": selected,
                "requests": body,
                "requests_sha256": digest(body),
            }
            save_private(path, entry)
            try:
                with request_progress(f"limpeza das fontes: {role}"):
                    if self.continuity is not None:
                        self.continuity.require()
                    self.books[book_id].batch_update({"requests": body})
            except Exception as exc:
                code = exc.response.status_code if isinstance(exc, APIError) else 0
                entry["state"] = (
                    "rejected"
                    if 400 <= code < 500 and code not in (408, 499)
                    else "uncertain"
                )
                if entry["state"] == "uncertain" and self.continuity is not None:
                    self.continuity.lease.note_uncertain()
                entry["error_type"] = type(exc).__name__
                save_private(path, entry)
                raise
            # Metadados do Worksheet em cache não podem manter rowCount anterior.
            self.handles[book_id] = {
                w.title: w for w in self.books[book_id].worksheets()
            }
            fresh, _ = self.capture(targets)
            verify_transaction(entry, fresh, removed)
            entry["state"] = "verified"
            save_private(path, entry)
        if self.continuity is not None:
            affected = {
                tables[title].get("source_title", title)
                for title, body in requests.items()
                if body
            }
            for title in sorted(affected):
                self.continuity.finish(self.locations(title)[0][1])
        return keys
