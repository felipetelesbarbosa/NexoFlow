from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import defaultdict
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any, cast

from config import TIPO_PRIMEIRO_ANUNCIO, TIPO_ULTIMO_ANUNCIO
from geography import normalize_geography
from pedido_utils import (
    business_order_datetime,
    effective_order_status_code,
    farmalider_order_status_name,
    farmalider_payment_method_display,
    is_order_sale,
    normalize_farmalider_payment_code,
    parse_weni_order_list,
    weni_order_datetime_text,
)
from urn_utils import resolve_contact_urns

AD_FIELDS = [
    "primeiro_anuncio_origem",
    "primeiro_anuncio_id",
    "primeiro_anuncio_titulo",
    "primeiro_anuncio_url",
    "primeiro_anuncio_clique_id",
    "primeiro_anuncio_data",
    "ultimo_anuncio_origem",
    "ultimo_anuncio_id",
    "ultimo_anuncio_titulo",
    "ultimo_anuncio_url",
    "ultimo_anuncio_clique_id",
    "ultimo_anuncio_data",
    "primeiro_anuncio_tipo_campanha",
    "primeiro_anuncio_canal_destino",
    "ultimo_anuncio_tipo_campanha",
    "ultimo_anuncio_canal_destino",
]

# Alias mantido para compatibilidade com integrações antigas do projeto.
META_FIELDS = AD_FIELDS


FULL_LOAD_25_PARTS = 4
FULL_LOAD_25_MANIFEST = Path("logs/full_load_25_manifest.json")
_FULL_LOAD_25_COMPONENTS = {"weni", "analytics"}


def _full_load_25_uuid(contact: dict[str, Any]) -> str:
    return str(contact.get("uuid") or contact.get("contact_uuid") or "").strip()


def _full_load_25_uuids(contacts: list[dict[str, Any]]) -> list[str]:
    return sorted(
        {
            _full_load_25_uuid(contact)
            for contact in contacts
            if _full_load_25_uuid(contact)
        }
    )


def _full_load_25_digest(uuids: list[str]) -> str:
    return hashlib.sha256("\n".join(uuids).encode("utf-8")).hexdigest()


def _full_load_25_write(payload: dict[str, Any]) -> None:
    path = FULL_LOAD_25_MANIFEST
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix="full-load-25-", suffix=".json", dir=path.parent
    )
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(path)
    finally:
        temp_path.unlink(missing_ok=True)


def _full_load_25_load() -> dict[str, Any]:
    path = FULL_LOAD_25_MANIFEST
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Manifesto da carga completa 25% inválido: {path}."
        ) from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise RuntimeError("Manifesto da carga completa 25% incompatível.")
    uuids = payload.get("contact_uuids")
    if not isinstance(uuids, list) or not uuids:
        raise RuntimeError("Manifesto da carga completa 25% sem contatos.")
    canonical = [str(item).strip() for item in uuids if str(item).strip()]
    if canonical != sorted(set(canonical)):
        raise RuntimeError("Manifesto da carga completa 25% fora da ordem canônica.")
    if _full_load_25_digest(canonical) != str(payload.get("contacts_sha256") or ""):
        raise RuntimeError("Manifesto da carga completa 25% falhou no SHA-256.")
    return payload


def _full_load_25_completed(
    payload: dict[str, Any],
    component: str,
) -> set[int]:
    completed = payload.get("completed")
    if not isinstance(completed, dict):
        return set()
    values = completed.get(component)
    if not isinstance(values, list):
        return set()
    return {
        int(item)
        for item in values
        if str(item).isdigit() and 1 <= int(item) <= FULL_LOAD_25_PARTS
    }


def _full_load_25_new_manifest(
    contacts: list[dict[str, Any]],
) -> dict[str, Any]:
    uuids = _full_load_25_uuids(contacts)
    if not uuids:
        raise RuntimeError(
            "A Weni não retornou contatos para criar a carga completa 25%."
        )
    captured = (
        datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    )
    digest = _full_load_25_digest(uuids)
    campaign_id = hashlib.sha256(f"{captured}|{digest}".encode()).hexdigest()[:16]
    return {
        "schema_version": 1,
        "campaign_id": campaign_id,
        "captured_at_utc": captured,
        "total_parts": FULL_LOAD_25_PARTS,
        "contact_count": len(uuids),
        "contacts_sha256": digest,
        "contact_uuids": uuids,
        "completed": {"weni": [], "analytics": []},
    }


def prepare_full_load_quarter(
    contacts: list[dict[str, Any]],
    *,
    part: int,
    component: str,
) -> dict[str, Any]:
    if component not in _FULL_LOAD_25_COMPONENTS:
        raise ValueError(f"Componente inválido na carga 25%: {component}")
    if part not in range(1, FULL_LOAD_25_PARTS + 1):
        raise ValueError("A parte da carga completa 25% deve ser 1, 2, 3 ou 4.")

    if FULL_LOAD_25_MANIFEST.exists():
        payload = _full_load_25_load()
        completed = _full_load_25_completed(payload, component)
        if part == 1 and part in completed:
            all_components_complete = all(
                _full_load_25_completed(payload, name)
                == set(range(1, FULL_LOAD_25_PARTS + 1))
                for name in _FULL_LOAD_25_COMPONENTS
            )
            if not all_components_complete:
                raise RuntimeError(
                    "A Parte 1 já foi concluída nesta campanha 25%. "
                    "Finalize as partes pendentes antes de iniciar uma nova."
                )
            FULL_LOAD_25_MANIFEST.with_name(
                "full_load_25_manifest.previous.json"
            ).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            payload = _full_load_25_new_manifest(contacts)
            _full_load_25_write(payload)
    else:
        if part != 1:
            raise RuntimeError(
                "A carga completa 25% ainda não foi iniciada. "
                "Execute primeiro a Parte 1."
            )
        payload = _full_load_25_new_manifest(contacts)
        _full_load_25_write(payload)

    completed = _full_load_25_completed(payload, component)
    missing = sorted(set(range(1, part)) - completed)
    if missing:
        raise RuntimeError(
            "A carga completa 25% deve ser executada em ordem. "
            f"Antes da Parte {part}, conclua: {', '.join(map(str, missing))}."
        )

    manifest_uuids = [str(item) for item in payload["contact_uuids"]]
    start = ((part - 1) * len(manifest_uuids)) // FULL_LOAD_25_PARTS
    end = (part * len(manifest_uuids)) // FULL_LOAD_25_PARTS
    selected_manifest = manifest_uuids[start:end]
    selected_set = frozenset(selected_manifest)
    current_map = {
        _full_load_25_uuid(contact): contact
        for contact in contacts
        if _full_load_25_uuid(contact)
    }
    current_set = set(current_map)
    manifest_set = set(manifest_uuids)
    selected_contacts = [
        current_map[uuid] for uuid in selected_manifest if uuid in current_map
    ]
    return {
        "part": part,
        "total_parts": FULL_LOAD_25_PARTS,
        "campaign_id": str(payload.get("campaign_id") or ""),
        "captured_at_utc": str(payload.get("captured_at_utc") or ""),
        "total_contacts": len(manifest_uuids),
        "selected_contacts": selected_contacts,
        "selected_uuids": selected_set,
        "selected_count": len(selected_contacts),
        "new_contacts_ignored": len(current_set - manifest_set),
        "missing_contacts": len(selected_set - current_set),
        "completed_parts": tuple(sorted(completed)),
    }


def mark_full_load_quarter_complete(
    *,
    component: str,
    part: int,
    campaign_id: str,
) -> tuple[bool, bool]:
    payload = _full_load_25_load()
    if str(payload.get("campaign_id") or "") != str(campaign_id or ""):
        raise RuntimeError("A campanha completa 25% mudou durante a execução.")
    completed = _full_load_25_completed(payload, component)
    if not set(range(1, part)).issubset(completed):
        raise RuntimeError("Não é possível concluir uma parte 25% fora de ordem.")
    completed.add(part)
    payload.setdefault("completed", {})[component] = sorted(completed)
    payload.setdefault("completed_at_utc", {})[f"{component}_{part}"] = (
        datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    )
    _full_load_25_write(payload)

    component_complete = completed == set(range(1, FULL_LOAD_25_PARTS + 1))
    campaign_complete = all(
        _full_load_25_completed(payload, name) == set(range(1, FULL_LOAD_25_PARTS + 1))
        for name in _FULL_LOAD_25_COMPONENTS
    )
    return component_complete, campaign_complete


