"""Contrato interno normalizado. Não descreve uma rota histórica da FarmaLíder."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from business_identity import cpf_checksum_valid
from business_recompra import DAYS, refused_normalized, timing
from pedido_utils import (
    BUSINESS_TIMEZONE,
    is_order_sale,
    normalize_farmalider_payment_code,
)
from product_scope import is_animal_product


@dataclass(frozen=True)
class Item:
    code: str
    name: str
    quantity: Decimal
    total: Decimal


@dataclass(frozen=True)
class OrderEvidence:
    segment: str | None
    order_id: str
    customer_id: str
    owner_id: str
    cpf: str
    contact_cpf: str
    customer_name: str
    contact_name: str
    customer_phone: str
    contact_phone: str
    date: datetime | None
    status: int
    payment: int
    freight: Decimal
    billed: Decimal
    items: tuple[Item, ...] | None
    confirmed: bool = False
    identity_matches: int = 1
    refusal_fields: dict[str, str] = field(default_factory=dict)
    opt_out: bool = False


def normalized(value):
    return " ".join(
        "".join(
            c
            for c in unicodedata.normalize("NFKD", str(value))
            if not unicodedata.combining(c)
        )
        .casefold()
        .split()
    )


def digits(value):
    return "".join(c for c in str(value) if c.isascii() and c.isdigit())


def cpf(value):
    value = digits(value)
    candidate = value.zfill(11)
    return candidate if cpf_checksum_valid(candidate) else value


def local_phone(value):
    number = digits(value)
    if number.startswith("55") and len(number) in {12, 13}:
        number = number[2:]
    return number[2:] if len(number) in {10, 11} else ""


def evaluate_order(order: OrderEvidence | None, segment: str, now: datetime):
    def decision(state, reason):
        return {"estado": state, "motivo": reason, "venda": False, "recompra": False}

    if segment not in DAYS:
        raise ValueError("SEGMENTO_INVALIDO")
    if order is None:
        return decision("ignorado", "SEM_PEDIDO")
    if not order.confirmed:
        return decision("pendente", "FONTE_NAO_CONFIRMADA")
    if order.segment != segment:
        return decision("ignorado", "SEGMENTO_NAO_COMPROVADO")
    if (
        not order.order_id
        or not order.customer_id
        or order.owner_id != order.customer_id
        or order.identity_matches != 1
    ):
        return decision("pendente", "IDENTIDADE_NAO_COMPROVADA")
    if any(
        c not in "0123456789.- \t\r\n" for c in str(order.cpf) + str(order.contact_cpf)
    ):
        return decision("pendente", "CPF_MALFORMADO")
    source_cpf, target_cpf = cpf(order.cpf), cpf(order.contact_cpf)
    if (
        not source_cpf
        or not target_cpf
        or source_cpf != target_cpf
        or set(source_cpf) == {"0"}
    ):
        return decision("pendente", "CPF_NAO_COMPROVADO")
    if not cpf_checksum_valid(source_cpf):
        left, right = (
            "".join(
                c if c.isalnum() else " " for c in normalized(order.customer_name)
            ).split(),
            "".join(
                c if c.isalnum() else " " for c in normalized(order.contact_name)
            ).split(),
        )
        names = bool(left and right and left[0] == right[0])
        phone = local_phone(order.customer_phone)
        if not names and not (phone and phone == local_phone(order.contact_phone)):
            return decision("pendente", "IDENTIDADE_INDEPENDENTE_AUSENTE")
    if (
        order.date is None
        or order.date.tzinfo is None
        or now.tzinfo is None
        or order.date > now
    ):
        return decision("pendente", "DATA_NAO_COMPROVADA")
    if order.items is None:
        return decision("pendente", "ITENS_AUSENTES")
    if not order.items:
        return decision("ignorado", "CANCELADO_SEM_ITENS")
    official = {
        "farmalider_status_pedido": order.status,
        "farmalider_forma_pagamento": order.payment,
    }
    if not is_order_sale(official):
        return decision("ignorado", "CANCELADO_OU_STATUS_INVALIDO")
    if normalize_farmalider_payment_code(order.payment) not in {
        str(i) for i in range(1, 7)
    }:
        return decision("pendente", "PAGAMENTO_NAO_COMPROVADO")
    amounts = [
        order.freight,
        order.billed,
        *(i.total for i in order.items),
        *(i.quantity for i in order.items),
    ]
    if any(not x.is_finite() or x < 0 for x in amounts) or any(
        i.quantity <= 0 for i in order.items
    ):
        return decision("pendente", "VALORES_INVALIDOS")
    shipping = [i for i in order.items if i.code == "0" and not i.name.strip()]
    if shipping and sum((i.total for i in shipping), Decimal(0)) != order.freight:
        return decision("pendente", "FRETE_NAO_COMPROVADO")
    products = [i for i in order.items if i not in shipping]
    if not products:
        return decision("pendente", "PRODUTOS_AUSENTES")
    eligible = (
        products
        if segment == "PET"
        else [
            i
            for i in products
            if not is_animal_product({"produto_nome": i.name, "produto_codigo": i.code})
        ]
    )
    clock = timing(
        order.date.astimezone(BUSINESS_TIMEZONE),
        now.astimezone(BUSINESS_TIMEZONE),
        DAYS[segment],
    )
    blocked = order.opt_out or refused_normalized(
        {k: normalized(v) for k, v in order.refusal_fields.items()}, segment
    )
    value = sum((i.total for i in products), Decimal(0))
    return {
        "estado": "validado",
        "venda": True,
        "produtos": str(value.quantize(Decimal("0.01"))),
        "frete": str(order.freight.quantize(Decimal("0.01"))),
        "faturamento": str(order.billed.quantize(Decimal("0.01"))),
        "alerta_total_divergente": value + order.freight != order.billed,
        "dias_recompra": DAYS[segment],
        "evento": clock["event_at"],
        "recompra": bool(eligible)
        and clock["due_today"]
        and clock["scheduled_future"]
        and not blocked,
        "bloqueio_marketing": blocked,
        "maioridade_exigida": segment == "FARMA",
        "venda_atribuida": False,
        "cobertura_historica": "nao_comprovada",
    }
