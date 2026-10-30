"""Reparo BI nativo em continuações, com comprovantes por arquivo."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from google.auth.exceptions import TransportError
from gspread.exceptions import APIError
from requests import RequestException

import dedup_bi as core
from sheets_continuation import ContinuationError, fingerprint


def split_table(title, change, snapshots):
    """Converte linhas lógicas em índices locais, sem reescrever fatos financeiros."""
    tables = {}
    offset = 0
    for part, ws, values in snapshots:
        first, last = offset + 2, offset + len(values)
        updates = [
            {**update, "row": update["row"] - offset}
            for update in change["updates"]
            if first <= update["row"] <= last
        ]
        deletions = [
            row - offset for row in change["deletions"] if first <= row <= last
        ]
        after = deepcopy(values)
        for update in updates:
            row, col = update["row"] - 1, update["column"] - 1
            after[row].extend([""] * max(0, col + 1 - len(after[row])))
            after[row][col] = update["value"]
        for number in sorted(deletions, reverse=True):
            del after[number - 1]
        key = f"{title}::{part.book_id}::{part.sheet_id}"
        tables[key] = {
            "title": title,
            "book": part.book_id,
            "sheet_id": ws.id,
            "part": part.number,
            "updates": updates,
            "deletions": deletions,
            "before": values,
            "after": after,
            "before_hash": core.digest(core.trimmed(values)),
            "after_hash": core.digest(core.trimmed(after)),
        }
        offset += len(values) - 1
    if sum(len(v["updates"]) for v in tables.values()) != len(change["updates"]) or sum(
        len(v["deletions"]) for v in tables.values()
    ) != len(change["deletions"]):
        raise ContinuationError("Uma linha BI não corresponde às continuações atuais.")
    return tables


def read_table(store, title, *, formatted=False):
    manager = store.continuity
    snapshots, result = [], []
    for _, ws, part in store.locations(title):
        values = core.read_values(ws, formatted=formatted)
        if not values:
            raise ContinuationError(f"Aba BI sem cabeçalho: {title}.")
        if part is None:
            part = manager.register_root(ws, values[0])[0]
        if fingerprint(values[0]) != part.schema:
            raise ContinuationError(
                "O schema da continuação mudou; reparo BI bloqueado."
            )
        if result and values[0] != result[0]:
            raise ContinuationError("Cabeçalhos diferentes entre continuações BI.")
        result.extend(values if not result else values[1:])
        snapshots.append((part, ws, values))
    if not snapshots:
        raise ContinuationError(f"Fonte BI ausente: {title}.")
    return result, snapshots


def read_state(store):
    store.refresh_handles()
    sources = {
        title: read_table(store, title, formatted=True)[0]
        for title in core.SOURCE_TITLES
    }
    current, snapshots = {}, {}
    for title in core.TARGET_TITLES:
        current[title], snapshots[title] = read_table(store, title)
    controls = core.read_values(store.handles[store.layout.operations]["Controle"])
    return sources, current, controls, snapshots


def receipt_path(directory, book_id):
    return directory / ("bi_parts_receipt_" + fingerprint(book_id)[:12] + ".json")


def matches_current(tables, snapshots, field):
    current = {
        (part.book_id, ws.id): values
        for parts in snapshots.values()
        for part, ws, values in parts
    }
    return all(
        core.digest(core.trimmed(current.get((t["book"], t["sheet_id"]), [])))
        == t[field]
        for t in tables.values()
    )


def refresh(store, removed_uuids, delivery_keys, directory):
    manager, directory = store.continuity, Path(directory)
    manager.require()
    if fingerprint(manager.sheet.get_all_values()) != manager.persisted_hash:
        raise ContinuationError("O índice mudou antes do reparo BI.")
    old_receipt = directory / "bi_receipt.json"
    if (
        old_receipt.is_file()
        and json.loads(old_receipt.read_text(encoding="utf-8")).get("state")
        == "sending"
    ):
        raise ContinuationError(
            "Há uma aplicação BI anterior à continuação sem confirmação; preservar para revisão."
        )
    path = directory / "bi_parts_plan.json"
    sources, current, controls, snapshots = read_state(store)
    plan = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    if plan is not None:
        if (
            plan.get("hub") != manager.index.config["hub"]
            or plan.get("segment") != manager.index.config["segment"]
        ):
            raise ContinuationError("O plano BI pertence a outro segmento.")
        if plan["sources_hash"] != core.digest(sources) or plan[
            "controls_hash"
        ] != core.digest(controls):
            for receipt in directory.glob("bi_parts_receipt_*.json"):
                evidence = json.loads(receipt.read_text(encoding="utf-8"))
                if evidence.get("state") == "sending":
                    selected = {
                        k: t
                        for k, t in plan["tables"].items()
                        if t["book"] == evidence["book"]
                    }
                    if not matches_current(selected, snapshots, "after_hash"):
                        raise ContinuationError(
                            "Fontes mudaram e um envio BI segue incerto. Exclusões não serão repetidas."
                        )
            archive = directory / ("bi_parts_previous_" + uuid4().hex)
            archive.mkdir(parents=True, mode=0o700)
            for previous in [
                path,
                *directory.glob("bi_parts_receipt_*.json"),
                directory / "bi_parts_sources.json",
                directory / "bi_parts_native",
            ]:
                if previous.exists():
                    previous.replace(archive / previous.name)
            plan = None
    if plan is None:
        mapping = {row[0]: str(row[1]) for row in controls[1:] if len(row) >= 2}
        desired, cutoff = core.prepare_targets(
            sources,
            current,
            mapping,
            removed_uuids=set(removed_uuids),
            updated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        )
        plan = {
            "hub": manager.index.config["hub"],
            "segment": manager.index.config["segment"],
            "operation": uuid4().hex,
            "sources_hash": core.digest(sources),
            "controls_hash": core.digest(controls),
            "snapshot_date": cutoff,
            "tables": {},
        }
        for title in core.TARGET_TITLES:
            change = core.diff_table(
                title,
                current[title],
                desired[title],
                removed_uuids=set(removed_uuids),
                allowed_delivery_removals=frozenset(delivery_keys),
            )
            plan["tables"].update(split_table(title, change, snapshots[title]))
        for book_id in sorted({t["book"] for t in plan["tables"].values()}):
            tables = {
                t["title"]: t for t in plan["tables"].values() if t["book"] == book_id
            }
            body = core.requests_for({"tables": tables})
            if len(json.dumps(body, ensure_ascii=False).encode()) > 1_500_000:
                raise ContinuationError(
                    "Lote BI excede 1,5 MB; nenhuma escrita foi iniciada."
                )
            backup = directory / "bi_parts_native" / fingerprint(book_id)[:12]
            backup.mkdir(parents=True, exist_ok=True, mode=0o700)
            core.backup_native(store.books[book_id], tables, backup)
        core.save(
            directory / "bi_parts_sources.json",
            {"sources": sources, "Controle": controls},
        )
        core.save(path, plan)
    titles = {
        t["title"]
        for t in plan["tables"].values()
        if t["before_hash"] != t["after_hash"]
    }
    for title in titles:
        state = manager.index.status.get(title, {})
        if (
            state.get("state") == "WRITING"
            and state.get("revision") != plan["operation"]
        ):
            raise ContinuationError(
                "Há outra gravação BI incompleta; retome o Analytics antes da limpeza."
            )
        manager.index.status[title] = {
            "state": "WRITING",
            "revision": plan["operation"],
        }
    if titles:
        manager.save()
    for book_id in sorted({t["book"] for t in plan["tables"].values()}):
        tables = {
            t["title"]: t for t in plan["tables"].values() if t["book"] == book_id
        }
        evidence_path = receipt_path(directory, book_id)
        evidence = (
            json.loads(evidence_path.read_text(encoding="utf-8"))
            if evidence_path.is_file()
            else {}
        )
        if evidence and evidence.get("plan_hash") != fingerprint(plan):
            raise ContinuationError("Comprovante BI divergente do plano revisado.")
        if matches_current(tables, snapshots, "after_hash"):
            core.save(
                evidence_path,
                {"state": "verified", "book": book_id, "plan_hash": fingerprint(plan)},
            )
            continue
        if evidence.get("state") == "sending":
            raise ContinuationError(
                "Envio BI anterior incerto; reenvio de exclusões bloqueado."
            )
        if not matches_current(tables, snapshots, "before_hash"):
            raise ContinuationError(
                "Uma continuação BI mudou; índices antigos não serão reutilizados."
            )
        body = core.requests_for({"tables": tables})
        manager.require()
        core.save(
            evidence_path,
            {"state": "sending", "book": book_id, "plan_hash": fingerprint(plan)},
        )
        try:
            if body:
                store.books[book_id].batch_update({"requests": body})
        except APIError as exc:
            if (
                400 <= exc.response.status_code < 500
                and exc.response.status_code not in (408, 499)
            ):
                core.save(
                    evidence_path,
                    {
                        "state": "rejected",
                        "book": book_id,
                        "plan_hash": fingerprint(plan),
                    },
                )
            else:
                manager.lease.note_uncertain()
            raise
        except (RequestException, TransportError):
            manager.lease.note_uncertain()
            raise
        for title, table in tables.items():
            ws = store.books[book_id].get_worksheet_by_id(table["sheet_id"])
            values = core.read_values(
                ws, phase="conferência da continuação após reparo"
            )
            if core.digest(core.trimmed(values)) != table["after_hash"]:
                raise ContinuationError(
                    "A continuação BI divergiu após o reparo; não repetir índices."
                )
            old = snapshots[title]
            snapshots[title] = [
                (part, ws, values)
                if part.book_id == book_id
                else (part, previous, data)
                for part, previous, data in old
            ]
        core.save(
            evidence_path,
            {"state": "verified", "book": book_id, "plan_hash": fingerprint(plan)},
        )
    if (
        core.digest(
            core.read_values(store.handles[store.layout.operations]["Controle"])
        )
        != plan["controls_hash"]
    ):
        raise ContinuationError(
            "Controle mudou durante o reparo BI; preservar comprovantes."
        )
    for title in titles:
        manager.index.status[title] = {
            "state": "READY",
            "revision": uuid4().hex,
            "parts": [
                {"number": part.number, "rows": len(values) - 1}
                for part, _, values in snapshots[title]
            ],
        }
    if titles:
        manager.save()
