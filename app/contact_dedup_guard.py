"""Pure checks for destructive contact deduplication; no network or file writes."""

import re
import unicodedata
from collections import Counter
from uuid import UUID

from analytics import get_fields, is_valid_cpf, normalize_cpf, normalize_value
from farmalider_integration import (
    _identity_phone,
    _positive_id,
    _ultimo_pedido_locator_id,
)
from urn_utils import native_contact_urns


def _normalized(value):
    text = unicodedata.normalize("NFKD", normalize_value(value)).casefold()
    return " ".join("".join(c for c in text if not unicodedata.combining(c)).split())


def contact_uuid(contact):
    """Require a non-nil UUID with canonical hyphens, never an omitted selector."""
    if not isinstance(contact, dict):
        return ""
    value = contact.get("uuid")
    if not isinstance(value, str) or not re.fullmatch(
        r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", value
    ):
        return ""
    parsed = UUID(value)
    return str(parsed) if parsed.int else ""


def contact_refusals(contact, *, opt_out_lgpd_uuid="", opt_out_marketing_uuid=""):
    """Capture only refusals and blocking; never infer or transfer an Opt-In.

    Optional resolved group UUIDs recognize Opt-Out memberships whose API objects
    omit names. Returned evidence does not change the input contact.
    """
    contact = contact if isinstance(contact, dict) else {}
    fields = get_fields(contact)
    negative_values = {
        "recusado",
        "nao",
        "negado",
        "inativo",
        "recusa",
        "opt-out",
        "opt out",
        "opt_out",
        "optout",
        "false",
        "0",
        "cancelado",
        "nao autorizado",
        "nao quero receber",
        "bloqueado",
    }
    lgpd_sources = [
        "campo:" + key
        for key in ("opt_in_lgpd", "opt_in_lgpd_status")
        if _normalized(fields.get(key)) in negative_values
    ]
    marketing_sources = [
        "campo:" + key
        for key in ("marketing_opt_in", "opt_in_marketing")
        if _normalized(fields.get(key)) in negative_values
    ]
    for group in contact.get("groups") or []:
        if isinstance(group, dict):
            name, identifier = group.get("name"), group.get("uuid")
        elif isinstance(group, str):
            name, identifier = group, group
        else:
            continue
        key = re.sub(r"[^a-z0-9]", "", _normalized(name))
        if key == "optoutlgpd" or (
            opt_out_lgpd_uuid and identifier == opt_out_lgpd_uuid
        ):
            lgpd_sources.append("grupo:Opt-Out LGPD")
        if key == "optoutmarketing" or (
            opt_out_marketing_uuid and identifier == opt_out_marketing_uuid
        ):
            marketing_sources.append("grupo:Opt-Out Marketing")
    true_values = {"true", "1", "sim"}
    blocked = _normalized(contact.get("blocked")) in true_values
    stopped = _normalized(contact.get("stopped")) in true_values
    reasons = []
    if lgpd_sources:
        reasons.append("RECUSA_LGPD")
    if marketing_sources:
        reasons.append("RECUSA_MARKETING")
    if blocked:
        reasons.append("BLOQUEADO")
    if stopped:
        reasons.append("PARADO")
    return {
        "lgpd_refused": bool(lgpd_sources),
        "marketing_refused": bool(marketing_sources),
        "blocked": blocked,
        "stopped": stopped,
        "lgpd_sources": sorted(set(lgpd_sources)),
        "marketing_sources": sorted(set(marketing_sources)),
        "reasons": reasons,
    }


def native_phones(contact):
    return {
        _identity_phone(u)
        for u in native_contact_urns(contact)
        if u.startswith(("tel:", "whatsapp:")) and len(_identity_phone(u)) in (10, 11)
    } - {""}


def customer_phones(customer):
    return {
        _identity_phone(customer.get(k))
        for k in ("telefone", "celular", "telefone1", "telefone2", "fone")
        if len(_identity_phone(customer.get(k))) in (10, 11)
    } - {""}


def refs(contact):
    f = get_fields(contact)
    return {_positive_id(f.get("pedido_id")), _ultimo_pedido_locator_id(f)} - {""}


