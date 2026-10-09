"""Reconciliação dos atendimentos marcados como pedido, sem presumir atribuição."""
from __future__ import annotations

import hashlib
import json
import logging
import os
from collections import Counter
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from analytics import _sales_order_is_valid, cpf_query_priority, get_fields, normalize_contact
from farmalider_client import FarmaliderAuthError, FarmaliderError, FarmaliderUnavailableError
from farmalider_integration import apply_pedido_api_confirmation, resolve_contact_order, weni_identity_guard
from pedido_utils import business_order_datetime, effective_order_status_code
from weni_update import (
    ContactUpdatePlan, UpdateStats, _apply_purchase_candidate, _ensure_order_fields,
    _prepare_frozen_plan_for_apply, audit_plans, load_review_snapshot, write_review_snapshot,
)

TICKET_COLUMNS = [
    "ticket_uuid", "protocolo", "contact_uuid", "tags", "aberto_em", "encerrado_em",
    "resultado_validacao", "pedido_chave", "pedido_id", "pedido_data", "pedido_status", "pedido_valor",
    "vinculo_atendimento", "atualizado_em",
]
DELIVERY_ORDER_COLUMNS = [
    "pedido_chave", "pedido_id", "cliente_id", "pedido_data", "data", "pedido_status",
    "pedido_status_nome", "pedido_valor", "venda_realizada", "vinculo_atendimento",
    "quantidade_atendimentos", "atualizado_em",
]
TAGS = {"pedido", "pedido finalizado"}


def _datetime(value):
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result if result.tzinfo is not None else None
    except (TypeError, ValueError):
        return None


def select_tickets(rooms, *, cutoff):
    selected, rejected, seen = [], Counter(), set()
    for room in rooms:
        uid = str(room.get("uuid") or "")
        if uid in seen:
            continue
        seen.add(uid)
        tags = room.get("tags") or []
        if not isinstance(tags, list):
            raise ValueError("Atendimento com estrutura de tags inválida.")
        names = [str(tag.get("name") or "").strip() for tag in tags if isinstance(tag, dict)]
        if not any(" ".join(name.casefold().split()) in TAGS for name in names):
            continue
        ended = _datetime(room.get("ended_at"))
        if ended is None or ended > cutoff or room.get("is_active") is True:
            rejected["ENCERRAMENTO_AUSENTE_OU_FORA_DO_CORTE"] += 1
            continue
        if not (room.get("user") or room.get("first_user_message_sent_at") or room.get("first_user_assigned_at")):
            rejected["ATENDENTE_NAO_IDENTIFICADO"] += 1
            continue
        contact = room.get("contact")
        external_id = str(contact.get("external_id") or "") if isinstance(contact, dict) else ""
        try:
            UUID(uid)
            UUID(external_id)
        except ValueError:
            rejected["VINCULO_WENI_AUSENTE_OU_INVALIDO"] += 1
            continue
        selected.append({"ticket_uuid": uid, "protocolo": str(room.get("protocol") or ""),
                         "contact_uuid": external_id, "tags": ", ".join(names),
                         "aberto_em": str(room.get("created_on") or ""),
                         "encerrado_em": str(room.get("ended_at") or ""),
                         "custom_fields": room.get("custom_fields") or {}})
    return selected, dict(rejected)


def ticket_order_link(ticket, order, *, order_id_field="pedido_id"):
    """A tag e a proximidade de datas não comprovam qual pedido gerou o ticket."""
    fields = ticket.get("custom_fields")
    raw_id = fields.get(order_id_field) if isinstance(fields, dict) else None
    if isinstance(raw_id, (str, int)) and str(raw_id).strip():
        return "CONFIRMADO_POR_ID" if str(raw_id).strip() == order.get("pedido_id") else "OUTRO_PEDIDO_NO_TICKET"
    opened, ended = _datetime(ticket.get("aberto_em")), _datetime(ticket.get("encerrado_em"))
    emitted = business_order_datetime(order.get("data_hora"))
    if opened and ended and emitted:
        if opened <= emitted <= ended:
            return "COMPATIVEL_COM_PERIODO_SEM_ID"
        return "FORA_DO_PERIODO_DO_ATENDIMENTO"
    return "SEM_VINCULO_COMPROVADO"


