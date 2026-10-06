from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from analytics import normalize_cpf, normalize_value, parse_date, parse_time


def cliente_link_status(
    weni_cpf: str,
    api_cliente: dict[str, Any] | None,
) -> tuple[str, str, str]:
    """
    Retorna: status, cliente_id, cliente_nome.
    """
    normalized_weni = normalize_cpf(weni_cpf)

    if not normalized_weni:
        return "CPF_NAO_INFORMADO", "", ""

    if api_cliente is None:
        return "CPF_NAO_ENCONTRADO", "", ""

    api_cpf = normalize_cpf(api_cliente.get("cpf"), pad_to_11=True)
    cliente_id = normalize_value(api_cliente.get("id")).strip()
    cliente_nome = normalize_value(api_cliente.get("nome")).strip()

    if api_cpf and api_cpf != normalized_weni:
        return "CPF_DIVERGENTE_API", cliente_id, cliente_nome

    return "CPF_CONFIRMADO", cliente_id, cliente_nome


def _decimal(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(value).replace(",", "."))
    except InvalidOperation:
        return Decimal("0")


def apply_pedido_api_confirmation(
    order: dict[str, str],
    items: list[dict[str, str]],
    pedido_api: dict[str, Any] | None,
    *,
    linked_cliente_id: str,
    confirmed_at: str,
) -> tuple[dict[str, str], list[dict[str, str]]]:
    """
    Enriquecer o pedido Weni com a resposta oficial da FarmaLíder.
    Não inventa nome de produto nem total geral que a API não fornece.
    """
    if pedido_api is None:
        order["status_confirmacao"] = "PEDIDO_NAO_ENCONTRADO_API"
        return order, items

    capa = pedido_api.get("capa")
    api_items = pedido_api.get("itens")

    if not isinstance(capa, dict):
        order["status_confirmacao"] = "ERRO_RESPOSTA_PEDIDO_API"
        order["farmalider_erro"] = "Resposta sem objeto 'capa'."
        return order, items

    if not isinstance(api_items, list):
        api_items = []

    api_id = normalize_value(capa.get("id")).strip()
    requested_id = order.get("pedido_id", "").strip()

    if requested_id and api_id and requested_id != api_id:
        order["status_confirmacao"] = "PEDIDO_ID_DIVERGENTE_API"
        order["farmalider_erro"] = (
            f"pedido_id Weni={requested_id}; capa.id API={api_id}"
        )
        return order, items

    api_cliente_id = normalize_value(capa.get("codCliente")).strip()
    if (
        linked_cliente_id
        and api_cliente_id
        and linked_cliente_id != api_cliente_id
    ):
        order["status_confirmacao"] = "PEDIDO_CLIENTE_DIVERGENTE_API"
    elif linked_cliente_id:
        order["status_confirmacao"] = "CONFIRMADO_API"
    else:
        order["status_confirmacao"] = "CONFIRMADO_API_SEM_CLIENTE_VINCULADO"

    order["origem_pedido"] = "WENI_ULTIMO_PEDIDO+FARMALIDER_API"
    order["farmalider_public_id"] = normalize_value(capa.get("publicId"))
    order["farmalider_emissao"] = normalize_value(capa.get("emissao"))
    order["farmalider_status_pedido"] = normalize_value(capa.get("status"))
    order["farmalider_cod_filial"] = normalize_value(capa.get("codFilial"))
    order["farmalider_cod_cliente"] = api_cliente_id
    order["farmalider_forma_pagamento"] = normalize_value(
        capa.get("formaPagamento")
    )
    order["farmalider_cupom"] = normalize_value(capa.get("cupom"))
    order["farmalider_frete"] = normalize_value(capa.get("frete"))
    order["farmalider_pedido_web"] = normalize_value(capa.get("pedidoWeb"))
    order["farmalider_cancelamento"] = normalize_value(
        capa.get("cancelamento")
    )
    order["farmalider_entrega"] = normalize_value(capa.get("entrega"))
    order["farmalider_confirmado_em"] = confirmed_at
    order["farmalider_erro"] = ""

    # A emissão da API é a data oficial do pedido quando disponível.
    emissao = order["farmalider_emissao"].strip()
    if emissao and parse_date(emissao):
        order["data_hora"] = emissao
        order["data"] = parse_date(emissao)
        order["hora"] = parse_time(emissao)
        for item in items:
            item["data_hora"] = emissao
            item["data"] = order["data"]
            item["hora"] = order["hora"]

    api_total = Decimal("0")
    api_qty = Decimal("0")
    for item in api_items:
        if not isinstance(item, dict):
            continue
        api_total += _decimal(item.get("total"))
        api_qty += _decimal(item.get("quantidade"))

    order["valor_total_api_itens"] = f"{api_total:.2f}"
    if api_qty == api_qty.to_integral_value():
        order["quantidade_itens_api"] = str(int(api_qty))
    else:
        order["quantidade_itens_api"] = format(api_qty.normalize(), "f")

    return order, items
