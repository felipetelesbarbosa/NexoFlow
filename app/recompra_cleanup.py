"""Limpeza revisada: somente remoção do grupo; sem mensagens, exclusões ou inclusões."""

from collections import Counter
from pathlib import Path

from requests import RequestException

from farmalider_client import (
    FarmaliderAuthError,
    FarmaliderError,
    FarmaliderUnavailableError,
)
from farmalider_customers import prepare_customers
from recompra import (
    RecompraReadCache,
    append_audit,
    atomic_json,
    cancelled_order_reason,
    digest,
    ensure_review_current,
    guard,
    iter_prioritized_contacts,
    member,
    now_local,
    resolve_latest,
)
from recompra_lock import state_lock
from recompra_profiles import profile_for
from recompra_review_audit import has_incomplete_query
from task_progress import TaskProgress
from weni_client import WeniError


def inspect_cleanup_structure(weni, segment):
    profile = profile_for(segment)
    org = weni.get_org()
    if (
        org.get("name") != f"Delivery {profile.brand}"
        or org.get("timezone") != "America/Belem"
    ):
        raise RuntimeError(
            "Organização ou fuso Weni não corresponde ao perfil selecionado."
        )
    groups = [g for g in weni.list_groups() if g.get("name") == profile.group]
    if len(groups) != 1 or not groups[0].get("uuid"):
        raise RuntimeError("Grupo de Recompra ausente ou ambíguo.")
    return {
        "segment": segment,
        "group_uuid": groups[0]["uuid"],
        "org": org.get("uuid") or org["name"],
    }


def cancellation_evidence(contact, farm, now):
    local = cancelled_order_reason(None, contact)
    if local:
        return {"reason": local, "order_id": "", "date": ""}
    try:
        prepare_customers(
            farm.farm if isinstance(farm, RecompraReadCache) else farm, None
        )
        order, _ = resolve_latest(contact, farm, now.isoformat())
    except (FarmaliderAuthError, FarmaliderUnavailableError):
        raise
    except (FarmaliderError, RequestException):
        return {"reason": "CONSULTA_PENDENTE", "order_id": "", "date": ""}
    if has_incomplete_query(
        {"order_resolution_status": (order or {}).get("status_confirmacao", "")}
    ):
        return {"reason": "CONSULTA_PENDENTE", "order_id": "", "date": ""}
    return {
        "reason": cancelled_order_reason(order),
        "order_id": (order or {}).get("pedido_id", ""),
        "date": (order or {}).get("data_hora", ""),
    }


def make_cleanup_review(weni, farm, segment, *, now_fn=now_local):
    structure = inspect_cleanup_structure(weni, segment)
    profile = profile_for(segment)
    now = now_fn()
    plans = []
    # Consolidar UUIDs antes de consultar ou propor remoções.
    contacts = iter_prioritized_contacts(weni.iter_contacts())
    with TaskProgress(
        "Recompra: revisão de cancelados", None, batch_size=1000, interval=15
    ) as progress:
        try:
            for contact in contacts:
                if not member(contact, structure["group_uuid"], profile.group):
                    progress.advance()
                    continue
                evidence = cancellation_evidence(contact, farm, now)
                if evidence["reason"]:
                    plans.append(
                        {
                            "contact_uuid": contact["uuid"],
                            "guard": guard(contact),
                            **evidence,
                        }
                    )
                progress.advance()
        finally:
            contacts.close()
    review = {
        "schema": 1,
        "mode": "cleanup_cancelled",
        "day": now.date().isoformat(),
        "structure": structure,
        "plans": plans,
    }
    ensure_review_current(review, now_fn())
    return review


def write_cleanup_review(review, path):
    atomic_json(path, {"review": review, "sha256": digest(review)})
    counts = Counter(p["reason"] for p in review["plans"])
    Path(path).with_suffix(".txt").write_text(
        "NexoFlow — Limpeza de cancelados — "
        + review["structure"]["segment"]
        + "\n"
        + "Somente remoções do grupo de Recompra. Sem excluir contatos, alterar campos ou enviar mensagens.\n"
        + str(dict(counts))
        + "\n"
        + "\n".join(f"{p['contact_uuid']} | {p['reason']}" for p in review["plans"])
        + "\n",
        encoding="utf-8-sig",
    )