def _order_plan(contact, resolved, farm, captured_at, available_fields):
    fields = get_fields(contact)
    plan = ContactUpdatePlan(contact_uuid=contact["uuid"], contact_name=str(contact.get("name") or ""))
    _apply_purchase_candidate(plan, contact, farm_client=farm, captured_at=captured_at,
                              available_weni_fields=available_fields, resolved_order=resolved)
    # Always guard the identity, including orders kept only in Sheets because Weni has a newer snapshot.
    plan.guards["__invalid_cpf_identity"] = weni_identity_guard(contact)
    for name in ("cpf", "ultimo_pedido", "pedido_id", "pedido_data", "pedido_status",
                 "pedido_produtos", "pedido_quantidade_itens", "pedido_valor_produtos",
                 "pedido_valor", "pedido_forma_pagamento"):
        plan.guards[name] = fields.get(name)
    return plan


def reconcile_tickets(tickets, contacts, farm, *, captured_at, available_fields, order_id_field="pedido_id"):
    _ensure_order_fields(available_fields)
    by_uuid = {str(contact.get("uuid") or ""): contact for contact in contacts}
    selected_ids = {ticket["contact_uuid"] for ticket in tickets}
    selected_contacts = [by_uuid[uid] for uid in selected_ids if uid in by_uuid]
    selected_contacts.sort(key=lambda contact: (cpf_query_priority(get_fields(contact).get("cpf")), contact["uuid"]))
    resolved_by_uuid, plans, summary = {}, [], Counter()
    for index, contact in enumerate(selected_contacts, 1):
        try:
            resolved = resolve_contact_order(contact, farm_client=farm, captured_at=captured_at)
        except (FarmaliderAuthError, FarmaliderUnavailableError):
            raise
        except FarmaliderError:
            resolved = ({"status_confirmacao": "ERRO_API"}, [])
        resolved_by_uuid[contact["uuid"]] = resolved
        plan = _order_plan(contact, resolved, farm, captured_at, available_fields)
        # Include unchanged/blocked contacts so their identity is checked again before publishing evidence.
        plans.append(plan)
        outcome = plan.order_resolution_status or "SEM_PEDIDO_VALIDADO"
        summary[outcome] += 1
        if index % 500 == 0 or index == len(selected_contacts):
            logging.info("Delivery: clientes verificados=%s/%s; resultados=%s.", index, len(selected_contacts), dict(summary))
    audit_plans(plans, opt_out_group_available=True, opt_in_group_available=True)
    orders, items, rows, ticket_orders = {}, {}, [], {}
    for ticket in tickets:
        order, order_items = resolved_by_uuid.get(ticket["contact_uuid"], (None, []))
        custom = ticket.get("custom_fields")
        explicit_id = custom.get(order_id_field) if isinstance(custom, dict) else None
        explicit_id = str(explicit_id).strip() if isinstance(explicit_id, (int, str)) and not isinstance(explicit_id, bool) else ""
        # An explicit historical ID can be verified only against the customer identified in this execution.
        if (explicit_id.isdigit() and int(explicit_id) > 0 and order
                and order.get("status_confirmacao") in {"CONFIRMADO_API", "CANCELADO_API"}
                and order.get("farmalider_cliente_id") and explicit_id != order.get("pedido_id")):
            cache_key = (ticket["contact_uuid"], explicit_id)
            if cache_key not in ticket_orders:
                template = dict(order, pedido_id=explicit_id)
                try:
                    response = farm.get_pedido(explicit_id)
                    ticket_orders[cache_key] = apply_pedido_api_confirmation(template, [], response,
                        linked_cliente_id=order["farmalider_cliente_id"], confirmed_at=captured_at)
                except (FarmaliderAuthError, FarmaliderUnavailableError):
                    raise
                except FarmaliderError:
                    ticket_orders[cache_key] = ({"status_confirmacao": "ERRO_API"}, [])
            order, order_items = ticket_orders[cache_key]
        outcome = str((order or {}).get("status_confirmacao") or ("CONTATO_WENI_NAO_LOCALIZADO" if ticket["contact_uuid"] not in by_uuid else "SEM_PEDIDO_VALIDADO"))
        usable = bool(order and order_items and order.get("status_validacao") == "OK"
                      and outcome in {"CONFIRMADO_API", "CANCELADO_API"})
        row = {key: ticket.get(key, "") for key in TICKET_COLUMNS}
        row.update(resultado_validacao=outcome, atualizado_em=captured_at,
                   vinculo_atendimento="SEM_PEDIDO_VALIDADO")
        if usable:
            row.update(pedido_chave=order["pedido_chave"], pedido_id=order["pedido_id"], pedido_data=order["data_hora"],
                       pedido_status=effective_order_status_code(order),
                       pedido_valor=order["valor_total_compra"],
                       vinculo_atendimento=ticket_order_link(ticket, order, order_id_field=order_id_field))
            orders[order["pedido_chave"]] = order
            for item in order_items:
                items[item["item_chave"]] = item
        rows.append(row)
    return plans, {"tickets": rows, "orders": list(orders.values()), "items": list(items.values()),
                   "summary": dict(summary), "cutoff": captured_at}


