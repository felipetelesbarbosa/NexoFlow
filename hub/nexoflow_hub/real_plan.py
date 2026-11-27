"""Planejamento FARMA HML de um recorte completo e limitado, nunca APPLY.

Usa snapshots em memória e os planejadores Windows. Dados pessoais individuais
não são escritos no Hub; só contagens e estados de cobertura. Uma falta de
estado, reserva ou contexto não é substituída por uma fixture/estado vazio.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from copy import deepcopy
from datetime import UTC, timedelta
from hashlib import sha256
from itertools import islice
from pathlib import Path
from typing import cast

from order_history import HistoryQuery, normalize_order, page_envelope

from .farma_read_probe import farmalider_client_from_worker
from .real_read_probe import safe_source, weni_client_from_worker
from .real_read_transport import ProbePending, require_scope


def bounded(values, maximum):
    result = list(islice(values, maximum + 1))
    if len(result) > maximum:
        raise ProbePending("LIMITE_AMOSTRA_EXCEDIDO")
    return result


def private_json(variable):
    value = os.environ.get(variable)
    if not value:
        raise ProbePending("ESTADO_PRIVADO_AUSENTE")
    try:
        path = Path(value)
        if path.stat().st_size > 32 * 1024 * 1024:
            raise ProbePending("LIMITE_AMOSTRA_EXCEDIDO")
        raw = path.read_bytes()
        if os.environ.get(variable + "_SHA256") != sha256(raw).hexdigest():
            raise ProbePending("ESTADO_PRIVADO_AUSENTE")
        data = json.loads(raw.decode("utf-8-sig"))
    except (OSError, ValueError, UnicodeError):
        raise ProbePending("ESTADO_PRIVADO_AUSENTE") from None
    if (
        not isinstance(data, dict)
        or data.get("segmento", data.get("segment", "FARMA")) != "FARMA"
    ):
        raise ProbePending("ESTADO_PRIVADO_AUSENTE")
    return data


def inputs():
    import reservas_farma
    from purchase_checks import merge_purchase_checks

    weni = private_json("HUB_PLAN_WENI_STATE_FILE")
    recompra = private_json("HUB_PLAN_RECOMPRA_STATE_FILE")
    from pedido_utils import business_order_datetime

    if not business_order_datetime(weni.get("last_success_utc")):
        raise ProbePending("ESTADO_PRIVADO_AUSENTE")
    if recompra.get("schema") != 1 or not isinstance(recompra.get("contacts"), dict):
        raise ProbePending("ESTADO_PRIVADO_AUSENTE")
    # A marca de origem deve ser fornecida pelo operador que transfere o
    # estado correto. Não inferimos um checkpoint FARMA de um estado PET.
    if os.environ.get("HUB_PLAN_STATE_SEGMENT") != "FARMA":
        raise ProbePending("ESTADO_PRIVADO_AUSENTE")
    if not os.environ.get(reservas_farma.AMBIENTE_SHA):
        raise ProbePending("RESERVAS_NAO_CONFIRMADAS")
    try:
        reservations = reservas_farma.carregar("FARMA")
    except (ValueError, RuntimeError, OSError):
        raise ProbePending("RESERVAS_NAO_CONFIRMADAS") from None
    if not reservations.sha256:
        raise ProbePending("RESERVAS_NAO_CONFIRMADAS")
    recompra["pending_purchase_checks"] = merge_purchase_checks(
        recompra.get("pending_purchase_checks"), weni.get("pending_purchase_checks")
    )
    return weni, recompra, reservations


def collect_history(client, query, cutoff, *, max_pages):
    """Confere todas as páginas do recorte e deduplica por identidade oficial."""
    records, raw_orders = [], {}
    expected_total = None
    expected_pages = None
    for page in range(1, max_pages + 1):
        rows, total, pages = page_envelope(
            client.get_pedidos_history(query, page), query, page
        )
        if expected_total is None:
            expected_total, expected_pages = total, pages
        elif (total, pages) != (expected_total, expected_pages):
            raise ProbePending("CONTEXTO_INCOMPLETO")
        if pages > max_pages:
            raise ProbePending("LIMITE_AMOSTRA_EXCEDIDO")
        for row in rows:
            header = row["capa"]
            if str(header.get("segmento", "")).upper() != "FARMA" or not query.contains(
                header.get("emissao")
            ):
                raise ProbePending("CONTEXTO_INCOMPLETO")
            key = str(header["id"])
            if key in raw_orders:
                raise ProbePending("CONTEXTO_INCOMPLETO")
            raw_orders[key] = row
            records.append(normalize_order(row, "FARMA", cutoff.isoformat()))
        if page >= max(1, pages):
            break
    if expected_total != len(records):
        raise ProbePending("CONTEXTO_INCOMPLETO")
    return records, raw_orders


def sales_plan(records):
    """Mesma normalização financeira de order_history; nada entra em publicação."""
    counts = Counter(record["state"] for record in records)
    valid = [record for record in records if record["state"] == "valido"]
    pending = counts["pendente"] + counts["ignorado"]
    return {
        "estado": "parcial" if pending else "planejado",
        "regra": "order_history.normalize_order",
        "pedidos_observados": len(records),
        "pedidos_validos": len(valid),
        "pedidos_cancelados": counts["cancelado"],
        "pedidos_pendentes": pending,
        "receita_produtos_centavos": sum(r["products_cents"] for r in valid),
        "frete_centavos": sum(r["freight_cents"] for r in valid),
        "faturamento_centavos": sum(r["revenue_cents"] for r in valid),
        "totais_incluem_apenas_confirmados": True,
        # A conversa humana, vínculo e histórico anterior do cliente precisam
        # ser confirmados pelo módulo comercial. Não inferir venda do clique.
        "atribuicao_comercial": "pendente",
        "aplicado": False,
    }


class DirectorySnapshot:
    """Adaptador de consulta à base oficial capturada, com zero gravações.

    Não é instância do cliente Windows: prepare_customers não pode registrar
    observações via armazenamento remoto. Nenhuma ausência vira pedido zero.
    """

    def __init__(self, directory, orders):
        self.customer_directory = directory
        self.orders = orders

    def get_cliente_by_cpf(self, cpf):
        from farmalider_client import FarmaliderLookupError

        data, reason = self.customer_directory.general_base_payload(cpf)
        if reason:
            raise FarmaliderLookupError(reason)
        return data

    def get_cliente_cadastro_by_cpf(self, cpf):
        return self.customer_directory.candidates(cpf)

    def get_pedido(self, order_id):
        from farmalider_client import FarmaliderLookupError

        value = self.orders.get(str(order_id))
        if value is None:
            value = self.customer_directory.order_by_id(str(order_id))
        if value is None:
            raise FarmaliderLookupError("PEDIDO_NAO_CONFIRMADO_BASE_GERAL")
        return deepcopy(value)


def weni_snapshot(weni, cutoff, *, max_contacts, max_messages, max_events):
    from config import WENI_CONTACTS_API_URL, WENI_EVENTS_API_URL, WENI_MESSAGES_API_URL
    from pedido_utils import business_order_datetime

    contacts = bounded(
        weni._iter_paginated(
            WENI_CONTACTS_API_URL,
            {"deleted": "false", "order_by": "modified_on", "limit": 250},
            item_label="contatos",
            strict_items=True,
        ),
        max_contacts,
    )
    # Não simular um corte antigo com um cadastro atual modificado depois dele.
    if any(
        not c.get("uuid")
        or (modified := business_order_datetime(c.get("modified_on"))) is None
        or modified > cutoff
        for c in contacts
    ):
        raise ProbePending("CONTEXTO_INCOMPLETO")
    messages = bounded(
        weni._iter_paginated(
            WENI_MESSAGES_API_URL,
            {"before": weni.format_datetime(cutoff), "limit": 250},
            item_label="mensagens",
            strict_items=True,
        ),
        max_messages,
    )
    if any(
        (sent := business_order_datetime(m.get("created_on"))) is None or sent > cutoff
        for m in messages
    ):
        raise ProbePending("CONTEXTO_INCOMPLETO")

    class Events:
        remaining = max_events

        def list_ctwa_events(self, *, after, before):
            records = bounded(
                weni._iter_paginated(
                    WENI_EVENTS_API_URL,
                    {
                        "date_start": weni.format_datetime(after),
                        "date_end": weni.format_datetime(before),
                        "event_name": "ctwa",
                        "limit": 250,
                    },
                    item_label="eventos CTWA",
                    strict_items=True,
                ),
                self.remaining,
            )
            self.remaining -= len(records)
            return records

    return contacts, messages, Events()


def update_plan(weni, farm, contacts, messages, events, state, reservations, cutoff):
    import weni_update as wu
    from contact_dedup_guard import distinct_order_contacts
    from customer_discovery import build_new_customer_plans
    from farmalider_client import FarmaliderClient
    from meta_events import read_meta_events
    from purchase_checks import normalize_purchase_checks

    if len({c["uuid"] for c in contacts}) != len(contacts):
        raise ProbePending("CONTEXTO_INCOMPLETO")
    fields = wu._available_weni_fields(weni)
    wu._ensure_multichannel_fields(weni, fields)
    wu._ensure_order_fields(fields)
    groups = wu._resolve_required_groups(
        weni, (wu.WENI_UPDATE_OPT_IN_GROUP, wu.WENI_UPDATE_OPT_OUT_GROUP)
    )
    opt_in, in_id = groups[wu.WENI_UPDATE_OPT_IN_GROUP]
    opt_out, out_id = groups[wu.WENI_UPDATE_OPT_OUT_GROUP]
    if not (opt_in and opt_out):
        raise ProbePending("CONTEXTO_INCOMPLETO")

    # Todo o contexto observado, inclusive metadados CTWA, e a revisão
    # existente do checkpoint de compra. Sem POST, criações ou deduplicação.
    grouped = wu._group_messages_by_contact(messages)
    if any(not wu._extract_contact_uuid(m) for m in messages):
        raise ProbePending("CONTEXTO_INCOMPLETO")
    meta_events = read_meta_events(
        events,
        contacts,
        messages,
        before=cutoff,
        state=state,
        full=True,
        initial_days=wu.WENI_UPDATE_INITIAL_LOOKBACK_DAYS,
        overlap_minutes=wu.WENI_UPDATE_OVERLAP_MINUTES,
    )
    ads_complete = not any(
        meta_events.report.get(key)
        for key in ("failed_batches", "invalid", "unmatched", "ambiguous")
    )
    pending_checks = normalize_purchase_checks(state.get("pending_purchase_checks"))
    distinct = distinct_order_contacts(contacts)
    plans = []
    for contact in sorted(
        contacts, key=lambda c: wu.cpf_query_priority(wu.get_fields(c).get("cpf"))
    ):
        uid = contact["uuid"]
        context = [*grouped.get(uid, []), *meta_events.by_contact.get(uid, [])]
        candidate = {
            wu.message_id(m)
            for m in grouped.get(uid, [])
            if wu.message_id(m) and wu.message_direction(m) == "in"
        }
        plans.append(
            wu._build_contact_plan(
                contact,
                context_messages=context,
                candidate_message_ids=candidate,
                farm_client=cast(FarmaliderClient, farm),
                opt_in_group_name=wu.WENI_UPDATE_OPT_IN_GROUP,
                opt_in_group_uuid=in_id,
                opt_out_group_name=wu.WENI_UPDATE_OPT_OUT_GROUP,
                opt_out_group_uuid=out_id,
                captured_at=wu.iso_utc(cutoff),
                available_weni_fields=fields,
                pending_purchase_check=pending_checks.get(uid),
                ads_history_complete=ads_complete,
                preserve_distinct_orders=uid in distinct,
            )
        )
    new, creation_pending = build_new_customer_plans(
        farm,
        contacts,
        captured_at=wu.iso_utc(cutoff),
        available_fields=fields,
        quarter=None,
    )
    plans.extend(new)
    wu.audit_plans(
        plans, opt_out_group_available=opt_out, opt_in_group_available=opt_in
    )
    protected = [p for p in plans if reservations.protege(p.contact_uuid)]
    actionable = [
        p for p in plans if p.has_changes and not reservations.protege(p.contact_uuid)
    ]
    unresolved = sum(
        p.order_resolution_status.startswith(("ERRO_", "CPF_IDENTIDADE_"))
        or p.order_resolution_status == "API_DESABILITADA"
        for p in plans
    )
    # Uma revisão por contato é computada, mas não é armazenada nem aplicada.
    return {
        "estado": "parcial" if not ads_complete or creation_pending or unresolved or protected else "planejado",
        "consultas_pendentes": unresolved,
        "regra": "weni_update._build_contact_plan + audit_plans + customer_discovery",
        "contatos_revisados": len(contacts),
        "novos_contatos_propostos": len(new),
        "planos_com_mudanca": len(actionable),
        "campos_propostos": sum(len(p.fields) for p in actionable),
        "grupos_propostos": sum(len(p.group_actions) for p in actionable),
        "reservas_adiadas": len(protected),
        "ctwa_cobertura_confirmada": ads_complete,
        "pendencias_criacao": sum(creation_pending.values()),
        "pedidos_confirmados_por_contato": sum(p.order_validated for p in plans),
        "aplicado": False,
    }


def recompra_plan(weni, farm, contacts, state, reservations, cutoff):
    import recompra as rc

    structure = rc.inspect_structure(weni, segment="FARMA")
    if structure["errors"]:
        raise ProbePending("CONTEXTO_INCOMPLETO")
    # A revisão usa o estado verdadeiro, preservado e sem registrar admissões.
    plans = rc.build_plans(contacts, farm, structure, state, now=cutoff, workers=1)
    review = rc.make_review(plans, structure, now=cutoff, state=state)
    if review.get("reservas_farma_sha256") != reservations.sha256:
        raise ProbePending("RESERVAS_NAO_CONFIRMADAS")
    protected = [p for p in plans if reservations.protege(p["contact_uuid"])]
    actionable = [p for p in plans if not reservations.protege(p["contact_uuid"])]
    unresolved = sum(rc.has_incomplete_query(p) for p in plans)
    return {
        "estado": "parcial" if unresolved or protected else "planejado",
        "regra": "recompra.build_plans + make_review (D+25)",
        "contatos_revisados": len(plans),
        "reservas_adiadas": len(protected),
        "inclusoes_propostas": sum(p.get("action") == "add" for p in actionable),
        "remocoes_propostas": sum(p.get("action") == "remove" for p in actionable),
        "campos_propostos": sum(len(p.get("fields") or {}) for p in actionable),
        "consultas_pendentes": unresolved,
        "aplicado": False,
    }


def _plan_from_worker(cutoff):
    require_scope()
    if os.environ.get("HUB_REAL_PLAN_ENABLED") != "true":
        raise ProbePending("ESCOPO_FARMA_HML_OBRIGATORIO")
    state, recompra_state, reservations = inputs()
    from farmalider_customers import CustomerDirectory
    from pedido_utils import business_order_datetime

    checkpoint = business_order_datetime(state.get("last_success_utc"))
    if checkpoint is None or checkpoint > cutoff:
        raise ProbePending("CONTEXTO_INCOMPLETO")

    start = os.environ.get("HUB_PLAN_HISTORY_START", "")
    end = os.environ.get("HUB_PLAN_HISTORY_END", "")
    query = HistoryQuery("FARMA", start, end, 500)
    if query.end_at > cutoff or query.end_at - query.start_at > timedelta(days=32):
        raise ProbePending("CONTEXTO_INCOMPLETO")
    if os.environ.get("HUB_FARMALIDER_DIRECTORY_PROBE") != "true":
        raise ProbePending("CONTEXTO_INCOMPLETO")

    # Limites explícitos de homologação. Se o recorte os exceder, a execução
    # permanece pendente; nunca chamar a primeira página de cobertura integral.
    max_contacts, max_messages, max_events, max_pages = 5_000, 30_000, 30_000, 50
    with (
        farmalider_client_from_worker() as farm,
        weni_client_from_worker(planning=True) as weni,
    ):
        records, orders = collect_history(farm, query, cutoff, max_pages=max_pages)
        raw = farm.get_clientes_segmento("FARMA")
        if not isinstance(raw, list) or not raw or len(raw) > 50_000:
            raise ProbePending("CONTEXTO_INCOMPLETO")
        directory = CustomerDirectory(raw, segment="FARMA")
        if not directory.by_id:
            raise ProbePending("CONTEXTO_INCOMPLETO")
        snapshot = DirectorySnapshot(directory, orders)
        contacts, messages, events = weni_snapshot(
            weni,
            cutoff,
            max_contacts=max_contacts,
            max_messages=max_messages,
            max_events=max_events,
        )
        # Cada cálculo é independente; falta de prova nunca é substituída por
        # um plano vazio. Recompra é planejada sobre a Weni observada, sem
        # simular como se a atualização anterior já tivesse sido aplicada.
        update = safe_source(
            lambda: update_plan(
                weni, snapshot, contacts, messages, events, state, reservations, cutoff
            )
        )
        analytics = sales_plan(records)
        recompra = safe_source(
            lambda: recompra_plan(
                weni, snapshot, contacts, recompra_state, reservations, cutoff
            )
        )
        return {
            "estado": "parcial",
            "periodo": [start, end],
            "checkpoint_weni_utc": checkpoint.astimezone(UTC).isoformat(),
            "corte_utc": cutoff.astimezone(UTC).isoformat(),
            "fontes": {
                "weni": {
                    "estado": "validada"
                    if update.get("ctwa_cobertura_confirmada")
                    else "parcial",
                    "sintetico": False,
                    "cobertura_integral": bool(update.get("ctwa_cobertura_confirmada")),
                    "contatos": len(contacts),
                    "mensagens": len(messages),
                },
                "farmalider": {
                    "estado": "parcial"
                    if directory.skipped or directory.conflicted_ids or analytics["pedidos_pendentes"]
                    else "validada",
                    "sintetico": False,
                    "cobertura_integral": not (
                        directory.skipped or directory.conflicted_ids or analytics["pedidos_pendentes"]
                    ),
                    "pedidos": len(records),
                    "cadastros_recebidos": len(raw),
                    "cadastros_validos": len(directory.by_id),
                },
            },
            "planos": {
                "atualizacao_weni": update,
                "analytics": analytics,
                "recompra": recompra,
            },
            "publicacoes": 0,
            "externas_gravacoes": 0,
        }


def plan_from_worker(cutoff):
    """Worker process exclusivo: omite saídas impróprias dos módulos de desktop."""
    import logging
    from contextlib import redirect_stderr, redirect_stdout

    previous = logging.root.manager.disable
    try:
        logging.disable(logging.CRITICAL)
        with (
            open(os.devnull, "w") as sink,
            redirect_stdout(sink),
            redirect_stderr(sink),
        ):
            return _plan_from_worker(cutoff)
    finally:
        logging.disable(previous)