def read_cleanup_review(path, segment):
    import json

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    review = data.get("review", {})
    if (
        data.get("sha256") != digest(review)
        or review.get("schema") != 1
        or review.get("mode") != "cleanup_cancelled"
        or review.get("structure", {}).get("segment") != segment
    ):
        raise RuntimeError("Revisão de limpeza inválida ou de outro perfil.")
    seen = set()
    for plan in review["plans"]:
        uid = plan.get("contact_uuid")
        if (
            not uid
            or uid in seen
            or not (
                plan.get("reason", "").startswith(("PEDIDO_", "PAGAMENTO_"))
                or plan.get("reason") == "CONSULTA_PENDENTE"
            )
        ):
            raise RuntimeError("Plano de limpeza inválido.")
        seen.add(uid)
    return review


def apply_cleanup_review(
    review, weni, farm, *, state_path, audit_path, now_fn=now_local
):
    profile = profile_for(review["structure"]["segment"])
    ensure_review_current(review, now_fn())
    if inspect_cleanup_structure(weni, profile.segment) != review["structure"]:
        raise RuntimeError("Grupo ou organização mudou após a revisão.")
    summary = Counter()

    def defer(uid, key, reason):
        summary[key] += 1
        append_audit(
            {
                "mode": "cleanup_cancelled",
                "segment": profile.segment,
                "contact_uuid": uid,
                "status": key.upper(),
                "reason": reason,
                "at": now_fn().isoformat(),
            },
            audit_path,
        )

    with state_lock(state_path):
        farm.reset_execution_reads()
        reads = RecompraReadCache(farm)
        with TaskProgress(
            "Recompra: remoção de cancelados",
            len(review["plans"]),
            batch_size=100,
            interval=15,
        ) as progress:
            for plan in review["plans"]:
                ensure_review_current(review, now_fn())
                uid = plan["contact_uuid"]
                if plan["reason"] == "CONSULTA_PENDENTE":
                    defer(uid, "consultas_pendentes", "CONSULTA_DA_REVISAO")
                    progress.advance()
                    continue
                try:
                    current = weni.get_contact(uuid=uid)
                    if not current:
                        defer(uid, "conflitos", "CONTATO_AUSENTE_OU_ALTERADO")
                        progress.advance()
                        continue
                    if not member(
                        current, review["structure"]["group_uuid"], profile.group
                    ):
                        summary["ja_removidos"] += 1
                        progress.advance()
                        continue
                    if guard(current) != plan["guard"]:
                        defer(uid, "conflitos", "CONTATO_AUSENTE_OU_ALTERADO")
                        progress.advance()
                        continue
                    evidence = cancellation_evidence(current, reads, now_fn())
                    if evidence["reason"] == "CONSULTA_PENDENTE":
                        defer(uid, "consultas_pendentes", "RECONSULTA_API")
                        progress.advance()
                        continue
                    if any(
                        evidence[key] != plan[key]
                        for key in ("reason", "order_id", "date")
                    ):
                        defer(uid, "conflitos", "CONTATO_AUSENTE_OU_ALTERADO")
                        progress.advance()
                        continue
                    latest = weni.get_contact(uuid=uid)
                except (RequestException, WeniError):
                    defer(uid, "consultas_pendentes", "RELEITURA_WENI")
                    progress.advance()
                    continue
                if not latest or guard(latest) != plan["guard"]:
                    defer(uid, "conflitos", "CONTATO_ALTERADO_ANTES_DA_REMOCAO")
                    progress.advance()
                    continue
                ensure_review_current(review, now_fn())
                event = {
                    "mode": "cleanup_cancelled",
                    "segment": profile.segment,
                    "contact_uuid": uid,
                    "reason": plan["reason"],
                    "at": now_fn().isoformat(),
                }
                # Intenção persistida antes do único POST; uma resposta perdida não autoriza retry.
                append_audit({**event, "status": "REMOCAO_INICIADA"}, audit_path)
                weni.contact_group_action(
                    uid, action="remove", group=review["structure"]["group_uuid"]
                )
                verified = weni.get_contact(uuid=uid)
                if not verified or member(
                    verified, review["structure"]["group_uuid"], profile.group
                ):
                    raise RuntimeError(
                        "Resultado da remoção incerto. Confira a Weni e preserve a auditoria antes de retomar."
                    )
                append_audit({**event, "status": "REMOVIDO"}, audit_path)
                summary["removidos"] += 1
                progress.advance()
    return dict(summary)
