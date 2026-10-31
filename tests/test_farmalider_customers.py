"""Cadastro por segmento: seleção, escopo, cache e falhas com dados sintéticos."""

import json
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date
from threading import Event
from unittest.mock import Mock, patch

from analytics import is_valid_cpf, normalize_cpf
from farmalider_client import FarmaliderAuthError, FarmaliderClient, FarmaliderError
from farmalider_customers import CustomerDirectory, ExecutionReadCache, enrichment
from farmalider_integration import select_cliente_response

CPF = "52998224725"


def customer(**changes):
    result = {
        "id": 17,
        "cpf": int(CPF),
        "nome": "Pessoa Sintética",
        "celular": 91987654321,
        "email": None,
        "sexo": "F",
        "nascimento": "1990-04-12T00:00:00",
        "cadastro": "2020-01-01T00:00:00",
        "rg": "NAO-COPIAR",
        "enderecos": [
            {
                "id": 4,
                "clienteId": 17,
                "principal": 1,
                "cidade": "BELEM",
                "uf": "PA",
                "bairro": "CIDADE VELHA",
                "cep": "66023170",
                "logradouro": "Rua Sintética",
                "numero": "10",
                "complemento": "",
            }
        ],
    }
    result.update(changes)
    return result


def customer_snapshot(**changes):
    person = customer(**changes)
    return {
        "cliente": person,
        "ultimoPedido": {
            **{
                k: person["enderecos"][0].get(k)
                for k in (
                    "cep",
                    "uf",
                    "cidade",
                    "bairro",
                    "logradouro",
                    "numero",
                    "complemento",
                )
            },
            "id": 8,
            "codCliente": person["id"],
            "emissao": "2026-10-07T10:00:00",
            "status": 2,
            "formaPagamento": 5,
            "frete": 9.99,
            "segmento": "FARMA",
        },
        "itens": [
            {
                "codPedido": 8,
                "codProduto": 901,
                "descricao": "Creme humano sintético",
                "quantidade": 1,
                "valor": 20,
                "total": 20,
            }
        ],
    }


