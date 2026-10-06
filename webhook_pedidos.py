from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

import secrets_config as secrets
from analytics import build_sales_metrics, parse_ultimo_pedido_raw
from google_sheets import GoogleSheetsStore


app = FastAPI(
    title="NexoFlow - Pedidos",
    version="1.0",
)


def _enabled() -> bool:
    return bool(getattr(secrets, "WEBHOOK_PEDIDOS_ENABLED", False))


def _expected_secret() -> str:
    return str(getattr(secrets, "WEBHOOK_SHARED_SECRET", "")).strip()


def _spreadsheet_id() -> str:
    return str(getattr(secrets, "GOOGLE_SPREADSHEET_ID", "")).strip()


class PedidoWebhook(BaseModel):
    contact_uuid: str
    contact_urn: str | None = None
    telefone: str | None = None
    cliente: str | None = None
    cpf: str | None = None
    ultimo_pedido: str | dict[str, Any]
    weni_modified_on: str | None = None


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "webhook_pedidos_enabled": _enabled(),
    }


@app.post("/weni/pedido")
def receive_order(
    body: PedidoWebhook,
    x_webhook_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    # O endpoint pode existir no código sem estar habilitado em produção.
    if not _enabled():
        raise HTTPException(
            status_code=503,
            detail="Webhook de pedidos ainda não habilitado.",
        )

    expected = _expected_secret()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="WEBHOOK_SHARED_SECRET não configurado.",
        )

    if x_webhook_secret != expected:
        raise HTTPException(status_code=401, detail="Não autorizado.")

    raw = (
        json.dumps(body.ultimo_pedido, ensure_ascii=False)
        if isinstance(body.ultimo_pedido, dict)
        else body.ultimo_pedido
    )

    phone = (body.telefone or "").strip()
    if not phone and body.contact_urn:
        phone = (
            body.contact_urn[4:]
            if body.contact_urn.startswith("tel:")
            else body.contact_urn
        )

    captured_at = datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    )

    order, items = parse_ultimo_pedido_raw(
        raw,
        contact_uuid=body.contact_uuid.strip(),
        phone=phone,
        client_name=(body.cliente or "").strip(),
        cpf=(body.cpf or "").strip(),
        modified_on=(body.weni_modified_on or "").strip(),
        captured_at=captured_at,
    )

    if order is None:
        raise HTTPException(
            status_code=400,
            detail="ultimo_pedido vazio.",
        )

    if order.get("status_validacao") == "ERRO":
        raise HTTPException(
            status_code=422,
            detail={
                "message": "ultimo_pedido inválido.",
                "error": order.get("erro_parse", ""),
            },
        )

    store = GoogleSheetsStore(_spreadsheet_id())
    orders_inserted, orders_updated = store.upsert_orders([order])
    items_inserted, items_updated = store.upsert_order_items(items)

    # Mantém a métrica diária atualizada caso o webhook seja ativado.
    full_orders = store.load_order_records()
    full_items = store.load_order_item_records()
    store.replace_sales_metrics(
        build_sales_metrics(full_orders, full_items)
    )

    return {
        "status": "ok",
        "pedido_chave": order["pedido_chave"],
        "orders_inserted": orders_inserted,
        "orders_updated": orders_updated,
        "items_inserted": items_inserted,
        "items_updated": items_updated,
    }
