"""Módulo OPCIONAL para captura exata de cada referral de anúncio.

A sincronização diária preserva corretamente o primeiro anúncio e o anúncio mais
recente, mas não consegue reconstruir anúncios intermediários se ocorrerem entre
duas execuções. Este webhook é a evolução necessária para métricas exatas de
"conversas por anúncio".
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from analytics import EVENT_COLUMNS
from google_sheets import GoogleSheetsStore
from project_paths import load_private_settings
from webhook_runtime import WEBHOOK_WRITE_LOCK, shared_secret_matches

_settings = load_private_settings()
GOOGLE_SPREADSHEET_ID = _settings.GOOGLE_SPREADSHEET_ID
WEBHOOK_SHARED_SECRET = _settings.WEBHOOK_SHARED_SECRET

app = FastAPI(title="Weni Meta Ads Events")


class WeniAdEvent(BaseModel):
    contact_uuid: str = ""
    contact_urn: str = ""
    source_type: str = ""
    source_id: str = ""
    headline: str = ""
    source_url: str = ""
    ctwa_clid: str = ""
    received_at: str = ""


def build_event_id(event: WeniAdEvent) -> str:
    if event.ctwa_clid:
        return event.ctwa_clid
    raw = "|".join(
        [event.contact_uuid, event.source_id, event.received_at, event.headline]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/weni/meta-event")
def receive_event(
    event: WeniAdEvent, x_webhook_secret: str | None = Header(default=None)
) -> dict[str, str]:
    if not shared_secret_matches(WEBHOOK_SHARED_SECRET, x_webhook_secret):
        raise HTTPException(status_code=401, detail="Não autorizado.")
    if event.source_type and event.source_type != "ad":
        return {"status": "ignored", "reason": "source_type não é ad"}

    event_id = build_event_id(event)
    received_at = event.received_at or datetime.now(UTC).isoformat(timespec="seconds")
    row = [
        event_id,
        received_at,
        event.contact_uuid,
        event.contact_urn,
        event.source_type,
        event.source_id,
        event.headline,
        event.source_url,
        event.ctwa_clid,
    ]
    if len(row) != len(EVENT_COLUMNS):
        raise HTTPException(
            status_code=500,
            detail="Estrutura do evento incompatível com a planilha.",
        )
    with WEBHOOK_WRITE_LOCK:
        store = GoogleSheetsStore(GOOGLE_SPREADSHEET_ID)
        try:
            if event_id in store.existing_event_ids():
                return {"status": "duplicate", "event_id": event_id}
            store.append_event(row)
        finally:
            store.close()

    return {"status": "created", "event_id": event_id}
