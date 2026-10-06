from __future__ import annotations

import hashlib
from decimal import Decimal, InvalidOperation
from typing import Any

from pedido_utils import business_order_datetime, farmalider_order_status_name, is_order_cancelled


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
    """The API now puts product names in codProduto; numeric values stay legacy codes."""
    value = api_item.get("codProduto")
    if value is not None and (isinstance(value, bool) or not isinstance(value, (int, str))):
        raise ValueError("Produto da API deve ser um código inteiro ou nome em texto.")
    text = _text(value)
    is_code = isinstance(value, int) or (text.isascii() and text.isdigit())
    code = text if is_code else ""
    supplied_name = text if text and not is_code else ""
    name = ""
    for field in ("nome", "descricao"):
        description = api_item.get(field)
        if description is not None and not isinstance(description, str):
            raise ValueError(f"{field} do produto deve ser texto.")
        if not name and description is not None:
            name = description.strip()
    return code, name or supplied_name


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
    confirmed_at: str,
) -> tuple[dict[str, str], list[dict[str, str]]]:
    """Replace financial details by validated API items; retain explicit provenance."""
    from analytics import _item_key

    order = dict(order)
    items = [dict(item) for item in items]
    if pedido_api is None:
        return _failure(order, items, "PEDIDO_NAO_ENCONTRADO_API", "Pedido não encontrado na API.")
    if not isinstance(pedido_api, dict) or not isinstance(pedido_api.get("capa"), dict):
        return _failure(order, items, "ERRO_RESPOSTA_PEDIDO_API", "Resposta sem objeto capa.")
    capa = pedido_api["capa"]
    api_id, requested_id = _positive_id(capa.get("id")), _positive_id(order.get("pedido_id"))
    if not api_id or not requested_id:
        return _failure(order, items, "PEDIDO_ID_INVALIDO_API", "Identidade do pedido ausente ou inválida.")
    if api_id != requested_id:
        return _failure(order, items, "PEDIDO_ID_DIVERGENTE_API", "Identidade do pedido divergente.")
    api_cliente_id, linked_id = _positive_id(capa.get("codCliente")), _positive_id(linked_cliente_id)
    if not api_cliente_id or not linked_id:
        return _failure(order, items, "PEDIDO_CLIENTE_NAO_VERIFICADO_API", "Proprietário do pedido não verificado.")
    if api_cliente_id != linked_id:
        return _failure(order, items, "PEDIDO_CLIENTE_DIVERGENTE_API", "Proprietário do pedido divergente.")
    emitted = business_order_datetime(capa.get("emissao"))
    if emitted is None:
        return _failure(order, items, "PEDIDO_DATA_INVALIDA_API", "Emissão do pedido ausente ou inválida.")
    api_items = pedido_api.get("itens")
    if not isinstance(api_items, list) or not api_items:
        return _failure(order, items, "ERRO_ITENS_PEDIDO_API", "Lista de itens ausente ou vazia.")

    api_total, api_qty = Decimal("0"), Decimal("0")
    canonical_items: list[dict[str, str]] = []
    key = f"FARMALIDER:{api_id}"
    date_time = emitted.isoformat(timespec="seconds")
    date, hour = emitted.date().isoformat(), emitted.strftime("%H:%M:%S")
    try:
        for position, api_item in enumerate(api_items, 1):
            if not isinstance(api_item, dict):
                raise ValueError("Item da API não é um objeto.")
            if "codPedido" in api_item and _positive_id(api_item["codPedido"]) != api_id:
                return _failure(order, items, "ITEM_PEDIDO_DIVERGENTE_API", "Item pertence a outro pedido ou não possui identidade válida.")
            quantity = _decimal(api_item.get("quantidade"), "quantidade", positive=True)
            unit = _decimal(api_item.get("valor"), "valor unitário")
            total = _decimal(api_item.get("total"), "total do item")
            code, name = _api_product_identity(api_item)
            if not name:
                name = _matching_name(code, items, quantity, unit, total, api_items)
            if not code and not name:
                raise ValueError("Item sem código ou nome identificável.")
            canonical_items.append({
                "item_chave": _item_key(key, position), "pedido_chave": key,
                "pedido_id": api_id, "data_hora": date_time, "data": date, "hora": hour,
                "contact_uuid": order.get("contact_uuid", ""), "telefone": order.get("telefone", ""),
                "cliente": order.get("cliente", ""), "produto_ordem": str(position),
                "produto_codigo": code, "produto_nome": name,
                "quantidade": _quantity_text(quantity), "valor_unitario": f"{unit:.2f}",
                "valor_total": f"{total:.2f}", "capturado_em": confirmed_at,
            })
            api_total += total
            api_qty += quantity
        freight = _decimal(capa["frete"], "frete") if capa.get("frete") not in (None, "") else None
        official_total = None
        for field in ("valorTotal", "valorTotalPedido", "valorTotalCompra", "totalPedido", "totalGeral", "total"):
            if capa.get(field) not in (None, ""):
                official_total = _decimal(capa[field], "total geral")
                break
    except ValueError as exc:
        return _failure(order, items, "ERRO_ITENS_PEDIDO_API", str(exc))

    if official_total is not None:
        purchase_total, provenance = official_total, "TOTAL_GERAL_API"
    elif freight is not None:
        purchase_total, provenance = api_total + freight, "SOMA_ITENS_MAIS_FRETE_API"
    else:
        purchase_total, provenance = api_total, "SOMA_ITENS_API"
    # Canonical API snapshots already carry the original Weni comparison.
    # Comparing the refreshed API total to itself would erase that audit trail.
    canonical_api = "API" in order.get("valor_origem", "")
    previous_value = order.get("valor_total_weni", "") if canonical_api else order.get("valor_total_compra", "")
    previous_origin = order.get("origem_pedido", "")
    previous_total = None
    if previous_value and "WENI" in previous_origin:
        try:
            previous_total = _decimal(previous_value, "total Weni")
        except ValueError:
            pass
    difference = previous_total - purchase_total if previous_total is not None else Decimal("0")
    validation = "ATENÇÃO_TOTAL_DIVERGENTE" if abs(difference) > Decimal("0.01") else "OK"
    if provenance == "SOMA_ITENS_API":
        validation = "ATENCAO_TOTAL_PARCIAL"
    order.update({
        "pedido_id": api_id, "pedido_chave": key, "data_hora": date_time, "data": date, "hora": hour,
        "farmalider_cliente_id": linked_id, "farmalider_cod_cliente": api_cliente_id,
        "status_validacao": validation,
        "erro_parse": "", "farmalider_erro": "", "farmalider_confirmado_em": confirmed_at,
        "origem_pedido": "WENI_ULTIMO_PEDIDO+FARMALIDER_API" if "WENI" in previous_origin else "FARMALIDER_CLIENTE_ULTIMO_PEDIDO",
        "valor_total_compra": f"{purchase_total:.2f}", "valor_total_itens": f"{api_total:.2f}",
        "valor_total_api_itens": f"{api_total:.2f}", "quantidade_itens_api": _quantity_text(api_qty),
        "total_api": f"{official_total:.2f}" if official_total is not None else "",
        "quantidade_itens": _quantity_text(api_qty), "quantidade_produtos": str(len(canonical_items)),
        "diferenca_total": f"{purchase_total - api_total:.2f}", "valor_origem": provenance,
        "valor_total_weni": f"{previous_total:.2f}" if previous_total is not None else "",
        "diferenca_total_weni_api": f"{difference:.2f}" if previous_total is not None else "",
        "farmalider_frete": f"{freight:.2f}" if freight is not None else "",
    })
    for target, source in (
        ("farmalider_public_id", "publicId"), ("farmalider_emissao", "emissao"),
        ("farmalider_status_pedido", "status"), ("farmalider_cod_filial", "codFilial"),
        ("farmalider_forma_pagamento", "formaPagamento"), ("farmalider_cupom", "cupom"),
        ("farmalider_pedido_web", "pedidoWeb"), ("farmalider_cancelamento", "cancelamento"),
        ("farmalider_entrega", "entrega"),
    ):
        order[target] = _text(capa.get(source))
    order["farmalider_status_pedido_nome"] = farmalider_order_status_name(capa.get("status"))
    # Only the fresh API response determines cancellation, not an old snapshot.
    order["status_confirmacao"] = ""
    order["status_confirmacao"] = "CANCELADO_API" if is_order_cancelled(order) else "CONFIRMADO_API"
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