def full_load_quarter_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


BASE_COLUMNS = [
    "contact_uuid",
    "telefone",
    "weni_name",
    "nome",
    "cpf",
    "cpf_normalizado",
    "email",
    "idade",
    "maior_de_18_anos",
    "opt_in_lgpd",
    "contact_urn",
    "contact_urn_whatsapp",
    "contact_urn_instagram",
    "contact_urn_facebook",
    "contact_canal_principal",
    "farmalider_cliente_id",
    "farmalider_cliente_nome",
    "farmalider_cliente_status",
    "farmalider_cliente_consultado_em",
    *AD_FIELDS,
    "ultimo_pedido",
    "pedido_id",
    "pedido_data",
    "pedido_status",
    "pedido_status_nome",
    "pedido_forma_pagamento",
    "pedido_forma_pagamento_nome",
    "pedido_produtos",
    "pedido_quantidade_itens",
    "pedido_valor_produtos",
    "pedido_valor",
    "voltou_por_outro_anuncio",
    "weni_created_on",
    "weni_modified_on",
    "sincronizado_em",
    "cidade",
    "estado",
    "cep",
    "bairro",
    "genero",
    "ultima_compra",
    "pedido_revisao_pendente",
]

HISTORY_COLUMNS = [
    "acao",
    "sincronizado_em",
    *[column for column in BASE_COLUMNS if column != "sincronizado_em"],
]

METRIC_COLUMNS = [
    "data",
    "tipo_atribuicao",
    "anuncio_id",
    "anuncio_titulo",
    "contatos",
]

EVENT_COLUMNS = [
    "event_id",
    "recebido_em",
    "contact_uuid",
    "contact_urn",
    "source_type",
    "anuncio_id",
    "anuncio_titulo",
    "anuncio_url",
    "clique_id",
]

META_CAMPAIGN_COLUMNS = [
    "anuncio_id",
    "anuncio_nome",
    "conjunto_id",
    "conjunto_nome",
    "campanha_id",
    "campanha_nome",
    "investimento",
    "impressoes",
    "cliques",
    "atualizado_em",
]

CONTROL_COLUMNS = ["chave", "valor", "atualizado_em"]

ORDER_COLUMNS = [
    "pedido_chave",
    "pedido_id",
    "origem_pedido",
    "status_confirmacao",
    "data_hora",
    "data",
    "hora",
    "contact_uuid",
    "telefone",
    "cliente",
    "cpf",
    "cpf_normalizado",
    "farmalider_cliente_id",
    "primeiro_anuncio_origem",
    "primeiro_anuncio_id",
    "primeiro_anuncio_titulo",
    "primeiro_anuncio_data",
    "primeiro_anuncio_tipo_campanha",
    "primeiro_anuncio_canal_destino",
    "ultimo_anuncio_origem",
    "ultimo_anuncio_id",
    "ultimo_anuncio_titulo",
    "ultimo_anuncio_data",
    "ultimo_anuncio_tipo_campanha",
    "ultimo_anuncio_canal_destino",
    "valor_total_compra",
    "valor_total_faturamento",
    "valor_total_itens",
    "diferenca_total",
    "quantidade_produtos",
    "quantidade_itens",
    "status_validacao",
    "erro_parse",
    "farmalider_public_id",
    "farmalider_emissao",
    "farmalider_status_pedido",
    "farmalider_status_pedido_nome",
    "farmalider_cod_filial",
    "farmalider_cod_cliente",
    "farmalider_forma_pagamento",
    "farmalider_forma_pagamento_nome",
    "farmalider_cupom",
    "farmalider_frete",
    "farmalider_pedido_web",
    "farmalider_cancelamento",
    "farmalider_entrega",
    "valor_total_api_itens",
    "quantidade_itens_api",
    "farmalider_confirmado_em",
    "farmalider_erro",
    "valor_origem",
    "total_api",
    "valor_total_weni",
    "diferenca_total_weni_api",
    "ultimo_pedido_raw",
    "weni_modified_on",
    "capturado_em",
]

ORDER_ITEM_COLUMNS = [
    "item_chave",
    "pedido_chave",
    "pedido_id",
    "data_hora",
    "data",
    "hora",
    "contact_uuid",
    "telefone",
    "cliente",
    "produto_ordem",
    "produto_nome",
    "produto_codigo",
    "quantidade",
    "valor_unitario",
    "valor_total",
    "capturado_em",
    "categoria",
]

SALES_METRIC_COLUMNS = [
    "data",
    "pedidos",
    "pedidos_confirmados_api",
    "clientes_compradores",
    "unidades_vendidas",
    "faturamento_produtos",
    "faturamento_frete",
    "faturamento",
    "faturamento_confirmado_api",
]


BI_SUMMARY_COLUMNS = [
    "data",
    "atualizado_em",
    "contatos_total",
    "novos_contatos",
    "contatos_com_cpf",
    "cpfs_validos",
    "contatos_sem_cpf",
    "clientes_farmalider",
    "clientes_nao_encontrados",
    "whatsapp",
    "instagram",
    "facebook",
    "outro",
    "opt_in_lgpd",
    "opt_out_lgpd",
    "lgpd_nao_informado",
    "maiores_18",
    "menores_18",
    "maioridade_nao_informada",
    "contatos_ads",
    "clientes_compradores_total",
    "pedidos_total",
    "faturamento_produtos_total",
    "faturamento_frete_total",
    "faturamento_total",
    "pedidos_dia",
    "pedidos_confirmados_api_dia",
    "clientes_compradores_dia",
    "unidades_vendidas_dia",
    "faturamento_produtos_dia",
    "faturamento_frete_dia",
    "faturamento_total_dia",
    "faturamento_dia",
    "faturamento_confirmado_api_dia",
    "ticket_medio_dia",
]

BI_CHANNEL_COLUMNS = [
    "chave",
    "data",
    "canal",
    "contatos",
    "contatos_com_cpf",
    "clientes_farmalider",
    "contatos_ads",
    "opt_in_lgpd",
    "atualizado_em",
]

BI_CONVERSION_COLUMNS = [
    "chave",
    "data",
    "etapa_ordem",
    "etapa",
    "quantidade",
    "taxa_base_pct",
    "taxa_etapa_anterior_pct",
    "atualizado_em",
]

BI_SALES_COLUMNS = [
    "data",
    "pedidos",
    "pedidos_confirmados_api",
    "clientes_compradores",
    "unidades_vendidas",
    "faturamento_produtos",
    "faturamento_frete",
    "faturamento_total",
    "faturamento",
    "faturamento_confirmado_api",
    "ticket_medio",
    "taxa_confirmacao_pct",
    "atualizado_em",
]

BI_ADS_COLUMNS = [
    "data_snapshot",
    "tipo_atribuicao",
    "origem",
    "tipo_campanha",
    "canal_destino",
    "anuncio_id",
    "anuncio_titulo",
    "contatos",
    "clientes_farmalider",
    "compradores",
    "pedidos",
    "faturamento",
    "atualizado_em",
]

BI_ORDERS_COLUMNS = [
    "pedido_chave",
    "pedido_id",
    "pedido_data",
    "data",
    "hora",
    "cliente",
    "cpf",
    "pedido_produtos",
    "pedido_quantidade_itens",
    "pedido_valor_produtos",
    "pedido_valor",
    "pedido_frete",
    "pedido_faturamento_total",
    "pedido_status",
    "pedido_status_nome",
    "pedido_forma_pagamento",
    "pedido_forma_pagamento_nome",
    "canal",
    "primeiro_anuncio_origem",
    "ultimo_anuncio_origem",
    "atualizado_em",
    "cidade",
    "estado",
    "cep",
    "bairro",
    "idade",
    "cliente_chave",
    "venda_valida",
    "genero",
]


BI_STATUS_COLUMNS = [
    "atualizado_em",
    "versao",
    "status",
    "modo_execucao",
    "duracao_segundos",
    "weni_recebidos",
    "contatos_processados",
    "cpfs_unicos_consultados",
    "farmalider_http_requests",
    "farmalider_retries",
    "farmalider_429",
    "farmalider_5xx",
    "google_leituras",
    "google_escritas",
    "contatos_inseridos",
    "contatos_atualizados",
    "contatos_sem_mudanca",
    "pedidos_confirmados_api",
]


def normalize_cpf(value: Any, pad_to_11: bool = False) -> str:
    digits = "".join(ch for ch in normalize_value(value) if ch.isdigit())
    if pad_to_11 and digits and len(digits) < 11:
        digits = digits.zfill(11)
    return digits


