from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import secrets_config as secrets
from analytics import get_fields, is_valid_cpf, normalize_cpf, normalize_value, parse_ultimo_pedido
from ad_attribution import (
    GOOGLE_ADS_ORIGIN,
    GOOGLE_ADS_WRITE_FIELDS,
    extract_google_ads_attribution,
)
from config import (
    WENI_UPDATE_AUDIT_FILE,
    WENI_UPDATE_CONTEXT_LOOKBACK_HOURS,
    WENI_UPDATE_INITIAL_LOOKBACK_DAYS,
    WENI_UPDATE_OPT_IN_GROUP,
    WENI_UPDATE_OPT_OUT_GROUP,
    WENI_UPDATE_OVERLAP_MINUTES,
    WENI_UPDATE_STATE_FILE,
)
from contact_enrichment import (
    FieldEvidence,
    infer_contact_fields,
    message_created_on,
    message_id,
)
from farmalider_client import FarmaliderAuthError, FarmaliderClient, FarmaliderError
from farmalider_integration import apply_pedido_api_confirmation
from weni_client import WeniClient
from urn_utils import (
    CHANNEL_FIELD_MAP,
    native_contact_urns,
    resolve_contact_urns,
    urn_channel,
)


ALLOWED_WRITE_FIELDS = {
    "contact_urn",
    "contact_urn_whatsapp",
    "contact_urn_instagram",
    "contact_urn_facebook",
    "contact_canal_principal",
    "cpf",
    "idade",
    "maior_de_18_anos",
    "opt_in_lgpd",
    "pedido_id",
    "pedido_data",
    "pedido_produtos",
    "pedido_quantidade_itens",
    "pedido_valor",
    "ultima_compra",
    *GOOGLE_ADS_WRITE_FIELDS,
}

REQUIRED_MULTICHANNEL_FIELDS = {
    "contact_urn_whatsapp",
    "contact_urn_instagram",
    "contact_urn_facebook",
    "contact_canal_principal",
}


PURCHASE_FIELDS = {
    "pedido_id",
    "pedido_data",
    "pedido_produtos",
    "pedido_quantidade_itens",
    "pedido_valor",
    "ultima_compra",
}


@dataclass(frozen=True)
class GroupAction:
    action: str
    group: str
    reason: str
    group_name: str = ""


@dataclass
class ContactUpdatePlan:
    contact_uuid: str
    contact_name: str = ""
    contact_urn: str = ""
    contact_channel: str = ""
    fields: dict[str, Any] = field(default_factory=dict)
    previous: dict[str, Any] = field(default_factory=dict)
    guards: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, dict[str, str]] = field(default_factory=dict)
    group_actions: list[GroupAction] = field(default_factory=list)
    purchase_confirmed: bool = False
    purchase_confirmation: str = ""

    @property
    def has_changes(self) -> bool:
        return bool(self.fields or self.group_actions)


@dataclass
class UpdateStats:
    messages_incoming: int = 0
    contacts_modified: int = 0
    contacts_considered: int = 0
    plans_with_changes: int = 0
    field_changes: int = 0
    group_actions: int = 0
    contacts_updated: int = 0
    contacts_failed: int = 0
    contacts_conflicted: int = 0
    contacts_already_satisfied: int = 0
    purchase_confirmed: int = 0
    purchase_skipped: int = 0


@dataclass(frozen=True)
class UpdateWindow:
    started_at: datetime
    after: datetime | None
    full: bool


class PlanAuditError(RuntimeError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _parse_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None

    candidates = [text]
    if text.endswith("Z"):
        candidates.append(text[:-1] + "+00:00")

    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            pass

    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
    ):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _weni_datetime(value: Any) -> str:
    dt = _parse_datetime(value)
    if dt is None:
        return ""
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _safe_number(value: Any) -> int | float | None:
    text = str(value or "").strip().replace(",", ".")
    if not text:
        return None
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    if number == number.to_integral_value():
        return int(number)
    return float(number)


def _semantic_text(value: Any) -> str:
    return str(value or "").strip()


def _same_value(field_name: str, current: Any, proposed: Any) -> bool:
    if field_name == "cpf":
        current_cpf = normalize_cpf(current)
        proposed_cpf = normalize_cpf(proposed)
        if current_cpf and proposed_cpf:
            return current_cpf == proposed_cpf
    if field_name in {"idade", "pedido_quantidade_itens", "pedido_valor"}:
        current_num = _safe_number(current)
        proposed_num = _safe_number(proposed)
        if current_num is not None and proposed_num is not None:
            return Decimal(str(current_num)) == Decimal(str(proposed_num))
    if field_name in {"pedido_data", "ultima_compra"}:
        current_dt = _parse_datetime(current)
        proposed_dt = _parse_datetime(proposed)
        if current_dt is not None and proposed_dt is not None:
            return current_dt == proposed_dt
    return _semantic_text(current).casefold() == _semantic_text(proposed).casefold()


def _extract_contact_uuid(message: dict[str, Any]) -> str:
    contact = message.get("contact")
    if isinstance(contact, dict):
        return str(contact.get("uuid") or "").strip()
    if isinstance(contact, str):
        return contact.strip()
    return str(message.get("contact_uuid") or "").strip()


def _extract_message_urn(message: dict[str, Any]) -> str:
    for key in ("urn", "contact_urn"):
        value = str(message.get(key) or "").strip()
        if value:
            return value
    contact = message.get("contact")
    if isinstance(contact, dict):
        urn = str(contact.get("urn") or "").strip()
        if urn:
            return urn
    return ""


def _preferred_contact_urn(contact: dict[str, Any]) -> str:
    return resolve_contact_urns(contact, get_fields(contact)).principal_urn


def _sync_contact_channel_fields(
    plan: ContactUpdatePlan,
    contact: dict[str, Any],
    current_fields: dict[str, Any],
) -> None:
    """Sincroniza somente identidades de canal confirmadas pela Weni."""
    resolved = resolve_contact_urns(contact, current_fields)
    plan.contact_urn = resolved.principal_urn
    plan.contact_channel = resolved.principal_channel

    if resolved.principal_urn:
        _set_field_if_changed(
            plan,
            current_fields,
            "contact_urn",
            resolved.principal_urn,
            reason="URN principal determinada pelas URNs oficiais retornadas pela Weni",
        )

    for channel, field_name in CHANNEL_FIELD_MAP.items():
        urn = resolved.channel_urns.get(channel, "")
        if not urn:
            continue
        _set_field_if_changed(
            plan,
            current_fields,
            field_name,
            urn,
            reason=f"URN oficial de {channel} retornada pela Weni",
        )

    if resolved.principal_channel:
        _set_field_if_changed(
            plan,
            current_fields,
            "contact_canal_principal",
            resolved.principal_channel,
            reason="canal principal classificado a partir da URN oficial da Weni",
        )

    channel_fields = {
        "contact_urn",
        "contact_urn_whatsapp",
        "contact_urn_instagram",
        "contact_urn_facebook",
        "contact_canal_principal",
    }
    if channel_fields & set(plan.fields):
        # Guarda a fonte nativa usada para montar o plano. No apply congelado,
        # se a identidade de canal mudar enquanto o atendimento continua 24h,
        # apenas este contato entra em conflito e é reprocessado depois.
        plan.guards["__native_urns"] = list(resolved.native_urns)


def _ad_event_values(prefix: str, attribution: Any) -> dict[str, str]:
    """Mapeia uma evidência Google Ads para os campos genéricos de atribuição."""
    occurred = _weni_datetime(attribution.occurred_at)
    ad_id = attribution.ad_id or attribution.click_id
    title = attribution.title or attribution.campaign_type or GOOGLE_ADS_ORIGIN
    values = {
        f"{prefix}_anuncio_origem": GOOGLE_ADS_ORIGIN,
        f"{prefix}_anuncio_id": ad_id,
        f"{prefix}_anuncio_titulo": title,
        f"{prefix}_anuncio_url": attribution.url,
        f"{prefix}_anuncio_clique_id": attribution.click_id,
        f"{prefix}_anuncio_data": occurred,
        f"{prefix}_anuncio_tipo_campanha": attribution.campaign_type,
        f"{prefix}_anuncio_canal_destino": attribution.destination_channel,
    }
    return {key: value for key, value in values.items() if str(value or "").strip()}


