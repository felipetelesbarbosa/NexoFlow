from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from typing import Any

from pedido_utils import (
    business_order_datetime,
    farmalider_order_status_name,
    farmalider_payment_method_name,
    is_order_cancelled,
)


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _positive_id(value: Any) -> str:
    """API identities are positive integers, not booleans or decimal numbers."""
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return ""
    text = str(value).strip()
    if not text.isascii() or not text.isdigit() or int(text) <= 0:
        return ""
    return str(int(text))


def _cliente_object(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    if "cliente" in payload:
        cliente = payload["cliente"]
        return cliente if isinstance(cliente, dict) else None
    return payload


def cliente_link_status(
    weni_cpf: str, api_cliente: dict[str, Any] | None,
) -> tuple[str, str, str]:
    """Validate either the official cliente envelope or a legacy flat response."""
    from analytics import is_valid_cpf, normalize_cpf

    normalized_weni = normalize_cpf(weni_cpf)
    if not normalized_weni:
        return "CPF_NAO_INFORMADO", "", ""
    if not is_valid_cpf(normalized_weni):
        return "CPF_INVALIDO", "", ""
    if api_cliente is None:
        return "CPF_NAO_ENCONTRADO", "", ""
    cliente = _cliente_object(api_cliente)
    if cliente is None:
        return "ERRO_RESPOSTA_CLIENTE_API", "", ""
    raw_cpf = cliente.get("cpf")
    if isinstance(raw_cpf, bool) or not isinstance(raw_cpf, (int, str)):
        return "CPF_NAO_INFORMADO_API", "", ""
    api_cpf = normalize_cpf(raw_cpf, pad_to_11=True)
    cliente_id = _positive_id(cliente.get("id"))
    cliente_nome = _text(cliente.get("nome"))
    if not api_cpf:
        return "CPF_NAO_INFORMADO_API", "", ""
    if api_cpf != normalized_weni:
        return "CPF_DIVERGENTE_API", "", ""
    if not cliente_id:
        return "CLIENTE_ID_INVALIDO_API", "", ""
    return "CPF_CONFIRMADO", cliente_id, cliente_nome


def _decimal(value: Any, label: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool) or value is None or value == "":
        raise ValueError(f"{label} ausente ou inválido.")
    try:
        number = Decimal(str(value).replace(",", "."))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{label} inválido.") from exc
    if not number.is_finite() or number < 0 or (positive and number <= 0):
        raise ValueError(f"{label} fora do domínio permitido.")
    return number


def _quantity_text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _api_product_identity(api_item: dict[str, Any]) -> tuple[str, str]:
    """Use descricao as the product name; codProduto remains only an optional code."""
    raw_code = api_item.get("codProduto")
    if raw_code is not None and (
        isinstance(raw_code, bool) or not isinstance(raw_code, (int, str))
    ):
        raise ValueError("codProduto da API deve ser inteiro ou texto.")

    description = api_item.get("descricao")
    if not isinstance(description, str) or not description.strip():
        raise ValueError("descricao do produto ausente ou inválida.")

    return _text(raw_code), description.strip()


def _pedido_from_cliente_payload(
    payload: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Adapt GET cliente/cpf to the same capa+itens shape used by GET pedido."""
    if not isinstance(payload, dict):
        return None
    latest = payload.get("ultimoPedido")
    items = payload.get("itens")
    if not isinstance(latest, dict) or not isinstance(items, list) or not items:
        return None
    return {"capa": dict(latest), "itens": items}


def _failure(
    order: dict[str, str], items: list[dict[str, str]], status: str, message: str,
) -> tuple[dict[str, str], list[dict[str, str]]]:
    order["status_confirmacao"] = status
    order["status_validacao"] = "ERRO"
    order["farmalider_erro"] = message
    return order, items


def _matching_name(
    code: str, old_items: list[dict[str, str]],
    quantity: Decimal, unit: Decimal, total: Decimal,
    api_items: list[dict[str, Any]],
) -> str:
    if code:
        matches = [item for item in old_items if _text(item.get("produto_codigo")) == code]
        if len(matches) == 1:
            return _text(matches[0].get("produto_nome"))
        if matches:
            return ""
    # No positional correspondence: only one exact financial match is usable.
    signature_matches = 0
    for candidate in api_items:
        if not isinstance(candidate, dict):
            continue
        try:
            if (
                _decimal(candidate.get("quantidade"), "quantidade", positive=True) == quantity
                and _decimal(candidate.get("valor"), "valor unitário") == unit
                and _decimal(candidate.get("total"), "total") == total
            ):
                signature_matches += 1
        except ValueError:
            continue
    if signature_matches != 1:
        return ""
    matches = []
    for item in old_items:
        if code and _text(item.get("produto_codigo")):
            continue
        try:
            same = (
                _decimal(item.get("quantidade"), "quantidade", positive=True) == quantity
                and _decimal(item.get("valor_unitario"), "valor_unitario") == unit
                and _decimal(item.get("valor_total"), "valor_total") == total
            )
        except ValueError:
            continue
        if same:
            matches.append(item)
    return _text(matches[0].get("produto_nome")) if len(matches) == 1 else ""


def apply_pedido_api_confirmation(
    order: dict[str, str], items: list[dict[str, str]],
    pedido_api: dict[str, Any] | None, *, linked_cliente_id: str,
    confirmed_at: str, allow_locator_without_customer: bool = False,
) -> tuple[dict[str, str], list[dict[str, str]]]:
    """Build the canonical order from the current FarmaLíder API response."""
    from analytics import _item_key

    order = dict(order)
    if pedido_api is None:
        return _failure(order, [], "PEDIDO_NAO_ENCONTRADO_API", "Pedido não encontrado na API.")
    if not isinstance(pedido_api, dict) or not isinstance(pedido_api.get("capa"), dict):
        return _failure(order, [], "ERRO_RESPOSTA_PEDIDO_API", "Resposta sem objeto capa.")

    capa = pedido_api["capa"]
    api_id = _positive_id(capa.get("id"))
    requested_id = _positive_id(order.get("pedido_id"))
    if not api_id or not requested_id:
        return _failure(order, [], "PEDIDO_ID_INVALIDO_API", "Identidade do pedido ausente ou inválida.")
    if api_id != requested_id:
        return _failure(order, [], "PEDIDO_ID_DIVERGENTE_API", "Identidade do pedido divergente.")

    api_cliente_id = _positive_id(capa.get("codCliente"))
    linked_id = _positive_id(linked_cliente_id)
    if not api_cliente_id:
        return _failure(order, [], "PEDIDO_CLIENTE_NAO_VERIFICADO_API", "Proprietário do pedido não verificado.")
    if not linked_id:
        if not allow_locator_without_customer:
            return _failure(order, [], "PEDIDO_CLIENTE_NAO_VERIFICADO_API", "Proprietário do pedido não verificado.")
        # Fallback controlado: pedido_id/ultimo_pedido pertencem ao próprio
        # contato Weni e servem apenas como localizadores. A API continua sendo
        # a fonte dos dados do pedido; o codCliente retornado fica registrado.
        linked_id = api_cliente_id
    elif api_cliente_id != linked_id:
        return _failure(order, [], "PEDIDO_CLIENTE_DIVERGENTE_API", "Proprietário do pedido divergente.")

    emitted = business_order_datetime(capa.get("emissao"))
    if emitted is None:
        return _failure(order, [], "PEDIDO_DATA_INVALIDA_API", "Emissão do pedido ausente ou inválida.")

    api_items = pedido_api.get("itens")
    if not isinstance(api_items, list) or not api_items:
        return _failure(order, [], "ERRO_ITENS_PEDIDO_API", "Lista de itens ausente ou vazia.")

    api_total = Decimal("0")
    api_qty = Decimal("0")
    canonical_items: list[dict[str, str]] = []
    key = f"FARMALIDER:{api_id}"
    date_time = emitted.isoformat(timespec="seconds")
    date = emitted.date().isoformat()
    hour = emitted.strftime("%H:%M:%S")

    try:
        for position, api_item in enumerate(api_items, 1):
            if not isinstance(api_item, dict):
                raise ValueError("Item da API não é um objeto.")
            if "codPedido" in api_item and _positive_id(api_item["codPedido"]) != api_id:
                return _failure(
                    order, [], "ITEM_PEDIDO_DIVERGENTE_API",
                    "Item pertence a outro pedido ou não possui identidade válida.",
                )

            quantity = _decimal(api_item.get("quantidade"), "quantidade", positive=True)
            unit = _decimal(api_item.get("valor"), "valor unitário")
            total = (
                _decimal(api_item.get("total"), "total do item")
                if api_item.get("total") not in (None, "")
                else quantity * unit
            )
            code, name = _api_product_identity(api_item)

            canonical_items.append({
                "item_chave": _item_key(key, position),
                "pedido_chave": key,
                "pedido_id": api_id,
                "data_hora": date_time,
                "data": date,
                "hora": hour,
                "contact_uuid": order.get("contact_uuid", ""),
                "telefone": order.get("telefone", ""),
                "cliente": order.get("cliente", ""),
                "produto_ordem": str(position),
                "produto_nome": name,
                "produto_codigo": code,
                "quantidade": _quantity_text(quantity),
                "valor_unitario": f"{unit:.2f}",
                "valor_total": f"{total:.2f}",
                "capturado_em": confirmed_at,
            })
            api_total += total
            api_qty += quantity

        freight = (
            _decimal(capa["frete"], "frete")
            if capa.get("frete") not in (None, "")
            else None
        )
        official_total = None
        for field in (
            "valorTotal", "valorTotalPedido", "valorTotalCompra",
            "totalPedido", "totalGeral", "total",
        ):
            if capa.get(field) not in (None, ""):
                official_total = _decimal(capa[field], "total geral")
                break
    except ValueError as exc:
        return _failure(order, [], "ERRO_ITENS_PEDIDO_API", str(exc))

    # Contrato Weni: pedido_valor é somente produtos. Para BI/faturamento,
    # o frete fica separado e também compõe o total cobrado do pedido.
    purchase_total = api_total
    freight_value = freight if freight is not None else Decimal("0")
    billing_total = purchase_total + freight_value
    provenance = "SOMA_ITENS_API"

    order.update({
        "pedido_id": api_id,
        "pedido_chave": key,
        "data_hora": date_time,
        "data": date,
        "hora": hour,
        "farmalider_cliente_id": linked_id,
        "farmalider_cod_cliente": api_cliente_id,
        "status_validacao": "OK",
        "erro_parse": "",
        "farmalider_erro": "",
        "farmalider_confirmado_em": confirmed_at,
        "origem_pedido": order.get("origem_pedido") or "FARMALIDER_API",
        "valor_total_compra": f"{purchase_total:.2f}",
        "valor_total_faturamento": f"{billing_total:.2f}",
        "valor_total_itens": f"{api_total:.2f}",
        "valor_total_api_itens": f"{api_total:.2f}",
        "quantidade_itens_api": _quantity_text(api_qty),
        "total_api": f"{official_total:.2f}" if official_total is not None else "",
        "quantidade_itens": _quantity_text(api_qty),
        "quantidade_produtos": str(len(canonical_items)),
        "diferenca_total": "0.00",
        "valor_origem": provenance,
        "valor_total_weni": "",
        "diferenca_total_weni_api": "",
        "farmalider_frete": f"{freight:.2f}" if freight is not None else "",
    })

    for target, source in (
        ("farmalider_public_id", "publicId"),
        ("farmalider_emissao", "emissao"),
        ("farmalider_status_pedido", "status"),
        ("farmalider_cod_filial", "codFilial"),
        ("farmalider_forma_pagamento", "formaPagamento"),
        ("farmalider_cupom", "cupom"),
        ("farmalider_pedido_web", "pedidoWeb"),
        ("farmalider_cancelamento", "cancelamento"),
        ("farmalider_entrega", "entrega"),
    ):
        order[target] = _text(capa.get(source))

    order["farmalider_status_pedido_nome"] = farmalider_order_status_name(
        capa.get("status")
    )
    order["farmalider_forma_pagamento_nome"] = farmalider_payment_method_name(
        capa.get("formaPagamento")
    )
    order["status_confirmacao"] = (
        "CANCELADO_API" if is_order_cancelled(order) else "CONFIRMADO_API"
    )
    return order, canonical_items


def _empty_order(contact: dict[str, Any], captured_at: str) -> dict[str, str]:
    from analytics import ORDER_COLUMNS, get_fields, get_phone_and_urn, normalize_cpf, normalize_order_source, normalize_value

    fields = get_fields(contact)
    order = {field: "" for field in ORDER_COLUMNS}
    uuid = normalize_value(contact.get("uuid")).strip()
    phone, _ = get_phone_and_urn(contact, fields)
    raw = normalize_order_source(fields.get("ultimo_pedido"))
    order.update({
        "contact_uuid": uuid, "telefone": phone,
        "cliente": normalize_value(fields.get("nome") or contact.get("name")).strip(),
        "cpf": normalize_value(fields.get("cpf")).strip(), "cpf_normalizado": normalize_cpf(fields.get("cpf")),
        "pedido_chave": hashlib.sha256(f"{uuid}|{raw}".encode()).hexdigest()[:32],
        "ultimo_pedido_raw": raw, "capturado_em": captured_at,
        "weni_modified_on": normalize_value(contact.get("modified_on")).strip(),
        "origem_pedido": "FARMALIDER_CLIENTE_ULTIMO_PEDIDO",
    })
    return order


def _ultimo_pedido_locator_id(fields: dict[str, Any]) -> str:
    """Extract only an order ID from ultimo_pedido; never trust it as order data."""
    raw: Any = fields.get("ultimo_pedido")
    if isinstance(raw, dict) and "value" in raw:
        raw = raw.get("value")

    payload: Any = raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return ""
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return ""

    if not isinstance(payload, dict):
        return ""
    return _positive_id(
        payload.get("pedido_id")
        or payload.get("pedidoId")
        or payload.get("codigo")
        or payload.get("codPedido")
        or payload.get("id")
    )


def resolve_contact_order(
    contact: dict[str, Any], *, farm_client: Any, captured_at: str,
    linked_cliente_id: str = "", cliente_response: dict[str, Any] | None = None,
    pedido_responses_by_id: dict[str, dict[str, Any] | None] | None = None,
) -> tuple[dict[str, str] | None, list[dict[str, str]]]:
    """
    Resolve o pedido usando a FarmaLíder como fonte de verdade.

    Ordem de descoberta:
      1. CPF -> GET cliente/cpf -> ultimoPedido + itens;
      2. campo Weni pedido_id, quando o GET por CPF não puder ser usado;
      3. ultimo_pedido, somente como último localizador de pedido.

    pedido_id e ultimo_pedido nunca substituem os dados oficiais retornados por
    GET pedido/{id}. Se a API não estiver disponível, os campos pedido_* não
    são reconstruídos a partir do snapshot legado.
    """
    from analytics import get_fields, is_valid_cpf, normalize_cpf
    from farmalider_client import FarmaliderAuthError, FarmaliderError

    fields = get_fields(contact)
    cpf = normalize_cpf(fields.get("cpf"))
    linked_id = _positive_id(linked_cliente_id)
    current_pedido_id = _positive_id(fields.get("pedido_id"))
    ultimo_pedido_id = _ultimo_pedido_locator_id(fields)

    if farm_client is None:
        return None, []

    def fetch_pedido(order_id: str) -> dict[str, Any] | None:
        if not order_id:
            return None
        if pedido_responses_by_id is not None and order_id in pedido_responses_by_id:
            return pedido_responses_by_id[order_id]
        response = farm_client.get_pedido(order_id)
        if pedido_responses_by_id is not None:
            pedido_responses_by_id[order_id] = response
        return response

    def resolve_locator(
        order_id: str,
        source: str,
        *,
        expected_cliente_id: str = "",
    ) -> tuple[dict[str, str] | None, list[dict[str, str]]]:
        if not order_id:
            return None, []
        try:
            response = fetch_pedido(order_id)
        except FarmaliderAuthError:
            raise
        except FarmaliderError:
            return None, []
        if not isinstance(response, dict):
            return None, []

        order = _empty_order(contact, captured_at)
        order["pedido_id"] = order_id
        order["farmalider_cliente_id"] = expected_cliente_id
        order["origem_pedido"] = source
        confirmed_order, confirmed_items = apply_pedido_api_confirmation(
            order,
            [],
            response,
            linked_cliente_id=expected_cliente_id,
            confirmed_at=captured_at,
            allow_locator_without_customer=not bool(expected_cliente_id),
        )
        if (
            confirmed_order.get("status_validacao") == "OK"
            and confirmed_items
        ):
            return confirmed_order, confirmed_items
        return confirmed_order, confirmed_items

    def resolve_weni_locators(
        *,
        expected_cliente_id: str = "",
    ) -> tuple[dict[str, str] | None, list[dict[str, str]]]:
        # pedido_id é um campo do próprio NexoFlow e tem precedência.
        # ultimo_pedido vem de outra integração e é deliberadamente o último
        # recurso para descobrir um ID que depois será validado via GET pedido.
        tried: set[str] = set()
        for order_id, source in (
            (current_pedido_id, "FARMALIDER_PEDIDO_ID_WENI"),
            (ultimo_pedido_id, "FARMALIDER_ULTIMO_PEDIDO_LOCATOR"),
        ):
            if not order_id or order_id in tried:
                continue
            tried.add(order_id)
            resolved_order, resolved_items = resolve_locator(
                order_id,
                source,
                expected_cliente_id=expected_cliente_id,
            )
            if (
                resolved_order is not None
                and resolved_order.get("status_validacao") == "OK"
                and resolved_items
            ):
                return resolved_order, resolved_items
        return None, []

    # Sem CPF válido, ainda podemos revalidar um pedido que já esteja
    # associado ao contato por pedido_id e, por último, por ultimo_pedido.
    if not cpf or not is_valid_cpf(cpf):
        return resolve_weni_locators(expected_cliente_id=linked_id)

    try:
        payload = (
            cliente_response
            if cliente_response is not None
            else farm_client.get_cliente_by_cpf(cpf)
        )
    except FarmaliderAuthError:
        raise
    except FarmaliderError:
        return resolve_weni_locators(expected_cliente_id=linked_id)

    if payload is None:
        return resolve_weni_locators(expected_cliente_id=linked_id)

    status, confirmed_cliente_id, _ = cliente_link_status(cpf, payload)
    if status != "CPF_CONFIRMADO":
        # Resposta concreta com CPF divergente/cliente inválido é falha dura:
        # não tentamos contornar uma inconsistência de identidade.
        order = _empty_order(contact, captured_at)
        return _failure(
            order, [], status,
            "Cliente não confirmado pela consulta oficial de CPF.",
        )

    if linked_id and linked_id != confirmed_cliente_id:
        order = _empty_order(contact, captured_at)
        return _failure(
            order, [], "CLIENTE_ID_DIVERGENTE_API",
            "Vínculo do cliente divergente da consulta oficial.",
        )
    linked_id = confirmed_cliente_id

    latest = payload.get("ultimoPedido") if isinstance(payload, dict) else None
    pedido_id = _positive_id(latest.get("id")) if isinstance(latest, dict) else ""
    if not pedido_id:
        return resolve_weni_locators(expected_cliente_id=linked_id)

    latest_owner = (
        _positive_id(latest.get("codCliente"))
        if "codCliente" in latest
        else linked_id
    )
    if latest_owner != linked_id:
        order = _empty_order(contact, captured_at)
        return _failure(
            order, [], "PEDIDO_CLIENTE_DIVERGENTE_API",
            "Último pedido pertence a outro cliente.",
        )

    # O GET por CPF já é suficiente para montar o snapshot completo.
    fallback_order = _empty_order(contact, captured_at)
    fallback_order["pedido_id"] = pedido_id
    fallback_order["farmalider_cliente_id"] = linked_id
    fallback_order["origem_pedido"] = "FARMALIDER_CLIENTE_CPF"
    fallback_response = _pedido_from_cliente_payload(payload)
    if fallback_response is not None:
        fallback_order, fallback_items = apply_pedido_api_confirmation(
            fallback_order,
            [],
            fallback_response,
            linked_cliente_id=linked_id,
            confirmed_at=captured_at,
        )
    else:
        fallback_items = []

    # GET pedido/{codigo} é o snapshot final preferencial do mesmo pedido.
    try:
        response = fetch_pedido(pedido_id)
    except FarmaliderAuthError:
        raise
    except FarmaliderError:
        return fallback_order, fallback_items

    if isinstance(response, dict):
        order = _empty_order(contact, captured_at)
        order["pedido_id"] = pedido_id
        order["farmalider_cliente_id"] = linked_id
        order["origem_pedido"] = "FARMALIDER_PEDIDO_API"
        confirmed_order, confirmed_items = apply_pedido_api_confirmation(
            order,
            [],
            response,
            linked_cliente_id=linked_id,
            confirmed_at=captured_at,
        )
        if (
            confirmed_order.get("status_validacao") == "OK"
            and confirmed_items
        ):
            return confirmed_order, confirmed_items
        # Resposta concreta inconsistente do endpoint de pedido é falha dura.
        return confirmed_order, confirmed_items

    return fallback_order, fallback_items

# NexoFlow 1.0
