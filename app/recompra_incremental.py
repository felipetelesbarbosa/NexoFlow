"""Seleção incremental local; nenhuma escrita remota ou checkpoint no dry-run."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import timedelta
from time import monotonic

from analytics import get_fields, normalize_cpf
from farmalider_customers import CustomerDirectory, directory_for, prepare_customers
from recompra_profiles import profile_for


def collect_contacts(weni, state, now, *, full=False, segment=None):
    """Modified_on Weni é um cursor de contatos, nunca de compras da API."""
    from pedido_utils import business_order_datetime
    from runtime_profile import segment as active_segment

    segment = segment or active_segment()
    if state.get("segment", segment) != segment:
        raise RuntimeError("Estado incremental pertence a outro segmento.")

    cache = state.get("incremental") or {}
    cursor = business_order_datetime(cache.get("cursor"))
    entries = cache.get("contacts") or {}
    ready = (
        state.get("segment") == segment
        and cache.get("ready")
        and cursor is not None
        and cursor <= now
        and all(isinstance(entry.get("snapshot"), dict) for entry in entries.values())
    )
    if full or not ready:
        contacts = list(weni.iter_contacts())
        return contacts, {
            "complete": True,
            "cursor": now.isoformat(),
            "weni_loaded": len(contacts),
            "full_refresh": True,
            "contact_uuids": sorted({c["uuid"] for c in contacts}),
        }
    assert cursor is not None
    changes = list(weni.iter_contacts(after=cursor - timedelta(minutes=15)))
    changed_ids = {c["uuid"] for c in changes}
    # Duplicações divergentes dentro da própria paginação são conservadas
    # para a auditoria existente; um delta legítimo substitui o snapshot antigo.
    contacts = [
        entry["snapshot"] for uid, entry in entries.items() if uid not in changed_ids
    ]
    contacts.extend(changes)
    return contacts, {
        "complete": True,
        "cursor": now.isoformat(),
        "weni_loaded": len(changes),
    }


def select_contacts(contacts, farm, structure, state, now, *, full=False):
    from farmalider_integration import cpf_cadastro_status
    from recompra import digest, guard

    contacts = [dict(contact) for contact in contacts]
    from contact_dedup_guard import distinct_order_contacts, refs

    protected = distinct_order_contacts(contacts)
    occurrences = Counter(c["uuid"] for c in contacts)
    for contact in contacts:
        contact.pop("_distinct_order_refs", None)
        if contact["uuid"] in protected:
            contact["_distinct_order_refs"] = sorted(refs(contact), key=int)
    segment = structure.get("segment", "FARMA")
    if state.get("segment", segment) != segment:
        raise RuntimeError("Estado incremental pertence a outro segmento.")
    started = monotonic()
    prepare_customers(farm, len(contacts), force=segment == "FARMA")
    directory_seconds = monotonic() - started
    compared_at = monotonic()
    directory = directory_for(farm)
    index = state.get("incremental", {}).get("contacts", {})
    policy = digest({"structure": structure, "policy": profile_for(segment).policy})
    sources, selected, source_cache = {}, [], {}
    checks = state.get("pending_purchase_checks") or {}
    from pedido_utils import business_order_datetime

    for contact in contacts:
        uid = contact["uuid"]
        cpf = normalize_cpf(get_fields(contact).get("cpf"))
        invalid = cpf_cadastro_status(get_fields(contact).get("cpf"))
        source_key = (cpf, invalid)
        if source_key not in source_cache:
            source = None
            if isinstance(directory, CustomerDirectory):
                snapshots, _ = directory.general_base_payload(cpf)
                # Campo omitido, conflito ou pedido incompleto nunca vira cache
                # negativo. PET conserva seu fallback individual nesses casos.
                if snapshots:
                    source = digest(snapshots)
                elif not directory.candidates(cpf):
                    source = "AUSENTE_BASE_GERAL"
            if invalid:
                source = invalid
            source_cache[source_key] = source
        source = source_cache[source_key]
        if source and contact.get("_distinct_order_refs"):
            source = digest(
                {
                    "source": source,
                    "distinct_order_refs": contact["_distinct_order_refs"],
                }
            )
        sources[uid] = source
        saved = index.get(uid) or {}
        next_check = business_order_datetime(saved.get("next_check"))
        if (
            full
            or occurrences[uid] > 1
            or not source
            or saved.get("retry")
            or uid in checks
            or saved.get("policy") != policy
            or saved.get("source") != source
            or saved.get("contact") != digest(guard(contact))
            or (saved.get("next_check") and next_check is None)
            or (next_check is not None and next_check <= now)
        ):
            selected.append(contact)
    return (
        selected,
        sources,
        {
            "mode": "completa"
            if full
            else "incremental"
            if index
            else "primeira_execucao",
            "loaded": len(contacts),
            "selected": len(selected),
            "unchanged": len(contacts) - len(selected),
            "policy": policy,
            "directory_seconds": round(directory_seconds, 3),
            "comparison_seconds": round(monotonic() - compared_at, 3),
        },
    )


def annotate_plans(plans, sources, selection):
    for plan in plans:
        source = sources.get(plan["contact_uuid"])
        plan["_incremental"] = {"source": source, "policy": selection["policy"]}


def remember_plan(state, plan, structure, now, *, confirmed=True, retry=False):
    """Só o chamador que confirmou o resultado pode registrar este checkpoint."""
    from recompra import TZ, digest, field_guard
    from recompra_review_audit import has_incomplete_query

    uid = plan["contact_uuid"]
    info = plan.get("_incremental")
    if not info:
        return False
    expected = deepcopy(plan["guard"])
    if confirmed:
        expected["fields"].update(
            {k: field_guard(k, v) for k, v in plan["fields"].items()}
        )
    group = structure["group_uuid"]
    if confirmed and plan["action"] in {"remove", "replace"}:
        expected["groups"] = [g for g in expected["groups"] if g != group]
    if confirmed and plan["action"] in {"add", "replace"}:
        expected["groups"] = sorted(set(expected["groups"]) | {group})
    next_check = ""
    if (
        plan["in_group"]
        or plan.get("within_window")
        or plan.get("order_resolution_status") == "CPF_NAO_ENCONTRADO"
    ):
        next_check = (
            (now.astimezone(TZ) + timedelta(days=1))
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .isoformat()
        )
    snapshot = {
        "uuid": uid,
        "name": expected["name"],
        "fields": expected["fields"],
        "urns": expected["urns"],
        "groups": expected["groups"],
    }
    entry = {
        **info,
        "contact": digest(expected),
        "next_check": next_check,
        "retry": bool(retry or has_incomplete_query(plan)),
        "snapshot": snapshot,
    }
    bucket = state.setdefault("incremental", {}).setdefault("contacts", {})
    changed = bucket.get(uid) != entry
    bucket[uid] = entry
    return changed