def _set_ad_field(
    plan: ContactUpdatePlan,
    current_fields: dict[str, Any],
    field_name: str,
    value: str,
    *,
    attribution: Any,
    available_weni_fields: set[str] | None,
    only_if_blank: bool = False,
) -> None:
    if available_weni_fields is not None and field_name not in available_weni_fields:
        return
    if only_if_blank and str(current_fields.get(field_name) or "").strip():
        return
    evidence = FieldEvidence(
        field=field_name,
        value=value,
        message_id=attribution.message_id,
        created_on=attribution.occurred_at,
        reason=attribution.reason,
    )
    _set_field_if_changed(plan, current_fields, field_name, value, evidence=evidence)


def _same_ad_event(current_fields: dict[str, Any], prefix: str, attribution: Any) -> bool:
    origin = str(current_fields.get(f"{prefix}_anuncio_origem") or "").strip().casefold()
    if origin not in {"google ads", "googleads", "google adwords", "adwords"}:
        return False
    current_click = str(current_fields.get(f"{prefix}_anuncio_clique_id") or "").strip()
    current_id = str(current_fields.get(f"{prefix}_anuncio_id") or "").strip()
    if current_click and attribution.click_id:
        return current_click == attribution.click_id
    candidate_id = attribution.ad_id or attribution.click_id
    if current_id and candidate_id:
        return current_id == candidate_id
    current_date = _parse_datetime(current_fields.get(f"{prefix}_anuncio_data"))
    candidate_date = _parse_datetime(attribution.occurred_at)
    return current_date is not None and candidate_date is not None and current_date == candidate_date


def _sync_google_ads_attribution(
    plan: ContactUpdatePlan,
    contact: dict[str, Any],
    current_fields: dict[str, Any],
    context_messages: list[dict[str, Any]],
    *,
    available_weni_fields: set[str] | None,
) -> None:
    """
    Sincroniza atribuição Google Ads somente quando a evidência chega à Weni.

    O canal de destino vem da URN da própria mensagem. Origem de anúncio nunca
    fabrica nem altera URNs de contato.
    """
    detected: list[tuple[datetime, Any]] = []
    resolved_contact = resolve_contact_urns(contact, current_fields)
    # Se a mensagem não trouxer URN, só usamos fallback quando o contato possui
    # exatamente um canal conhecido. Em contato multicanal, deixamos em branco
    # para não inventar o canal por onde o anúncio abriu a conversa.
    contact_channels = [
        channel for channel, urn in resolved_contact.channel_urns.items() if urn
    ]
    single_contact_channel = contact_channels[0] if len(contact_channels) == 1 else ""

    for message in context_messages:
        attribution = extract_google_ads_attribution(message)
        if attribution is None:
            continue
        if not attribution.destination_channel and single_contact_channel:
            attribution = replace(attribution, destination_channel=single_contact_channel)
        occurred = _parse_datetime(attribution.occurred_at)
        if occurred is None:
            # Sem data confiável não há como decidir primeiro/último anúncio.
            continue
        detected.append((occurred, attribution))

    if not detected:
        return
    detected.sort(key=lambda item: (item[0], item[1].message_id))
    first = detected[0][1]
    last = detected[-1][1]

    # Primeiro anúncio é imutável depois que existe evidência válida.
    first_markers = (
        "primeiro_anuncio_origem",
        "primeiro_anuncio_id",
        "primeiro_anuncio_clique_id",
        "primeiro_anuncio_data",
    )
    has_first = any(str(current_fields.get(key) or "").strip() for key in first_markers)
    if not has_first:
        for field_name, value in _ad_event_values("primeiro", first).items():
            _set_ad_field(
                plan,
                current_fields,
                field_name,
                value,
                attribution=first,
                available_weni_fields=available_weni_fields,
            )
    elif _same_ad_event(current_fields, "primeiro", first):
        # Mesmo anúncio: apenas completa metadados ausentes, sem sobrescrever o primeiro registro.
        for field_name, value in _ad_event_values("primeiro", first).items():
            _set_ad_field(
                plan,
                current_fields,
                field_name,
                value,
                attribution=first,
                available_weni_fields=available_weni_fields,
                only_if_blank=True,
            )

    # Último anúncio só muda quando a evidência Google Ads é realmente mais nova.
    last_markers = (
        "ultimo_anuncio_origem",
        "ultimo_anuncio_id",
        "ultimo_anuncio_clique_id",
        "ultimo_anuncio_data",
    )
    has_last = any(str(current_fields.get(key) or "").strip() for key in last_markers)
    current_last_date = _parse_datetime(current_fields.get("ultimo_anuncio_data"))
    candidate_last_date = _parse_datetime(last.occurred_at)

    replace_last = not has_last
    if has_last and current_last_date is not None and candidate_last_date is not None:
        replace_last = candidate_last_date > current_last_date

    if replace_last:
        for field_name, value in _ad_event_values("ultimo", last).items():
            _set_ad_field(
                plan,
                current_fields,
                field_name,
                value,
                attribution=last,
                available_weni_fields=available_weni_fields,
            )
    elif _same_ad_event(current_fields, "ultimo", last):
        for field_name, value in _ad_event_values("ultimo", last).items():
            _set_ad_field(
                plan,
                current_fields,
                field_name,
                value,
                attribution=last,
                available_weni_fields=available_weni_fields,
                only_if_blank=True,
            )


def _contact_in_group(contact: dict[str, Any], *, group_name: str, group_uuid: str) -> bool:
    groups = contact.get("groups")
    if not isinstance(groups, list):
        return False
    expected_name = group_name.strip().casefold()
    expected_uuid = group_uuid.strip().casefold()
    for item in groups:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip().casefold()
            uuid = str(item.get("uuid") or "").strip().casefold()
            if (expected_name and name == expected_name) or (
                expected_uuid and uuid == expected_uuid
            ):
                return True
        else:
            text = str(item or "").strip().casefold()
            if text and text in {expected_name, expected_uuid}:
                return True
    return False


def _message_sort_key(message: dict[str, Any]) -> tuple[datetime, str]:
    return (
        _parse_datetime(message_created_on(message))
        or datetime.min.replace(tzinfo=timezone.utc),
        message_id(message),
    )


def _load_state(path: Path = WENI_UPDATE_STATE_FILE) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        logging.warning("Estado do NexoFlow Weni inválido. Será ignorado.")
        return {}


def _save_state(payload: dict[str, Any], path: Path = WENI_UPDATE_STATE_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix="weni-update-", suffix=".json", dir=path.parent)
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(path)
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)


_AUDIT_HANDLES: dict[str, Any] = {}


