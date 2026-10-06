"""Shared order semantics, independent of API clients and analytics schemas."""
from __future__ import annotations

import json
import unicodedata
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

BUSINESS_TIMEZONE = ZoneInfo("America/Belem")
FARMALIDER_ORDER_STATUS_NAMES = {
    0: "Em processamento",
    1: "Em trânsito",
    2: "Concluído",
    3: "Cancelado",
    4: "Pronto para rota",
}


def farmalider_order_status_name(value: Any) -> str:
    """Return the documented StatusPedido label; unknown codes stay unknown."""
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return ""
    text = str(value).strip()
    if not text.isascii() or not text.isdigit():
        return ""
    # Bound the conversion rather than accepting arbitrarily long numeric input.
    normalized = text.lstrip("0") or "0"
    if len(normalized) != 1:
        return ""
    return FARMALIDER_ORDER_STATUS_NAMES.get(int(normalized), "")


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
    documented_cancel = farmalider_order_status_name(order.get("farmalider_status_pedido")) == "Cancelado"
    return documented_cancel or "cancel" in status or confirmation == "cancelado_api"


def is_order_completed(order: dict[str, Any]) -> bool:
    """Only the documented completed state qualifies as a completed purchase."""
    if is_order_cancelled(order):
        return False
    status = order.get("farmalider_status_pedido")
    if farmalider_order_status_name(status) == "Concluído":
        return True
    if isinstance(status, str):
        # Legacy contacts can store the enum name in the status field itself.
        # A separate display label never overrides a conflicting/unknown code.
        text = "".join(
            character for character in unicodedata.normalize("NFKD", status.strip())
            if not unicodedata.combining(character)
        ).casefold()
        return text == "concluido"
    return False


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
        "origem_pedido", "farmalider_cancelamento", "farmalider_status_pedido", "farmalider_status_pedido_nome",
        "valor_origem", "valor_total_weni", "diferenca_total_weni_api",
    )
    payload = {key: "" if order.get(key) is None else str(order.get(key)) for key in metadata_fields}
    for key in ("valor_total_compra", "valor_total_api_itens", "farmalider_frete", "total_api"):
        payload[key] = _number_text(order.get(key), money=True)
    for key in ("quantidade_itens", "quantidade_itens_api", "quantidade_produtos"):
        payload[key] = _number_text(order.get(key))
    payload["produtos"] = products
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