def is_valid_cpf(value: Any) -> bool:
    cpf = normalize_cpf(value)
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False

    def digit(base: str, factor: int) -> str:
        total = sum(
            int(n) * weight
            for n, weight in zip(base, range(factor, 1, -1), strict=False)
        )
        result = (total * 10) % 11
        return "0" if result == 10 else str(result)

    return cpf[9] == digit(cpf[:9], 10) and cpf[10] == digit(cpf[:10], 11)


def cpf_query_priority(value: Any) -> int:
    """Valid identifiers first, invalid populated identifiers next, absent last."""
    cpf = normalize_cpf(value)
    return 0 if is_valid_cpf(cpf) else (1 if cpf else 2)


def normalize_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        if "value" in value:
            return normalize_value(value["value"])
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if isinstance(value, list):
        return "; ".join(normalize_value(v) for v in value)
    return str(value)


def normalize_order_source(value: Any) -> str:
    """Normalize absent Weni order fields without treating invalid content as empty."""
    while isinstance(value, dict) and "value" in value:
        value = value["value"]
    raw = (
        json.dumps(value, ensure_ascii=False, sort_keys=True)
        if isinstance(value, (dict, list))
        else normalize_value(value)
    ).strip()
    return "" if raw.casefold() == "null" else raw


def get_fields(contact: dict[str, Any]) -> dict[str, Any]:
    fields = contact.get("fields")
    return fields if isinstance(fields, dict) else {}


def get_phone_and_urn(
    contact: dict[str, Any],
    fields: dict[str, Any],
) -> tuple[str, str]:
    urns = contact.get("urns") or []
    if not isinstance(urns, list):
        urns = []

    resolved = resolve_contact_urns(contact, fields)
    tel_urn = next(
        (u for u in urns if isinstance(u, str) and u.startswith("tel:")),
        "",
    )
    whatsapp_urn = resolved.channel_urns.get("whatsapp", "")
    if tel_urn:
        phone = tel_urn[4:]
    elif whatsapp_urn.startswith("whatsapp:"):
        phone = whatsapp_urn.split(":", 1)[1]
    else:
        phone = normalize_value(fields.get("telefone") or fields.get("celular")).strip()
    return phone, resolved.principal_urn


def is_ads_contact(contact: dict[str, Any]) -> bool:
    fields = get_fields(contact)
    keys = (
        "primeiro_anuncio_origem",
        "primeiro_anuncio_id",
        "primeiro_anuncio_clique_id",
        "ultimo_anuncio_origem",
        "ultimo_anuncio_id",
        "ultimo_anuncio_clique_id",
    )
    return any(normalize_value(fields.get(key)).strip() for key in keys)


def is_meta_ads_contact(contact: dict[str, Any]) -> bool:
    """Alias legado: a detecção agora é genérica para Meta Ads e Google Ads."""
    return is_ads_contact(contact)


def has_ultimo_pedido(contact: dict[str, Any]) -> bool:
    fields = get_fields(contact)
    return any(
        normalize_value(fields.get(key)).strip()
        for key in (
            "ultimo_pedido",
            "pedido_id",
            "pedido_produtos",
        )
    )


def is_relevant_contact(contact: dict[str, Any]) -> bool:
    return is_ads_contact(contact) or has_ultimo_pedido(contact)


def normalize_contact(
    contact: dict[str, Any],
    sync_time: str,
) -> dict[str, str]:
    fields = normalize_geography(get_fields(contact))
    phone, urn = get_phone_and_urn(contact, fields)
    resolved_urns = resolve_contact_urns(contact, fields)

    first_id = normalize_value(fields.get("primeiro_anuncio_id")).strip()
    last_id = normalize_value(fields.get("ultimo_anuncio_id")).strip()

    if first_id and last_id and first_id != last_id:
        returned_other_ad = "Sim"
    elif first_id and last_id:
        returned_other_ad = "Não"
    else:
        returned_other_ad = "Não informado"

    row = {
        "genero": normalize_value(fields.get("genero")).strip(),
        "ultima_compra": normalize_value(fields.get("ultima_compra")).strip(),
        "pedido_revisao_pendente": normalize_value(
            fields.get("pedido_revisao_pendente")
        ).strip(),
        "cidade": normalize_value(fields.get("cidade")).strip(),
        "estado": normalize_value(fields.get("estado")).strip(),
        "cep": normalize_value(fields.get("cep")).strip(),
        "bairro": normalize_value(fields.get("bairro")).strip(),
        "contact_uuid": normalize_value(contact.get("uuid")),
        "telefone": phone,
        "weni_name": normalize_value(contact.get("name")),
        "nome": normalize_value(fields.get("nome")),
        "cpf": normalize_value(fields.get("cpf")),
        "cpf_normalizado": normalize_cpf(fields.get("cpf")),
        "email": normalize_value(fields.get("email")),
        "idade": normalize_value(fields.get("idade")),
        "maior_de_18_anos": normalize_value(fields.get("maior_de_18_anos")),
        "opt_in_lgpd": normalize_value(fields.get("opt_in_lgpd")),
        "contact_urn": urn,
        "contact_urn_whatsapp": resolved_urns.channel_urns.get("whatsapp", "")
        or normalize_value(fields.get("contact_urn_whatsapp")),
        "contact_urn_instagram": normalize_value(fields.get("contact_urn_instagram"))
        or resolved_urns.channel_urns.get("instagram", ""),
        "contact_urn_facebook": normalize_value(fields.get("contact_urn_facebook"))
        or resolved_urns.channel_urns.get("facebook", ""),
        "contact_canal_principal": normalize_value(
            fields.get("contact_canal_principal")
        )
        or resolved_urns.principal_channel,
        "farmalider_cliente_id": "",
        "farmalider_cliente_nome": "",
        "farmalider_cliente_status": "",
        "farmalider_cliente_consultado_em": "",
        "ultimo_pedido": normalize_value(fields.get("ultimo_pedido")),
        "voltou_por_outro_anuncio": returned_other_ad,
        "weni_created_on": normalize_value(contact.get("created_on")),
        "weni_modified_on": normalize_value(contact.get("modified_on")),
        "sincronizado_em": sync_time,
    }

    for key in AD_FIELDS:
        row[key] = normalize_value(fields.get(key))

    for key in (
        "pedido_id",
        "pedido_data",
        "pedido_status",
        "pedido_forma_pagamento",
        "pedido_produtos",
        "pedido_quantidade_itens",
        "pedido_valor_produtos",
        "pedido_valor",
    ):
        row[key] = normalize_value(fields.get(key))
    payment_code = normalize_farmalider_payment_code(row["pedido_forma_pagamento"])
    if (
        payment_code == "0"
        or row["pedido_forma_pagamento"].strip().casefold() == "cancelado"
    ):
        row["pedido_forma_pagamento"] = "Cancelado"
    elif payment_code:
        row["pedido_forma_pagamento"] = payment_code
    row["pedido_status"] = effective_order_status_code(row) or row["pedido_status"]
    row["pedido_status_nome"] = farmalider_order_status_name(row["pedido_status"])
    row["pedido_forma_pagamento_nome"] = farmalider_payment_method_display(
        row["pedido_forma_pagamento"]
    )

    return row


def parse_date(value: str) -> str:
    if not value:
        return ""
    raw = value.strip()
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.date().isoformat()
    except ValueError:
        if len(raw) >= 10 and raw[4:5] == "-" and raw[7:8] == "-":
            return raw[:10]
        return ""


def parse_time(value: str) -> str:
    if not value:
        return ""
    raw = value.strip()
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.time().replace(tzinfo=None).isoformat(timespec="seconds")
    except ValueError:
        return ""


def build_daily_metrics(
    base_records: list[dict[str, str]],
) -> list[list[Any]]:
    counts: dict[tuple[str, str, str, str], int] = defaultdict(int)

    definitions = [
        (
            TIPO_PRIMEIRO_ANUNCIO,
            "primeiro_anuncio_data",
            "primeiro_anuncio_id",
            "primeiro_anuncio_titulo",
        ),
        (
            TIPO_ULTIMO_ANUNCIO,
            "ultimo_anuncio_data",
            "ultimo_anuncio_id",
            "ultimo_anuncio_titulo",
        ),
    ]

    for record in base_records:
        for label, date_key, id_key, title_key in definitions:
            date = parse_date(record.get(date_key, ""))
            ad_id = record.get(id_key, "").strip()
            title = record.get(title_key, "").strip()

            if not date or not (ad_id or title):
                continue

            counts[(date, label, ad_id, title)] += 1

    return [
        [date, label, ad_id, title, count]
        for (date, label, ad_id, title), count in sorted(counts.items())
    ]