def _append_audit(event: dict[str, Any], path: Path = WENI_UPDATE_AUDIT_FILE) -> None:
    """Anexa JSONL reutilizando o handle durante a execução.

    Em cargas completas isso evita dezenas de milhares de open/close sem
    alterar a ordem nem a durabilidade por linha (buffering=1).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    key = str(path.resolve())
    handle = _AUDIT_HANDLES.get(key)
    if handle is None or getattr(handle, "closed", True):
        handle = path.open("a", encoding="utf-8", buffering=1)
        _AUDIT_HANDLES[key] = handle
    handle.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")


def _close_audit_handles() -> None:
    for handle in list(_AUDIT_HANDLES.values()):
        try:
            handle.flush()
            handle.close()
        except OSError:
            pass
    _AUDIT_HANDLES.clear()


def resolve_window(*, full: bool, started_at: datetime | None = None) -> UpdateWindow:
    started = started_at or utc_now()
    if full:
        return UpdateWindow(started_at=started, after=None, full=True)

    state = _load_state()
    checkpoint = _parse_datetime(state.get("last_success_utc"))
    if checkpoint is None:
        checkpoint = started - timedelta(days=WENI_UPDATE_INITIAL_LOOKBACK_DAYS)
        logging.info(
            "Primeira execução incremental: usando janela inicial de %s dias.",
            WENI_UPDATE_INITIAL_LOOKBACK_DAYS,
        )
    after = checkpoint - timedelta(minutes=WENI_UPDATE_OVERLAP_MINUTES)
    return UpdateWindow(started_at=started, after=after, full=False)


def _group_messages_by_contact(
    messages: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for message in messages:
        uuid = _extract_contact_uuid(message)
        if not uuid:
            continue
        grouped.setdefault(uuid, []).append(message)
    for values in grouped.values():
        values.sort(key=_message_sort_key)
    return grouped


def _build_evidence_payload(evidence: FieldEvidence) -> dict[str, str]:
    return {
        "message_id": evidence.message_id,
        "created_on": evidence.created_on,
        "reason": evidence.reason,
    }


def _set_field_if_changed(
    plan: ContactUpdatePlan,
    current_fields: dict[str, Any],
    field_name: str,
    value: Any,
    *,
    evidence: FieldEvidence | None = None,
    reason: str = "",
) -> None:
    if value is None or str(value).strip() == "":
        return
    current = current_fields.get(field_name)
    if _same_value(field_name, current, value):
        return
    plan.previous[field_name] = current
    plan.fields[field_name] = value
    if evidence is not None:
        plan.evidence[field_name] = _build_evidence_payload(evidence)
    elif reason:
        plan.evidence[field_name] = {"reason": reason}


def _purchase_is_cancelled(order: dict[str, str]) -> bool:
    cancellation = str(order.get("farmalider_cancelamento") or "").strip().casefold()
    if cancellation and cancellation not in {"0", "false", "none", "null", "nao", "não"}:
        return True
    status = str(order.get("farmalider_status_pedido") or "").strip().casefold()
    return "cancel" in status


def _product_summary(items: list[dict[str, str]]) -> str:
    parts: list[str] = []
    for item in items:
        name = str(item.get("produto_nome") or "").strip()
        qty = str(item.get("quantidade") or "").strip()
        if not name:
            continue
        parts.append(f"{name} x{qty or '1'}")
    return " | ".join(parts)


def _apply_purchase_candidate(
    plan: ContactUpdatePlan,
    contact: dict[str, Any],
    *,
    farm_client: FarmaliderClient | None,
    captured_at: str,
) -> bool:
    current_fields = get_fields(contact)
    raw = str(current_fields.get("ultimo_pedido") or "").strip()
    if not raw:
        return False

    order, items = parse_ultimo_pedido(contact, captured_at=captured_at)
    if order is None or order.get("status_validacao") == "ERRO":
        return False

    if not order.get("pedido_id", "").strip():
        existing_order_id = str(current_fields.get("pedido_id") or "").strip()
        if existing_order_id:
            order["pedido_id"] = existing_order_id
            for item in items:
                item["pedido_id"] = existing_order_id

    pedido_id = order.get("pedido_id", "").strip()
    if not pedido_id or farm_client is None:
        return False

    try:
        pedido_api = farm_client.get_pedido(pedido_id)
        order, items = apply_pedido_api_confirmation(
            order,
            items,
            pedido_api,
            linked_cliente_id=str(current_fields.get("id_do_cliente") or "").strip(),
            confirmed_at=captured_at,
        )
    except FarmaliderAuthError:
        raise
    except FarmaliderError:
        logging.exception("Falha ao confirmar pedido na FarmaLíder API.")
        return False

    confirmation = order.get("status_confirmacao", "")
    if not confirmation.startswith("CONFIRMADO_API") or _purchase_is_cancelled(order):
        return False

    proposed_date = _weni_datetime(order.get("data_hora"))
    if not proposed_date:
        return False

    current_last_purchase = _parse_datetime(current_fields.get("ultima_compra"))
    proposed_dt = _parse_datetime(proposed_date)
    if (
        current_last_purchase is not None
        and proposed_dt is not None
        and current_last_purchase > proposed_dt
    ):
        logging.info(
            "Pedido %s confirmado, mas ultima_compra atual é mais recente; ignorando snapshot antigo.",
            pedido_id,
        )
        return False

    current_order_date = _parse_datetime(current_fields.get("pedido_data"))
    if current_order_date is not None and proposed_dt is not None and current_order_date > proposed_dt:
        return False

    order_value = _safe_number(order.get("valor_total_compra"))
    quantity = _safe_number(
        order.get("quantidade_itens_api") or order.get("quantidade_itens")
    )
    summary = _product_summary(items)

    _set_field_if_changed(
        plan,
        current_fields,
        "pedido_id",
        pedido_id,
        reason="pedido confirmado pela API FarmaLíder",
    )
    _set_field_if_changed(
        plan,
        current_fields,
        "pedido_data",
        proposed_date,
        reason="data oficial do pedido confirmado pela API FarmaLíder",
    )
    if order_value is not None:
        _set_field_if_changed(
            plan,
            current_fields,
            "pedido_valor",
            order_value,
            reason="valor do ultimo_pedido confirmado pela API FarmaLíder",
        )
    if quantity is not None:
        _set_field_if_changed(
            plan,
            current_fields,
            "pedido_quantidade_itens",
            quantity,
            reason="quantidade do pedido confirmado pela API FarmaLíder",
        )
    if summary:
        _set_field_if_changed(
            plan,
            current_fields,
            "pedido_produtos",
            summary,
            reason="resumo dos produtos do pedido confirmado",
        )
    _set_field_if_changed(
        plan,
        current_fields,
        "ultima_compra",
        proposed_date,
        reason="compra confirmada pela API FarmaLíder",
    )

    plan.purchase_confirmed = True
    plan.purchase_confirmation = confirmation
    return True


def _build_contact_plan(
    contact: dict[str, Any],
    *,
    context_messages: list[dict[str, Any]],
    candidate_message_ids: set[str],
    farm_client: FarmaliderClient | None,
    opt_out_group_name: str,
    opt_out_group_uuid: str,
    captured_at: str,
    opt_in_group_name: str = WENI_UPDATE_OPT_IN_GROUP,
    opt_in_group_uuid: str = "",
    available_weni_fields: set[str] | None = None,
) -> ContactUpdatePlan:
    contact_uuid = str(contact.get("uuid") or "").strip()
    fields = get_fields(contact)
    contact_name = str(contact.get("name") or fields.get("nome") or "").strip()
    plan = ContactUpdatePlan(
        contact_uuid=contact_uuid,
        contact_name=contact_name,
    )

    _sync_contact_channel_fields(plan, contact, fields)

    evidences = infer_contact_fields(
        context_messages,
        candidate_message_ids=candidate_message_ids,
    )
    for field_name, evidence in evidences.items():
        _set_field_if_changed(
            plan,
            fields,
            field_name,
            evidence.value,
            evidence=evidence,
        )

    _sync_google_ads_attribution(
        plan,
        contact,
        fields,
        context_messages,
        available_weni_fields=available_weni_fields,
    )

    # O valor efetivo de opt_in_lgpd é a fonte de verdade para os grupos.
    # A rotina corrige os dois lados, inclusive quando o contato já chega com
    # associação inconsistente: ativo <-> Opt-In, recusado <-> Opt-Out.
    desired_lgpd = str(
        plan.fields.get("opt_in_lgpd", fields.get("opt_in_lgpd") or "")
    ).strip().casefold()
    is_opt_in = _contact_in_group(
        contact,
        group_name=opt_in_group_name,
        group_uuid=opt_in_group_uuid,
    )
    is_opt_out = _contact_in_group(
        contact,
        group_name=opt_out_group_name,
        group_uuid=opt_out_group_uuid,
    )
    opt_in_target = opt_in_group_uuid or opt_in_group_name
    opt_out_target = opt_out_group_uuid or opt_out_group_name

    if desired_lgpd == "ativo":
        if not is_opt_in:
            plan.group_actions.append(
                GroupAction(
                    action="add",
                    group=opt_in_target,
                    reason="opt_in_lgpd ativo",
                    group_name=opt_in_group_name,
                )
            )
        if is_opt_out:
            plan.group_actions.append(
                GroupAction(
                    action="remove",
                    group=opt_out_target,
                    reason="opt_in_lgpd ativo",
                    group_name=opt_out_group_name,
                )
            )
    elif desired_lgpd == "recusado":
        # Primeiro garante o grupo correto e só depois remove o incompatível.
        # Assim, uma falha intermediária não deixa o contato sem o grupo que
        # corresponde ao valor atual de opt_in_lgpd.
        if not is_opt_out:
            plan.group_actions.append(
                GroupAction(
                    action="add",
                    group=opt_out_target,
                    reason="opt_in_lgpd recusado",
                    group_name=opt_out_group_name,
                )
            )
        if is_opt_in:
            plan.group_actions.append(
                GroupAction(
                    action="remove",
                    group=opt_in_target,
                    reason="opt_in_lgpd recusado",
                    group_name=opt_in_group_name,
                )
            )

    if plan.group_actions:
        # As ações de grupo dependem do valor efetivo de opt_in_lgpd. Guardar
        # a origem impede aplicar uma decisão antiga caso outro flow altere o
        # consentimento durante a revisão humana.
        plan.guards["opt_in_lgpd"] = fields.get("opt_in_lgpd")

    _apply_purchase_candidate(
        plan,
        contact,
        farm_client=farm_client,
        captured_at=captured_at,
    )
    if plan.purchase_confirmed:
        # ultimo_pedido é a origem estruturada da confirmação. Se ele mudar
        # durante a revisão, o plano antigo é ignorado somente para o contato.
        plan.guards["ultimo_pedido"] = fields.get("ultimo_pedido")
    return plan

def audit_plans(
    plans: list[ContactUpdatePlan],
    *,
    opt_out_group_available: bool,
    opt_in_group_available: bool = True,
) -> None:
    errors: list[str] = []
    seen: set[str] = set()

    for plan in plans:
        if not plan.contact_uuid:
            errors.append("plano sem contact_uuid")
            continue
        if plan.contact_uuid in seen:
            errors.append(f"contact_uuid duplicado no plano: {plan.contact_uuid}")
        seen.add(plan.contact_uuid)

        unknown = sorted(set(plan.fields) - ALLOWED_WRITE_FIELDS)
        if unknown:
            errors.append(
                f"{plan.contact_uuid}: campos não autorizados: {', '.join(unknown)}"
            )

        for field_name, value in plan.fields.items():
            if value is None or str(value).strip() == "":
                errors.append(f"{plan.contact_uuid}: tentativa de gravar vazio em {field_name}")

        if "cpf" in plan.fields:
            cpf = normalize_cpf(plan.fields["cpf"])
            if not is_valid_cpf(cpf):
                errors.append(f"{plan.contact_uuid}: CPF inválido")
            elif str(plan.fields["cpf"]).strip() != cpf:
                errors.append(f"{plan.contact_uuid}: CPF deve ser gravado com 11 dígitos sem pontuação")

        if "idade" in plan.fields:
            age = _safe_number(plan.fields["idade"])
            if not isinstance(age, int) or not 1 <= age <= 120:
                errors.append(f"{plan.contact_uuid}: idade fora da faixa segura")
            expected = "sim" if isinstance(age, int) and age >= 18 else "não"
            majority = str(
                plan.fields.get("maior_de_18_anos", expected)
            ).strip().casefold()
            if age is not None and majority != expected:
                errors.append(f"{plan.contact_uuid}: idade e maioridade inconsistentes")

        if "maior_de_18_anos" in plan.fields:
            if str(plan.fields["maior_de_18_anos"]).strip().casefold() not in {"sim", "não"}:
                errors.append(f"{plan.contact_uuid}: valor inválido em maior_de_18_anos")

        if "opt_in_lgpd" in plan.fields:
            if str(plan.fields["opt_in_lgpd"]).strip().casefold() not in {"ativo", "recusado"}:
                errors.append(f"{plan.contact_uuid}: valor inválido em opt_in_lgpd")

        if "contact_canal_principal" in plan.fields:
            channel = str(plan.fields["contact_canal_principal"]).strip().casefold()
            if channel not in {"whatsapp", "instagram", "facebook", "outro"}:
                errors.append(f"{plan.contact_uuid}: canal principal inválido")

        expected_channel_fields = {
            "contact_urn_whatsapp": "whatsapp",
            "contact_urn_instagram": "instagram",
            "contact_urn_facebook": "facebook",
        }
        for field_name, expected_channel in expected_channel_fields.items():
            if field_name not in plan.fields:
                continue
            detected = urn_channel(plan.fields[field_name])
            if detected != expected_channel:
                errors.append(
                    f"{plan.contact_uuid}: {field_name} não contém URN de {expected_channel}"
                )

        for field_name in ("primeiro_anuncio_canal_destino", "ultimo_anuncio_canal_destino"):
            if field_name in plan.fields:
                channel = str(plan.fields[field_name]).strip().casefold()
                if channel not in {"whatsapp", "instagram", "facebook", "outro"}:
                    errors.append(f"{plan.contact_uuid}: canal de destino de anúncio inválido em {field_name}")

        for field_name in ("primeiro_anuncio_origem", "ultimo_anuncio_origem"):
            if field_name in plan.fields and str(plan.fields[field_name]).strip() != GOOGLE_ADS_ORIGIN:
                errors.append(f"{plan.contact_uuid}: origem de anúncio não autorizada pelo detector Google Ads")

        if set(plan.fields) & PURCHASE_FIELDS and not plan.purchase_confirmed:
            errors.append(
                f"{plan.contact_uuid}: campos de pedido sem confirmação FarmaLíder"
            )

        for action in plan.group_actions:
            if action.action not in {"add", "remove"}:
                errors.append(f"{plan.contact_uuid}: ação de grupo inválida")
            if not action.group:
                errors.append(f"{plan.contact_uuid}: grupo vazio")
                continue

            group_name = (action.group_name or action.group).strip()
            if (
                group_name.casefold() == WENI_UPDATE_OPT_IN_GROUP.casefold()
                and not opt_in_group_available
            ):
                errors.append(
                    f"{plan.contact_uuid}: grupo '{WENI_UPDATE_OPT_IN_GROUP}' não foi localizado"
                )
            if (
                group_name.casefold() == WENI_UPDATE_OPT_OUT_GROUP.casefold()
                and not opt_out_group_available
            ):
                errors.append(
                    f"{plan.contact_uuid}: grupo '{WENI_UPDATE_OPT_OUT_GROUP}' não foi localizado"
                )

    if errors:
        preview = "\n".join(f"- {item}" for item in errors[:30])
        if len(errors) > 30:
            preview += f"\n- ... e mais {len(errors) - 30} erro(s)"
        raise PlanAuditError(
            "Auditoria obrigatória do plano falhou. Nenhuma gravação foi iniciada:\n"
            + preview
        )


def _audit_plan_event(
    plan: ContactUpdatePlan,
    *,
    mode: str,
    status: str,
    error: str = "",
) -> dict[str, Any]:
    return {
        "timestamp_utc": iso_utc(utc_now()),
        "mode": mode,
        "status": status,
        "contact_uuid": plan.contact_uuid,
        "previous": plan.previous,
        "guards": plan.guards,
        "changes": plan.fields,
        "evidence": plan.evidence,
        "group_actions": [asdict(item) for item in plan.group_actions],
        "purchase_confirmed": plan.purchase_confirmed,
        "purchase_confirmation": plan.purchase_confirmation,
        "error": error,
    }


REVIEW_SCHEMA_VERSION = 5


def _canonical_plan(plan: ContactUpdatePlan) -> dict[str, Any]:
    """Parte semanticamente relevante do plano usada para travar o apply ao dry-run revisado."""
    return {
        "contact_uuid": plan.contact_uuid,
        "previous": plan.previous,
        "guards": plan.guards,
        "changes": plan.fields,
        "evidence": plan.evidence,
        "group_actions": [asdict(item) for item in plan.group_actions],
        "purchase_confirmed": plan.purchase_confirmed,
        "purchase_confirmation": plan.purchase_confirmation,
    }


def _plan_digest(plans: list[ContactUpdatePlan]) -> str:
    canonical = [_canonical_plan(plan) for plan in sorted(plans, key=lambda item: item.contact_uuid)]
    payload = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _display_value(value: Any) -> str:
    if value is None or str(value).strip() == "":
        return "<vazio>"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return str(value)


def _review_summary(plans: list[ContactUpdatePlan], stats: UpdateStats) -> dict[str, Any]:
    field_counts: dict[str, int] = {}
    opt_in_add = 0
    opt_in_remove = 0
    opt_out_add = 0
    opt_out_remove = 0
    lgpd_contacts = 0
    cpf_contacts = 0
    age_contacts = 0
    purchase_contacts = 0
    channel_contacts = 0
    google_ads_contacts = 0
    principal_channels: dict[str, int] = {}

    for plan in plans:
        for field_name in plan.fields:
            field_counts[field_name] = field_counts.get(field_name, 0) + 1
        if "opt_in_lgpd" in plan.fields:
            lgpd_contacts += 1
        if "cpf" in plan.fields:
            cpf_contacts += 1
        if {"idade", "maior_de_18_anos"} & set(plan.fields):
            age_contacts += 1
        if PURCHASE_FIELDS & set(plan.fields):
            purchase_contacts += 1
        if {"contact_urn", "contact_urn_whatsapp", "contact_urn_instagram", "contact_urn_facebook", "contact_canal_principal"} & set(plan.fields):
            channel_contacts += 1
        if any(
            str(plan.fields.get(field_name) or "").strip().casefold() == "google ads"
            for field_name in ("primeiro_anuncio_origem", "ultimo_anuncio_origem")
        ):
            google_ads_contacts += 1
        if plan.contact_channel:
            principal_channels[plan.contact_channel] = principal_channels.get(plan.contact_channel, 0) + 1
        for action in plan.group_actions:
            group_name = (action.group_name or action.group).strip().casefold()
            if group_name == WENI_UPDATE_OPT_IN_GROUP.casefold():
                if action.action == "add":
                    opt_in_add += 1
                elif action.action == "remove":
                    opt_in_remove += 1
            elif group_name == WENI_UPDATE_OPT_OUT_GROUP.casefold():
                if action.action == "add":
                    opt_out_add += 1
                elif action.action == "remove":
                    opt_out_remove += 1

    return {
        "messages_incoming": stats.messages_incoming,
        "contacts_considered": stats.contacts_considered,
        "contacts_with_changes": len(plans),
        "field_changes": sum(len(plan.fields) for plan in plans),
        "group_actions": sum(len(plan.group_actions) for plan in plans),
        "purchase_confirmed": stats.purchase_confirmed,
        "field_counts": dict(sorted(field_counts.items())),
        "lgpd_contacts": lgpd_contacts,
        "cpf_contacts": cpf_contacts,
        "age_or_majority_contacts": age_contacts,
        "purchase_contacts": purchase_contacts,
        "channel_contacts": channel_contacts,
        "google_ads_contacts": google_ads_contacts,
        "principal_channels": dict(sorted(principal_channels.items())),
        "opt_in_additions": opt_in_add,
        "opt_in_removals": opt_in_remove,
        "opt_out_additions": opt_out_add,
        "opt_out_removals": opt_out_remove,
    }


def write_review_snapshot(
    plans: list[ContactUpdatePlan],
    stats: UpdateStats,
    *,
    full: bool,
    json_path: Path,
    captured_at_utc: str = "",
) -> tuple[Path, Path, str]:
    """Grava snapshot verificável e relatório TXT para revisão humana antes do apply."""
    json_path = Path(json_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    txt_path = json_path.with_suffix(".txt")
    digest = _plan_digest(plans)
    summary = _review_summary(plans, stats)

    created_at = iso_utc(utc_now())
    snapshot_cutoff = str(captured_at_utc or created_at).strip()
    payload = {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "created_at_utc": created_at,
        "captured_at_utc": snapshot_cutoff,
        "mode": "full" if full else "incremental",
        "plan_sha256": digest,
        "summary": summary,
        "plans": [
            {
                "display": {
                    "contact_name": plan.contact_name,
                    "contact_urn": plan.contact_urn,
                    "contact_channel": plan.contact_channel,
                },
                **_canonical_plan(plan),
            }
            for plan in sorted(plans, key=lambda item: item.contact_uuid)
        ],
    }
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    lines = [
        "==========================================================",
        " NexoFlow - Revisão Humana do NexoFlow Weni",
        "==========================================================",
        "",
        f"Gerado em UTC: {payload['created_at_utc']}",
        f"Corte do snapshot em UTC: {payload['captured_at_utc']}",
        f"Modo: {'CARGA COMPLETA' if full else 'INCREMENTAL'}",
        f"Plano SHA-256: {digest}",
        "",
        "IMPORTANTE:",
        "Este relatório é somente leitura. Nenhuma alteração foi aplicada.",
        "Na carga completa, este plano fica CONGELADO após o dry-run.",
        "Novas mensagens e novos contatos não invalidam toda a carga.",
        "No apply, cada contato é relido imediatamente antes da gravação.",
        "Se os dados relevantes daquele contato mudaram, somente ele é",
        "ignorado como conflito e será reprocessado pela próxima incremental.",
        "",
        "RESUMO",
        "----------------------------------------------------------",
        f"Mensagens recebidas analisadas: {summary['messages_incoming']}",
        f"Contatos considerados: {summary['contacts_considered']}",
        f"Contatos com alterações: {summary['contacts_with_changes']}",
        f"Alterações de campos: {summary['field_changes']}",
        f"Ações de grupo: {summary['group_actions']}",
        f"Contatos com alteração de LGPD: {summary['lgpd_contacts']}",
        f"Contatos com CPF detectado/alterado: {summary['cpf_contacts']}",
        f"Contatos com identificação de canal alterada: {summary['channel_contacts']}",
        f"Contatos com atribuição Google Ads detectada/atualizada: {summary['google_ads_contacts']}",
        f"Canais principais no plano: {summary['principal_channels']}",
        f"Contatos com idade/maioridade: {summary['age_or_majority_contacts']}",
        f"Inclusões em Opt-In LGPD: {summary['opt_in_additions']}",
        f"Remoções de Opt-In LGPD: {summary['opt_in_removals']}",
        f"Inclusões em Opt-Out LGPD: {summary['opt_out_additions']}",
        f"Remoções de Opt-Out LGPD: {summary['opt_out_removals']}",
        f"Contatos com campos de pedido: {summary['purchase_contacts']}",
        f"Pedidos confirmados pela FarmaLíder: {summary['purchase_confirmed']}",
        "",
        "ALTERAÇÕES POR CAMPO",
        "----------------------------------------------------------",
    ]
    if summary["field_counts"]:
        for field_name, count in summary["field_counts"].items():
            lines.append(f"{field_name}: {count}")
    else:
        lines.append("Nenhuma alteração de campo proposta.")

    lines.extend(["", "DETALHES POR CONTATO", "=========================================================="])
    if not plans:
        lines.append("Nenhuma alteração proposta.")

    for index, plan in enumerate(sorted(plans, key=lambda item: item.contact_uuid), start=1):
        label = plan.contact_name or "Contato sem nome"
        lines.extend([
            "",
            f"[{index}] {label}",
            f"UUID: {plan.contact_uuid}",
            f"URN principal: {plan.contact_urn or '<não disponível>'}",
            f"Canal principal: {plan.contact_channel or '<não identificado>'}",
        ])
        if plan.fields:
            lines.append("Campos:")
            for field_name in sorted(plan.fields):
                previous = _display_value(plan.previous.get(field_name))
                proposed = _display_value(plan.fields.get(field_name))
                lines.append(f"  - {field_name}: {previous}  ->  {proposed}")
                evidence = plan.evidence.get(field_name) or {}
                evidence_parts = []
                if evidence.get("message_id"):
                    evidence_parts.append(f"mensagem={evidence['message_id']}")
                if evidence.get("created_on"):
                    evidence_parts.append(f"data={evidence['created_on']}")
                if evidence.get("reason"):
                    evidence_parts.append(f"motivo={evidence['reason']}")
                if evidence_parts:
                    lines.append("    Evidência: " + " | ".join(evidence_parts))
        if plan.group_actions:
            lines.append("Grupos:")
            for action in plan.group_actions:
                verb = "ADICIONAR" if action.action == "add" else "REMOVER"
                group_label = action.group_name or action.group
                lines.append(
                    f"  - {verb} em {group_label} "
                    f"(alvo={action.group}) | motivo={action.reason}"
                )
        if plan.purchase_confirmed:
            lines.append(
                "Pedido FarmaLíder: CONFIRMADO"
                + (f" | {plan.purchase_confirmation}" if plan.purchase_confirmation else "")
            )

    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    return json_path, txt_path, digest


def verify_review_snapshot(
    plans: list[ContactUpdatePlan],
    *,
    full: bool,
    json_path: Path,
) -> str:
    """Impede aplicar um plano diferente daquele que foi exibido ao operador."""
    path = Path(json_path)
    if not path.exists():
        raise PlanAuditError(
            f"Snapshot de revisão não encontrado: {path}. Execute o dry-run e revise o relatório novamente."
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PlanAuditError("Snapshot de revisão inválido ou corrompido.") from exc

    if payload.get("schema_version") != REVIEW_SCHEMA_VERSION:
        raise PlanAuditError("Versão do snapshot de revisão incompatível.")
    expected_mode = "full" if full else "incremental"
    if payload.get("mode") != expected_mode:
        raise PlanAuditError("O snapshot revisado pertence a outro modo de execução.")

    reviewed_digest = str(payload.get("plan_sha256") or "").strip().lower()
    current_digest = _plan_digest(plans)
    if not reviewed_digest or reviewed_digest != current_digest:
        raise PlanAuditError(
            "O plano mudou depois da revisão humana. Nenhuma gravação foi iniciada. "
            "Execute novamente o dry-run, revise o novo relatório e confirme outra vez."
        )
    logging.info("Plano atual confere com o snapshot revisado: %s", current_digest)
    return current_digest


def load_review_snapshot(
    *,
    full: bool,
    json_path: Path,
) -> tuple[list[ContactUpdatePlan], dict[str, Any], str]:
    """Carrega exatamente o plano revisado e valida a integridade do snapshot."""
    path = Path(json_path)
    if not path.exists():
        raise PlanAuditError(
            f"Snapshot de revisão não encontrado: {path}. Execute o dry-run e revise o relatório novamente."
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PlanAuditError("Snapshot de revisão inválido ou corrompido.") from exc

    if payload.get("schema_version") != REVIEW_SCHEMA_VERSION:
        raise PlanAuditError(
            "Versão do snapshot de revisão incompatível. Execute novamente a carga completa para gerar um snapshot novo."
        )
    expected_mode = "full" if full else "incremental"
    if payload.get("mode") != expected_mode:
        raise PlanAuditError("O snapshot revisado pertence a outro modo de execução.")

    raw_plans = payload.get("plans")
    if not isinstance(raw_plans, list):
        raise PlanAuditError("Snapshot de revisão sem lista de planos válida.")

    plans: list[ContactUpdatePlan] = []
    for raw in raw_plans:
        if not isinstance(raw, dict):
            raise PlanAuditError("Snapshot de revisão contém plano inválido.")
        display = raw.get("display") if isinstance(raw.get("display"), dict) else {}
        raw_actions = raw.get("group_actions") or []
        if not isinstance(raw_actions, list):
            raise PlanAuditError("Snapshot de revisão contém ações de grupo inválidas.")
        actions: list[GroupAction] = []
        for item in raw_actions:
            if not isinstance(item, dict):
                raise PlanAuditError("Snapshot de revisão contém ação de grupo inválida.")
            actions.append(
                GroupAction(
                    action=str(item.get("action") or ""),
                    group=str(item.get("group") or ""),
                    reason=str(item.get("reason") or ""),
                    group_name=str(item.get("group_name") or ""),
                )
            )
        plan = ContactUpdatePlan(
            contact_uuid=str(raw.get("contact_uuid") or "").strip(),
            contact_name=str(display.get("contact_name") or "").strip(),
            contact_urn=str(display.get("contact_urn") or "").strip(),
            contact_channel=str(display.get("contact_channel") or "").strip(),
            fields=dict(raw.get("changes") or {}),
            previous=dict(raw.get("previous") or {}),
            guards=dict(raw.get("guards") or {}),
            evidence=dict(raw.get("evidence") or {}),
            group_actions=actions,
            purchase_confirmed=bool(raw.get("purchase_confirmed")),
            purchase_confirmation=str(raw.get("purchase_confirmation") or ""),
        )
        plans.append(plan)

    reviewed_digest = str(payload.get("plan_sha256") or "").strip().lower()
    current_digest = _plan_digest(plans)
    if not reviewed_digest or reviewed_digest != current_digest:
        raise PlanAuditError(
            "O snapshot de revisão foi alterado ou está corrompido. Nenhuma gravação foi iniciada."
        )

    captured_at = str(payload.get("captured_at_utc") or "").strip()
    if not captured_at or _parse_datetime(captured_at) is None:
        raise PlanAuditError("Snapshot de revisão sem corte temporal válido.")

    logging.info(
        "Snapshot revisado carregado sem recalcular o histórico: %s contato(s) | sha256=%s",
        len(plans),
        current_digest,
    )
    return plans, payload, current_digest


def _same_guard_value(current: Any, expected: Any) -> bool:
    if isinstance(current, (dict, list)) or isinstance(expected, (dict, list)):
        try:
            left = json.dumps(current, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
            right = json.dumps(expected, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
            return left == right
        except TypeError:
            pass
    return _semantic_text(current).casefold() == _semantic_text(expected).casefold()


def _prepare_frozen_plan_for_apply(
    plan: ContactUpdatePlan,
    current_contact: dict[str, Any],
    *,
    opt_in_group_name: str,
    opt_in_group_uuid: str,
    opt_out_group_name: str,
    opt_out_group_uuid: str,
) -> tuple[ContactUpdatePlan | None, str]:
    """
    Faz controle otimista por contato sem recalcular mensagens/histórico.

    Retorna um plano somente com operações ainda pendentes. Se algum valor
    relevante mudou para algo diferente do anterior e do revisado, o contato
    inteiro é marcado como conflito para não sobrescrever informação nova.
    """
    current_fields = get_fields(current_contact)
    pending_fields: dict[str, Any] = {}
    conflicts: list[str] = []

    for field_name, proposed in plan.fields.items():
        current = current_fields.get(field_name)
        previous = plan.previous.get(field_name)
        if _same_value(field_name, current, proposed):
            # Outra automação já chegou ao mesmo resultado. Não regrava.
            continue
        if _same_value(field_name, current, previous):
            pending_fields[field_name] = proposed
            continue
        conflicts.append(
            f"{field_name} mudou de {_display_value(previous)} para {_display_value(current)}"
        )

    for guard_name, expected in plan.guards.items():
        if guard_name == "__native_urns":
            current_native = sorted(native_contact_urns(current_contact))
            expected_native = sorted(str(item) for item in (expected or []) if str(item).strip())
            if current_native != expected_native:
                conflicts.append("URNs nativas da Weni mudaram após a revisão")
            continue

        # Quando o próprio plano altera o campo guardado, o teste de previous
        # acima já faz a validação correta (anterior ou proposto).
        if guard_name in plan.fields:
            continue
        current = current_fields.get(guard_name)
        if not _same_guard_value(current, expected):
            conflicts.append(
                f"fonte {guard_name} mudou de {_display_value(expected)} para {_display_value(current)}"
            )

    if conflicts:
        return None, "; ".join(conflicts[:8])

    pending_actions: list[GroupAction] = []
    for action in plan.group_actions:
        group_name = action.group_name or action.group
        group_uuid = action.group
        if group_name.strip().casefold() == opt_in_group_name.strip().casefold():
            group_uuid = opt_in_group_uuid or action.group
        elif group_name.strip().casefold() == opt_out_group_name.strip().casefold():
            group_uuid = opt_out_group_uuid or action.group
        is_member = _contact_in_group(
            current_contact,
            group_name=group_name,
            group_uuid=group_uuid,
        )
        if action.action == "add" and is_member:
            continue
        if action.action == "remove" and not is_member:
            continue
        pending_actions.append(
            GroupAction(
                action=action.action,
                group=group_uuid,
                reason=action.reason,
                group_name=group_name,
            )
        )

    prepared = ContactUpdatePlan(
        contact_uuid=plan.contact_uuid,
        contact_name=plan.contact_name,
        contact_urn=plan.contact_urn,
        contact_channel=plan.contact_channel,
        fields=pending_fields,
        previous=plan.previous,
        guards=plan.guards,
        evidence=plan.evidence,
        group_actions=pending_actions,
        purchase_confirmed=plan.purchase_confirmed,
        purchase_confirmation=plan.purchase_confirmation,
    )
    return prepared, ""


def _build_context_for_contact(
    client: WeniClient,
    *,
    contact_uuid: str,
    candidate_messages: list[dict[str, Any]],
    started_at: datetime,
    full: bool,
) -> list[dict[str, Any]]:
    if not candidate_messages:
        return []
    if full:
        return client.list_messages(
            contact=contact_uuid,
            before=started_at,
        )

    timestamps = [
        dt
        for dt in (_parse_datetime(message_created_on(item)) for item in candidate_messages)
        if dt is not None
    ]
    earliest = min(timestamps) if timestamps else started_at
    context_start = earliest - timedelta(hours=WENI_UPDATE_CONTEXT_LOOKBACK_HOURS)
    return client.list_messages(
        after=context_start,
        before=started_at,
        contact=contact_uuid,
    )


def _resolve_group(client: WeniClient, group_name: str) -> tuple[bool, str]:
    groups = client.list_groups(group_name)
    for group in groups:
        name = str(group.get("name") or "").strip()
        if name.casefold() == group_name.casefold():
            return True, str(group.get("uuid") or "").strip()
    return False, ""

def _resolve_required_groups(
    client: WeniClient,
    group_names: tuple[str, ...],
) -> dict[str, tuple[bool, str]]:
    """Resolve vários grupos com uma única listagem da API."""
    groups = client.list_groups()
    by_name = {
        str(group.get("name") or "").strip().casefold(): str(group.get("uuid") or "").strip()
        for group in groups
        if isinstance(group, dict) and str(group.get("name") or "").strip()
    }
    return {
        name: (name.casefold() in by_name, by_name.get(name.casefold(), ""))
        for name in group_names
    }


def _available_weni_fields(client: WeniClient) -> set[str]:
    fields = client.list_fields()
    return {
        str(item.get("key") or "").strip()
        for item in fields
        if isinstance(item, dict) and str(item.get("key") or "").strip()
    }


def _missing_multichannel_fields(client: WeniClient, available: set[str] | None = None) -> list[str]:
    available_fields = available if available is not None else _available_weni_fields(client)
    return sorted(REQUIRED_MULTICHANNEL_FIELDS - available_fields)


def _missing_google_ads_fields(available: set[str]) -> list[str]:
    return sorted(GOOGLE_ADS_WRITE_FIELDS - available)


def _ensure_multichannel_fields(client: WeniClient, available: set[str] | None = None) -> None:
    missing = _missing_multichannel_fields(client, available)
    if not missing:
        return
    joined = ", ".join(missing)
    raise PlanAuditError(
        "Campos multicanal obrigatórios não existem na Weni: "
        f"{joined}. Crie esses campos como Texto na Weni antes de continuar. "
        "Nenhuma alteração foi gravada."
    )


def _resolve_opt_out_group(client: WeniClient) -> tuple[bool, str]:
    return _resolve_group(client, WENI_UPDATE_OPT_OUT_GROUP)


def _resolve_opt_in_group(client: WeniClient) -> tuple[bool, str]:
    return _resolve_group(client, WENI_UPDATE_OPT_IN_GROUP)


def _open_farmalider() -> FarmaliderClient | None:
    enabled = bool(getattr(secrets, "FARMALIDER_API_ENABLED", True))
    token = str(getattr(secrets, "FARMALIDER_API_TOKEN", "")).strip()
    placeholder = "COLE_SEU_TOKEN_FARMALIDER_AQUI"
    if not enabled:
        logging.warning(
            "FarmaLíder API desabilitada: campos de compra não serão atualizados."
        )
        return None
    if not token or token == placeholder:
        logging.warning(
            "Token FarmaLíder ausente: campos de compra não serão atualizados."
        )
        return None
    use_hml = bool(getattr(secrets, "FARMALIDER_USE_HML", False))
    return FarmaliderClient(token, use_hml=use_hml)


def check_update_connections() -> dict[str, Any]:
    token = str(getattr(secrets, "WENI_API_TOKEN", "")).strip()
    if not token or token == "COLE_SEU_TOKEN_WENI_AQUI":
        raise RuntimeError("Token da Weni não configurado em secrets_config.py.")

    result: dict[str, Any] = {}
    weni = WeniClient(token)
    farm: FarmaliderClient | None = None
    try:
        result["weni"] = weni.test_update_access(WENI_UPDATE_OPT_OUT_GROUP)
        opt_in_available, _ = _resolve_opt_in_group(weni)
        available_fields = _available_weni_fields(weni)
        result["weni"]["opt_in_group_found"] = opt_in_available
        result["weni"]["missing_multichannel_fields"] = _missing_multichannel_fields(weni, available_fields)
        result["weni"]["missing_google_ads_fields"] = _missing_google_ads_fields(available_fields)
        farm = _open_farmalider()
        if farm is not None:
            result["farmalider"] = farm.test_connection()
        else:
            result["farmalider"] = {"ok": False, "optional": True}
        return result
    finally:
        _close_audit_handles()
        weni.close()
        if farm is not None:
            farm.close()


def run_update(
    *,
    apply: bool,
    full: bool = False,
    review_out: Path | None = None,
    require_review: Path | None = None,
) -> UpdateStats:
    token = str(getattr(secrets, "WENI_API_TOKEN", "")).strip()
    if not token or token == "COLE_SEU_TOKEN_WENI_AQUI":
        raise RuntimeError("Token da Weni não configurado em secrets_config.py.")

    frozen_full_apply = bool(apply and full and require_review is not None)
    window = None if frozen_full_apply else resolve_window(full=full)
    stats = UpdateStats()
    weni = WeniClient(token)
    farm = None if frozen_full_apply else _open_farmalider()
    captured_at = "" if window is None else iso_utc(window.started_at)

    try:
        available_weni_fields = _available_weni_fields(weni)
        _ensure_multichannel_fields(weni, available_weni_fields)
        missing_google_ads = _missing_google_ads_fields(available_weni_fields)
        if missing_google_ads:
            logging.warning(
                "Campos de atribuição Google Ads ausentes na Weni: %s. "
                "A detecção continuará, mas esses metadados não serão gravados até os campos existirem.",
                ", ".join(missing_google_ads),
            )
        resolved_groups = _resolve_required_groups(
            weni,
            (WENI_UPDATE_OPT_OUT_GROUP, WENI_UPDATE_OPT_IN_GROUP),
        )
        opt_out_available, opt_out_uuid = resolved_groups[WENI_UPDATE_OPT_OUT_GROUP]
        opt_in_available, opt_in_uuid = resolved_groups[WENI_UPDATE_OPT_IN_GROUP]
        logging.info(
            "Weni: grupos operacionais resolvidos em uma única listagem da API."
        )
        if not opt_in_available:
            logging.warning(
                "Grupo '%s' não foi localizado. Planos de Opt-In serão bloqueados pela auditoria.",
                WENI_UPDATE_OPT_IN_GROUP,
            )
        if not opt_out_available:
            logging.warning(
                "Grupo '%s' não foi localizado. Planos de Opt-Out serão bloqueados pela auditoria.",
                WENI_UPDATE_OPT_OUT_GROUP,
            )

        if frozen_full_apply:
            plans, review_payload, digest = load_review_snapshot(
                full=True,
                json_path=Path(require_review),
            )
            audit_plans(
                plans,
                opt_out_group_available=opt_out_available,
                opt_in_group_available=opt_in_available,
            )

            summary = review_payload.get("summary") if isinstance(review_payload.get("summary"), dict) else {}
            stats.messages_incoming = int(summary.get("messages_incoming") or 0)
            stats.contacts_considered = int(summary.get("contacts_considered") or len(plans))
            stats.plans_with_changes = len(plans)
            stats.field_changes = sum(len(plan.fields) for plan in plans)
            stats.group_actions = sum(len(plan.group_actions) for plan in plans)
            stats.purchase_confirmed = sum(1 for plan in plans if plan.purchase_confirmed)
            captured_at = str(review_payload.get("captured_at_utc") or "").strip()

            logging.info(
                "APPLY de carga completa usará o snapshot congelado; o histórico não será recalculado. "
                "Novas mensagens/contatos ficam para a próxima incremental."
            )

            conflicted_uuids: list[str] = []
            for index, plan in enumerate(plans, start=1):
                # Em atendimento 24h, relê somente este contato imediatamente
                # antes da escrita. Mudanças em outros contatos não cancelam a carga.
                current_contact = weni.get_contact(uuid=plan.contact_uuid)
                stats.contacts_modified += 1
                if current_contact is None:
                    stats.contacts_conflicted += 1
                    conflicted_uuids.append(plan.contact_uuid)
                    reason = "contato não localizado no momento do apply"
                    _append_audit(
                        _audit_plan_event(
                            plan,
                            mode="apply-frozen",
                            status="conflict_skipped",
                            error=reason,
                        )
                    )
                    logging.warning(
                        "Conflito %s/%s em %s: %s",
                        index,
                        len(plans),
                        plan.contact_uuid,
                        reason,
                    )
                    continue

                prepared, conflict = _prepare_frozen_plan_for_apply(
                    plan,
                    current_contact,
                    opt_in_group_name=WENI_UPDATE_OPT_IN_GROUP,
                    opt_in_group_uuid=opt_in_uuid,
                    opt_out_group_name=WENI_UPDATE_OPT_OUT_GROUP,
                    opt_out_group_uuid=opt_out_uuid,
                )
                if prepared is None:
                    stats.contacts_conflicted += 1
                    conflicted_uuids.append(plan.contact_uuid)
                    _append_audit(
                        _audit_plan_event(
                            plan,
                            mode="apply-frozen",
                            status="conflict_skipped",
                            error=conflict,
                        )
                    )
                    logging.warning(
                        "Conflito %s/%s em %s: %s",
                        index,
                        len(plans),
                        plan.contact_uuid,
                        conflict,
                    )
                    continue

                if not prepared.has_changes:
                    stats.contacts_already_satisfied += 1
                    _append_audit(
                        _audit_plan_event(
                            plan,
                            mode="apply-frozen",
                            status="already_satisfied",
                        )
                    )
                    continue

                try:
                    if prepared.fields:
                        weni.update_contact_fields(prepared.contact_uuid, prepared.fields)
                    for action in prepared.group_actions:
                        weni.contact_group_action(
                            prepared.contact_uuid,
                            action=action.action,
                            group=action.group,
                        )
                    stats.contacts_updated += 1
                    _append_audit(
                        _audit_plan_event(
                            prepared,
                            mode="apply-frozen",
                            status="applied",
                        )
                    )
                except Exception as exc:
                    stats.contacts_failed += 1
                    _append_audit(
                        _audit_plan_event(
                            prepared,
                            mode="apply-frozen",
                            status="failed",
                            error=exc.__class__.__name__,
                        )
                    )
                    raise RuntimeError(
                        "Falha durante a gravação do snapshot congelado na Weni. "
                        "O checkpoint não foi avançado."
                    ) from exc

                if index % 250 == 0:
                    logging.info(
                        "Aplicação do snapshot: %s/%s revisados | aplicados=%s | conflitos=%s | já satisfeitos=%s",
                        index,
                        len(plans),
                        stats.contacts_updated,
                        stats.contacts_conflicted,
                        stats.contacts_already_satisfied,
                    )

            _save_state(
                {
                    "last_success_utc": captured_at,
                    "last_mode": "full-frozen-snapshot",
                    "review_sha256": digest,
                    "contacts_updated": stats.contacts_updated,
                    "contacts_conflicted": stats.contacts_conflicted,
                    "pending_conflict_uuids": conflicted_uuids,
                    "contacts_already_satisfied": stats.contacts_already_satisfied,
                    "field_changes": stats.field_changes,
                    "group_actions": stats.group_actions,
                }
            )
            logging.info(
                "Snapshot congelado concluído: aplicados=%s | conflitos ignorados=%s | já satisfeitos=%s. "
                "O checkpoint foi mantido no corte do dry-run para que mudanças posteriores sejam reprocessadas.",
                stats.contacts_updated,
                stats.contacts_conflicted,
                stats.contacts_already_satisfied,
            )
            return stats

        assert window is not None

        incoming = weni.list_messages(
            after=window.after,
            before=window.started_at,
            folder="incoming",
        )
        stats.messages_incoming = len(incoming)
        incoming_by_contact = _group_messages_by_contact(incoming)
        full_context_by_contact: dict[str, list[dict[str, Any]]] = {}
        if window.full:
            # Na carga completa, busca o histórico contextual uma única vez.
            # Evita uma chamada paginada por contato.
            all_context_messages = weni.list_messages(before=window.started_at)
            full_context_by_contact = _group_messages_by_contact(all_context_messages)

        modified_contacts = weni.list_contacts(after=window.after)
        stats.contacts_modified = len(modified_contacts)
        contacts_by_uuid = {
            str(contact.get("uuid") or "").strip(): contact
            for contact in modified_contacts
            if str(contact.get("uuid") or "").strip()
        }

        # Conflitos isolados de uma carga completa congelada entram
        # explicitamente na próxima incremental, mesmo se a Weni não refletir
        # a mudança no modified_on do contato (por exemplo, só associação a grupo).
        state = _load_state()
        pending_conflicts = state.get("pending_conflict_uuids") or []
        if isinstance(pending_conflicts, list) and pending_conflicts:
            unique_pending = sorted({str(item).strip() for item in pending_conflicts if str(item).strip()})
            logging.info(
                "Reprocessando %s conflito(s) pendente(s) da carga completa.",
                len(unique_pending),
            )
            for pending_uuid in unique_pending:
                if pending_uuid in contacts_by_uuid:
                    continue
                pending_contact = weni.get_contact(uuid=pending_uuid)
                if pending_contact is not None:
                    contacts_by_uuid[pending_uuid] = pending_contact

        # Mensagens eventualmente podem vir sem UUID no payload. Resolve cada
        # URN apenas uma vez; mensagens repetidas do mesmo canal reutilizam cache.
        urn_contact_cache: dict[str, dict[str, Any] | None] = {}
        for message in incoming:
            uuid = _extract_contact_uuid(message)
            if uuid:
                continue
            urn = _extract_message_urn(message)
            if not urn:
                continue
            if urn not in urn_contact_cache:
                urn_contact_cache[urn] = weni.get_contact(urn=urn)
            contact = urn_contact_cache[urn]
            if contact is None:
                continue
            resolved_uuid = str(contact.get("uuid") or "").strip()
            if not resolved_uuid:
                continue
            contacts_by_uuid[resolved_uuid] = contact
            incoming_by_contact.setdefault(resolved_uuid, []).append(message)
        if urn_contact_cache:
            logging.info(
                "Weni: %s URN(s) sem UUID resolvida(s) com cache local.",
                len(urn_contact_cache),
            )

        all_contact_uuids = set(contacts_by_uuid) | set(incoming_by_contact)
        plans: list[ContactUpdatePlan] = []

        for contact_uuid in sorted(all_contact_uuids):
            contact = contacts_by_uuid.get(contact_uuid)
            if contact is None:
                contact = weni.get_contact(uuid=contact_uuid)
            if contact is None:
                logging.warning("Contato %s não foi localizado; ignorando.", contact_uuid)
                continue

            candidate_messages = incoming_by_contact.get(contact_uuid, [])
            candidate_ids = {
                message_id(item) for item in candidate_messages if message_id(item)
            }
            if window.full:
                context = full_context_by_contact.get(contact_uuid, candidate_messages)
            else:
                context = _build_context_for_contact(
                    weni,
                    contact_uuid=contact_uuid,
                    candidate_messages=candidate_messages,
                    started_at=window.started_at,
                    full=False,
                )
                if not context:
                    context = candidate_messages

            plan = _build_contact_plan(
                contact,
                context_messages=context,
                candidate_message_ids=candidate_ids,
                farm_client=farm,
                opt_out_group_name=WENI_UPDATE_OPT_OUT_GROUP,
                opt_out_group_uuid=opt_out_uuid,
                captured_at=captured_at,
                opt_in_group_name=WENI_UPDATE_OPT_IN_GROUP,
                opt_in_group_uuid=opt_in_uuid,
                available_weni_fields=available_weni_fields,
            )
            stats.contacts_considered += 1
            if plan.purchase_confirmed:
                stats.purchase_confirmed += 1
            elif str(get_fields(contact).get("ultimo_pedido") or "").strip():
                stats.purchase_skipped += 1

            if plan.has_changes:
                plans.append(plan)

        stats.plans_with_changes = len(plans)
        stats.field_changes = sum(len(plan.fields) for plan in plans)
        stats.group_actions = sum(len(plan.group_actions) for plan in plans)

        # ETAPA OBRIGATÓRIA: nenhum POST é feito antes desta auditoria completa.
        audit_plans(
            plans,
            opt_out_group_available=opt_out_available,
            opt_in_group_available=opt_in_available,
        )
        logging.info(
            "Auditoria do plano aprovada: %s contato(s), %s campo(s), %s ação(ões) de grupo.",
            stats.plans_with_changes,
            stats.field_changes,
            stats.group_actions,
        )

        if review_out is not None:
            review_json, review_txt, digest = write_review_snapshot(
                plans,
                stats,
                full=full,
                json_path=Path(review_out),
                captured_at_utc=captured_at,
            )
            logging.info(
                "Relatório de revisão humana gerado: %s | snapshot=%s | sha256=%s",
                review_txt,
                review_json,
                digest,
            )

        if apply and full and require_review is None:
            raise PlanAuditError(
                "Carga completa em modo APPLY exige um snapshot de revisão humana. "
                "Execute primeiro o dry-run completo e revise o relatório."
            )
        if require_review is not None:
            verify_review_snapshot(plans, full=full, json_path=Path(require_review))

        mode = "apply" if apply else "dry-run"
        if not apply:
            for plan in plans:
                _append_audit(_audit_plan_event(plan, mode=mode, status="planned"))
            logging.info("DRY-RUN concluído. Nenhum contato foi alterado na Weni.")
            return stats

        for plan in plans:
            try:
                if plan.fields:
                    weni.update_contact_fields(plan.contact_uuid, plan.fields)
                for action in plan.group_actions:
                    weni.contact_group_action(
                        plan.contact_uuid,
                        action=action.action,
                        group=action.group,
                    )
                stats.contacts_updated += 1
                _append_audit(_audit_plan_event(plan, mode=mode, status="applied"))
            except Exception as exc:
                stats.contacts_failed += 1
                _append_audit(
                    _audit_plan_event(
                        plan,
                        mode=mode,
                        status="failed",
                        error=exc.__class__.__name__,
                    )
                )
                # Não avança checkpoint. A próxima execução reprocessará a janela
                # e corrigirá com segurança o que já tiver sido gravado.
                raise RuntimeError(
                    "Falha durante a gravação na Weni. O checkpoint não foi avançado."
                ) from exc

        _save_state(
            {
                "last_success_utc": captured_at,
                "last_mode": "full" if full else "incremental",
                "contacts_updated": stats.contacts_updated,
                "field_changes": stats.field_changes,
                "group_actions": stats.group_actions,
            }
        )
        return stats
    finally:
        _close_audit_handles()
        weni.close()
        if farm is not None:
            farm.close()