def build_delivery_order_records(tickets, orders, *, updated_at):
    by_key = {order["pedido_chave"]: order for order in orders if order.get("pedido_chave")}
    grouped = {}
    for ticket in tickets:
        key = ticket.get("pedido_chave")
        if key and ticket.get("resultado_validacao") in {"CONFIRMADO_API", "CANCELADO_API"}:
            grouped.setdefault(key, {})[ticket["ticket_uuid"]] = ticket
    records = []
    for key, unique in sorted(grouped.items()):
        order = by_key.get(key)
        if not order or order.get("status_validacao") != "OK":
            continue
        links = {ticket.get("vinculo_atendimento") for ticket in unique.values()}
        records.append(dict(zip(DELIVERY_ORDER_COLUMNS, [
            key, order["pedido_id"], order.get("farmalider_cliente_id", ""),
            order["data_hora"], order["data"], effective_order_status_code(order),
            order.get("farmalider_status_pedido_nome", ""), float(Decimal(order["valor_total_compra"])),
            int(_sales_order_is_valid(order)),
            "CONFIRMADO_POR_ID" if "CONFIRMADO_POR_ID" in links else "SEM_VINCULO_COMPROVADO",
            len(unique), updated_at,
        ])))
    return records


def write_delivery_review(plans, delivery, path):
    stats = UpdateStats(contacts_considered=len(plans), orders_validated=sum(p.order_validated for p in plans))
    write_review_snapshot(plans, stats, full=True, json_path=path, captured_at_utc=delivery["cutoff"])
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["delivery"] = delivery
    payload["delivery_sha256"] = _digest(delivery)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if os.name != "nt":
        path.chmod(0o600)
        path.with_suffix(".txt").chmod(0o600)
    with path.with_suffix(".txt").open("a", encoding="utf-8-sig") as report:
        report.write("\nATENDIMENTOS DELIVERY\n")
        report.write(f"Tickets selecionados: {len(delivery['tickets'])}; pedidos únicos confirmados: {len(delivery['orders'])}.\n")
        report.write("A tag seleciona clientes. Apenas CONFIRMADO_POR_ID comprova o vínculo de um pedido com o ticket.\n")
        report.write("O endpoint por CPF informa somente o último pedido; o histórico de pedidos de cada ticket pode ficar pendente.\n")
        report.write("Resultados por cliente: " + json.dumps(delivery["summary"], ensure_ascii=False) + "\n")
        for ticket in delivery["tickets"]:
            report.write(f"Ticket {ticket['ticket_uuid']} | contato {ticket['contact_uuid']} | tags {ticket['tags']} | "
                         f"checagem {ticket['resultado_validacao']} | pedido {ticket['pedido_id'] or '<não validado>'} | "
                         f"emissão {ticket['pedido_data'] or '<ausente>'} | vínculo {ticket['vinculo_atendimento']}\n")
    return payload


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def apply_delivery_review(path, weni, *, store_factory):
    plans, payload, _ = load_review_snapshot(full=True, json_path=path)
    delivery = payload.get("delivery")
    if not isinstance(delivery, dict) or _digest(delivery) != payload.get("delivery_sha256"):
        raise ValueError("Snapshot Delivery ausente ou alterado; execute a reconciliação novamente.")
    audit_plans(plans, opt_out_group_available=True, opt_in_group_available=True)
    _ensure_order_fields({item.get("key") for item in weni.list_fields()})
    accepted, conflicts, current_contacts = set(), set(), []
    for plan in plans:
        current = weni.get_contact(uuid=plan.contact_uuid)
        if current is None:
            conflicts.add(plan.contact_uuid)
            continue
        prepared, reason = _prepare_frozen_plan_for_apply(plan, current,
            opt_in_group_name="", opt_in_group_uuid="", opt_out_group_name="", opt_out_group_uuid="")
        if prepared is None:
            conflicts.add(plan.contact_uuid)
            continue
        audit_plans([prepared], opt_out_group_available=True, opt_in_group_available=True)
        if prepared.fields:
            weni.update_contact_fields(plan.contact_uuid, prepared.fields)
        accepted.add(plan.contact_uuid)
        merged = deepcopy(current)
        merged["fields"] = {**get_fields(current), **prepared.fields}
        base_record = normalize_contact(merged, delivery["cutoff"])
        confirmed = next((order for order in delivery["orders"] if order["contact_uuid"] == plan.contact_uuid), None)
        if confirmed:
            priority = cpf_query_priority(get_fields(current).get("cpf"))
            base_record.update(farmalider_cliente_id=confirmed.get("farmalider_cliente_id", ""),
                farmalider_cliente_status={0: "CPF_CONFIRMADO", 1: "CPF_INVALIDO_ENCONTRADO", 2: "CPF_NAO_INFORMADO"}[priority],
                farmalider_cliente_consultado_em=delivery["cutoff"])
            # The order confirms the customer ID, but does not supply the official customer name.
            base_record.pop("farmalider_cliente_nome", None)
        else:
            # Preserve the separate customer-validation metadata when only the ticket check failed.
            for name in ("farmalider_cliente_id", "farmalider_cliente_nome", "farmalider_cliente_status", "farmalider_cliente_consultado_em"):
                base_record.pop(name, None)
        current_contacts.append(base_record)
    # A partial/conflicting client never exports a successful reconciliation to Sheets.
    tickets = [row for row in delivery["tickets"] if row["contact_uuid"] in accepted]
    orders = [order for order in delivery["orders"] if order["contact_uuid"] in accepted]
    keys = {order["pedido_chave"] for order in orders}
    items = [item for item in delivery["items"] if item["pedido_chave"] in keys]
    store = store_factory()
    base = store.upsert_contacts_detailed(current_contacts)
    all_orders = store.upsert_orders_detailed(orders).final_records
    all_items = store.upsert_order_items_detailed(items).final_records
    store.upsert_delivery_tickets(tickets)
    store.refresh_delivery_bi(all_orders)
    from analytics import build_bi_conversion_records, build_bi_order_rows, build_bi_sales_rows, build_bi_summary_record, build_sales_metrics
    snapshot_date = business_order_datetime(delivery["cutoff"]).date().isoformat()
    store.replace_sales_metrics(build_sales_metrics(all_orders, all_items))
    store.replace_bi_orders(build_bi_order_rows(base.final_records, all_orders, all_items, updated_at=delivery["cutoff"]))
    store.replace_bi_sales(build_bi_sales_rows(all_orders, all_items, snapshot_date=snapshot_date, updated_at=delivery["cutoff"]))
    store.upsert_bi_summary(build_bi_summary_record(base.final_records, all_orders, all_items, snapshot_date=snapshot_date, updated_at=delivery["cutoff"]))
    store.upsert_bi_conversion(build_bi_conversion_records(base.final_records, all_orders, snapshot_date=snapshot_date, updated_at=delivery["cutoff"]))
    logging.info("Delivery: contatos aceitos=%s; conflitos=%s; tickets enviados=%s; pedidos únicos enviados=%s.",
                 len(accepted), len(conflicts), len(tickets), len(keys))
    return {"contacts_accepted": len(accepted), "conflicts": len(conflicts), "tickets": len(tickets), "orders": len(keys)}
