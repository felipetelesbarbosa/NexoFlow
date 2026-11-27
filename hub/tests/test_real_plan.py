"""Planejadores compartilham regras Windows, com fontes de fixture e zero rede."""

import os
import sys
import unittest
from datetime import UTC, datetime
from unittest.mock import patch

import synthetic_settings
from nexoflow_hub.real_plan import (
    bounded,
    collect_history,
    recompra_plan,
    sales_plan,
    update_plan,
)
from nexoflow_hub.real_read_transport import ProbePending

from order_history import HistoryQuery

NOW = datetime(2026, 11, 27, 12, tzinfo=UTC)
UID = "00000000-0000-4000-8000-000000000001"


def order(id=1, segment="FARMA"):
    return {
        "capa": {
            "id": id,
            "segmento": segment,
            "codCliente": 1,
            "emissao": "2026-11-07T10:00:00-03:00",
            "status": 2,
            "formaPagamento": 3,
            "frete": "5.00",
        },
        "itens": [
            {
                "id": 10,
                "codPedido": id,
                "codProduto": 15,
                "descricao": "Produto sintético",
                "quantidade": 2,
                "valor": "7.25",
                "total": "14.50",
                "desconto": 0,
            }
        ],
    }


class History:
    def __init__(self, second=None, total=2):
        self.second = second or order(2)
        self.total = total

    def get_pedidos_history(self, query, page):
        return {
            "pedidos": [order(1) if page == 1 else self.second],
            "pagina": page,
            "limite": query.limit,
            "totalRegistros": self.total,
            "totalPaginas": self.total,
        }


class Rules(unittest.TestCase):
    def test_history_all_pages_and_financial_amounts(self):
        r, _ = collect_history(
            History(),
            HistoryQuery("FARMA", "2026-11-07", "2026-11-09", 1),
            NOW,
            max_pages=2,
        )
        p = sales_plan(r)
        self.assertEqual(p["pedidos_validos"], 2)
        self.assertEqual(p["receita_produtos_centavos"], 2900)
        self.assertEqual(p["frete_centavos"], 1000)
        self.assertEqual(p["faturamento_centavos"], 3900)
        self.assertEqual(p["atribuicao_comercial"], "pendente")
        self.assertFalse(p["aplicado"])

    def test_reject_duplicate_or_cross_segment_and_truncated_period(self):
        query = HistoryQuery("FARMA", "2026-11-07", "2026-11-09", 1)
        for client, maximum in [
            (History(second=order(1)), 2),
            (History(second=order(2, "PET")), 2),
            (History(), 1),
        ]:
            with self.assertRaises(ProbePending):
                collect_history(client, query, NOW, max_pages=maximum)

    def test_bounds_fail_closed(self):
        self.assertEqual(bounded(iter([1, 2]), 2), [1, 2])
        with self.assertRaises(ProbePending):
            bounded(iter([1, 2, 3]), 2)

    @patch.dict(sys.modules, {"secrets_config": synthetic_settings})
    @patch.dict(os.environ, {"NEXOFLOW_PERFIL": "FARMA"})
    def test_reserved_update_uses_real_rule_without_mutations(self):
        from nexoflow_hub.real_plan import DirectorySnapshot

        import weni_update as wu
        from farmalider_customers import CustomerDirectory
        from reservas_farma import Reservas

        class Weni:
            def list_fields(self):
                return [
                    {"key": k, "value_type": "text"}
                    for k in (
                        wu.REQUIRED_MULTICHANNEL_FIELDS | wu.REQUIRED_ORDER_FIELDS
                    )
                ]

            def list_groups(self, *args, **kwargs):
                return [
                    {"uuid": "in", "name": wu.WENI_UPDATE_OPT_IN_GROUP},
                    {"uuid": "out", "name": wu.WENI_UPDATE_OPT_OUT_GROUP},
                ]

            def list_ctwa_events(self, **kwargs):
                return []

        weni = Weni()
        contact = {
            "uuid": UID,
            "name": "Contato sintético",
            "urns": [],
            "fields": {"opt_in_lgpd": "ativo", "marketing_opt_in": ""},
            "groups": [{"uuid": "out", "name": wu.WENI_UPDATE_OPT_OUT_GROUP}],
        }
        farm = DirectorySnapshot(CustomerDirectory([], segment="FARMA"), {})
        r = update_plan(
            weni,
            farm,
            [contact],
            [],
            weni,
            {},
            Reservas("synthetic", frozenset({UID})),
            NOW,
        )
        self.assertEqual(r["reservas_adiadas"], 1)
        self.assertEqual(r["grupos_propostos"], 0)
        self.assertFalse(r["aplicado"])

    @patch.dict(sys.modules, {"secrets_config": synthetic_settings})
    @patch.dict(os.environ, {"NEXOFLOW_PERFIL": "FARMA"})
    def test_reserved_recompra_uses_shared_review(self):
        from nexoflow_hub.real_plan import DirectorySnapshot

        import recompra as rc
        from farmalider_customers import CustomerDirectory
        from reservas_farma import Reservas

        res = Reservas("synthetic", frozenset({UID}))
        structure = {
            "segment": "FARMA",
            "group_uuid": "g",
            "opt_out_uuid": "out",
            "event_uuid": "event",
            "event_signature": "fixture",
            "delivery_hour": -1,
            "errors": [],
        }
        contact = {
            "uuid": UID,
            "name": "Contato sintético",
            "urns": [],
            "fields": {"marketing_opt_in": "recusado"},
            "groups": [
                {"uuid": "g", "name": rc.GROUP},
                {"uuid": "out", "name": rc.OPT_OUT},
            ],
        }
        farm = DirectorySnapshot(CustomerDirectory([], segment="FARMA"), {})
        with (
            patch.object(rc, "inspect_structure", return_value=structure),
            patch("reservas_farma.carregar", return_value=res),
        ):
            result = recompra_plan(
                object(), farm, [contact], {"schema": 1, "contacts": {}}, res, NOW
            )
        self.assertEqual(result["reservas_adiadas"], 1)
        self.assertEqual(result["remocoes_propostas"], 0)
        self.assertFalse(result["aplicado"])