class CustomerDirectoryTests(unittest.TestCase):
    def test_accepts_empty_list_but_not_missing_or_wrong_schema(self):
        self.assertEqual(CustomerDirectory([]).candidates(CPF), [])
        for payload in (None, {}, {"clientes": []}, [None], "erro"):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                CustomerDirectory(payload)

    def test_index_discards_unneeded_personal_fields(self):
        directory = CustomerDirectory([customer()])
        payload = json.dumps(directory.candidates(CPF))
        self.assertNotIn("NAO-COPIAR", payload)
        self.assertNotIn('"rg"', payload)
        self.assertIn('"logradouro"', payload)
        self.assertEqual(directory.metrics()["cadastros_indexados"], 1)
        self.assertNotIn(CPF, json.dumps(directory.metrics()))

    def test_restores_only_mathematically_valid_leading_zero(self):
        prefix = "012345678"
        for count in (9, 10):
            total = sum(
                int(value) * weight
                for value, weight in zip(prefix, range(count + 1, 1, -1), strict=True)
            )
            prefix += str((total * 10 % 11) % 10)
        self.assertTrue(is_valid_cpf(prefix))
        directory = CustomerDirectory([customer(cpf=int(prefix))])
        self.assertEqual(normalize_cpf(str(int(prefix))), prefix)
        self.assertEqual(len(directory.candidates(prefix)), 1)

    def test_numeric_invalid_cpf_keeps_only_proven_numeric_zero_loss_alias(self):
        numeric = CustomerDirectory([customer(cpf=123)])
        textual = CustomerDirectory([customer(cpf="123")])
        self.assertEqual(len(numeric.candidates("000123")), 1)
        self.assertEqual(textual.candidates("000123"), [])

    def test_zero_empty_malformed_do_not_authorize_any_customer(self):
        for cpf in (0, "00000000000", "", None, "abc", True, 123.5):
            with self.subTest(cpf=cpf):
                directory = CustomerDirectory([customer(cpf=cpf)])
                self.assertEqual(directory.candidates(str(cpf)), [])

    def test_same_cpf_with_two_customer_ids_remains_ambiguous(self):
        payload = [customer(), customer(id=18)]
        directory = CustomerDirectory(payload)
        result, selected = select_cliente_response(
            CPF, payload, customer_directory=directory
        )
        self.assertEqual(result[0], "CPF_IDENTIDADE_AMBIGUA")
        self.assertIsNone(selected)

    def test_identical_duplicate_id_is_collapsed_but_conflicting_id_is_blocked(self):
        first = customer()
        directory = CustomerDirectory([first, deepcopy(first)])
        self.assertEqual(len(directory.candidates(CPF)), 1)
        conflicting = CustomerDirectory([first, customer(celular=91999999999)])
        result, _ = select_cliente_response(
            CPF, [first], customer_directory=conflicting
        )
        self.assertEqual(result[0], "CPF_IDENTIDADE_AMBIGUA")

    def test_conflicting_id_with_changed_cpf_blocks_both_old_and_new_keys(self):
        directory = CustomerDirectory([customer(), customer(cpf=123)])
        for cpf in (CPF, "123"):
            candidates, reason = directory.constrain(
                cpf, [{"cliente": customer(cpf=cpf)}]
            )
            self.assertEqual(candidates, [])
            self.assertEqual(reason, "CPF_IDENTIDADE_AMBIGUA")

    def test_directory_constrains_actual_cpf_payload_to_known_farma_candidate(self):
        directory = CustomerDirectory([customer()])
        payload = [
            {"cliente": customer(id=99)},
            {"cliente": customer(), "ultimoPedido": {"id": 8}},
        ]
        result, selected = select_cliente_response(
            CPF, payload, customer_directory=directory
        )
        self.assertEqual(result[:2], ("CPF_CONFIRMADO", "17"))
        self.assertEqual(selected["ultimoPedido"]["id"], 8)

    def test_other_id_never_borrows_order_from_known_farma_customer(self):
        directory = CustomerDirectory([customer()])
        result, selected = select_cliente_response(
            CPF,
            {"cliente": customer(id=99), "ultimoPedido": {"id": 8}},
            customer_directory=directory,
        )
        self.assertEqual(result[0], "CLIENTE_ID_DIVERGENTE_API")
        self.assertIsNone(selected)

    def test_invalid_cpf_matching_broken_id_is_not_discarded_by_segment_filter(self):
        directory = CustomerDirectory([customer(cpf=123)])
        payload = [customer(cpf=123), customer(cpf=123, id=0)]
        result, _ = select_cliente_response(
            "123",
            payload,
            weni_identity={"nome": "Pessoa"},
            customer_directory=directory,
        )
        self.assertEqual(result[0], "CLIENTE_ID_INVALIDO_API")

    def test_absence_is_not_a_negative_lookup_and_does_not_remove_valid_api_result(
        self,
    ):
        result, _ = select_cliente_response(
            CPF, {"cliente": customer()}, customer_directory=CustomerDirectory([])
        )
        self.assertEqual(result[0], "CPF_CONFIRMADO")

    def test_invalid_cpf_identity_must_agree_with_both_official_customer_sources(self):
        directory = CustomerDirectory([customer(cpf=123)])
        result, selected = select_cliente_response(
            "123",
            {"cliente": customer(cpf=123, nome="Outra Pessoa", celular=91988887777)},
            weni_identity={"nome": "Outra Pessoa", "telefone": "+5591988887777"},
            customer_directory=directory,
        )
        self.assertEqual(result[0], "CPF_IDENTIDADE_DIVERGENTE")
        self.assertIsNone(selected)

    def test_invalid_cpf_requires_first_name_or_local_phone_per_candidate(self):
        directory = CustomerDirectory([customer(cpf=123)])
        for identity, expected in [
            ({"nome": "Pessoa Outro Sobrenome"}, "CPF_INVALIDO_ENCONTRADO"),
            (
                {"nome": "Outro", "telefone": "+5585987654321"},
                "CPF_INVALIDO_ENCONTRADO",
            ),
            ({"nome": "Outro"}, "CPF_IDENTIDADE_DIVERGENTE"),
            ({}, "CPF_IDENTIDADE_INSUFICIENTE"),
        ]:
            with self.subTest(identity=identity):
                result, _ = select_cliente_response(
                    "123",
                    directory.candidates("123"),
                    weni_identity=identity,
                    customer_directory=directory,
                )
                self.assertEqual(result[0], expected)