def resolve_contact_order(
    contact: dict[str, Any], *, farm_client: Any, captured_at: str,
    linked_cliente_id: str = "", cliente_response: dict[str, Any] | None = None,
) -> tuple[dict[str, str] | None, list[dict[str, str]]]:
    """Use populated ultimo_pedido first; only an empty field permits CPF fallback."""
    from analytics import get_fields, is_valid_cpf, normalize_cpf, normalize_order_source, parse_ultimo_pedido

    fields = get_fields(contact)
    raw = normalize_order_source(fields.get("ultimo_pedido"))
    order, items = parse_ultimo_pedido(contact, captured_at=captured_at)
    valid_weni = order is not None and not order.get("status_validacao", "").startswith("ERRO")
    if raw and not valid_weni:
        return order, items
    if raw and not _positive_id(order.get("pedido_id")):
        if order.get("pedido_id"):
            return _failure(order, items, "PEDIDO_ID_INVALIDO_WENI", "Identidade do pedido da Weni deve ser um inteiro positivo.")
        return order, items
    if raw:
        order["valor_origem"] = order.get("valor_origem") or "WENI"
        # Retain the official snapshot already saved for this same order, without
        # assigning an API confirmation merely because the raw JSON claims one.
        snapshot_contact = {**contact, "fields": {**fields, "ultimo_pedido": None}}
        snapshot, _ = parse_ultimo_pedido(snapshot_contact, captured_at=captured_at)
        retained_confirmation = (
            snapshot is not None
            and not snapshot.get("status_validacao", "").startswith("ERRO")
            and snapshot.get("status_confirmacao") in {"CONFIRMADO_API", "CANCELADO_API"}
            and all(order.get(key) == snapshot.get(key) for key in (
                "pedido_id", "data_hora", "valor_total_compra", "status_confirmacao",
                "farmalider_status_pedido", "farmalider_cancelamento",
            ))
        )
        if not retained_confirmation:
            order["status_confirmacao"] = "NAO_CONFIRMADO_API"
        return order, items
    if valid_weni:
        order["valor_origem"] = order.get("valor_origem") or "WENI"
        if farm_client is None:
            order["status_confirmacao"] = "NAO_CONFIRMADO_API"
            return order, items
    elif farm_client is None:
        return order, items

    cpf = normalize_cpf(fields.get("cpf"))
    linked_id = _positive_id(linked_cliente_id)
    requested_id = _positive_id((order or {}).get("pedido_id")) if valid_weni else ""
    fallback = not raw
    if not cpf:
        if valid_weni:
            order["status_confirmacao"] = "NAO_CONFIRMADO_API"
            return order, items
        return order, items
    if order is None:
        order = _empty_order(contact, captured_at)
    if cpf and not is_valid_cpf(cpf):
        return _failure(order, items, "CPF_INVALIDO", "CPF não permite verificar o proprietário do pedido.")
    if cpf:
        from farmalider_client import FarmaliderAuthError, FarmaliderError

        try:
            payload = cliente_response if cliente_response is not None else farm_client.get_cliente_by_cpf(cpf)
        except FarmaliderAuthError:
            raise
        except FarmaliderError:
            return _failure(order, items, "ERRO_API", "Falha na consulta oficial do cliente.")
        status, confirmed_cliente_id, _ = cliente_link_status(cpf, payload)
        if status != "CPF_CONFIRMADO":
            return _failure(order, items, status, "Cliente não confirmado pela consulta oficial de CPF.")
        if linked_id and linked_id != confirmed_cliente_id:
            return _failure(order, items, "CLIENTE_ID_DIVERGENTE_API", "Vínculo do cliente divergente da consulta oficial.")
        linked_id = confirmed_cliente_id
        if fallback:
            latest = payload.get("ultimoPedido") if isinstance(payload, dict) else None
            if not isinstance(latest, dict):
                return _failure(order, items, "ULTIMO_PEDIDO_NAO_INFORMADO_API", "Cliente não possui último pedido informado.")
            requested_id = _positive_id(latest.get("id"))
            if not requested_id:
                return _failure(order, items, "PEDIDO_ID_INVALIDO_API", "Último pedido possui identidade inválida.")
            latest_owner = _positive_id(latest.get("codCliente")) if "codCliente" in latest else linked_id
            if latest_owner != linked_id:
                return _failure(order, items, "PEDIDO_CLIENTE_DIVERGENTE_API", "Último pedido pertence a outro cliente.")
            if not valid_weni or _positive_id(order.get("pedido_id")) != requested_id:
                order = _empty_order(contact, captured_at)
                items = []
    if not linked_id:
        return _failure(order, items, "PEDIDO_CLIENTE_NAO_VERIFICADO_API", "Proprietário do pedido não verificado.")
    if not requested_id:
        return _failure(order, items, "PEDIDO_ID_INVALIDO_API", "Identidade do pedido ausente ou inválida.")
    order["pedido_id"] = requested_id
    order["farmalider_cliente_id"] = linked_id
    from farmalider_client import FarmaliderAuthError, FarmaliderError

    try:
        response = farm_client.get_pedido(requested_id)
    except FarmaliderAuthError:
        raise
    except FarmaliderError:
        return _failure(order, items, "ERRO_API", "Falha na consulta oficial do pedido.")
    return apply_pedido_api_confirmation(order, items, response, linked_cliente_id=linked_id, confirmed_at=captured_at)
