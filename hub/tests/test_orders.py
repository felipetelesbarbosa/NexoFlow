"""Variações de valores/evidências; decisões reais, sem espelhar fixtures."""

from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from nexoflow_hub.orders import Item, OrderEvidence, evaluate_order

from pedido_utils import BUSINESS_TIMEZONE, is_order_sale


@pytest.fixture
def order():
    return OrderEvidence(
        "FARMA",
        "o1",
        "c1",
        "c1",
        "52998224725",
        "52998224725",
        "Nome Sintético",
        "Nome Sintético",
        "",
        "",
        datetime(2026, 1, 1, 13, tzinfo=BUSINESS_TIMEZONE),
        2,
        5,
        Decimal("7.25"),
        Decimal("55.75"),
        (
            Item("i1", "Produto", Decimal(2), Decimal("48.50")),
            Item("0", "", Decimal(1), Decimal("7.25")),
        ),
        confirmed=True,
    )


def at_day(order, day=25):
    return order.date + timedelta(days=day, hours=-1)


def test_values_shipping_units_and_no_double_freight(order):
    out = evaluate_order(order, "FARMA", at_day(order))
    assert (
        out["produtos"] == "48.50"
        and out["frete"] == "7.25"
        and out["faturamento"] == "55.75"
    )
    assert not out["alerta_total_divergente"]
    divergent = evaluate_order(
        replace(order, billed=Decimal("54.00")), "FARMA", at_day(order)
    )
    assert divergent["faturamento"] == "54.00" and divergent["alerta_total_divergente"]


def test_source_confirmation_is_explicit_and_not_assumed(order):
    from dataclasses import fields

    without_proof = {
        f.name: getattr(order, f.name)
        for f in fields(OrderEvidence)
        if f.name != "confirmed"
    }
    unconfirmed = OrderEvidence(**without_proof)
    result = evaluate_order(unconfirmed, "FARMA", at_day(order))
    assert result["estado"] == "pendente" and result["venda"] is False


@pytest.mark.parametrize("status", [-2, -1, 0, 4, 1, 2, 3, 999])
def test_shared_windows_statuses(order, status):
    result = evaluate_order(replace(order, status=status), "FARMA", at_day(order))
    assert result["venda"] == is_order_sale(
        {
            "farmalider_status_pedido": status,
            "farmalider_forma_pagamento": order.payment,
        }
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("owner_id", "other"),
        ("identity_matches", 2),
        ("contact_cpf", "11144477735"),
        ("date", None),
        ("items", None),
        ("confirmed", False),
        ("freight", Decimal("NaN")),
    ],
)
def test_insufficient_evidence_never_becomes_confirmed_sale(order, field, value):
    result = evaluate_order(replace(order, **{field: value}), "FARMA", at_day(order))
    assert result["estado"] == "pendente" and not result["venda"]


def test_invalid_cpf_requires_independent_identity(order):
    invalid = replace(
        order,
        cpf="12345678901",
        contact_cpf="12345678901",
        customer_name="",
        contact_name="",
    )
    assert not evaluate_order(invalid, "FARMA", at_day(order))["venda"]
    phone = replace(
        invalid, customer_phone="+55 91 99900-0001", contact_phone="+55 11 99900-0001"
    )
    assert evaluate_order(phone, "FARMA", at_day(order))["venda"]
    assert not evaluate_order(
        replace(phone, contact_phone="+55 11 99900-0002"), "FARMA", at_day(order)
    )["venda"]


@pytest.mark.parametrize("segment,days", [("FARMA", 25), ("PET", 30)])
def test_marketing_recency_and_segment_product_scope(order, segment, days):
    current = replace(order, segment=segment)
    assert evaluate_order(current, segment, at_day(order, days))["recompra"]
    assert not evaluate_order(current, segment, at_day(order, days + 1))["recompra"]
    assert not evaluate_order(
        replace(current, opt_out=True, refusal_fields={"marketing_opt_in": "Sim"}),
        segment,
        at_day(order, days),
    )["recompra"]
    veterinary = replace(
        current, items=(Item("v1", "Ração para gatos", Decimal(1), Decimal("48.50")),)
    )
    assert evaluate_order(veterinary, segment, at_day(order, days))["recompra"] == (
        segment == "PET"
    )
