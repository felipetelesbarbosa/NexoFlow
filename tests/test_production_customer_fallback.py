"""Regressões de produção, segregação e fallback sem APIs reais."""

import unittest
from contextlib import closing
from unittest.mock import patch

from farmalider_client import FarmaliderClient, FarmaliderError
from farmalider_customers import CustomerDirectory
from recompra_profiles import PetRecompraClient
from tests.test_farmalider_customers import CPF, customer_snapshot


class ProductionCustomerFallbackTests(unittest.TestCase):
    def test_legacy_hml_flag_never_selects_homologation(self):
        with closing(FarmaliderClient("synthetic", use_hml=True)) as farm:
            self.assertFalse(farm.use_hml)
            self.assertEqual(
                farm._delivery_path("clientes/FARMA"), "/api/Delivery/clientes/FARMA"
            )

    def test_pet_falls_back_once_per_cpf_when_bulk_fails(self):
        payload = customer_snapshot()
        payload["ultimoPedido"]["segmento"] = "PET"
        with closing(PetRecompraClient("synthetic")) as farm:
            with (
                patch.object(
                    farm,
                    "get_clientes_segmento",
                    side_effect=FarmaliderError("sintético"),
                ) as bulk,
                patch.object(farm, "_request_json", return_value=payload) as individual,
            ):
                self.assertEqual(farm.get_cliente_by_cpf(CPF)["ultimoPedido"]["id"], 8)
                farm.get_cliente_by_cpf(CPF)
                self.assertEqual(farm.get_pedido(8)["capa"]["id"], 8)
                self.assertEqual(bulk.call_count, 1)
                self.assertEqual(individual.call_count, 1)
                farm.reset_execution_reads()
                farm.get_cliente_by_cpf(CPF)
                self.assertEqual(bulk.call_count, 2)
                self.assertEqual(individual.call_count, 2)

    def test_wrong_or_unproven_segment_cannot_authorize_individual_customer(self):
        for client, wrong in ((FarmaliderClient, "PET"), (PetRecompraClient, "FARMA")):
            for marker in (wrong, ""):
                payload = customer_snapshot()
                payload["ultimoPedido"]["segmento"] = marker
                with closing(client("synthetic")) as farm:
                    with (
                        patch.object(farm, "get_clientes_segmento", return_value=[]),
                        patch.object(farm, "_request_json", return_value=payload),
                    ):
                        with self.assertRaises(FarmaliderError):
                            farm.get_cliente_by_cpf(CPF)

    def test_bulk_excludes_explicit_foreign_customer_even_with_matching_order(self):
        payload = customer_snapshot(segmento="PET")
        self.assertFalse(CustomerDirectory([payload], segment="FARMA").candidates(CPF))

    def test_bulk_timeout_is_longer_without_extending_individual_timeout(self):
        from contextlib import nullcontext
        from unittest.mock import Mock

        from farmalider_client import RequestPermit

        with closing(FarmaliderClient("synthetic")) as farm:
            response = Mock(status_code=200, headers={}, content=b"[]")
            response.json.return_value = []
            with (
                patch.object(farm.session, "get", return_value=response) as get,
                patch.object(
                    farm,
                    "_request_slot",
                    side_effect=lambda _: nullcontext(RequestPermit(0, 4)),
                ),
            ):
                farm.get_clientes_segmento("FARMA")
                self.assertEqual(get.call_args.kwargs["timeout"], (10, 600))
                response.json.return_value = {
                    "segmento": "FARMA",
                    "cliente": {"id": 17},
                }
                farm.get_cliente_by_cpf(CPF)
                self.assertEqual(get.call_args.kwargs["timeout"], (10, 90))

    def test_mixed_segment_candidates_keep_only_selected_segment(self):
        from copy import deepcopy

        payload = customer_snapshot()
        foreign = deepcopy(payload)
        foreign["cliente"]["id"] = 99
        foreign["ultimoPedido"]["segmento"] = "PET"
        with closing(FarmaliderClient("synthetic")) as farm:
            with patch.object(farm, "_request_json", return_value=[foreign, payload]):
                self.assertEqual(farm.get_cliente_by_cpf(CPF), [payload])

    def test_root_segment_proves_cached_order_without_accepting_foreign_header(self):
        payload = customer_snapshot()
        payload["segmento"] = "PET"
        payload["ultimoPedido"].pop("segmento")
        with closing(PetRecompraClient("synthetic")) as farm:
            with (
                patch.object(farm, "get_clientes_segmento", return_value=[]),
                patch.object(farm, "_request_json", return_value=payload) as get,
            ):
                farm.get_cliente_by_cpf(CPF)
                self.assertEqual(farm.get_pedido(8)["capa"]["segmento"], "PET")
                self.assertEqual(get.call_count, 1)
