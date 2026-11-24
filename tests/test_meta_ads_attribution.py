"""Regressões comerciais FARMA sem clientes ou credenciais reais."""

import json
import os
import tempfile
import unittest
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from openpyxl import Workbook

from meta_ads_attribution import (
    FLOWS_SOURCE,
    PAYLOAD_KEY,
    Conversation,
    Room,
    apply_attribution,
    audit_conversations,
    load_conversations,
    optional_room_export,
)
from tests.test_delivery_spreadsheets import ROOM_HEADERS


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


class ConversationAuditTests(unittest.TestCase):
    def setUp(self):
        self.conversations = {}
        self.events = []
        self.contacts = []
        self.coverage = [
            dict(
                segmento="FARMA",
                vigente="Sim",
                inicio="2026-11-01",
                fim="2026-11-15",
                extracao="extraida",
                pendencias="0",
                atualizado=moment(15, 9).isoformat(),
            )
        ]

    def add_conversation(self, ad, uid, owner, opening, *, human=True):
        urn = f"whatsapp:{uid}"
        conversation = Conversation(
            f"chat-{ad}-{uid}", opening, opening + timedelta(hours=1), human
        )
        self.events.append(event(ad, uid, opening))
        self.conversations.setdefault(urn, []).append(conversation)
        if owner:
            self.contacts.append(
                dict(
                    contact_uuid=uid,
                    farmalider_cliente_id=owner,
                    farmalider_cliente_status="CPF_CONFIRMADO",
                )
            )
        return conversation

    def run_audit(self, history=(), orders=(), raw=(), *, start=1, end=4, **kwargs):
        return audit_conversations(
            {
                "BI_Meta_Resultados": [
                    dict(
                        segmento="FARMA",
                        classificacao="FARMA",
                        data="2026-11-02",
                        anuncio_id=ad,
                        conversas_iniciadas_meta=count,
                        investimento_atribuivel="25",
                        moeda="BRL",
                    )
                    for ad, count in zip("abcd", "2111", strict=True)
                ]
            },
            self.events,
            self.contacts,
            orders,
            history,
            raw,
            self.coverage,
            self.conversations,
            None,
            date(2026, 11, start),
            date(2026, 11, end),
            moment(15),
            **kwargs,
        )

    def test_checks_each_conversation_and_deduplicates_purchases_across_channels(self):
        self.add_conversation("a", "1", "77", moment(1))
        self.add_conversation("b", "1", "77", moment(1, 14))
        self.add_conversation("c", "2", "88", moment(2))
        self.add_conversation("d", "3", None, moment(3))
        self.add_conversation("pet", "7", "22", moment(2))
        self.events[-1]["segment"] = "PET"
        self.events.append(self.events[0])
        self.events.append(event("no-opening", "missing", moment(2)))
        history = [
            historical("direct", "77", "1", moment(1).date(), "25"),
            historical("cross-channel", "77", "", moment(8).date(), "50"),
            historical("too-late", "77", "", moment(8).date(), "75"),
            historical("cancelled", "88", "2", moment(3).date(), state="cancelado"),
        ]
        orders = [order("direct", "77", "1", moment(1, 10, 30))]
        raw = [
            dict(
                segment="FARMA",
                id=oid,
                owner="77",
                record=json.dumps(
                    dict(
                        segment="FARMA",
                        id=oid,
                        owner="77",
                        state="valido",
                        date=at.isoformat(),
                        revenue_cents=cents,
                    )
                ),
            )
            for oid, at, cents in (
                ("cross-channel", moment(8, 14), 5000),
                ("too-late", moment(8, 14, 0, 1), 7500),
            )
        ]
        result = self.run_audit(history, orders, raw, failed_urns={"whatsapp:missing"})
        self.assertEqual(
            result["situacoes"],
            dict(
                com_pedido=2,
                sem_pedido_apos_7d=1,
                em_acompanhamento=0,
                pendente_de_conferencia=1,
            ),
        )
        self.assertEqual(result["conversas_weni_identificadas"], 4)
        self.assertEqual(result["diferenca_meta_weni"], "1")
        self.assertEqual(result["eventos_sem_conversa_comprovada"], 1)
        self.assertEqual(result["eventos_com_falha_na_leitura_weni"], 1)
        self.assertEqual(result["pedidos_comprovados_distintos"], 2)
        self.assertEqual(result["pedidos_na_conversa_original"], 1)
        self.assertEqual(result["pedidos_apos_conversa_original_7d"], 1)
        self.assertEqual(result["pedidos_atribuidos_fora_do_periodo"], 1)
        self.assertEqual(result["receita_atribuida_comprovada"], "75")
        self.assertEqual(result["roas_sobre_receita_comprovada"], "0.25")
        self.assertEqual(result["roas_na_conversa_original"], "0.25")
        self.assertEqual(result["cac_sobre_clientes_comprovados"], "100")

    def test_does_not_report_no_purchase_when_coverage_or_time_is_missing(self):
        self.add_conversation("a", "1", "77", moment(1))
        self.add_conversation("b", "2", "88", moment(9))
        history = [historical("sem-hora", "77", "1", moment(2).date())]
        result = self.run_audit(history, end=10)
        self.assertEqual(result["situacoes"]["em_acompanhamento"], 1)
        self.assertEqual(result["situacoes"]["pendente_de_conferencia"], 1)
        self.assertEqual(
            result["pendencias_por_motivo"], {"PEDIDO_SEM_EMISSAO_CONCILIADA": 1}
        )
        self.assertIsNone(result["roas_sobre_receita_comprovada"])
        self.coverage[0]["atualizado"] = moment(8, 9, 59).isoformat()
        result = self.run_audit(end=10)
        self.assertEqual(result["situacoes"]["sem_pedido_apos_7d"], 0)
        self.assertEqual(
            result["pendencias_por_motivo"], {"COBERTURA_DE_PEDIDOS_INCOMPLETA": 1}
        )

    def test_overlapping_conversations_share_order_but_each_is_checked(self):
        self.add_conversation("a", "1", "77", moment(1))
        self.add_conversation("b", "1", "77", moment(2))
        sale = historical("sale", "77", "1", moment(3).date(), "50")
        orders = [order("sale", "77", "1", moment(3))]
        result = self.run_audit([sale], orders)
        self.assertEqual(result["situacoes"]["com_pedido"], 2)
        self.assertEqual(result["pedidos_comprovados_distintos"], 1)
        self.assertEqual(result["receita_atribuida_comprovada"], "50")

    def test_cac_reselects_the_first_purchase_within_the_period(self):
        self.add_conversation("a", "1", "77", moment(2))
        history = [
            historical("previous", "77", "1", moment(1).date()),
            historical("attributed", "77", "1", moment(2).date()),
        ]
        orders = [
            order("previous", "77", "1", moment(1)),
            order("attributed", "77", "1", moment(2, 10, 30)),
        ]
        wide = self.run_audit(history, orders)
        self.assertEqual(wide["clientes_com_primeira_compra_atribuida_comprovada"], 0)
        narrow = self.run_audit(history, orders, start=2)
        self.assertEqual(narrow["clientes_com_primeira_compra_atribuida_comprovada"], 1)
        self.assertEqual(narrow["cac_sobre_clientes_comprovados"], "100")

    def test_official_directory_can_confirm_identity_without_a_prior_purchase(self):
        from farmalider_customers import CustomerDirectory

        self.add_conversation("a", "1", None, moment(1))
        cpf = "52998224725"
        directory = CustomerDirectory(
            [{"id": "77", "cpf": cpf, "nome": "Pessoa de teste"}]
        )
        weni = [dict(uuid="1", fields={"cpf": cpf})]
        result = self.run_audit(weni_contacts=weni, directory=directory)
        self.assertEqual(result["situacoes"]["sem_pedido_apos_7d"], 1)
        weni.append(dict(uuid="2", fields={"cpf": cpf}))
        result = self.run_audit(weni_contacts=weni, directory=directory)
        self.assertEqual(result["situacoes"]["sem_pedido_apos_7d"], 0)
        self.assertEqual(
            result["pendencias_por_motivo"], {"CLIENTE_OFICIAL_NAO_CONFIRMADO": 1}
        )

    def test_a_failed_contact_read_does_not_skip_other_contacts(self):
        with patch("meta_ads_attribution.ReadOnlyEvidenceClient") as client:
            client.return_value.get_org.return_value = dict(
                name="Delivery FarmaLíder",
                timezone="America/Belem",
                uuid="11111111-1111-4111-8111-111111111111",
            )
            client.return_value.list_conversation_classifications.side_effect = [
                ValueError(),
                [],
            ]
            conversations, failed = load_conversations(
                "test", {"a", "b"}, moment(1), moment(15)
            )
            self.assertEqual(failed, {"a"})
            self.assertEqual(conversations, {"b": ()})
            client.return_value.close.assert_called_once()