def _to_decimal(value: Any, field_name: str) -> Decimal:
    if value is None or value == "":
        raise ValueError(f"{field_name} está vazio.")

    if isinstance(value, bool):
        raise ValueError(f"{field_name} deve ser numérico, não booleano.")
    raw = str(value).strip().replace("R$", "").replace(" ", "")

    if "," in raw and "." in raw:
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif "," in raw:
        raw = raw.replace(",", ".")

    try:
        number = Decimal(raw)
        if not number.is_finite():
            raise ValueError(f"{field_name} deve ser finito.")
        return number
    except InvalidOperation as exc:
        raise ValueError(
            f"{field_name} possui valor numérico inválido: {value!r}"
        ) from exc


def _money(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _quantity(value: Any) -> Decimal:
    qty = _to_decimal(value, "quantidade")
    if qty < 0:
        raise ValueError("quantidade não pode ser negativa.")
    return qty


def _quantity_text(value: Decimal) -> str:
    if value == value.to_integral_value():
        return str(int(value))
    return format(value.normalize(), "f")


def _canonical_order_key(
    contact_uuid: str,
    data_hora: str,
    raw: str,
    pedido_id: str = "",
) -> str:
    if pedido_id:
        return f"FARMALIDER:{pedido_id}"

    basis = f"{contact_uuid}|{data_hora}" if data_hora else f"{contact_uuid}|{raw}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:32]


def _item_key(pedido_chave: str, position: int) -> str:
    basis = f"{pedido_chave}|{position}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:32]


def _parse_order_items(
    produtos: list[Any],
    *,
    pedido_chave: str,
    pedido_id: str,
    data_hora: str,
    data: str,
    hora: str,
    contact_uuid: str,
    phone: str,
    client_name: str,
    captured_at: str,
) -> tuple[list[dict[str, str]], Decimal, Decimal]:
    """Valida os itens preservando quantidades, descontos e valores de origem."""
    item_rows: list[dict[str, str]] = []
    total_itens = Decimal("0")
    total_unidades = Decimal("0")

    for position, product in enumerate(produtos, start=1):
        if not isinstance(product, dict):
            raise ValueError(f"produto na posição {position} não é um objeto.")

        nome = normalize_value(product.get("nome")).strip()
        codigo = normalize_value(
            product.get("codigo") or product.get("codProduto")
        ).strip()
        if not nome and not codigo:
            raise ValueError(f"produto na posição {position} sem nome ou código.")

        quantidade = _quantity(product.get("quantidade"))
        valor_unitario = _to_decimal(
            product.get("valor_unitario"),
            f"produto {position}.valor_unitario",
        )
        valor_total = _to_decimal(
            product.get("valor_total"),
            f"produto {position}.valor_total",
        )
        if valor_unitario < 0 or valor_total < 0:
            raise ValueError(f"produto {position} possui valor negativo.")

        total_itens += valor_total
        total_unidades += quantidade

        item_rows.append(
            {
                "item_chave": _item_key(pedido_chave, position),
                "pedido_chave": pedido_chave,
                "pedido_id": pedido_id,
                "data_hora": data_hora,
                "data": data,
                "hora": hora,
                "contact_uuid": contact_uuid,
                "telefone": phone,
                "cliente": client_name,
                "produto_ordem": str(position),
                "produto_nome": nome,
                **(
                    {"categoria": normalize_value(product["categoria"]).strip()}
                    if product.get("categoria")
                    else {}
                ),
                "produto_codigo": codigo,
                "quantidade": _quantity_text(quantidade),
                "valor_unitario": _money(valor_unitario),
                "valor_total": _money(valor_total),
                "capturado_em": captured_at,
            }
        )

    return item_rows, total_itens, total_unidades


def _parse_order_totals(
    payload: dict[str, Any],
    *,
    total_compra: Decimal,
    total_itens: Decimal,
    total_unidades: Decimal,
) -> tuple[Decimal, Decimal, str]:
    """Confere frete, diferença e quantidade sem recalcular valores dos itens."""
    comparison_total = total_itens
    if normalize_value(payload.get("farmalider_frete")).strip():
        freight = _to_decimal(payload["farmalider_frete"], "farmalider_frete")
        if freight < 0:
            raise ValueError("farmalider_frete não pode ser negativo.")
        comparison_total += freight
    difference = total_compra - comparison_total
    status = "OK" if abs(difference) <= Decimal("0.01") else "ATENÇÃO_TOTAL_DIVERGENTE"
    if "quantidade_itens" in payload:
        reported_qty = _quantity(payload["quantidade_itens"])
        if reported_qty != total_unidades:
            raise ValueError(
                "quantidade_itens diverge da soma das quantidades dos produtos."
            )

    return comparison_total, difference, status


def parse_ultimo_pedido_raw(
    raw: str,
    *,
    contact_uuid: str,
    phone: str = "",
    client_name: str = "",
    cpf: str = "",
    modified_on: str = "",
    captured_at: str,
) -> tuple[dict[str, str] | None, list[dict[str, str]]]:
    """
    Parser reutilizável do JSON armazenado em `ultimo_pedido`.

    Hoje ele é usado pela sincronização periódica.
    No futuro, o webhook poderá chamar esta mesma função, garantindo
    que sincronização e webhook produzam exatamente a mesma estrutura.
    """
    raw = (raw or "").strip()
    if not raw:
        return None, []

    fallback_key = _canonical_order_key(contact_uuid, "", raw)

    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("ultimo_pedido deve conter um objeto JSON.")

        pedido_id = normalize_value(
            payload.get("pedido_id")
            or payload.get("pedidoId")
            or payload.get("codigo")
            or payload.get("codPedido")
        ).strip()

        data_hora = normalize_value(payload.get("data_hora")).strip()
        if not data_hora:
            raise ValueError("data_hora não informado.")

        order_dt = business_order_datetime(data_hora)
        if order_dt is None:
            raise ValueError(
                f"data_hora inválido ou fora do padrão ISO/Weni: {data_hora!r}"
            )
        data = order_dt.date().isoformat()
        hora = order_dt.time().replace(tzinfo=None).isoformat(timespec="seconds")

        total_compra = _to_decimal(
            payload.get("valor_total_compra"),
            "valor_total_compra",
        )
        if total_compra < 0:
            raise ValueError("valor_total_compra não pode ser negativo.")

        produtos = payload.get("produtos")
        if not isinstance(produtos, list):
            raise ValueError("produtos precisa ser uma lista.")

        pedido_chave = _canonical_order_key(contact_uuid, data_hora, raw, pedido_id)

        item_rows, total_itens, total_unidades = _parse_order_items(
            produtos,
            pedido_chave=pedido_chave,
            pedido_id=pedido_id,
            data_hora=data_hora,
            data=data,
            hora=hora,
            contact_uuid=contact_uuid,
            phone=phone,
            client_name=client_name,
            captured_at=captured_at,
        )
        comparison_total, difference, status = _parse_order_totals(
            payload,
            total_compra=total_compra,
            total_itens=total_itens,
            total_unidades=total_unidades,
        )

        order_row = {
            "pedido_chave": pedido_chave,
            "pedido_id": pedido_id,
            "origem_pedido": "WENI_ULTIMO_PEDIDO",
            "status_confirmacao": (
                "NAO_CONFIRMADO_API" if pedido_id else "NAO_CONFIRMADO_SEM_PEDIDO_ID"
            ),
            "data_hora": data_hora,
            "data": data,
            "hora": hora,
            "contact_uuid": contact_uuid,
            "telefone": phone,
            "cliente": client_name,
            "cpf": cpf,
            "cpf_normalizado": normalize_cpf(cpf),
            "farmalider_cliente_id": "",
            "primeiro_anuncio_origem": "",
            "primeiro_anuncio_id": "",
            "primeiro_anuncio_titulo": "",
            "primeiro_anuncio_data": "",
            "primeiro_anuncio_tipo_campanha": "",
            "primeiro_anuncio_canal_destino": "",
            "ultimo_anuncio_origem": "",
            "ultimo_anuncio_id": "",
            "ultimo_anuncio_titulo": "",
            "ultimo_anuncio_data": "",
            "ultimo_anuncio_tipo_campanha": "",
            "ultimo_anuncio_canal_destino": "",
            "valor_total_compra": _money(total_itens),
            "valor_total_faturamento": _money(comparison_total),
            "valor_total_itens": _money(total_itens),
            "diferenca_total": _money(difference),
            "quantidade_produtos": str(len(produtos)),
            "quantidade_itens": _quantity_text(total_unidades),
            "status_validacao": status,
            "erro_parse": "",
            "farmalider_public_id": "",
            "farmalider_emissao": "",
            "farmalider_status_pedido": "",
            "farmalider_status_pedido_nome": "",
            "farmalider_cod_filial": "",
            "farmalider_cod_cliente": "",
            "farmalider_forma_pagamento": "",
            "farmalider_cupom": "",
            "farmalider_frete": "",
            "farmalider_pedido_web": "",
            "farmalider_cancelamento": "",
            "farmalider_entrega": "",
            "valor_total_api_itens": "",
            "quantidade_itens_api": "",
            "farmalider_confirmado_em": "",
            "farmalider_erro": "",
            "valor_origem": "WENI",
            "total_api": "",
            "valor_total_weni": "",
            "diferenca_total_weni_api": "",
            "ultimo_pedido_raw": raw,
            "weni_modified_on": modified_on,
            "capturado_em": captured_at,
        }
        for key in (
            "origem_pedido",
            "status_confirmacao",
            "farmalider_cancelamento",
            "farmalider_status_pedido",
            "farmalider_frete",
            "valor_origem",
            "total_api",
            "valor_total_api_itens",
            "quantidade_itens_api",
            "farmalider_cod_cliente",
            "farmalider_cliente_id",
            "farmalider_emissao",
            "farmalider_confirmado_em",
            "valor_total_weni",
            "diferenca_total_weni_api",
            "farmalider_erro",
            "farmalider_status_pedido_nome",
            "farmalider_forma_pagamento",
            "farmalider_forma_pagamento_nome",
        ):
            if key in payload:
                order_row[key] = normalize_value(payload[key])
        official_status_name = farmalider_order_status_name(
            effective_order_status_code(order_row)
        )
        if official_status_name:
            order_row["farmalider_status_pedido_nome"] = official_status_name
        order_row["farmalider_forma_pagamento_nome"] = (
            farmalider_payment_method_display(order_row["farmalider_forma_pagamento"])
        )
        upstream_validation = normalize_value(payload.get("status_validacao")).strip()
        if upstream_validation and upstream_validation not in {"OK", "VALIDADO_WENI"}:
            order_row["status_validacao"] = upstream_validation
            if upstream_validation.startswith("ERRO"):
                order_row["erro_parse"] = (
                    "Snapshot de pedido marcado com erro de validação na origem."
                )
        return order_row, item_rows

    except (
        json.JSONDecodeError,
        ValueError,
        TypeError,
        InvalidOperation,
        OverflowError,
    ) as exc:
        error_row = {
            "pedido_chave": fallback_key,
            "pedido_id": "",
            "origem_pedido": "WENI_ULTIMO_PEDIDO",
            "status_confirmacao": "ERRO_DADOS_WENI",
            "data_hora": "",
            "data": "",
            "hora": "",
            "contact_uuid": contact_uuid,
            "telefone": phone,
            "cliente": client_name,
            "cpf": cpf,
            "cpf_normalizado": normalize_cpf(cpf),
            "farmalider_cliente_id": "",
            "primeiro_anuncio_origem": "",
            "primeiro_anuncio_id": "",
            "primeiro_anuncio_titulo": "",
            "primeiro_anuncio_data": "",
            "primeiro_anuncio_tipo_campanha": "",
            "primeiro_anuncio_canal_destino": "",
            "ultimo_anuncio_origem": "",
            "ultimo_anuncio_id": "",
            "ultimo_anuncio_titulo": "",
            "ultimo_anuncio_data": "",
            "ultimo_anuncio_tipo_campanha": "",
            "ultimo_anuncio_canal_destino": "",
            "valor_total_compra": "",
            "valor_total_faturamento": "",
            "valor_total_itens": "",
            "diferenca_total": "",
            "quantidade_produtos": "",
            "quantidade_itens": "",
            "status_validacao": "ERRO",
            "erro_parse": str(exc),
            "farmalider_public_id": "",
            "farmalider_emissao": "",
            "farmalider_status_pedido": "",
            "farmalider_status_pedido_nome": "",
            "farmalider_cod_filial": "",
            "farmalider_cod_cliente": "",
            "farmalider_forma_pagamento": "",
            "farmalider_cupom": "",
            "farmalider_frete": "",
            "farmalider_pedido_web": "",
            "farmalider_cancelamento": "",
            "farmalider_entrega": "",
            "valor_total_api_itens": "",
            "quantidade_itens_api": "",
            "farmalider_confirmado_em": "",
            "farmalider_erro": "",
            "valor_origem": "",
            "total_api": "",
            "valor_total_weni": "",
            "diferenca_total_weni_api": "",
            "ultimo_pedido_raw": raw,
            "weni_modified_on": modified_on,
            "capturado_em": captured_at,
        }
        return error_row, []


def _split_weni_order_list(value: Any) -> list[str]:
    raw = normalize_value(value).strip()
    if not raw:
        return []
    return parse_weni_order_list(raw)


def _derived_order_payload(fields: dict[str, Any]) -> dict[str, Any] | None:
    """Build a legacy-compatible order object from the flat Weni order fields."""
    names = (
        "pedido_id",
        "pedido_data",
        "pedido_produtos",
        "pedido_quantidade_itens",
        "pedido_valor_produtos",
        "pedido_valor",
    )
    if not any(normalize_value(fields.get(key)).strip() for key in names):
        return None

    pedido_id = normalize_value(fields.get("pedido_id")).strip()
    pedido_data = normalize_value(fields.get("pedido_data")).strip()
    pedido_valor = normalize_value(fields.get("pedido_valor")).strip()

    raw_products = fields.get("pedido_produtos")
    if isinstance(raw_products, dict) and "value" in raw_products:
        raw_products = raw_products["value"]

    # Backward compatibility for snapshots written before the flat Weni contract.
    if isinstance(raw_products, str) and raw_products.strip().startswith("{"):
        try:
            metadata = json.loads(raw_products)
        except json.JSONDecodeError:
            metadata = None
        if isinstance(metadata, dict) and isinstance(metadata.get("produtos"), list):
            payload = dict(metadata)
            envelope_id = normalize_value(metadata.get("pedido_id")).strip()
            payload["pedido_id"] = pedido_id or envelope_id
            payload["data_hora"] = (
                pedido_data or normalize_value(metadata.get("data_hora")).strip()
            )
            payload["valor_total_compra"] = (
                pedido_valor
                or normalize_value(metadata.get("valor_total_compra")).strip()
            )
            payload["quantidade_itens"] = normalize_value(
                fields.get("pedido_quantidade_itens")
            ).strip()
            if pedido_id and envelope_id and pedido_id != envelope_id:
                payload["produtos"] = None
            return payload

    try:
        product_names = _split_weni_order_list(raw_products)
        quantities = _split_weni_order_list(fields.get("pedido_quantidade_itens"))
        unit_values = _split_weni_order_list(fields.get("pedido_valor_produtos"))
    except ValueError:
        # Keep order-level data without inventing item relationships from bad CSV.
        product_names, quantities, unit_values = [], [], []

    product_rows: list[dict[str, Any]] | None = None
    if (
        product_names
        and all(product_names)
        and len(product_names) == len(quantities) == len(unit_values)
    ):
        rows: list[dict[str, Any]] = []
        try:
            for name, qty_raw, unit_raw in zip(
                product_names, quantities, unit_values, strict=False
            ):
                qty = _to_decimal(qty_raw, "quantidade")
                unit = _to_decimal(unit_raw, "valor_unitario")
                rows.append(
                    {
                        "nome": name,
                        "quantidade": _quantity_text(qty),
                        "valor_unitario": _money(unit),
                        "valor_total": _money(qty * unit),
                    }
                )
        except ValueError:
            rows = []
        if rows:
            product_rows = rows

    raw_status = normalize_value(fields.get("pedido_status")).strip()
    raw_payment = normalize_value(fields.get("pedido_forma_pagamento")).strip()
    payment_code = normalize_farmalider_payment_code(raw_payment)
    payment_value = (
        "Cancelado"
        if payment_code == "0" or raw_payment.casefold() == "cancelado"
        else payment_code or raw_payment
    )
    status_code = (
        effective_order_status_code(
            {
                "pedido_status": raw_status,
                "pedido_forma_pagamento": payment_value,
            }
        )
        or raw_status
    )
    return {
        "pedido_id": pedido_id,
        "data_hora": pedido_data,
        "valor_total_compra": pedido_valor,
        "produtos": product_rows,
        "farmalider_status_pedido": status_code,
        "farmalider_forma_pagamento": payment_value,
    }


def parse_ultimo_pedido(
    contact: dict[str, Any],
    captured_at: str,
) -> tuple[dict[str, str] | None, list[dict[str, str]]]:
    """Parse legacy ultimo_pedido and the current flat Weni order snapshot."""
    fields = get_fields(contact)
    raw = normalize_order_source(fields.get("ultimo_pedido"))

    contact_uuid = normalize_value(contact.get("uuid")).strip()
    phone, _ = get_phone_and_urn(contact, fields)
    client_name = (
        normalize_value(fields.get("nome")).strip()
        or normalize_value(contact.get("name")).strip()
    )
    context = dict(
        contact_uuid=contact_uuid,
        phone=phone,
        client_name=client_name,
        cpf=normalize_value(fields.get("cpf")).strip(),
        modified_on=normalize_value(contact.get("modified_on")).strip(),
        captured_at=captured_at,
    )

    original_order, original_items = parse_ultimo_pedido_raw(raw, **context)
    original_valid = original_order is not None and not str(
        original_order.get("status_validacao") or ""
    ).startswith("ERRO")
    if raw and not original_valid:
        return original_order, original_items

    derived_payload = _derived_order_payload(fields)
    if derived_payload is None:
        return original_order, original_items

    derived_order, derived_items = parse_ultimo_pedido_raw(
        json.dumps(derived_payload, ensure_ascii=False),
        **context,
    )
    if derived_order is None:
        return original_order, original_items
    derived_order["ultimo_pedido_raw"] = raw
    if derived_order["origem_pedido"] == "WENI_ULTIMO_PEDIDO":
        derived_order["origem_pedido"] = "WENI_PEDIDO_FIELDS"

    derived_valid = not str(derived_order.get("status_validacao") or "").startswith(
        "ERRO"
    )
    if not original_valid:
        return (
            (derived_order, derived_items)
            if derived_valid or original_order is None
            else (original_order, original_items)
        )

    # original_valid só pode ser verdadeiro para uma linha já produzida.
    original_order = cast(dict[str, str], original_order)
    if derived_valid:
        confirmation = derived_order.get("status_confirmacao", "")
        verified = (
            confirmation.startswith("CONFIRMADO_API") or confirmation == "CANCELADO_API"
        )
        derived_dt = business_order_datetime(derived_order.get("data_hora", ""))
        original_dt = business_order_datetime(original_order.get("data_hora", ""))
        original_id = str(original_order.get("pedido_id") or "").strip()
        derived_id = str(derived_order.get("pedido_id") or "").strip()
        same_id = (
            original_id.isascii()
            and original_id.isdigit()
            and int(original_id) > 0
            and derived_id.isascii()
            and derived_id.isdigit()
            and int(derived_id) == int(original_id)
        )
        if (
            same_id
            and verified
            and derived_dt is not None
            and original_dt is not None
            and derived_dt >= original_dt
        ):
            return derived_order, derived_items
    return original_order, original_items


def _order_revenue_parts(record: dict[str, str]) -> tuple[Decimal, Decimal, Decimal]:
    """Return products, freight and billed total for a validated order."""
    try:
        products = _to_decimal(record.get("valor_total_compra"), "valor_total_compra")
    except ValueError:
        products = Decimal("0")
    try:
        freight = _to_decimal(record.get("farmalider_frete"), "farmalider_frete")
    except ValueError:
        freight = Decimal("0")

    explicit_total = str(record.get("valor_total_faturamento") or "").strip()
    if explicit_total:
        try:
            total = _to_decimal(explicit_total, "valor_total_faturamento")
        except ValueError:
            total = products + freight
    else:
        total = products + freight
    return products, freight, total


def build_sales_metrics(
    order_records: list[dict[str, str]],
    item_records: list[dict[str, str]],
) -> list[list[Any]]:
    orders_by_date: dict[str, set[str]] = defaultdict(set)
    confirmed_by_date: dict[str, set[str]] = defaultdict(set)
    clients_by_date: dict[str, set[str]] = defaultdict(set)
    product_revenue_by_date: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    freight_revenue_by_date: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    revenue_by_date: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    confirmed_revenue_by_date: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    units_by_date: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))

    for record in order_records:
        if not _sales_order_is_valid(record):
            continue

        date = record.get("data", "").strip()
        order_key = record.get("pedido_chave", "").strip()
        contact_uuid = bi_customer_key(record)
        if not date or not order_key:
            continue

        orders_by_date[date].add(order_key)
        if contact_uuid:
            clients_by_date[date].add(contact_uuid)

        products, freight, total = _order_revenue_parts(record)
        product_revenue_by_date[date] += products
        freight_revenue_by_date[date] += freight
        revenue_by_date[date] += total

        confirmation = record.get("status_confirmacao", "")
        if confirmation.startswith("CONFIRMADO_API"):
            confirmed_by_date[date].add(order_key)
            confirmed_revenue_by_date[date] += total

    valid_order_keys = {
        record.get("pedido_chave", "").strip()
        for record in order_records
        if _sales_order_is_valid(record)
    }

    for record in item_records:
        if record.get("pedido_chave", "").strip() not in valid_order_keys:
            continue
        date = record.get("data", "").strip()
        if not date:
            continue
        try:
            units_by_date[date] += _quantity(record.get("quantidade", "0"))
        except ValueError:
            pass

    dates = sorted(
        set(orders_by_date)
        | set(confirmed_by_date)
        | set(clients_by_date)
        | set(product_revenue_by_date)
        | set(freight_revenue_by_date)
        | set(revenue_by_date)
        | set(units_by_date)
    )

    return [
        [
            date,
            len(orders_by_date[date]),
            len(confirmed_by_date[date]),
            len(clients_by_date[date]),
            _quantity_text(units_by_date[date]),
            _money(product_revenue_by_date[date]),
            _money(freight_revenue_by_date[date]),
            _money(revenue_by_date[date]),
            _money(confirmed_revenue_by_date[date]),
        ]
        for date in dates
    ]