class ExecutionReadCacheTests(unittest.TestCase):
    def setUp(self):
        self.cache = ExecutionReadCache()
        self.addCleanup(self.cache.close)

    def test_reuses_success_and_not_found_without_sharing_mutable_payload(self):
        fetch = Mock(return_value={"cliente": {"id": 17}})
        first = self.cache.read("cpf", CPF, fetch)
        first["cliente"]["id"] = 99
        self.assertEqual(self.cache.read("cpf", CPF, fetch)["cliente"]["id"], 17)
        fetch.assert_called_once()
        absent = Mock(return_value=None)
        self.assertIsNone(self.cache.read("cpf", "123", absent))
        self.assertIsNone(self.cache.read("cpf", "123", absent))
        absent.assert_called_once()

    def test_transient_failure_is_not_cached(self):
        fetch = Mock(side_effect=[FarmaliderError("sintético"), {"id": 17}])
        with self.assertRaises(FarmaliderError):
            self.cache.read("cpf", CPF, fetch)
        self.assertEqual(self.cache.read("cpf", CPF, fetch), {"id": 17})
        self.assertEqual(fetch.call_count, 2)

    def test_parallel_consumers_share_one_request(self):
        started, release = Event(), Event()

        def fetch():
            started.set()
            if not release.wait(5):
                raise RuntimeError("Tempo de teste excedido")
            return {"id": 17}

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [
                pool.submit(self.cache.read, "cpf", CPF, fetch) for _ in range(8)
            ]
            self.assertTrue(started.wait(5))
            release.set()
            self.assertEqual([f.result(timeout=5) for f in futures], [{"id": 17}] * 8)
        self.assertEqual(self.cache.hits, 7)

    def test_full_cache_keeps_prior_reads_and_does_not_fail_official_response(self):
        first = Mock(return_value={"id": 17})
        self.cache.read("cpf", CPF, first)
        self.cache.db.execute("PRAGMA max_page_count = 4")
        large = {"data": "x" * 100000}
        self.assertEqual(self.cache.read("pedido", "18", lambda: large), large)
        self.assertTrue(self.cache.write_disabled)
        self.assertEqual(self.cache.read("cpf", CPF, first), {"id": 17})
        first.assert_called_once()

    def test_cache_is_private_and_removed_on_close(self):
        cache = ExecutionReadCache()
        folder = cache.path.parent
        if os.name != "nt":
            self.assertEqual(cache.path.stat().st_mode & 0o777, 0o600)
        cache.close()
        self.assertFalse(folder.exists())