class CommercialMetaTests(unittest.TestCase):
    def test_auto_discovers_download_and_reads_dates_from_finalized_rooms(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            downloads = root / "Downloads"
            downloads.mkdir()
            imports = root / "importacoes"
            imports.mkdir()
            book = Workbook()
            self.addCleanup(book.close)
            sheet = book.active
            sheet.title = "rooms"
            sheet.append(ROOM_HEADERS)
            sheet.append([
                "10000000-0000-4000-8000-000000000001", "Teste", "whatsapp:1",
                "2026-11-01 10:00:00", "2026-11-01 11:00:00", False,
                "['Pedido Finalizado']", "agent@example.test", "Delivery FarmaLíder", "",
            ])
            previous = imports / "Conversas_Delivery.xlsx"
            book.save(previous)
            sheet.append([
                "10000000-0000-4000-8000-000000000002", "Teste", "whatsapp:2",
                "2026-11-03 10:00:00", "2026-11-03 11:00:00", False,
                "['Pedido Finalizado']", "agent@example.test", "Delivery FarmaLíder", "",
            ])
            latest_valid = downloads / "Conversas_Delivery (1).xlsx"
            book.save(latest_valid)
            malformed = downloads / "Conversas_Delivery(2).xlsx"
            malformed.write_bytes(b"not an xlsx")
            for timestamp, path in enumerate((previous, latest_valid, malformed), 1_700_000_000):
                os.utime(path, (timestamp, timestamp))

            with patch.object(Path, "home", return_value=root):
                export, status = optional_room_export(
                    root,
                    {"inicio": "2026-10-01", "fim": "2026-10-31"},
                    date(2026, 11, 1),
                    date(2026, 11, 4),
                    moment(5),
                )

        self.assertEqual(status, "utilizado")
        start, end, rooms = export
        self.assertEqual((start, end), (date(2026, 11, 1), date(2026, 11, 3)))
        self.assertEqual(set(rooms), {"whatsapp:1", "whatsapp:2"})

    def test_flows_and_official_orders_attribute_without_an_export(self):
        tables = facts()
        direct = moment(1, 12)
        later = moment(4, 12)
        apply(
            tables,
            [event("a", "1", moment(1), conversation_id="11111111-1111-4111-8111-111111111111")],
            [order("10", "77", "1", direct), order("11", "77", "1", later)],
            [
                historical("10", "77", "1", direct.date(), "19.50"),
                historical("11", "77", "1", later.date(), "45.00"),
            ],
            None,
            {"whatsapp:1": (
                Conversation("11111111-1111-4111-8111-111111111111", moment(1), moment(1, 14), True),
                Conversation("later", moment(4, 11), moment(4, 13), True),
            )},
        )
        result = audit(tables, 0)
        self.assertEqual(result["origem_evidencia"], FLOWS_SOURCE)
        self.assertEqual(result["pedidos_conversa_anuncio"], 1)
        self.assertEqual(result["receita_conversa_anuncio"], "19.50")
        self.assertEqual(result["pedidos_apos_conversa_7d"], 1)
        self.assertEqual(result["receita_apos_conversa_7d"], "45.00")
        self.assertEqual(result["novos_clientes_anuncio"], 1)
        self.assertTrue(result["cobertura_comercial"])

    def test_flows_end_of_day_requires_actual_room_for_attribution(self):
        opened = moment(1, 21, 17)
        room = Room(moment(1, 21, 20), moment(1, 21, 47))
        day_end = moment(2, 2, 59, 59).replace(microsecond=999999)
        conversations = {"whatsapp:1": (Conversation("room", opened, day_end, True),)}
        for export, purchase, expected in (
            (None, moment(1, 22), None),
            ({"whatsapp:1": [room]}, moment(1, 21, 30), 1),
        ):
            with self.subTest(export=export is not None):
                tables = facts()
                apply(
                    tables,
                    [event("a", "1", opened)],
                    [order("10", "77", "1", purchase)],
                    [historical("10", "77", "1", purchase.date())],
                    export,
                    conversations,
                )
                result = audit(tables, 0)
                self.assertEqual(result["pedidos_conversa_anuncio"], expected)
                self.assertEqual(result["cobertura_comercial"], expected is not None)
                if export is None:
                    self.assertIsNone(result["receita_conversa_anuncio"])

    def test_partial_xlsx_counts_confirmed_sales_without_assuming_coverage(self):
        tables = facts()
        purchase = moment(1, 12)
        rooms = {"whatsapp:1": [Room(moment(1, 11), moment(1, 13))]}
        summary = apply(
            tables,
            [event("a", "1", moment(1)), event("a", "2", moment(1))],
            [order("10", "77", "1", purchase), order("11", "88", "2", purchase)],
            [
                historical("10", "77", "1", purchase.date()),
                historical("11", "88", "2", purchase.date()),
            ],
            rooms,
            {"whatsapp:1": (Conversation("a", moment(1), moment(1, 14), True),)},
        )
        result = audit(tables, 0)
        self.assertEqual(result["pedidos_conversa_anuncio"], 1)
        self.assertEqual(result["receita_conversa_anuncio"], "19.50")
        self.assertIsNone(result["pedidos_apos_conversa_7d"])
        self.assertFalse(result["cobertura_comercial"])
        self.assertEqual(summary["direto"], 1)
        self.assertEqual(summary["pedidos_pendentes_por_motivo"], {"SEM_ATENDIMENTO_COMPROVADO": 1})

    def test_flows_missing_human_or_unique_conversation_leaves_pending(self):
        purchase = moment(1, 12)
        for conversations in (
            (),
            (Conversation("bot", moment(1), moment(1, 14), False),),
            (
                Conversation("first", moment(1), moment(1, 14), True),
                Conversation("second", moment(1, 11), moment(1, 14), True),
            ),
        ):
            with self.subTest(conversations=len(conversations)):
                tables = facts()
                apply(
                    tables,
                    [event("a", "1", moment(1))],
                    [order("10", "77", "1", purchase)],
                    [historical("10", "77", "1", purchase.date())],
                    None,
                    {"whatsapp:1": conversations},
                )
                result = audit(tables, 0)
                self.assertIsNone(result["pedidos_conversa_anuncio"])
                self.assertIsNone(result["receita_conversa_anuncio"])
                self.assertFalse(result["cobertura_comercial"])

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
