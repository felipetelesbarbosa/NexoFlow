"""Carga completa reutiliza snapshots, inclusive null, sem HTTP por contato."""

import unittest
from contextlib import closing
from copy import deepcopy
from unittest.mock import patch

from recompra import RecompraReadCache
from recompra_profiles import PetRecompraClient
from tests.test_farmalider_customers import CPF, customer_snapshot


class PetGeneralSnapshotReuseTests(unittest.TestCase):
    def test_explicit_null_uses_general_endpoint_once_without_individual_get(self):
        payloads = []
        for i in range(200):
            payload = customer_snapshot(id=i + 1, cpf=str(10000000000 + i))
            payload["ultimoPedido"] = None
            payload["itens"] = []
            payloads.append(payload)
        with closing(PetRecompraClient("synthetic")) as farm:
            with patch.object(farm, "_request_json", return_value=payloads) as request:
                reads = RecompraReadCache(farm)
                for payload in payloads:
                    result = reads.get_cliente_by_cpf(payload["cliente"]["cpf"])
                    self.assertIsNone(result[0]["ultimoPedido"])
                self.assertEqual(request.call_count, 1)
                self.assertTrue(request.call_args.args[0].endswith("/clientes/PET"))
                self.assertEqual(reads.metrics()["consultas"], 0)

    def test_complete_pet_order_uses_general_endpoint_once_and_copies_payloads(self):
        payload = customer_snapshot()
        payload["ultimoPedido"]["segmento"] = "PET"
        with closing(PetRecompraClient("synthetic")) as farm:
            with patch.object(farm, "_request_json", return_value=[payload]) as request:
                reads = RecompraReadCache(farm)
                original = reads.get_cliente_by_cpf(CPF)
                original[0]["cliente"]["nome"] = "changed"
                order = reads.get_pedido("8")
                order["itens"][0]["descricao"] = "changed"
                self.assertEqual(
                    reads.get_cliente_by_cpf(CPF)[0]["cliente"]["nome"],
                    payload["cliente"]["nome"],
                )
                self.assertNotEqual(
                    reads.get_pedido("8")["itens"][0]["descricao"], "changed"
                )
                self.assertEqual(request.call_count, 1)
                self.assertEqual(reads.metrics()["consultas"], 0)

    def test_partial_general_record_retains_pet_individual_fallback(self):
        payload = customer_snapshot()
        payload["ultimoPedido"]["segmento"] = "PET"
        partial = deepcopy(payload)
        partial.pop("itens")
        with closing(PetRecompraClient("synthetic")) as farm:
            with patch.object(
                farm, "_request_json", side_effect=[[partial], payload]
            ) as request:
                result = RecompraReadCache(farm).get_cliente_by_cpf(CPF)
                self.assertEqual(result["ultimoPedido"]["id"], 8)
                self.assertEqual(request.call_count, 2)
                self.assertIn("/cliente/cpf/", request.call_args.args[0])
