"""Leitura incremental de eventos CTWA oficiais, sem interpretar texto do cliente."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from task_progress import TaskProgress
from urn_utils import native_contact_urns, urn_channel
from weni_client import WeniError


def event_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return result.astimezone(UTC) if result.tzinfo is not None else None


def event_message(event: dict[str, Any]) -> dict[str, Any] | None:
    """Adapta apenas o contrato CTWA confirmado na API, sem inventar headline/URL."""
    if event.get("event_name") != "ctwa":
        return None
    meta = event.get("metadata")
    if not isinstance(meta, dict):
        raise ValueError("CTWA_SEM_METADATA")
    urn = event.get("contact_urn")
    date = event_datetime(event.get("date"))
    required = ("campaign_source", "channel", "ctwa_id", "external_msg_id")
    if (
        not isinstance(urn, str)
        or urn_channel(urn) != "whatsapp"
        or not urn.startswith("whatsapp:")
        or not urn.removeprefix("whatsapp:").isdecimal()
        or date is None
        or any(
            not isinstance(meta.get(k), str) or not meta[k].strip() for k in required
        )
        or not meta["campaign_source"].isdecimal()
    ):
        raise ValueError("CTWA_INCOMPLETO")
    # O identificador externo não é impresso nos logs gerais.
    identity = "\n".join((urn, meta["channel"], meta["external_msg_id"]))
    return {
        "id": "ctwa:" + hashlib.sha256(identity.encode()).hexdigest(),
        "created_on": date.isoformat(),
        "direction": "in",
        "urn": urn,
        "text": "",
        "event_source": "weni_events_ctwa",
        "metadata": {
            "referral": {
                "source_type": "ad",
                "source_id": meta["campaign_source"],
                "ctwa_clid": meta["ctwa_id"],
            }
        },
    }


@dataclass
class MetaEvents:
    by_contact: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    report: dict[str, Any] = field(default_factory=dict)


def read_meta_events(
    weni,
    contacts: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    *,
    before: datetime,
    state: dict[str, Any],
    full: bool,
    initial_days: int,
    overlap_minutes: int,
) -> MetaEvents:
    fallback = before - timedelta(days=initial_days)
    checkpoint = event_datetime(state.get("meta_events_next_after_utc"))
    if checkpoint is not None and checkpoint > before:
        checkpoint = None
    after = (
        (checkpoint - timedelta(minutes=overlap_minutes)) if checkpoint else fallback
    )
    if full:
        dates = [
            d
            for m in messages
            if (d := event_datetime(m.get("created_on"))) and d < before
        ]
        after = min(dates + [after])
    batch = MetaEvents(
        report={
            "after": after.isoformat(),
            "before": before.isoformat(),
            "read": 0,
            "linked": 0,
            "invalid": 0,
            "unmatched": 0,
            "ambiguous": 0,
            "failed_batches": 0,
            "pending_from": "",
        }
    )
    index: dict[str, set[str]] = {}
    for contact in contacts:
        uid = str(contact.get("uuid") or "").strip()
        if uid:
            for urn in native_contact_urns(contact):
                index.setdefault(urn, set()).add(uid)
    pending: list[datetime] = []
    seen: dict[str, dict[str, Any]] = {}
    conflicting: set[str] = set()
    windows = max(
        1,
        (before - after + timedelta(days=7) - timedelta(microseconds=1))
        // timedelta(days=7),
    )
    with TaskProgress(
        "Weni: eventos de anúncios Meta", windows, unit="lotes"
    ) as progress:
        start = after
        while start < before:
            end = min(start + timedelta(days=7), before)
            try:
                events = weni.list_ctwa_events(after=start, before=end)
                if not isinstance(events, list):
                    raise ValueError("FORMATO_EVENTOS_INVALIDO")
                for raw in events:
                    batch.report["read"] += 1
                    try:
                        message = event_message(raw)
                    except (ValueError, TypeError, AttributeError):
                        batch.report["invalid"] += 1
                        pending.append(start)
                        continue
                    if message is None:
                        continue
                    date = event_datetime(message["created_on"])
                    if date is None or not start <= date < end:
                        continue
                    mid = message["id"]
                    if mid in seen:
                        if seen[mid] != message:
                            conflicting.add(mid)
                            pending.append(start)
                            batch.report["invalid"] += 1
                        continue
                    seen[mid] = message
            except WeniError as exc:
                if exc.status_code in {401, 403}:
                    raise
                batch.report["failed_batches"] += 1
                pending.append(start)
            except (RuntimeError, ValueError):
                batch.report["failed_batches"] += 1
                pending.append(start)
            start = end
            progress.advance()
    for mid, message in seen.items():
        if mid in conflicting:
            continue
        candidates = index.get(message["urn"], set())
        if len(candidates) != 1:
            batch.report["ambiguous" if candidates else "unmatched"] += 1
            pending.append(event_datetime(message["created_on"]) or after)
            continue
        uid = next(iter(candidates))
        message["contact"] = {"uuid": uid}
        batch.by_contact.setdefault(uid, []).append(message)
        batch.report["linked"] += 1
    if pending:
        batch.report["pending_from"] = min(pending).isoformat()
    if batch.report["failed_batches"]:
        logging.warning(
            "Weni: %s lote(s) de eventos Meta pendente(s); demais dados preservados e nova consulta na próxima carga.",
            batch.report["failed_batches"],
        )
    batch.report["contact_dates"] = {
        uid: min(m["created_on"] for m in events)
        for uid, events in batch.by_contact.items()
    }
    logging.info(
        "Weni: anúncios Meta | eventos=%s; vinculados=%s; sem vínculo=%s; ambíguos=%s; inválidos=%s; lotes pendentes=%s.",
        *(
            batch.report[k]
            for k in (
                "read",
                "linked",
                "unmatched",
                "ambiguous",
                "invalid",
                "failed_batches",
            )
        ),
    )
    return batch


def meta_event_state(report, previous, plans, conflicted_uuids, *, quarter=None):
    """O cursor Meta não salta lotes ou gravações que ainda estão pendentes."""
    if not report:
        return {k: v for k, v in previous.items() if k == "meta_events_next_after_utc"}
    before = event_datetime(report.get("before"))
    after = event_datetime(report.get("after"))
    if before is None or after is None:
        return {}
    candidates = [before]
    if pending := event_datetime(report.get("pending_from")):
        candidates.append(pending)
    if quarter is not None:
        candidates.append(
            event_datetime(previous.get("meta_events_next_after_utc")) or after
        )
    for uid in conflicted_uuids:
        if date := event_datetime(report.get("contact_dates", {}).get(uid)):
            candidates.append(date)
    for plan in plans:
        if plan.contact_uuid in conflicted_uuids:
            candidates.extend(
                d
                for e in plan.evidence.values()
                if "fonte=events.json" in e.get("reason", "")
                and (d := event_datetime(e.get("created_on"))) is not None
            )
    return {"meta_events_next_after_utc": min(candidates).isoformat()}