class CustomerClientTests(unittest.TestCase):
    def setUp(self):
        mode = patch(
            "secrets_config.FARMALIDER_CUSTOMER_DIRECTORY_MODE", "on", create=True
        )
        mode.start()
        self.addCleanup(mode.stop)
        self.client = FarmaliderClient("token-sintetico")
        self.addCleanup(self.client.close)

    def test_only_valid_segment_paths_are_allowed(self):
        with patch.object(self.client, "_request_json", return_value=[]) as get:
            self.client.get_clientes_segmento("FARMA")
            self.assertTrue(get.call_args.args[0].endswith("/clientes/FARMA"))
            self.client.get_clientes_segmento("PET")
            self.assertTrue(get.call_args.args[0].endswith("/clientes/PET"))
            for value in ("farma", "../PET", "FARMA?token=x", ""):
                with self.assertRaises(ValueError):
                    self.client.get_clientes_segmento(value)
            self.assertEqual(get.call_count, 2)

    def test_directory_loaded_once_and_never_replaces_live_order_payload(self):
        full = {
            "cliente": customer(),
            "ultimoPedido": {"id": 8, "segmento": "FARMA"},
            "itens": [],
        }
        with patch.object(
            self.client, "_request_json", side_effect=[[customer()], full]
        ) as get:
            self.assertTrue(self.client.prepare_customer_directory(expected_contacts=5))
            self.assertTrue(
                self.client.prepare_customer_directory(expected_contacts=50000)
            )
            self.assertEqual(self.client.get_cliente_cadastro_by_cpf(CPF)[0]["id"], 17)
            self.assertEqual(get.call_count, 1)
            self.assertEqual(
                self.client.get_cliente_by_cpf(CPF)["ultimoPedido"]["id"], 8
            )
            self.client.get_cliente_by_cpf(CPF)
            self.assertEqual(get.call_count, 2)
            self.assertEqual(
                self.client.metrics_snapshot()["execution_read_cache_hits"], 1
            )

    def test_auto_small_load_skips_bulk_and_off_keeps_legacy_lookup(self):
        for mode in ("auto", "off"):
            with (
                self.subTest(mode=mode),
                patch("secrets_config.FARMALIDER_CUSTOMER_DIRECTORY_MODE", mode),
                patch.object(
                    self.client,
                    "_request_json",
                    return_value={"segmento": "FARMA", "cliente": customer()},
                ) as get,
            ):
                self.assertFalse(
                    self.client.prepare_customer_directory(expected_contacts=1)
                )
                self.client.get_cliente_cadastro_by_cpf(CPF)
                self.assertTrue(get.call_args.args[0].endswith("/cliente/cpf/" + CPF))
                self.client.reset_execution_reads()

    def test_missing_customer_falls_back_without_claiming_no_purchase(self):
        with patch.object(
            self.client,
            "_request_json",
            side_effect=[
                [],
                {"segmento": "FARMA", "cliente": customer(), "ultimoPedido": {"id": 8}},
            ],
        ) as get:
            self.client.prepare_customer_directory(expected_contacts=1)
            payload = self.client.get_cliente_cadastro_by_cpf(CPF)
            self.assertEqual(payload["ultimoPedido"]["id"], 8)
            self.assertEqual(get.call_count, 2)

    def test_bad_bulk_schema_is_not_retried_for_every_contact(self):
        with patch.object(
            self.client,
            "_request_json",
            side_effect=[
                {"erro": "sintético"},
                {"segmento": "FARMA", "cliente": customer()},
            ],
        ) as get:
            self.assertFalse(
                self.client.prepare_customer_directory(expected_contacts=500)
            )
            self.assertFalse(
                self.client.prepare_customer_directory(expected_contacts=500)
            )
            self.client.get_cliente_by_cpf(CPF)
            self.assertEqual(get.call_count, 2)

    def test_authentication_error_is_propagated(self):
        with patch.object(
            self.client, "_request_json", side_effect=FarmaliderAuthError("sintético")
        ):
            with self.assertRaises(FarmaliderAuthError):
                self.client.prepare_customer_directory(expected_contacts=500)

    def test_reset_requires_fresh_individual_reads_and_fresh_directory(self):
        with patch.object(
            self.client,
            "_request_json",
            side_effect=[
                [customer()],
                {"id": 8},
                [customer(nome="Atualizado")],
                {"id": 9},
            ],
        ) as get:
            self.client.prepare_customer_directory(expected_contacts=500)
            self.assertEqual(self.client.get_pedido(8), {"id": 8})
            self.client.get_pedido(8)
            path = self.client._execution_cache.path
            self.client.reset_execution_reads()
            self.assertFalse(path.exists())
            self.client.prepare_customer_directory(expected_contacts=500)
            self.assertEqual(self.client.get_pedido(8), {"id": 9})
            self.assertEqual(get.call_count, 4)


class CustomerEnrichmentTests(unittest.TestCase):
    def test_missing_gender_age_and_geography_are_filled(self):
        person = CustomerDirectory([customer_snapshot()]).by_id["17"]
        values = enrichment({}, person, date(2026, 10, 21))
        self.assertEqual(
            values,
            {
                "genero": "Feminino",
                "idade": "36",
                "maior_de_18_anos": "Sim",
                "cidade": "Belém",
                "estado": "Pará",
                "bairro": "Cidade Velha",
                "cep": "66023170",
            },
        )
        self.assertFalse(
            set(values)
            & {"cpf", "nome", "telefone", "email", "pedido_data", "opt_in_lgpd"}
        )

    def test_existing_values_and_location_conflicts_are_preserved(self):
        fields = {"genero": "Outro", "idade": "99", "cidade": "Ananindeua"}
        values = enrichment(fields, customer(), date(2026, 10, 21))
        self.assertEqual(values, {})
        self.assertEqual(fields["idade"], "99")

    def test_unknown_future_and_invalid_birth_dates_do_not_invent_age(self):
        for value in (None, "", "inválida", "2027-01-01", "1800-01-01"):
            with self.subTest(value=value):
                self.assertNotIn(
                    "idade",
                    enrichment({}, customer(nascimento=value), date(2026, 10, 21)),
                )

    def test_foreign_or_ambiguous_principal_address_is_not_used(self):
        for addresses in (
            [{**customer()["enderecos"][0], "clienteId": 99}],
            customer()["enderecos"] * 2,
            [],
        ):
            with self.subTest(addresses=addresses):
                values = enrichment(
                    {}, customer(enderecos=addresses), date(2026, 10, 21)
                )
                self.assertFalse(set(values) & {"cidade", "estado", "bairro", "cep"})
