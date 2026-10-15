"""Recortes de pedidos usados no Analytics da farmácia, sem alterar a Weni."""

from __future__ import annotations

import json
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from analytics import (
    build_bi_conversion_records,
    build_bi_summary_record,
    parse_ultimo_pedido,
)
from pedido_utils import business_order_datetime
from product_scope import is_animal_product, pharmacy_items
from task_progress import TaskProgress

Row = dict[str, Any]
SCOPE_VALUE_ORIGIN = "FARMACIA_ITENS_HUMANOS"


def _decimal(value: Any, label: str) -> Decimal:
    try:
        result = Decimal(str(value).replace(",", "."))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Valor inválido em {label} do item humano.") from exc
    if not result.is_finite() or result < 0:
        raise ValueError(f"Valor inválido em {label} do item humano.")
    return result


def _number(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _order_id(value: Any) -> str:
    text = str(value or "").strip()
    return str(int(text)) if text.isascii() and text.isdigit() else text


def _raw_matches_order(record: Row, payload: Row) -> bool:
    current_id = _order_id(record.get("pedido_id"))
    raw_id = _order_id(
        payload.get("pedido_id")
        or payload.get("pedidoId")
        or payload.get("codigo")
        or payload.get("codPedido")
    )
    if current_id and current_id != raw_id:
        return False
    current_time = record.get("data_hora") or record.get("pedido_data")
    if current_time:
        current_dt = business_order_datetime(current_time)
        raw_dt = business_order_datetime(payload.get("data_hora"))
        if current_dt is None or raw_dt != current_dt:
            return False
    return True


def _raw_items(
    record: Row,
    field_name: str = "ultimo_pedido_raw",
    *,
    verify_identity: bool = True,
) -> list[Row]:
    raw = record.get(field_name)
    if not isinstance(raw, str) or not raw.strip():
        return []
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if not isinstance(payload, dict) or not isinstance(payload.get("produtos"), list):
        return []
    if verify_identity and not _raw_matches_order(record, payload):
        return []
    result: list[Row] = []
    for position, item in enumerate(payload["produtos"], start=1):
        if not isinstance(item, dict):
            continue
        row = dict(item)
        row["produto_nome"] = item.get("produto_nome") or item.get("nome") or ""
        row["produto_ordem"] = str(position)
        result.append(row)
    return result


def _same_product(current: Row, snapshot: Row) -> bool:
    current_code = str(
        current.get("produto_codigo") or current.get("codigo") or ""
    ).strip()
    snapshot_code = str(
        snapshot.get("produto_codigo") or snapshot.get("codigo") or ""
    ).strip()
    current_name = (
        str(current.get("produto_nome") or current.get("nome") or "").strip().casefold()
    )
    snapshot_name = (
        str(snapshot.get("produto_nome") or snapshot.get("nome") or "")
        .strip()
        .casefold()
    )
    return bool(
        (current_code and current_code == snapshot_code)
        or (current_name and current_name == snapshot_name)
    )


def _copy_matching_categories(items: list[Row], raw_items: list[Row]) -> None:
    by_position = {str(item.get("produto_ordem")): item for item in raw_items}
    for item in items:
        original = by_position.get(str(item.get("produto_ordem") or ""))
        if (
            not item.get("categoria")
            and original
            and original.get("categoria")
            and _same_product(item, original)
        ):
            item["categoria"] = original["categoria"]


def _has_stale_animal_snapshot(record: Row, field_name: str) -> bool:
    return not _raw_items(record, field_name) and any(
        is_animal_product(item)
        for item in _raw_items(record, field_name, verify_identity=False)
    )


def pharmacy_order_raw(order: Row, items: list[Row]) -> str:
    """JSON com apenas os itens humanos e os valores do recorte analítico."""
    payload = {
        "pedido_id": order.get("pedido_id", ""),
        "data_hora": order.get("data_hora", ""),
        "valor_total_compra": order.get("valor_total_faturamento", ""),
        "quantidade_itens": order.get("quantidade_itens", ""),
        "produtos": [
            {
                "codigo": item.get("produto_codigo") or item.get("codigo") or "",
                "nome": item.get("produto_nome") or item.get("nome") or "",
                **({"categoria": item["categoria"]} if item.get("categoria") else {}),
                "quantidade": item.get("quantidade", ""),
                "valor_unitario": item.get("valor_unitario", ""),
                "valor_total": item.get("valor_total", ""),
            }
            for item in items
        ],
    }
    for key in (
        "origem_pedido",
        "status_confirmacao",
        "farmalider_cancelamento",
        "farmalider_status_pedido",
        "farmalider_status_pedido_nome",
        "farmalider_forma_pagamento",
        "farmalider_forma_pagamento_nome",
        "farmalider_cod_cliente",
        "farmalider_cliente_id",
        "farmalider_frete",
        "farmalider_emissao",
        "farmalider_confirmado_em",
        "valor_origem",
        "total_api",
        "valor_total_api_itens",
        "quantidade_itens_api",
        "status_validacao",
    ):
        if key in order:
            payload[key] = order[key]
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def filter_pharmacy_order(
    order: Row, items: list[Row], *, include_freight: bool = False
) -> tuple[Row | None, list[Row]]:
    """Exclui pedidos pet e recorta mistos sem alterar identidade ou status.

    Sem evidência animal, o pedido fica intacto. O recorte misto usa os totais
    dos itens, já com descontos da API, e exclui o frete por padrão.
    """
    original_raw_items = _raw_items(order)
    raw_has_animal = any(is_animal_product(item) for item in original_raw_items)
    if not items and raw_has_animal:
        items = original_raw_items
    retained = pharmacy_items(items)
    if len(retained) == len(items) and not raw_has_animal:
        result = deepcopy(order)
        if _has_stale_animal_snapshot(order, "ultimo_pedido_raw"):
            if items:
                snapshot_order = dict(order)
                snapshot_order["quantidade_itens"] = _number(
                    sum(
                        (
                            _decimal(item.get("quantidade"), "quantidade")
                            for item in items
                        ),
                        Decimal("0"),
                    )
                )
                result["ultimo_pedido_raw"] = pharmacy_order_raw(snapshot_order, items)
            else:
                result["ultimo_pedido_raw"] = ""
        return result, deepcopy(items)
    if not retained:
        return None, []

    result = deepcopy(order)
    retained = deepcopy(retained)
    products_total = sum(
        (_decimal(item.get("valor_total"), "valor_total") for item in retained),
        Decimal("0"),
    )
    quantity = sum(
        (_decimal(item.get("quantidade"), "quantidade") for item in retained),
        Decimal("0"),
    )
    freight = (
        _decimal(order.get("farmalider_frete") or "0", "frete")
        if include_freight
        else Decimal("0")
    )
    product_money = f"{products_total:.2f}"
    billed_money = f"{products_total + freight:.2f}"
    for key in ("valor_total_compra", "valor_total_itens", "valor_total_api_itens"):
        result[key] = product_money
    for key in ("valor_total_faturamento", "total_api", "valor_total_weni"):
        result[key] = billed_money
    result.update(
        farmalider_frete=f"{freight:.2f}",
        diferenca_total="0.00",
        diferenca_total_weni_api="0.00",
        quantidade_produtos=str(len(retained)),
        quantidade_itens=_number(quantity),
        quantidade_itens_api=_number(quantity),
        valor_origem=SCOPE_VALUE_ORIGIN,
    )
    if result.get("status_validacao") == "ATENÇÃO_TOTAL_DIVERGENTE":
        result["status_validacao"] = "OK"
    result["ultimo_pedido_raw"] = pharmacy_order_raw(result, retained)
    return result, retained


def sanitize_order_record(record: Row) -> Row | None:
    """Barreira de gravação para pedidos que carregam seu snapshot JSON."""
    items = _raw_items(record)
    if not items:
        result = deepcopy(record)
        if _has_stale_animal_snapshot(record, "ultimo_pedido_raw"):
            result["ultimo_pedido_raw"] = ""
        return result
    result, _ = filter_pharmacy_order(record, items)
    return result


def _clear_contact_order(record: Row) -> Row:
    result = deepcopy(record)
    for key in result:
        if key in {"ultimo_pedido", "ultima_compra"} or (
            key.startswith("pedido_") and key != "pedido_revisao_pendente"
        ):
            result[key] = ""
    return result


def sanitize_contact_order(record: Row) -> Row:
    """Preserva o contato e retira campos pet apenas da cópia no Sheets."""
    raw_items = _raw_items(record, "ultimo_pedido")
    product_names = str(record.get("pedido_produtos") or "")
    animal_in_flat = any(
        is_animal_product({"nome": name}) for name in product_names.split(",")
    )
    if not any(is_animal_product(item) for item in raw_items) and not animal_in_flat:
        result = deepcopy(record)
        if _has_stale_animal_snapshot(record, "ultimo_pedido"):
            result["ultimo_pedido"] = ""
        return result

    if _has_stale_animal_snapshot(record, "ultimo_pedido"):
        # Uma lista flat não carrega descontos dos itens. Não recompor preços
        # usando o snapshot animal de outra compra.
        return _clear_contact_order(record)

    order, items = parse_ultimo_pedido(
        {
            "uuid": record.get("contact_uuid", ""),
            "name": record.get("nome", ""),
            "fields": record,
        },
        captured_at=str(record.get("sincronizado_em") or ""),
    )
    if order is None or order.get("status_validacao") == "ERRO" or not items:
        # Não deduzir preços/quantidades de uma lista incompleta de nomes.
        return _clear_contact_order(record)
    _copy_matching_categories(items, raw_items)
    filtered, retained = filter_pharmacy_order(order, items)
    if filtered is None:
        return _clear_contact_order(record)
    result = deepcopy(record)
    result.update(
        ultimo_pedido=pharmacy_order_raw(filtered, retained),
        pedido_produtos=", ".join(str(item["produto_nome"]) for item in retained),
        pedido_quantidade_itens=", ".join(str(item["quantidade"]) for item in retained),
        pedido_valor_produtos=", ".join(
            str(item["valor_unitario"]) for item in retained
        ),
        pedido_valor=filtered["valor_total_compra"],
    )
    return result


@dataclass
class PharmacyScopePlan:
    orders: list[Row] = field(default_factory=list)
    items: list[Row] = field(default_factory=list)
    contacts: list[Row] = field(default_factory=list)
    changed_orders: list[Row] = field(default_factory=list)
    changed_contacts: list[Row] = field(default_factory=list)
    removed_order_keys: set[str] = field(default_factory=set)
    removed_item_keys: set[str] = field(default_factory=set)
    history_changed: int = 0
    tickets_changed: int = 0

    def counts(self) -> dict[str, int]:
        return {
            "pedidos_pet_removidos": len(self.removed_order_keys),
            "itens_pet_removidos": len(self.removed_item_keys),
            "pedidos_mistos_ajustados": len(self.changed_orders),
            "contatos_saneados": len(self.changed_contacts),
            "historico_saneado": self.history_changed,
            "tickets_saneados": self.tickets_changed,
        }


def plan_pharmacy_scope(
    orders: list[Row], items: list[Row], contacts: list[Row] | None = None
) -> PharmacyScopePlan:
    """Planeja a limpeza do histórico inteiro sem executar I/O."""
    with TaskProgress(
        "Analytics: recorte de produtos para a farmácia",
        len(orders) + len(items) + len(contacts or []),
        unit="registros",
    ) as progress:
        plan = PharmacyScopePlan()
        by_order: dict[str, list[Row]] = defaultdict(list)
        classified_by_key: dict[str, Row] = {}
        for item in items:
            by_order[str(item.get("pedido_chave") or "")].append(item)
        for order in progress.track(orders):
            key = str(order.get("pedido_chave") or "")
            current_items = deepcopy(by_order.get(key) or _raw_items(order))
            _copy_matching_categories(current_items, _raw_items(order))
            for item in current_items:
                item_key = str(item.get("item_chave") or "")
                if item_key:
                    classified_by_key[item_key] = item
            filtered, _ = filter_pharmacy_order(order, current_items)
            if filtered is None:
                if key:
                    plan.removed_order_keys.add(key)
            else:
                plan.orders.append(filtered)
                if filtered != order:
                    plan.changed_orders.append(filtered)
        for item in items:
            item = classified_by_key.get(str(item.get("item_chave") or ""), item)
            if str(
                item.get("pedido_chave") or ""
            ) in plan.removed_order_keys or is_animal_product(item):
                key = str(item.get("item_chave") or "")
                if key:
                    plan.removed_item_keys.add(key)
            else:
                plan.items.append(deepcopy(item))
        for contact in progress.track(contacts or []):
            filtered = sanitize_contact_order(contact)
            plan.contacts.append(filtered)
            if filtered != contact:
                plan.changed_contacts.append(filtered)
        return plan


def sanitize_delivery_ticket(
    record: Row, *, excluded_keys: set[str], retained_by_key: dict[str, Row]
) -> Row:
    """Preserva o atendimento, retirando sua venda pet dos dados analíticos."""
    key = str(record.get("pedido_chave") or "")
    result = deepcopy(record)
    if key in excluded_keys:
        result["resultado_validacao"] = "FORA_ESCOPO_FARMACIA"
        result["vinculo_atendimento"] = "FORA_ESCOPO_FARMACIA"
        for field_name in (
            "pedido_chave",
            "pedido_id",
            "pedido_data",
            "pedido_status",
            "pedido_valor",
        ):
            result[field_name] = ""
    elif key in retained_by_key:
        result["pedido_valor"] = retained_by_key[key].get("valor_total_compra", "")
    return result


def recalculate_scope_snapshots(
    summary_records: list[Row],
    conversion_records: list[Row],
    contacts: list[Row],
    orders: list[Row],
    items: list[Row],
) -> tuple[list[Row], list[Row]]:
    """Corrige vendas de snapshots antigos sem reescrever métricas de contatos.

    Considera somente pedidos anteriores ao dia do snapshot. Quando há datas
    válidas de captura e atualização, também preserva o corte de observação.
    """
    scoped = plan_pharmacy_scope(orders, items, contacts)

    def observed_orders(record):
        snapshot_dt = business_order_datetime(record.get("data"))
        if snapshot_dt is None:
            return None
        observed_at = business_order_datetime(record.get("atualizado_em"))
        retained = []
        for order in scoped.orders:
            order_dt = business_order_datetime(
                order.get("data") or order.get("data_hora")
            )
            if order_dt is None or order_dt.date() > snapshot_dt.date():
                continue
            captured_at = business_order_datetime(order.get("capturado_em"))
            if (
                observed_at is not None
                and captured_at is not None
                and captured_at > observed_at
            ):
                continue
            retained.append(order)
        return snapshot_dt.date().isoformat(), retained

    sales_fields = {
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
    }
    summaries = []
    for record in summary_records:
        result = deepcopy(record)
        observed = observed_orders(record)
        if observed is not None:
            snapshot_date, retained = observed
            corrected = build_bi_summary_record(
                scoped.contacts,
                retained,
                scoped.items,
                snapshot_date=snapshot_date,
                updated_at=str(record.get("atualizado_em") or ""),
            )
            for key in sales_fields:
                if key in result:
                    result[key] = corrected[key]
        summaries.append(result)

    stage_counts: dict[str, dict[str, Decimal]] = defaultdict(dict)
    for record in conversion_records:
        stage = str(record.get("etapa_ordem") or "")
        if stage in {"1", "3"}:
            try:
                stage_counts[str(record.get("data") or "")][stage] = _decimal(
                    record.get("quantidade"), "quantidade"
                )
            except ValueError:
                continue
    conversions = []
    for record in conversion_records:
        result = deepcopy(record)
        observed = observed_orders(record)
        denominators = stage_counts.get(str(record.get("data") or ""), {})
        if (
            str(record.get("etapa_ordem") or "") == "4"
            and observed is not None
            and {"1", "3"} <= denominators.keys()
        ):
            snapshot_date, retained = observed
            corrected = build_bi_conversion_records(
                scoped.contacts,
                retained,
                snapshot_date=snapshot_date,
                updated_at=str(record.get("atualizado_em") or ""),
            )[-1]
            quantity = Decimal(corrected["quantidade"])
            result["quantidade"] = corrected["quantidade"]
            result["taxa_base_pct"] = (
                float(round(quantity * 100 / denominators["1"], 2))
                if denominators["1"]
                else 0.0
            )
            result["taxa_etapa_anterior_pct"] = (
                float(round(quantity * 100 / denominators["3"], 2))
                if denominators["3"]
                else 0.0
            )
        conversions.append(result)
    return summaries, conversions
