"""Shared order semantics, independent of API clients and analytics schemas."""
from __future__ import annotations

import csv
import io
import json
import unicodedata
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

BUSINESS_TIMEZONE = ZoneInfo("America/Belem")
FARMALIDER_ORDER_STATUS_NAMES = {
    -2: "Em aberto",
    -1: "Pendente de pagamento",
    0: "Em processamento",
    1: "Em trânsito",
    2: "Concluído",
    3: "Cancelado",
    4: "Pronto para rota",
}

FARMALIDER_ORDER_STATUS_ALIASES = {
    "emaberto": -2,
    "pendentedepagamento": -1,
    "pendentepagamento": -1,
    "prontopararota": 4,
    "emprocessamento": 0,
    "emtransito": 1,
    "concluido": 2,
    "cancelado": 3,
}

FARMALIDER_PAYMENT_METHOD_NAMES = {
    0: "Cancelado",
    1: "Dinheiro",
    2: "Débito",
    3: "Crédito",
    4: "Ticket",
    5: "Pix por Link de Pagamento",
    6: "Pix no POS",
}

FARMALIDER_PAYMENT_METHOD_ALIASES = {
    "_": 0,
    "dinheiro": 1,
    "debito": 2,
    "credito": 3,
    "ticket": 4,
    "pixporlinkdepagamento": 5,
    "pixnopos": 6,
}


def _enum_key(value: str) -> str:
    return "".join(
        character for character in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(character)
    ).casefold().replace(" ", "")


def serialize_weni_order_list(values: list[str]) -> str:
    """Keep comma-separated fields reversible, including punctuation in names."""
    return ", ".join(
        '"' + value.replace('"', '""') + '"'
        if any(char in value for char in ',"\r\n') else value
        for value in values
    )


def parse_weni_order_list(value: str) -> list[str]:
    """Read one CSV record; empty elements remain visible to the auditor."""
    if not value.strip():
        return []
    try:
        records = list(csv.reader(
            io.StringIO(value, newline=""), skipinitialspace=True, strict=True,
        ))
    except csv.Error as exc:
        raise ValueError("Lista de pedido com CSV inválido.") from exc
    if len(records) != 1:
        raise ValueError("Lista de pedido deve conter um único registro CSV.")
    return [part.strip() for part in records[0]]


def normalize_farmalider_payment_code(value: Any) -> str:
    """Accept official enum names and preserve nonnegative Int32 API codes."""
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return ""
    text = str(value).strip()
    if not text.isascii() or not text.isdigit():
        code = FARMALIDER_PAYMENT_METHOD_ALIASES.get(_enum_key(text))
        return "" if code is None else str(code)
    normalized = text.lstrip("0") or "0"
    if len(normalized) > 10 or int(normalized) > 2147483647:
        return ""
    return normalized


def normalize_farmalider_order_status_code(value: Any) -> str:
    """Recognize the documented -2..4 order codes and official enum names."""
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return ""
    text = str(value).strip()
    if text in {"-2", "-1"}:
        return text
    if not text.isascii() or not text.isdigit():
        code = FARMALIDER_ORDER_STATUS_ALIASES.get(_enum_key(text))
        return "" if code is None else str(code)
    # Bound the conversion rather than accepting arbitrarily long numeric input.
    normalized = text.lstrip("0") or "0"
    if len(normalized) != 1:
        return ""
    return normalized if int(normalized) in FARMALIDER_ORDER_STATUS_NAMES else ""


def farmalider_order_status_name(value: Any) -> str:
    """Return the documented StatusPedido label; unknown codes stay unknown."""
    code = normalize_farmalider_order_status_code(value)
    return FARMALIDER_ORDER_STATUS_NAMES.get(int(code), "") if code else ""


def farmalider_payment_method_name(value: Any) -> str:
    """Return a known payment label, including the Weni cancellation sentinel."""
    if isinstance(value, str) and value.strip().casefold() == "cancelado":
        return "Cancelado"
    code = normalize_farmalider_payment_code(value)
    return FARMALIDER_PAYMENT_METHOD_NAMES.get(int(code), "") if code else ""