def _bi_decimal(value: Any) -> Decimal:
    try:
        return _to_decimal(value, "bi")
    except ValueError:
        return Decimal("0")


def _bi_float(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _order_customer_identity_verified(record: dict[str, str]) -> bool:
    cpf = normalize_cpf(record.get("cpf_normalizado") or record.get("cpf"))
    return (
        not cpf
        or is_valid_cpf(cpf)
        or str(record.get("origem_pedido") or "").endswith("_IDENTIDADE_VALIDADA")
    )


def _sales_order_is_valid(record: dict[str, str]) -> bool:
    """API-confirmed ready-for-route, in-transit and completed orders enter sales KPIs."""
    confirmation = str(record.get("status_confirmacao") or "")
    if not confirmation.startswith(
        "CONFIRMADO_API"
    ) or not _order_customer_identity_verified(record):
        return False
    return (
        record.get("status_validacao") in ("OK", "ATENÇÃO_TOTAL_DIVERGENTE")
        and is_order_sale(record)
        and bool(str(record.get("pedido_chave") or "").strip())
    )


def _bi_valid_orders(order_records: list[dict[str, str]]) -> list[dict[str, str]]:
    return [record for record in order_records if _sales_order_is_valid(record)]


def build_bi_sales_rows(
    order_records: list[dict[str, str]],
    item_records: list[dict[str, str]],
    *,
    snapshot_date: str,
    updated_at: str,
) -> list[list[Any]]:
    base = build_sales_metrics(order_records, item_records)
    rows: list[list[Any]] = []
    dates_seen: set[str] = set()
    for row in base:
        (
            date,
            pedidos,
            confirmados,
            compradores,
            unidades,
            faturamento_produtos,
            faturamento_frete,
            faturamento_total,
            fat_confirmado,
        ) = row
        pedidos_i = int(pedidos or 0)
        confirmados_i = int(confirmados or 0)
        faturamento_d = _bi_decimal(faturamento_total)
        ticket = (faturamento_d / pedidos_i) if pedidos_i else Decimal("0")
        taxa = (Decimal(confirmados_i) * 100 / pedidos_i) if pedidos_i else Decimal("0")
        rows.append(
            [
                date,
                pedidos_i,
                confirmados_i,
                int(compradores or 0),
                float(_bi_decimal(unidades)),
                _bi_float(_bi_decimal(faturamento_produtos)),
                _bi_float(_bi_decimal(faturamento_frete)),
                _bi_float(faturamento_d),
                _bi_float(faturamento_d),
                _bi_float(_bi_decimal(fat_confirmado)),
                _bi_float(ticket),
                _bi_float(taxa),
                updated_at,
            ]
        )
        dates_seen.add(str(date))

    if snapshot_date not in dates_seen:
        rows.append(
            [
                snapshot_date,
                0,
                0,
                0,
                0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                updated_at,
            ]
        )
    rows.sort(key=lambda row: str(row[0]))
    return rows


def _bi_channel(record: dict[str, str]) -> str:
    value = (record.get("contact_canal_principal") or "").strip().casefold()
    if value in {"whatsapp", "instagram", "facebook"}:
        return value
    return "outro"


def _bi_is_ad_contact(record: dict[str, str]) -> bool:
    return any(
        (record.get(key) or "").strip()
        for key in (
            "primeiro_anuncio_id",
            "primeiro_anuncio_clique_id",
            "primeiro_anuncio_origem",
            "ultimo_anuncio_id",
            "ultimo_anuncio_clique_id",
            "ultimo_anuncio_origem",
        )
    )


def build_bi_summary_record(
    base_records: list[dict[str, str]],
    order_records: list[dict[str, str]],
    item_records: list[dict[str, str]],
    *,
    snapshot_date: str,
    updated_at: str,
) -> dict[str, Any]:
    valid_orders = _bi_valid_orders(order_records)
    all_buyers = {
        r.get("contact_uuid", "").strip()
        for r in valid_orders
        if r.get("contact_uuid", "").strip()
    }
    all_order_keys = {r.get("pedido_chave", "").strip() for r in valid_orders}
    all_products = sum((_order_revenue_parts(r)[0] for r in valid_orders), Decimal("0"))
    all_freight = sum((_order_revenue_parts(r)[1] for r in valid_orders), Decimal("0"))
    all_revenue = sum((_order_revenue_parts(r)[2] for r in valid_orders), Decimal("0"))

    sales_rows = build_bi_sales_rows(
        order_records, item_records, snapshot_date=snapshot_date, updated_at=updated_at
    )
    today = next(row for row in sales_rows if str(row[0]) == snapshot_date)

    counts = {"whatsapp": 0, "instagram": 0, "facebook": 0, "outro": 0}
    novos = com_cpf = cpfs_validos = clientes = nao_encontrados = 0
    opt_in = opt_out = maiores = menores = ads = 0
    for record in base_records:
        counts[_bi_channel(record)] += 1
        cpf = normalize_cpf(record.get("cpf_normalizado") or record.get("cpf"))
        if cpf:
            com_cpf += 1
        if is_valid_cpf(cpf):
            cpfs_validos += 1
        status = (record.get("farmalider_cliente_status") or "").strip()
        if status in {"CPF_CONFIRMADO", "CPF_INVALIDO_ENCONTRADO"}:
            clientes += 1
        elif status == "CPF_NAO_ENCONTRADO":
            nao_encontrados += 1
        created = business_order_datetime(record.get("weni_created_on", ""))
        if created is not None and created.date().isoformat() == snapshot_date:
            novos += 1
        lgpd = (record.get("opt_in_lgpd") or "").strip().casefold()
        if lgpd == "ativo":
            opt_in += 1
        elif lgpd == "recusado":
            opt_out += 1
        majority = (record.get("maior_de_18_anos") or "").strip().casefold()
        if majority in {"sim", "yes", "true", "1"}:
            maiores += 1
        elif majority in {"não", "nao", "no", "false", "0"}:
            menores += 1
        if _bi_is_ad_contact(record):
            ads += 1

    total = len(base_records)
    return {
        "data": snapshot_date,
        "atualizado_em": updated_at,
        "contatos_total": total,
        "novos_contatos": novos,
        "contatos_com_cpf": com_cpf,
        "cpfs_validos": cpfs_validos,
        "contatos_sem_cpf": max(0, total - com_cpf),
        "clientes_farmalider": clientes,
        "clientes_nao_encontrados": nao_encontrados,
        "whatsapp": counts["whatsapp"],
        "instagram": counts["instagram"],
        "facebook": counts["facebook"],
        "outro": counts["outro"],
        "opt_in_lgpd": opt_in,
        "opt_out_lgpd": opt_out,
        "lgpd_nao_informado": max(0, total - opt_in - opt_out),
        "maiores_18": maiores,
        "menores_18": menores,
        "maioridade_nao_informada": max(0, total - maiores - menores),
        "contatos_ads": ads,
        "clientes_compradores_total": len(all_buyers),
        "pedidos_total": len(all_order_keys),
        "faturamento_produtos_total": _bi_float(all_products),
        "faturamento_frete_total": _bi_float(all_freight),
        "faturamento_total": _bi_float(all_revenue),
        "pedidos_dia": int(today[1]),
        "pedidos_confirmados_api_dia": int(today[2]),
        "clientes_compradores_dia": int(today[3]),
        "unidades_vendidas_dia": float(today[4]),
        "faturamento_produtos_dia": float(today[5]),
        "faturamento_frete_dia": float(today[6]),
        "faturamento_total_dia": float(today[7]),
        "faturamento_dia": float(today[8]),
        "faturamento_confirmado_api_dia": float(today[9]),
        "ticket_medio_dia": float(today[10]),
    }


def build_bi_channel_records(
    base_records: list[dict[str, str]],
    *,
    snapshot_date: str,
    updated_at: str,
) -> list[dict[str, Any]]:
    channels = ["whatsapp", "instagram", "facebook", "outro"]
    result: list[dict[str, Any]] = []
    for channel in channels:
        rows = [r for r in base_records if _bi_channel(r) == channel]
        result.append(
            {
                "chave": f"{snapshot_date}|{channel}",
                "data": snapshot_date,
                "canal": channel,
                "contatos": len(rows),
                "contatos_com_cpf": sum(
                    1
                    for r in rows
                    if normalize_cpf(r.get("cpf_normalizado") or r.get("cpf"))
                ),
                "clientes_farmalider": sum(
                    1
                    for r in rows
                    if (r.get("farmalider_cliente_status") or "").strip()
                    in {"CPF_CONFIRMADO", "CPF_INVALIDO_ENCONTRADO"}
                ),
                "contatos_ads": sum(1 for r in rows if _bi_is_ad_contact(r)),
                "opt_in_lgpd": sum(
                    1
                    for r in rows
                    if (r.get("opt_in_lgpd") or "").strip().casefold() == "ativo"
                ),
                "atualizado_em": updated_at,
            }
        )
    return result


def build_bi_conversion_records(
    base_records: list[dict[str, str]],
    order_records: list[dict[str, str]],
    *,
    snapshot_date: str,
    updated_at: str,
) -> list[dict[str, Any]]:
    valid_orders = _bi_valid_orders(order_records)
    buyer_uuids = {r.get("contact_uuid", "").strip() for r in valid_orders}
    buyer_keys = {bi_customer_key(r) for r in valid_orders}
    buyers = {
        r.get("contact_uuid", "").strip()
        for r in base_records
        if r.get("contact_uuid", "").strip()
        and (
            r.get("contact_uuid", "").strip() in buyer_uuids
            or bi_customer_key({}, r) in buyer_keys
        )
    }
    stages = [
        (1, "Contatos", len(base_records)),
        (
            2,
            "CPF válido",
            sum(
                1
                for r in base_records
                if is_valid_cpf(normalize_cpf(r.get("cpf_normalizado") or r.get("cpf")))
            ),
        ),
        (
            3,
            "Cliente FarmaLíder",
            sum(
                1
                for r in base_records
                if (r.get("farmalider_cliente_status") or "").strip()
                in {"CPF_CONFIRMADO", "CPF_INVALIDO_ENCONTRADO"}
            ),
        ),
        (4, "Cliente comprador", len(buyers)),
    ]
    base = stages[0][2] or 0
    previous = 0
    result: list[dict[str, Any]] = []
    for order, label, qty in stages:
        base_rate = (qty * 100 / base) if base else 0.0
        prev_rate = (
            100.0 if order == 1 else ((qty * 100 / previous) if previous else 0.0)
        )
        result.append(
            {
                "chave": f"{snapshot_date}|{order}",
                "data": snapshot_date,
                "etapa_ordem": order,
                "etapa": label,
                "quantidade": qty,
                "taxa_base_pct": round(base_rate, 2),
                "taxa_etapa_anterior_pct": round(prev_rate, 2),
                "atualizado_em": updated_at,
            }
        )
        previous = qty
    return result


def _bi_display_number(value: Any) -> str:
    try:
        number = _to_decimal(value, "display")
    except ValueError:
        return ""
    return format(number.normalize(), "f")


def _bi_customer_age(value: Any) -> int | str:
    text = normalize_value(value).strip()
    if not text:
        return ""
    try:
        age = Decimal(text.replace(",", "."))
        if age.is_finite() and age >= 0 and age == age.to_integral_value():
            return int(age)
    except InvalidOperation:
        pass
    return ""


def bi_customer_key(order: dict[str, Any], base: dict[str, Any] | None = None) -> str:
    """Identidade estável da pessoa; nunca nome, data ou CPF em claro."""
    base = base or {}
    customer = str(order.get("farmalider_cliente_id") or "").strip()
    if not customer and str(order.get("status_confirmacao") or "").startswith(
        "CONFIRMADO_API"
    ):
        customer = str(order.get("farmalider_cod_cliente") or "").strip()
    if not customer and str(base.get("farmalider_cliente_status") or "") in {
        "CPF_CONFIRMADO",
        "CPF_INVALIDO_ENCONTRADO",
    }:
        customer = str(base.get("farmalider_cliente_id") or "").strip()
    if customer:
        identity = "farmalider:" + customer
    else:
        uuid = str(order.get("contact_uuid") or base.get("contact_uuid") or "").strip()
        if not uuid:
            return ""
        identity = "weni:" + uuid
    return hashlib.sha256(identity.encode()).hexdigest()[:32]


def build_bi_order_rows(
    base_records: list[dict[str, str]],
    order_records: list[dict[str, str]],
    item_records: list[dict[str, str]],
    *,
    updated_at: str,
) -> list[list[Any]]:
    """Order-level table ready for Looker Studio detail/buyers pages."""
    base_by_uuid = {
        (record.get("contact_uuid") or "").strip(): normalize_geography(record)
        for record in base_records
        if (record.get("contact_uuid") or "").strip()
    }
    items_by_order: dict[str, list[dict[str, str]]] = defaultdict(list)
    for item in item_records:
        key = (item.get("pedido_chave") or "").strip()
        if key:
            items_by_order[key].append(item)

    rows: list[list[Any]] = []
    for order in sorted(
        order_records,
        key=lambda row: (
            str(row.get("data_hora") or ""),
            str(row.get("pedido_id") or ""),
        ),
        reverse=True,
    ):
        if not _order_customer_identity_verified(order):
            continue
        key = (order.get("pedido_chave") or "").strip()
        pedido_id = (order.get("pedido_id") or "").strip()
        if not key or not pedido_id:
            continue
        items = sorted(
            items_by_order.get(key, []),
            key=lambda item: int(item.get("produto_ordem") or 0),
        )
        dt = business_order_datetime(order.get("data_hora"))
        contact_uuid = (order.get("contact_uuid") or "").strip()
        base = base_by_uuid.get(contact_uuid, {})
        status_code = effective_order_status_code(order)
        payment_code = (order.get("farmalider_forma_pagamento") or "").strip()

        rows.append(
            [
                key,
                pedido_id,
                weni_order_datetime_text(dt) if dt is not None else "",
                dt.date().isoformat() if dt is not None else "",
                dt.strftime("%H:%M:%S") if dt is not None else "",
                (
                    order.get("cliente")
                    or base.get("nome")
                    or base.get("weni_name")
                    or ""
                ).strip(),
                (
                    order.get("cpf_normalizado")
                    or order.get("cpf")
                    or base.get("cpf_normalizado")
                    or base.get("cpf")
                    or ""
                ).strip(),
                ", ".join(
                    (item.get("produto_nome") or "").strip()
                    for item in items
                    if (item.get("produto_nome") or "").strip()
                ),
                ", ".join(_bi_display_number(item.get("quantidade")) for item in items),
                ", ".join(
                    _bi_display_number(item.get("valor_unitario")) for item in items
                ),
                _bi_float(_bi_decimal(order.get("valor_total_compra"))),
                _bi_float(_order_revenue_parts(order)[1]),
                _bi_float(_order_revenue_parts(order)[2]),
                status_code,
                farmalider_order_status_name(status_code),
                payment_code,
                farmalider_payment_method_display(payment_code),
                (base.get("contact_canal_principal") or "outro").strip().casefold(),
                (order.get("primeiro_anuncio_origem") or "").strip(),
                (order.get("ultimo_anuncio_origem") or "").strip(),
                updated_at,
                (base.get("cidade") or "").strip(),
                (base.get("estado") or "").strip(),
                (base.get("cep") or "").strip(),
                (base.get("bairro") or "").strip(),
                _bi_customer_age(base.get("idade")),
                bi_customer_key(order, base),
                int(_sales_order_is_valid(order)),
                (base.get("genero") or "").strip(),
            ]
        )
    return rows


def build_bi_ads_rows(
    base_records: list[dict[str, str]],
    order_records: list[dict[str, str]],
    *,
    snapshot_date: str,
    updated_at: str,
) -> list[list[Any]]:
    dimensions = [
        ("Primeiro anúncio", "primeiro_anuncio_"),
        ("Último anúncio", "ultimo_anuncio_"),
    ]
    contact_groups: dict[tuple[str, ...], dict[str, Any]] = {}

    for label, prefix in dimensions:
        for record in base_records:
            ad_id = (record.get(prefix + "id") or "").strip()
            title = (record.get(prefix + "titulo") or "").strip()
            origin = (record.get(prefix + "origem") or "").strip()
            campaign = (record.get(prefix + "tipo_campanha") or "").strip()
            destination = (record.get(prefix + "canal_destino") or "").strip()
            if not any((ad_id, title, origin)):
                continue
            key = (label, origin, campaign, destination, ad_id, title)
            bucket = contact_groups.setdefault(
                key,
                {
                    "contatos": 0,
                    "clientes": 0,
                    "buyers": set(),
                    "orders": set(),
                    "revenue": Decimal("0"),
                },
            )
            bucket["contatos"] += 1
            if (record.get("farmalider_cliente_status") or "").strip() in {
                "CPF_CONFIRMADO",
                "CPF_INVALIDO_ENCONTRADO",
            }:
                bucket["clientes"] += 1

    for label, prefix in dimensions:
        for record in _bi_valid_orders(order_records):
            ad_id = (record.get(prefix + "id") or "").strip()
            title = (record.get(prefix + "titulo") or "").strip()
            origin = (record.get(prefix + "origem") or "").strip()
            campaign = (record.get(prefix + "tipo_campanha") or "").strip()
            destination = (record.get(prefix + "canal_destino") or "").strip()
            if not any((ad_id, title, origin)):
                continue
            key = (label, origin, campaign, destination, ad_id, title)
            bucket = contact_groups.setdefault(
                key,
                {
                    "contatos": 0,
                    "clientes": 0,
                    "buyers": set(),
                    "orders": set(),
                    "revenue": Decimal("0"),
                },
            )
            uuid = (record.get("contact_uuid") or "").strip()
            order_key = (record.get("pedido_chave") or "").strip()
            if uuid:
                bucket["buyers"].add(uuid)
            if order_key:
                bucket["orders"].add(order_key)
            bucket["revenue"] += _order_revenue_parts(record)[2]

    rows: list[list[Any]] = []
    for key in sorted(contact_groups):
        label, origin, campaign, destination, ad_id, title = key
        bucket = contact_groups[key]
        rows.append(
            [
                snapshot_date,
                label,
                origin,
                campaign,
                destination,
                ad_id,
                title,
                int(bucket["contatos"]),
                int(bucket["clientes"]),
                len(bucket["buyers"]),
                len(bucket["orders"]),
                _bi_float(bucket["revenue"]),
                updated_at,
            ]
        )

    if not rows:
        rows.append(
            [
                snapshot_date,
                "Sem dados",
                "",
                "",
                "",
                "",
                "Sem conversas atribuídas a anúncios",
                "",
                "",
                "",
                "",
                "",
                updated_at,
            ]
        )
    return rows


# NexoFlow 1.0