def validate_pair(
    canonical,
    duplicate,
    *,
    customer,
    related_contacts,
    orders,
    history_owner_ids=(),
    recorded_order_ids=(),
    opt_out_lgpd_uuid="",
    opt_out_marketing_uuid="",
    order_partition=None,
    canonical_recorded_ids=(),
):
    reasons = []
    if not isinstance(canonical, dict) or not canonical:
        return ["CONTATO_NAO_ATIVO"]
    if not isinstance(duplicate, dict) or not duplicate:
        return ["CONTATO_NAO_ATIVO"]
    canonical_uuid, duplicate_uuid = contact_uuid(canonical), contact_uuid(duplicate)
    if not canonical_uuid:
        reasons.append("UUID_CANONICO_INVALIDO")
    if not duplicate_uuid:
        reasons.append("UUID_DUPLICADO_INVALIDO")
    if canonical_uuid and canonical_uuid == duplicate_uuid:
        reasons.append("MESMO_UUID")
    related_contacts = list(related_contacts)
    related_uuids = [contact_uuid(c) for c in related_contacts]
    if "" in related_uuids:
        reasons.append("UUID_RELACIONADO_INVALIDO")
    counts = Counter(related_uuids)
    if canonical_uuid and counts[canonical_uuid] != 1:
        reasons.append("CANONICO_AUSENTE_OU_REPETIDO_NOS_RELACIONADOS")
    if duplicate_uuid and counts[duplicate_uuid] != 1:
        reasons.append("DUPLICADO_AUSENTE_OU_REPETIDO_NOS_RELACIONADOS")
    cf = normalize_cpf(get_fields(canonical).get("cpf"))
    df = normalize_cpf(get_fields(duplicate).get("cpf"))
    af = normalize_cpf(customer.get("cpf"))
    if not (is_valid_cpf(cf) and cf == df == af):
        reasons.append("CPF_SEM_VINCULO_VALIDO_UNICO")
    cid = _positive_id(customer.get("id"))
    if not cid:
        reasons.append("CLIENTE_API_INVALIDO")
    ps = customer_phones(customer)
    matches = {
        contact_uuid(c)
        for c in related_contacts
        if isinstance(c, dict) and ps & native_phones(c)
    }
    if order_partition is None:
        if not canonical_uuid or matches != {canonical_uuid}:
            reasons.append("TELEFONE_SEM_CONTATO_CANONICO_UNICO")
        if ps & native_phones(duplicate):
            reasons.append("DUPLICADO_TAMBEM_POSSUI_TELEFONE_API")
    else:
        canonical_orders = refs(canonical) | set(canonical_recorded_ids)
        duplicate_orders = refs(duplicate) | set(recorded_order_ids)
        if (
            canonical_orders != set(order_partition["canonical_orders"])
            or duplicate_orders != set(order_partition["duplicate_orders"])
            or refs(canonical) != set(order_partition["canonical_refs"])
            or refs(duplicate) != set(order_partition["duplicate_refs"])
        ):
            reasons.append("PEDIDOS_MUDARAM_APOS_REVISAO")
        if duplicate_orders and duplicate_orders != canonical_orders:
            reasons.append("PEDIDOS_DIFERENTES_PRESERVAR_CONTATOS")
        if not canonical_orders:
            # Sem compra, conservar a proteção anterior por telefone único.
            if matches != {canonical_uuid}:
                reasons.append("TELEFONE_SEM_CONTATO_CANONICO_UNICO")
        if any(
            ps & native_phones(c) and normalize_cpf(get_fields(c).get("cpf")) != cf
            for c in related_contacts
        ):
            reasons.append("TELEFONE_API_EM_OUTRO_CPF")
    if set(history_owner_ids) - {cid}:
        reasons.append("HISTORICO_DE_OUTRO_CLIENTE")
    checked_orders = refs(duplicate) | set(recorded_order_ids)
    if order_partition is not None:
        checked_orders |= refs(canonical) | set(canonical_recorded_ids)
    for oid in checked_orders:
        payload = orders.get(oid)
        capa = (payload or {}).get("capa") or {}
        if (
            _positive_id(capa.get("id")) != oid
            or _positive_id(capa.get("codCliente")) != cid
        ):
            reasons.append("PEDIDO_NAO_COMPROVADO_DO_MESMO_CLIENTE")
    consent_args = {
        "opt_out_lgpd_uuid": opt_out_lgpd_uuid,
        "opt_out_marketing_uuid": opt_out_marketing_uuid,
    }
    canonical_refusals = contact_refusals(canonical, **consent_args)
    duplicate_refusals = contact_refusals(duplicate, **consent_args)
    for key, reason in (
        ("lgpd_refused", "RECUSA_LGPD_NAO_PRESERVADA"),
        ("marketing_refused", "RECUSA_MARKETING_NAO_PRESERVADA"),
        ("blocked", "BLOQUEIO_NAO_PRESERVADO"),
        ("stopped", "PARADA_NAO_PRESERVADA"),
    ):
        if duplicate_refusals[key] and not canonical_refusals[key]:
            reasons.append(reason)
    return sorted(set(reasons))


def partition_cpf_contacts(contacts, customer, order_ids):
    """Agrupa conjuntos exatos de pedidos; nunca funde históricos diferentes."""
    buckets = {}
    for contact in contacts:
        key = frozenset(order_ids[contact["uuid"]])
        buckets.setdefault(key, []).append(contact)

    def preference(contact):
        return (
            not bool(native_phones(contact) & customer_phones(customer)),
            str(contact.get("created_on") or ""),
            contact["uuid"],
        )

    ordered = sorted(
        ((key, sorted(cs, key=preference)) for key, cs in buckets.items() if key),
        key=lambda entry: tuple(sorted(entry[0], key=int)),
    )
    survivors = [cs[0] for _, cs in ordered]
    pairs = [(cs[0], duplicate) for _, cs in ordered for duplicate in cs[1:]]
    empty = sorted(buckets.get(frozenset(), []), key=preference)
    if survivors:
        target = min(survivors, key=preference)
        pairs.extend((target, duplicate) for duplicate in empty)
    elif empty:
        target = empty[0]
        pairs.extend((target, duplicate) for duplicate in empty[1:])
    renames = []
    if len(survivors) > 1:
        full_name = str(customer.get("nome") or "").strip()
        if full_name:
            renames = [(c, f"{full_name} {i}") for i, c in enumerate(survivors, 1)]
    return pairs, renames


def distinct_order_contacts(contacts, order_ids=None):
    """Protege referências distintas; aceita histórico já lido sem novo GET."""
    by_cpf = {}
    for contact in contacts:
        cpf = normalize_cpf(get_fields(contact).get("cpf"))
        if not is_valid_cpf(cpf):
            continue
        ids = refs(contact)
        if order_ids is not None:
            ids |= set(order_ids.get(contact["uuid"], ()))
        if ids:
            by_cpf.setdefault(cpf, []).append((contact["uuid"], frozenset(ids)))
    return {
        uid
        for matches in by_cpf.values()
        if len({ids for _, ids in matches}) > 1
        for uid, _ in matches
    }
