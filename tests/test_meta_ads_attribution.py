"""Regressões comerciais FARMA sem clientes ou credenciais reais."""

import json
import unittest
from datetime import UTC, date, datetime, timedelta

from meta_ads_attribution import (
    PAYLOAD_KEY,
    Conversation,
    Room,
    apply_attribution,
)


def moment(day, hour=10, minute=0, second=0):
    return datetime(2026, 11, day, hour, minute, second, tzinfo=UTC)


def facts():
    return {
        "Meta_Ads_Diario": [
            dict(
                conta_id="account",
                anuncio_id=ad,
                data=moment(day).date().isoformat(),
                fuso="America/Belem",
                segmento="FARMA",
                classificacao="FARMA",
                payload_api_json="{}",
            )
            for ad, day in (("a", 1), ("b", 2), ("c", 4))
        ]
    }


def event(ad, uid, at, *, conversation_id=None):
    return dict(
        segment="FARMA",
        event_id=ad + uid + at.isoformat(),
        contact_uuid=uid,
        contact_urn=f"whatsapp:{uid}",
        link_status="unique",
        conversation_id=conversation_id,
        ad_id=ad,
        date=at.isoformat(),
    )


def order(oid, owner, uid, at):
    return dict(
        pedido_id=oid,
        pedido_chave=f"FARMA:{oid}",
        status_confirmacao="CONFIRMADO_API",
        status_validacao="OK",
        farmalider_status_pedido="2",
        farmalider_forma_pagamento="1",
        farmalider_cliente_id=owner,
        contact_uuid=uid,
        farmalider_emissao=at.isoformat(),
    )


def historical(oid, owner, uid, day, value="19.50", state="valido"):
    return dict(
        pedido_id=oid,
        segmento="FARMA",
        vigente="Sim",
        cliente_id=owner,
        contato_weni=uid,
        data=day.isoformat(),
        faturamento=value,
        estado=state,
    )


def apply(
    tables, touches, orders, history, rooms, conversations, *, start="2020-01-01"
):
    return apply_attribution(
        tables,
        touches,
        orders,
        history,
        [
            dict(
                segmento="FARMA",
                vigente="Sim",
                inicio=start,
                fim="2026-11-30",
                extracao="extraida",
                pendencias="0",
            )
        ],
        rooms,
        date(2026, 11, 1),
        date(2026, 11, 19),
        moment(20),
        lambda urns: {urn: conversations[urn] for urn in urns},
    )


def audit(tables, position):
    return json.loads(tables["Meta_Ads_Diario"][position]["payload_api_json"])[
        PAYLOAD_KEY
    ]