def farmalider_payment_method_display(value: Any) -> str:
    """Show an unmapped API code without inventing a payment method."""
    if isinstance(value, str) and value.strip().casefold() == "cancelado":
        return "Cancelado"
    code = normalize_farmalider_payment_code(value)
    if not code:
        return ""
    return farmalider_payment_method_name(code) or f"Não identificado (código {code})"


def business_order_datetime(value: Any) -> datetime | None:
    """Interpret API ISO or Weni display timestamps as America/Belem time."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        raw = value.strip()
        parsed = None
        for fmt in ("%d/%m/%y %H:%M:%S", "%d/%m/%Y %H:%M:%S"):
            try:
                parsed = datetime.strptime(raw, fmt)
                break
            except ValueError:
                pass
        if parsed is None:
            try:
                parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except (ValueError, OverflowError):
                return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=BUSINESS_TIMEZONE)
    return parsed.astimezone(BUSINESS_TIMEZONE)


def weni_order_datetime_text(value: Any) -> str:
    """Format an order timestamp for the Weni pedido_data contract."""
    parsed = business_order_datetime(value)
    return parsed.strftime("%d/%m/%y %H:%M:%S") if parsed is not None else ""


def is_order_cancelled(order: dict[str, Any]) -> bool:
    payment = order.get("farmalider_forma_pagamento", order.get("pedido_forma_pagamento"))
    if normalize_farmalider_payment_code(payment) == "0" or (
        isinstance(payment, str) and payment.strip().casefold() == "cancelado"
    ):
        return True
    cancellation = str(order.get("farmalider_cancelamento") or "").strip().casefold()
    if cancellation not in {"", "0", "false", "none", "null", "nao", "não"}:
        return True
    raw_status = order.get("farmalider_status_pedido", order.get("pedido_status"))
    status = str(raw_status if raw_status is not None else "").strip().casefold()
    confirmation = str(order.get("status_confirmacao") or "").strip().casefold()
    documented_cancel = farmalider_order_status_name(raw_status) == "Cancelado"
    return documented_cancel or "cancel" in status or confirmation == "cancelado_api"


def effective_order_status_code(order: dict[str, Any]) -> str:
    """Apply payment-0 cancellation without discarding the raw API status."""
    if is_order_cancelled(order):
        return "3"
    return normalize_farmalider_order_status_code(
        order.get("farmalider_status_pedido", order.get("pedido_status"))
    )


def is_order_completed(order: dict[str, Any]) -> bool:
    """Return True only for the documented completed state."""
    if is_order_cancelled(order):
        return False
    status = order.get("farmalider_status_pedido")
    if farmalider_order_status_name(status) == "Concluído":
        return True
    if isinstance(status, str):
        text = "".join(
            character for character in unicodedata.normalize("NFKD", status.strip())
            if not unicodedata.combining(character)
        ).casefold()
        return text == "concluido"
    return False


def is_order_sale(order: dict[str, Any]) -> bool:
    """Business sales include ready-for-route, in-transit and completed orders."""
    return not is_order_cancelled(order) and effective_order_status_code(order) in {"4", "1", "2"}


def is_order_made(order: dict[str, Any]) -> bool:
    """Count every documented non-cancelled operational state as a made order."""
    if is_order_cancelled(order):
        return False
    status = order.get("farmalider_status_pedido")
    label = farmalider_order_status_name(status)
    if label in {"Em processamento", "Pronto para rota", "Em trânsito", "Concluído"}:
        return True
    if isinstance(status, str):
        text = "".join(
            character for character in unicodedata.normalize("NFKD", status.strip())
            if not unicodedata.combining(character)
        ).casefold().replace(" ", "")
        return text in {"emprocessamento", "prontopararota", "emtransito", "concluido"}
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
        "farmalider_forma_pagamento", "farmalider_forma_pagamento_nome",
        "valor_origem", "valor_total_weni", "diferenca_total_weni_api",
    )
    payload = {key: "" if order.get(key) is None else str(order.get(key)) for key in metadata_fields}
    for key in ("valor_total_compra", "valor_total_api_itens", "farmalider_frete", "total_api"):
        payload[key] = _number_text(order.get(key), money=True)
    for key in ("quantidade_itens", "quantidade_itens_api", "quantidade_produtos"):
        payload[key] = _number_text(order.get(key))
    payload["produtos"] = products
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
# NexoFlow 1.0
