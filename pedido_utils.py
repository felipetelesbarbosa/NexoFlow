"""Shared order semantics, independent of API clients and analytics schemas."""
from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

BUSINESS_TIMEZONE = ZoneInfo("America/Belem")


def business_order_datetime(value: Any) -> datetime | None:
    """Interpret naive order timestamps as local business time, never as UTC."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except (ValueError, OverflowError):
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=BUSINESS_TIMEZONE)
    return parsed.astimezone(BUSINESS_TIMEZONE)


def is_order_cancelled(order: dict[str, Any]) -> bool:
    cancellation = str(order.get("farmalider_cancelamento") or "").strip().casefold()
    if cancellation not in {"", "0", "false", "none", "null", "nao", "não"}:
        return True
    status = str(order.get("farmalider_status_pedido") or "").strip().casefold()
    confirmation = str(order.get("status_confirmacao") or "").strip().casefold()
    # Numerical API status codes have no documented meaning in this integration.
    return "cancel" in status or confirmation == "cancelado_api"


def _number_text(value: Any, *, money: bool = False) -> str:
    if value is None or value == "":
        return ""
    try:
        if isinstance(value, bool):
            raise ValueError("boolean is not an order number")
        number = Decimal(str(value).replace(",", "."))
        if not number.is_finite():
            raise ValueError("non-finite order number")
        return f"{number:.2f}" if money else format(number.normalize(), "f")
    except (InvalidOperation, ValueError, TypeError):
        return ""


def serialize_pedido_products(
    order: dict[str, Any], items: list[dict[str, Any]],
) -> str:
    """Serialize an auditable snapshot without PII or volatile capture times."""
    products = [
        {
            "nome": str(item.get("produto_nome") or "").strip() or None,
            "codigo": str(item.get("produto_codigo") or "").strip() or None,
            "quantidade": _number_text(item.get("quantidade")),
            "valor_unitario": _number_text(item.get("valor_unitario"), money=True),
            "valor_total": _number_text(item.get("valor_total"), money=True),
        }
        for item in items
    ]
    metadata_fields = (
        "pedido_id", "data_hora", "status_confirmacao", "status_validacao",
        "origem_pedido", "farmalider_cancelamento", "farmalider_status_pedido",
        "valor_origem", "valor_total_weni", "diferenca_total_weni_api",
    )
    payload = {key: str(order.get(key) or "") for key in metadata_fields}
    for key in ("valor_total_compra", "valor_total_api_itens", "farmalider_frete", "total_api"):
        payload[key] = _number_text(order.get(key), money=True)
    for key in ("quantidade_itens", "quantidade_itens_api", "quantidade_produtos"):
        payload[key] = _number_text(order.get(key))
    payload["produtos"] = products
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
