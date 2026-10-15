"""Restrições privadas de nova compra ainda não confirmada pela API."""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import timedelta
from pathlib import Path
from typing import Any

from config import WENI_UPDATE_STATE_FILE
from contact_enrichment import (
    message_created_on,
    message_direction,
    message_text,
    normalize_text,
)
from pedido_utils import business_order_datetime

PENDING_PURCHASE_FIELD = "pedido_revisao_pendente"


def contact_pending_purchase_check(
    contact: dict[str, Any], saved_check: dict[str, str] | None = None
) -> dict[str, str] | None:
    """Lê a restrição portátil da Weni sem substituir a emissão oficial."""
    from analytics import get_fields, normalize_value

    raw = normalize_value(get_fields(contact).get(PENDING_PURCHASE_FIELD)).strip()
    field_check = None
    if raw and raw.casefold() != "resolvido":
        observed = business_order_datetime(raw)
        if observed is None:
            raise RuntimeError(
                "Revisão de pedido pendente possui data inválida; aplicação bloqueada."
            )
        field_check = {
            "observed_at": observed.isoformat(),
            "source": "WENI_PEDIDO_REVISAO_PENDENTE",
        }
    return merge_purchase_checks(
        {"contact": saved_check} if saved_check else {},
        {"contact": field_check} if field_check else {},
    ).get("contact")


def normalize_purchase_checks(value: Any) -> dict[str, dict[str, str]]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise RuntimeError("Restrições de compras inválidas; gere uma nova revisão.")
    result = {}
    for uid, raw in value.items():
        if not isinstance(uid, str) or not uid.strip() or not isinstance(raw, dict):
            raise RuntimeError("Restrição de compra malformada; aplicação bloqueada.")
        observed = business_order_datetime(raw.get("observed_at"))
        source = raw.get("source")
        if observed is None or not isinstance(source, str) or not source.strip():
            raise RuntimeError("Restrição de compra sem data ou origem válida.")
        result[uid] = {"observed_at": observed.isoformat(), "source": source.strip()}
    return result


def merge_purchase_checks(*maps: Any) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for mapping in maps:
        for uid, check in normalize_purchase_checks(mapping).items():
            previous = result.get(uid)
            if previous is None or check["observed_at"] > previous["observed_at"]:
                result[uid] = check
    return result


def load_purchase_check_state(path: Path | None = None) -> dict[str, Any]:
    path = Path(path or WENI_UPDATE_STATE_FILE)
    if not path.exists():
        return {}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            raise ValueError()
        normalize_purchase_checks(state.get("pending_purchase_checks"))
        return state
    except (OSError, ValueError) as exc:
        raise RuntimeError(
            "Estado privado de compras inválido; aplicação bloqueada."
        ) from exc


def load_pending_purchase_checks(path: Path | None = None) -> dict[str, dict[str, str]]:
    return normalize_purchase_checks(
        load_purchase_check_state(path).get("pending_purchase_checks")
    )


def register_pending_purchase_checks(
    checks: dict[str, dict[str, str]],
    *,
    path: Path | None = None,
    resolved: dict[str, dict[str, str]] | None = None,
) -> dict[str, dict[str, str]]:
    """Registra evidência revisada; resolved contém somente evidências já verificadas."""
    path = Path(path or WENI_UPDATE_STATE_FILE)
    state = load_purchase_check_state(path)
    pending = merge_purchase_checks(state.get("pending_purchase_checks"), checks)
    for uid, check in normalize_purchase_checks(resolved).items():
        if pending.get(uid) == check:
            pending.pop(uid)
    state["pending_purchase_checks"] = pending
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(
        prefix="purchase-checks-", suffix=".json", dir=path.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2)
        Path(name).replace(path)
    finally:
        Path(name).unlink(missing_ok=True)
    return pending


def official_order_resolves_check(check: dict[str, str], order: Any) -> bool:
    observed = business_order_datetime(check.get("observed_at"))
    if not isinstance(order, dict) or order.get("status_validacao") != "OK":
        return False
    emitted = business_order_datetime(order.get("data_hora"))
    return bool(
        observed
        and emitted
        and order.get("status_confirmacao") in {"CONFIRMADO_API", "CANCELADO_API"}
        and emitted.date() >= observed.date()
    )


def infer_pending_purchase_check(
    messages: list[dict[str, Any]], *, captured_at: str
) -> dict[str, str] | None:
    """Confirmação de pedido com nova solicitação no mesmo dia, sem inferir emissão."""
    cutoff = business_order_datetime(captured_at)
    if cutoff is None:
        return None
    requests = []
    confirmations = []
    views = []
    for message in messages:
        emitted = business_order_datetime(message_created_on(message))
        if emitted is None or emitted > cutoff:
            continue
        text = normalize_text(message_text(message))
        direction = message_direction(message)
        views.append((emitted, direction, text))
    latest_out = None
    for emitted, direction, text in sorted(views, key=lambda view: view[0]):
        if direction == "out":
            latest_out = (emitted, text)
        if direction == "in" and latest_out:
            offered_at, offer = latest_out
            if (
                offered_at.date() == emitted.date()
                and timedelta(0) <= emitted - offered_at < timedelta(hours=24)
                and offer.count("?") == 1
                and re.search(
                    r"\b(?:gostaria|deseja|quer|vamos|podemos)\b.{0,100}"
                    r"\b(?:fazer|iniciar|realizar)\b.{0,35}\bpedido\b",
                    offer,
                )
                and not re.search(
                    r"\b(?:lgpd|privacidade|idade|entrega|rota|status|acompanhar|cancelamento)\b"
                    r"|\bdados pessoais\b",
                    offer,
                )
                and re.match(
                    r"^(?:sim|quero sim|pode fazer|pode iniciar|pode realizar)(?:[.!\s]|$)",
                    text,
                )
                and not re.search(r"\b(?:nao|talvez|depois|amanha)\b", text)
            ):
                requests.append(emitted)
        if (
            direction == "in"
            and re.search(
                r"\b(?:quero|gostaria de|preciso|desejo|vou)\s+(?:fazer\s+)?(?:um\s+)?(?:novo\s+)?pedido\b"
                r"|\b(?:fazer|iniciar)\s+(?:um\s+)?(?:novo\s+)?pedido\b",
                text,
            )
            and not re.search(r"\b(?:nao|cancelar|cancelado|anterior|antigo)\b", text)
        ):
            requests.append(emitted)
        if (
            direction == "out"
            and re.search(
                r"\bpedido\s+(?:foi\s+|esta\s+|ja\s+)?(?:finalizado|realizado|confirmado|registrado)\b",
                text,
            )
            and not re.search(r"\b(?:nao|cancelado|anterior|antigo|sera|seria)\b", text)
        ):
            confirmations.append(emitted)
    matched = [
        confirmed
        for confirmed in confirmations
        if any(
            requested.date() == confirmed.date()
            and timedelta(0) <= confirmed - requested < timedelta(hours=24)
            for requested in requests
        )
    ]
    if not matched:
        return None
    return {
        "observed_at": max(matched).isoformat(),
        "source": "MENSAGENS_NOVA_SOLICITACAO_E_PEDIDO_CONFIRMADO",
    }