class CommercialMetaTests(unittest.TestCase):
    def test_direct_beats_later_touch_and_duplicate_order_does_not_count_twice(self):
        tables = facts()
        original = "1f95f280-5b4c-42dd-9761-c6800ae8eabe"
        later = "1f95f280-5b4c-42dd-9761-c6800ae8eabf"
        purchase = moment(2, 11, 30)
        rooms = {"whatsapp:1": [Room(moment(2, 11), moment(2, 12))]}
        conversations = {
            "whatsapp:1": (
                Conversation(original, moment(1, 10, 0, 4), moment(2, 13), True),
                Conversation(later, moment(2, 12, 59), moment(3), False),
            )
        }
        touches = [event("a", "1", moment(1)), event("b", "1", moment(2, 10))]
        live = order("10", "77", "1", purchase)
        canonical = historical("10", "77", "1", purchase.date())
        summary = apply(
            tables, touches, [live, live], [canonical, canonical], rooms, conversations
        )
        self.assertEqual(summary["direto"], 1)
        self.assertEqual(summary["posterior"], 0)
        self.assertEqual(audit(tables, 0)["novos_clientes_anuncio"], 1)
        self.assertEqual(audit(tables, 0)["receita_conversa_anuncio"], "19.50")
        self.assertTrue(audit(tables, 0)["cobertura_comercial"])

    def test_other_conversation_uses_last_click_and_does_not_count_as_acquisition(self):
        tables = facts()
        purchase = moment(4, 12)
        rooms = {"whatsapp:1": [Room(moment(4, 11), moment(4, 13))]}
        conversations = {
            "whatsapp:1": (
                Conversation("a", moment(1, second=4), moment(1, 18), False),
                Conversation("b", moment(2, second=4), moment(2, 18), False),
                Conversation("c", moment(4), moment(4, 18), True),
            )
        }
        apply(
            tables,
            [event("a", "1", moment(1)), event("b", "1", moment(2))],
            [order("10", "77", "1", purchase)],
            [historical("10", "77", "1", purchase.date(), "82.40")],
            rooms,
            conversations,
        )
        self.assertEqual(audit(tables, 0)["pedidos_apos_conversa_7d"], 0)
        self.assertEqual(audit(tables, 1)["pedidos_apos_conversa_7d"], 1)
        self.assertEqual(audit(tables, 1)["receita_apos_conversa_7d"], "82.40")
        self.assertEqual(audit(tables, 1)["novos_clientes_anuncio"], 0)

    def test_first_purchase_uses_full_owner_history_and_incomplete_history_has_no_cac(
        self,
    ):
        purchase = moment(1, 12)
        rooms = {"whatsapp:1": [Room(moment(1, 11), moment(1, 13))]}
        conversations = {
            "whatsapp:1": (Conversation("a", moment(1, second=4), moment(1, 19), True),)
        }
        orders = [order("10", "77", "1", purchase)]
        history = [
            historical("03", "77", "other", date(2020, 4, 2)),
            historical("10", "77", "1", purchase.date()),
        ]
        for start, expected in [("2020-01-01", 0), ("2025-01-01", None)]:
            tables = facts()
            apply(
                tables,
                [event("a", "1", moment(1))],
                orders,
                history,
                rooms,
                conversations,
                start=start,
            )
            self.assertEqual(audit(tables, 0)["pedidos_conversa_anuncio"], 1)
            self.assertEqual(audit(tables, 0)["novos_clientes_anuncio"], expected)

    def test_tag_does_not_allocate_two_orders_in_the_same_unidentified_room(self):
        tables = facts()
        first, second = moment(1, 12), moment(1, 12, 30)
        rooms = {"whatsapp:1": [Room(moment(1, 11), moment(1, 13))]}
        conversations = {
            "whatsapp:1": (Conversation("a", moment(1, second=4), moment(1, 19), True),)
        }
        apply(
            tables,
            [event("a", "1", moment(1))],
            [order("1", "77", "1", first), order("2", "77", "1", second)],
            [
                historical("1", "77", "1", first.date()),
                historical("2", "77", "1", second.date()),
            ],
            rooms,
            conversations,
        )
        self.assertIsNone(audit(tables, 0)["pedidos_conversa_anuncio"])
        self.assertIsNone(audit(tables, 0)["pedidos_apos_conversa_7d"])
        self.assertIsNone(audit(tables, 0)["receita_conversa_anuncio"])
        self.assertFalse(audit(tables, 0)["cobertura_comercial"])

    def test_post_window_uses_conversation_opening_and_is_inclusive(self):
        for extra, expected in ((0, 1), (1, 0)):
            tables = facts()
            opening = moment(1, second=4)
            purchase = opening + timedelta(days=7, seconds=extra)
            rooms = {
                "whatsapp:1": [
                    Room(
                        purchase - timedelta(minutes=5), purchase + timedelta(minutes=5)
                    )
                ]
            }
            conversations = {
                "whatsapp:1": (
                    Conversation("a", opening, moment(1, 18), False),
                    Conversation(
                        "b",
                        purchase - timedelta(minutes=10),
                        purchase + timedelta(hours=1),
                        True,
                    ),
                )
            }
            apply(
                tables,
                [event("a", "1", moment(1))],
                [order("1", "77", "1", purchase)],
                [historical("1", "77", "1", purchase.date())],
                rooms,
                conversations,
            )
            self.assertEqual(audit(tables, 0)["pedidos_apos_conversa_7d"], expected)
