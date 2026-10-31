"""Reconsulta pedidos oficiais já observados, sem modificar contatos da Weni."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from analytics import (
    _item_key,
    _order_customer_identity_verified,
    get_fields,
    normalize_cpf,
)
from config import FARMALIDER_MAX_WORKERS
from farmalider_client import (
    FarmaliderAuthError,
    FarmaliderError,
    FarmaliderUnavailableError,
)
from farmalider_integration import (
    _positive_id,
    apply_pedido_api_confirmation,
    select_cliente_response,
    weni_customer_identity,
)
from pedido_utils import (
    PENDING_ITEMS_STATUS,
    business_order_datetime,
    farmalider_payment_method_display,
    is_order_cancelled,
    serialize_pedido_products,
)
from task_progress import TaskProgress

Row = dict[str, str]
PedidoResponse = dict[str, Any] | list[dict[str, Any]] | None
STATUS_RECHECK_DAYS = 20


def verified_order_cancellation(order: Row) -> bool:
    """A confirmação de cancelamento exige o cabeçalho oficial do mesmo cliente."""
    if (
        order.get("_farmalider_cabecalho_verificado") == "1"
        and order.get("status_validacao") == "CANCELADO_SEM_ITENS"
        and order.get("status_confirmacao") == "CANCELADO_API"
        and order.get("_farmalider_erro_consulta_pedido") != "1"
    ):
        return True
    return order.get("_farmalider_cabecalho_verificado") == "1" and is_order_cancelled(
        {
            key: order.get(key, "")
            for key in (
                "farmalider_status_pedido",
                "farmalider_forma_pagamento",
                "farmalider_cancelamento",
            )
        }
    )


def _verified_observed_order(order: Row) -> bool:
    return bool(
        _positive_id(order.get("pedido_id"))
        and _positive_id(order.get("farmalider_cliente_id"))
        and str(order.get("status_confirmacao") or "")
        in {"CONFIRMADO_API", "CANCELADO_API", PENDING_ITEMS_STATUS}
        and _order_customer_identity_verified(order)
    )


def observed_orders_by_contact(existing_orders: list[Row]) -> dict[str, list[Row]]:
    """Index only independently verified history, never by shared CPF."""
    indexed: dict[str, list[Row]] = {}
    for order in existing_orders:
        if order.get("pedido_chave") and _verified_observed_order(order):
            indexed.setdefault(order.get("contact_uuid", ""), []).append(order)
    return indexed


def observed_orders_by_identity(
    existing_orders: list[Row],
) -> dict[tuple[str, str], list[Row]]:
    """Global official-order index; it never stores a Weni identity decision."""
    indexed: dict[tuple[str, str], list[Row]] = {}
    for order in existing_orders:
        if order.get("pedido_chave") and _verified_observed_order(order):
            identity = (
                _positive_id(order["pedido_id"]),
                _positive_id(order["farmalider_cliente_id"]),
            )
            indexed.setdefault(identity, []).append(order)
    return indexed


def preserve_old_latest_order(
    contact: dict[str, Any],
    *,
    existing_by_contact: dict[str, list[Row]],
    existing_by_identity: dict[tuple[str, str], list[Row]] | None = None,
    cliente_response: PedidoResponse,
    captured_at: str,
) -> bool:
    """Avoid a dedicated status GET only after a fresh CPF response identifies it.

    No API response is fabricated and no old identity result is shared. A new
    order ID, even with an old emission date, still requires its first GET.
    """
    prior = existing_by_contact.get(str(contact.get("uuid") or ""), [])
    if (not prior and not existing_by_identity) or cliente_response is None:
        return False
    result, selected = select_cliente_response(
        normalize_cpf(get_fields(contact).get("cpf")),
        cliente_response,
        weni_identity=weni_customer_identity(contact),
    )
    if result[0] not in {"CPF_CONFIRMADO", "CPF_INVALIDO_ENCONTRADO"} or not selected:
        return False
    latest = selected.get("ultimoPedido")
    cutoff = business_order_datetime(captured_at)
    if not isinstance(latest, dict) or cutoff is None:
        return False
    emitted = business_order_datetime(latest.get("emissao"))
    if emitted is None or (cutoff.date() - emitted.date()).days <= STATUS_RECHECK_DAYS:
        return False
    order_id, owner = _positive_id(latest.get("id")), result[1]
    if "codCliente" in latest and _positive_id(latest["codCliente"]) != owner:
        return False
    if existing_by_identity is not None:
        prior = existing_by_identity.get((order_id, owner), [])
    if len({old.get("pedido_chave") for old in prior}) != 1:
        return False
    return any(
        _positive_id(old.get("pedido_id")) == order_id
        and _positive_id(old.get("farmalider_cliente_id")) == owner
        and (old_emitted := business_order_datetime(old.get("data_hora"))) is not None
        and (cutoff.date() - old_emitted.date()).days > STATUS_RECHECK_DAYS
        for old in prior
    )


@dataclass
class ObservedOrdersResult:
    orders: list[Row]
    items: list[Row]
    api_errors: int = 0
    checked: int = 0
    refreshed: int = 0
    skipped_unverified: int = 0
    negative_headers: int = 0
    pending_without_items: int = 0
    skipped_outside_window: int = 0
    pending_dates: int = 0
    ambiguous_orders: int = 0


def revalidate_observed_orders(
    existing_orders: list[Row],
    *,
    scoped_contact_uuids: set[str],
    current_orders: list[Row],
    current_items: list[Row],
    existing_items: list[Row] | None = None,
    farm_client: Any,
    captured_at: str,
    pedido_responses_by_id: dict[str, PedidoResponse] | None = None,
    max_workers: int | None = None,
) -> ObservedOrdersResult:
    """Refresh verified orders aged 0..20 days, including completed/cancelled ones.

    Failed positive snapshots are absent from the returned updates. A verified
    negative header withdraws a sale while retaining its previous amounts and
    items; a proven cancellation does not require items to exclude the sale. Only raw GET
    responses are shared; every stored customer ownership is validated again.
    Current-load snapshots take precedence over historical attribution.
    """
    result = ObservedOrdersResult(
        orders=list(current_orders), items=list(current_items)
    )
    if farm_client is None:
        return result

    cache = pedido_responses_by_id if pedido_responses_by_id is not None else {}
    cutoff = business_order_datetime(captured_at)
    if cutoff is None:
        raise ValueError("Data da carga inválida para revalidar pedidos observados.")
    selected: dict[str, Row] = {}
    prior_keys_by_identity: dict[tuple[str, str], str] = {}
    ambiguous_identities: set[tuple[str, str]] = set()
    current_identities = {
        (
            _positive_id(row.get("pedido_id")),
            _positive_id(row.get("farmalider_cliente_id")),
        )
        for row in current_orders
    }
    for old in existing_orders:
        in_scope = str(old.get("contact_uuid") or "") in scoped_contact_uuids
        key = str(old.get("pedido_chave") or "").strip()
        if not key:
            continue
        if not _verified_observed_order(old):
            result.skipped_unverified += int(in_scope)
            continue
        identity = (
            _positive_id(old["pedido_id"]),
            _positive_id(old["farmalider_cliente_id"]),
        )
        if (
            identity in prior_keys_by_identity
            and prior_keys_by_identity[identity] != key
        ):
            ambiguous_identities.add(identity)
        prior_keys_by_identity.setdefault(identity, key)
        # Alias identity is global: the same official order may be linked to
        # another Weni contact/quarter. Only the dedicated GET queue is scoped.
        if not in_scope and not (
            identity in current_identities and identity[0] in cache
        ):
            continue
        emitted = business_order_datetime(old.get("data_hora"))
        age = (cutoff.date() - emitted.date()).days if emitted else -1
        if age < 0:
            result.pending_dates += 1
            result.api_errors += 1
            continue
        if age > STATUS_RECHECK_DAYS:
            result.skipped_outside_window += 1
            continue
        selected[key] = old
    if ambiguous_identities:
        result.ambiguous_orders = len(ambiguous_identities)
        result.api_errors += result.ambiguous_orders
        selected = {
            key: old
            for key, old in selected.items()
            if (
                _positive_id(old["pedido_id"]),
                _positive_id(old["farmalider_cliente_id"]),
            )
            not in ambiguous_identities
        }

    by_id: dict[str, list[Row]] = {}
    for old in selected.values():
        by_id.setdefault(_positive_id(old["pedido_id"]), []).append(old)
    updated_orders: dict[str, Row] = {}
    updated_items: dict[str, Row] = {}
    prior_items_by_key: dict[str, list[Row]] = {}
    for item in existing_items or []:
        prior_items_by_key.setdefault(item.get("pedido_chave", ""), []).append(item)

    def accept(order_id: str, response: PedidoResponse) -> None:
        for old in by_id[order_id]:
            order, items = apply_pedido_api_confirmation(
                old,
                [],
                response if isinstance(response, dict) else None,
                linked_cliente_id=old["farmalider_cliente_id"],
                confirmed_at=captured_at,
            )
            result.checked += 1
            if order.get("status_confirmacao") in {
                "PEDIDO_SEGMENTO_INVALIDO_API",
                "PEDIDO_NAO_ENCONTRADO_API",
            }:
                # Ignorar resposta inválida/ausente sem apagar o histórico nem
                # criar uma pendência de consulta. Falhas de rede seguem abaixo.
                continue
            complete = order.get("status_validacao") == "OK" and bool(items)
            if not complete:
                if not verified_order_cancellation(order):
                    result.api_errors += 1
                    continue
                # Identity and owner were verified before the negative header
                # became actionable. Missing items/date must never keep a
                # proven cancellation counted as a sale or invent new totals.
                partial = deepcopy(old)
                for field in (
                    "farmalider_status_pedido",
                    "farmalider_forma_pagamento",
                    "farmalider_cancelamento",
                    "farmalider_erro",
                ):
                    partial[field] = order.get(field, "")
                partial.update(
                    status_confirmacao="CANCELADO_API",
                    status_validacao=(
                        "CANCELADO_SEM_ITENS"
                        if order.get("status_validacao") == "CANCELADO_SEM_ITENS"
                        else "ERRO"
                    ),
                    farmalider_status_pedido_nome="Cancelado",
                    farmalider_forma_pagamento_nome=farmalider_payment_method_display(
                        order.get("farmalider_forma_pagamento")
                    ),
                    farmalider_confirmado_em=captured_at,
                )
                items = deepcopy(prior_items_by_key.get(old["pedido_chave"], []))
                if items:
                    partial["ultimo_pedido_raw"] = serialize_pedido_products(
                        partial, items
                    )
                order = partial
                result.negative_headers += 1
            # Preserve the original join key and attribution, even for native
            # layouts predating the current FARMALIDER:<id> key convention.
            key = old["pedido_chave"]
            order["pedido_chave"] = key
            updated_orders[key] = order
            for position, item in enumerate(items, start=1):
                item["pedido_chave"] = key
                if complete:
                    item["item_chave"] = _item_key(key, position)
                updated_items[item["item_chave"]] = item
            result.refreshed += 1

    def failed(order_id: str) -> None:
        count = len(by_id[order_id])
        result.checked += count
        result.api_errors += count

    with TaskProgress(
        "FarmaLíder: revalidação de pedidos observados",
        len(selected),
        unit="pedidos",
        detail=lambda: f"atualizados={result.refreshed}; falhas={result.api_errors}",
    ) as progress:
        pending = []
        for order_id in by_id:
            if order_id in cache:
                accept(order_id, cache[order_id])
                progress.advance(len(by_id[order_id]))
            else:
                pending.append(order_id)
        if pending:
            workers = min(
                len(pending),
                max(1, int(FARMALIDER_MAX_WORKERS)),
                max(1, int(max_workers or FARMALIDER_MAX_WORKERS)),
            )
            executor = ThreadPoolExecutor(
                max_workers=workers, thread_name_prefix="pedidos-observados"
            )
            progress.set_activity("aguardando API: FarmaLíder pedido por código")
            try:
                # Keep a bounded queue; the existing client supplies shared
                # rate limiting, adaptive concurrency, retry and cooldown.
                for start in range(0, len(pending), workers * 4):
                    futures = {
                        executor.submit(farm_client.get_pedido, order_id): order_id
                        for order_id in pending[start : start + workers * 4]
                    }
                    for future in as_completed(futures):
                        order_id = futures[future]
                        try:
                            response = future.result()
                        except (FarmaliderAuthError, FarmaliderUnavailableError):
                            farm_client.cancel_pending_requests()
                            for remaining in futures:
                                remaining.cancel()
                            raise
                        except FarmaliderError:
                            failed(order_id)
                        else:
                            cache[order_id] = response
                            accept(order_id, response)
                        progress.advance(len(by_id[order_id]))
            finally:
                executor.shutdown(wait=True, cancel_futures=True)
                progress.set_activity("")

    # Current snapshots are authoritative, including their selected Weni
    # attribution; do not add historical items to a current failed snapshot.
    current_by_key = {}
    aliases = {}
    current_item_orders = {item["pedido_chave"] for item in current_items}
    for current in current_orders:
        identity = (
            _positive_id(current.get("pedido_id")),
            _positive_id(current.get("farmalider_cliente_id")),
        )
        if identity in ambiguous_identities:
            continue
        if identity in prior_keys_by_identity and (
            current.get("status_validacao") != "OK"
            or current["pedido_chave"] not in current_item_orders
        ):
            # A failed current resolution of this same official order must
            # not overwrite preserved finance/items or a proven cancellation.
            continue
        old_key = prior_keys_by_identity.get(identity, current["pedido_chave"])
        aliases[current["pedido_chave"]] = old_key
        current_by_key[old_key] = dict(current, pedido_chave=old_key)
    updated_orders.update(current_by_key)
    result.orders = list(updated_orders.values())
    retained_items = {
        key: item
        for key, item in updated_items.items()
        if item["pedido_chave"] not in current_by_key
    }
    for item in current_items:
        if item["pedido_chave"] not in aliases:
            continue
        old_key = aliases.get(item["pedido_chave"], item["pedido_chave"])
        mapped = dict(item)
        if old_key != item["pedido_chave"]:
            mapped["pedido_chave"] = old_key
            mapped["item_chave"] = _item_key(old_key, int(item["produto_ordem"]))
        retained_items[mapped["item_chave"]] = mapped
    result.items = list(retained_items.values())
    logging.info(
        "FarmaLíder: pedidos observados revalidados=%s; atualizados=%s; "
        "falhas=%s; cancelamentos com itens anteriores preservados=%s; "
        "pendentes sem itens=%s; "
        "registros legados sem vínculo verificado=%s; fora da janela de 20 dias=%s; "
        "datas pendentes=%s; pedidos com chaves históricas ambíguas=%s.",
        result.checked,
        result.refreshed,
        result.api_errors,
        result.negative_headers,
        result.pending_without_items,
        result.skipped_unverified,
        result.skipped_outside_window,
        result.pending_dates,
        result.ambiguous_orders,
    )
    return result
