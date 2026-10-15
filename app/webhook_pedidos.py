from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from analytics import build_sales_metrics, parse_ultimo_pedido_raw
from google_sheets import GoogleSheetsStore
from pharmacy_scope import plan_pharmacy_scope
from project_paths import load_private_settings
from webhook_runtime import WEBHOOK_WRITE_LOCK, shared_secret_matches

secrets = load_private_settings()

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

    if not shared_secret_matches(expected, x_webhook_secret):
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

    captured_at = datetime.now(UTC).isoformat(timespec="seconds")

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

    with WEBHOOK_WRITE_LOCK:
        store = GoogleSheetsStore(_spreadsheet_id())
        try:
            orders_result, items_result = store.upsert_pharmacy_orders([order], items)
            scope = plan_pharmacy_scope(
                orders_result.final_records, items_result.final_records
            )
            if (
                scope.changed_orders
                or scope.removed_order_keys
                or scope.removed_item_keys
            ):
                scope = store.reconcile_pharmacy_scope(
                    base_records=[],
                    order_records=orders_result.final_records,
                    item_records=items_result.final_records,
                    include_history=False,
                )

            # Os upserts já devolveram as tabelas finais: não relê as mesmas abas.
            # Reenvios ainda comparam/reparam a aba de métricas caso uma gravação
            # anterior tenha falhado depois de persistir os pedidos ou itens.
            store.replace_sales_metrics(build_sales_metrics(scope.orders, scope.items))

        finally:
            store.close()

    return {
        "status": "ok",
        "pedido_chave": order["pedido_chave"],
        "orders_inserted": orders_result.inserted,
        "orders_updated": orders_result.updated,
        "items_inserted": items_result.inserted,
        "items_updated": items_result.updated,
    }
