"""Recompra FARMA com a base geral carregada: sem regravações nem HTTP redundante.

Todos os dados são sintéticos; a rede é simulada em ``_request_json``.
"""

import unittest
from collections import Counter
from copy import deepcopy
from datetime import timedelta
from unittest.mock import patch

import customer_observations
from analytics import is_valid_cpf
from farmalider_client import FarmaliderClient, FarmaliderError
from farmalider_customers import CustomerDirectory, prepare_customers
from recompra import build_plans
from tests.test_recompra import GROUP, NOW, STRUCTURE

EMITTED = (NOW - timedelta(days=10)).replace(tzinfo=None).isoformat()


def valid_cpf(number):
    digits = [int(char) for char in f"{number:09d}"]
    for size in (9, 10):
        total = sum(d * w for d, w in zip(digits, range(size + 1, 1, -1), strict=True))
        digits.append((total * 10 % 11) % 10)
    cpf = "".join(map(str, digits))
    assert is_valid_cpf(cpf)
    return cpf


def entry(index, *, latest="snapshot", items=True):
    """Registro de ``clientes/FARMA``; ``latest`` controla a evidência de pedido."""
    cpf = valid_cpf(100000 + index)
    person = {
        "id": index,
        "cpf": int(cpf),
        "nome": f"Pessoa {index}",
        "celular": 91990000000 + index,
        "enderecos": [],
    }
    result = {"cliente": person, "segmento": "FARMA"}
    if latest == "snapshot":
        result["ultimoPedido"] = {
            "id": 10000 + index,
            "codCliente": index,
            "emissao": EMITTED,
            "status": 2,
            "formaPagamento": 3,
            "frete": 0,
            "segmento": "FARMA",
        }
        if items:
            result["itens"] = [
                {
                    "codPedido": 10000 + index,
                    "codProduto": 900 + index,
                    "descricao": "Produto sintético",
                    "quantidade": 1,
                    "valor": 10,
                    "total": 10,
                }
            ]
    elif latest == "null":
        result["ultimoPedido"] = None
    return result, cpf


def rendered(mock_log):
    """Mensagens já formatadas, independentes do nível global de log."""
    return [c.args[0] % c.args[1:] for c in mock_log.call_args_list if c.args]


def weni_contact(index, cpf, *, grouped=False, marketing=""):
    return {
        "uuid": f"u{index}",
        "name": f"Pessoa {index}",
        "urns": [f"tel:+55919900{index:05d}"],
        "fields": {"cpf": cpf, "marketing_opt_in": marketing},
        "groups": [{"uuid": "g-recompra", "name": GROUP}] if grouped else [],
    }


class GeneralBaseRecompraTests(unittest.TestCase):
    def setUp(self):
        mode = patch(
            "secrets_config.FARMALIDER_CUSTOMER_DIRECTORY_MODE", "on", create=True
        )
        mode.start()
        self.addCleanup(mode.stop)
        self.http = Counter()
        self.base = []
        self.individual = {}
        self.bulk_error = None

    def fake_request(self, path, **_kwargs):
        if path.endswith("/clientes/FARMA"):
            self.http["clientes/FARMA"] += 1
            if self.bulk_error:
                raise self.bulk_error
            return deepcopy(self.base)
        if "/cliente/cpf/" in path:
            self.http["cliente/cpf"] += 1
            return deepcopy(self.individual.get(int(path.rsplit("/", 1)[1])))
        if "/pedido/" in path:
            self.http["pedido"] += 1
            return None
        raise AssertionError("Consulta inesperada")

    def plans(self, contacts, *, workers=4, structure=STRUCTURE):
        def counted_request(client, path, **kwargs):
            # Contabiliza como o transporte real: só HTTP entra em total_requests.
            client._record_request(0.0, status_code=200, endpoint_label="teste")
            return self.fake_request(path, **kwargs)

        with patch.object(FarmaliderClient, "_request_json", counted_request):
            client = FarmaliderClient("token-sintetico")
            try:
                return build_plans(
                    contacts,
                    client,
                    structure,
                    {"contacts": {}},
                    now=NOW,
                    workers=workers,
                )
            finally:
                client.close()

    def world(self, count, **kinds):
        contacts = []
        for index in range(1, count + 1):
            record, cpf = entry(index, **kinds)
            self.base.append(record)
            contacts.append(weni_contact(index, cpf))
        return contacts

    def test_directory_observations_are_recorded_once_per_run(self):
        contacts = self.world(60)
        calls = Counter()
        real = customer_observations.record_directory

        def counting(directory, at):
            calls["n"] += 1
            return real(directory, at)

        with patch.object(customer_observations, "record_directory", counting):
            plans = self.plans(contacts)
        self.assertEqual(calls["n"], 1)
        self.assertEqual({p["reason"] for p in plans}, {"JANELA_0_A_25"})
        self.assertEqual({p["action"] for p in plans}, {"add"})

    def test_prepare_customers_is_idempotent_for_the_same_directory(self):
        self.world(5)
        calls = Counter()
        real = customer_observations.record_directory

        def counting(directory, at):
            calls["n"] += 1
            return real(directory, at)

        with (
            patch.object(FarmaliderClient, "_request_json", self.fake_request),
            patch.object(customer_observations, "record_directory", counting),
        ):
            client = FarmaliderClient("token-sintetico")
            try:
                for _ in range(5):
                    prepare_customers(client, None)
                self.assertEqual(calls["n"], 1)
                self.assertEqual(self.http["clientes/FARMA"], 1)
                # Nova leitura (reset) é outro índice e volta a ser observada.
                client.reset_execution_reads()
                prepare_customers(client, None)
                self.assertEqual(calls["n"], 2)
            finally:
                client.close()

    def test_sufficient_base_needs_only_the_bulk_request(self):
        contacts = self.world(40)
        plans = self.plans(contacts)
        self.assertEqual(dict(self.http), {"clientes/FARMA": 1})
        self.assertEqual(len(plans), 40)
        self.assertTrue(all(p["order_id"] for p in plans))

    def test_explicit_null_last_order_is_resolved_from_the_base(self):
        contacts = self.world(10, latest="null")
        plans = self.plans(contacts)
        self.assertEqual(dict(self.http), {"clientes/FARMA": 1})
        self.assertEqual({p["reason"] for p in plans}, {"SEM_PEDIDO_CONFIRMADO"})
        self.assertEqual({p["action"] for p in plans}, {""})

    def test_omitted_last_order_is_not_absence_and_stays_pending(self):
        contacts = self.world(5, latest="omitted")
        plans = self.plans(contacts)
        self.assertEqual(dict(self.http), {"clientes/FARMA": 1})
        self.assertEqual(
            {p["reason"] for p in plans}, {"PEDIDO_NAO_CONFIRMADO_BASE_GERAL"}
        )
        self.assertEqual({p["action"] for p in plans}, {""})

    def test_incomplete_snapshot_is_pending_without_individual_request(self):
        contacts = self.world(5, items=False)
        plans = self.plans(contacts)
        self.assertEqual(dict(self.http), {"clientes/FARMA": 1})
        self.assertEqual(
            {p["reason"] for p in plans}, {"PEDIDO_NAO_CONFIRMADO_BASE_GERAL"}
        )
        self.assertFalse(any(p["fields"] or p["purchase"] for p in plans))

    def test_cpf_absent_from_base_is_pending_without_individual_request(self):
        contacts = self.world(3)
        stranger = weni_contact(99, valid_cpf(777777))
        plans = self.plans([*contacts, stranger])
        self.assertEqual(dict(self.http), {"clientes/FARMA": 1})
        by_uuid = {p["contact_uuid"]: p for p in plans}
        self.assertEqual(by_uuid["u99"]["reason"], "CPF_NAO_CONFIRMADO_BASE_GERAL")
        self.assertEqual(by_uuid["u99"]["action"], "")
        self.assertEqual(by_uuid["u1"]["reason"], "JANELA_0_A_25")

    def test_pending_base_never_removes_an_admitted_contact(self):
        contacts = self.world(2, items=False)
        for contact in contacts:
            contact["groups"] = [{"uuid": "g-recompra", "name": GROUP}]
        plans = self.plans(contacts)
        self.assertEqual({p["action"] for p in plans}, {""})
        self.assertTrue(all(p["in_group"] for p in plans))

    def test_divergent_duplicate_customer_keeps_ambiguous_identity(self):
        record, cpf = entry(1)
        other = deepcopy(record)
        other["itens"][0]["total"] = 99
        self.base.extend([record, other])
        plans = self.plans([weni_contact(1, cpf)])
        self.assertEqual(dict(self.http), {"clientes/FARMA": 1})
        self.assertEqual(plans[0]["reason"], "CPF_IDENTIDADE_AMBIGUA")
        self.assertEqual(plans[0]["action"], "")

    def test_refusal_and_opt_out_still_precede_the_base(self):
        contacts = self.world(2)
        contacts[0]["fields"]["marketing_opt_in"] = "Recusado"
        contacts[1]["groups"] = [{"uuid": "g-out", "name": "Opt-Out"}]
        plans = self.plans(contacts)
        self.assertEqual({p["reason"] for p in plans}, {"RECUSA_MARKETING"})

    def test_cancelled_orders_keep_their_block(self):
        contacts = self.world(2)
        self.base[0]["ultimoPedido"]["status"] = 3
        self.base[1]["ultimoPedido"]["formaPagamento"] = 0
        plans = self.plans(contacts)
        self.assertTrue(all(p["action"] == "" for p in plans))
        self.assertTrue(all(p["reason"] != "JANELA_0_A_25" for p in plans))

    def test_unavailable_base_stays_pending_without_individual_queries(self):
        self.bulk_error = FarmaliderError("base indisponível")
        contacts = self.world(3)
        for record in self.base:
            self.individual[record["cliente"]["cpf"]] = deepcopy(record)
        with patch("recompra.logging.info") as info:
            plans = self.plans(contacts)
        self.assertEqual(self.http["cliente/cpf"], 0)
        self.assertEqual({p["reason"] for p in plans}, {"ERRO_BASE_GERAL_INCOMPLETA"})
        summary = [m for m in rendered(info) if "duração=" in m][-1]
        self.assertIn(f"HTTP={sum(self.http.values())}", summary)

    def test_small_runs_also_use_only_general_base(self):
        with patch("secrets_config.FARMALIDER_CUSTOMER_DIRECTORY_MODE", "auto"):
            contacts = self.world(3)
            for record in self.base:
                self.individual[record["cliente"]["cpf"]] = deepcopy(record)
            plans = self.plans(contacts)
        self.assertEqual(self.http["clientes/FARMA"], 1)
        self.assertEqual(self.http["cliente/cpf"], 0)
        self.assertEqual({p["reason"] for p in plans}, {"JANELA_0_A_25"})

    def test_summary_log_separates_real_http_from_local_reads(self):
        contacts = self.world(20)
        with patch("recompra.logging.info") as info:
            self.plans(contacts)
        summary = [m for m in rendered(info) if "duração=" in m]
        self.assertTrue(summary)
        self.assertEqual(sum(self.http.values()), 1)
        self.assertIn("HTTP=1.", summary[-1])
        self.assertIn("'leituras_base_geral': 40", summary[-1])
        self.assertIn("'consultas': 0", summary[-1])

    def test_directory_snapshots_are_not_shared_between_contacts(self):
        contacts = self.world(2)
        # Mesmo CPF em dois contatos Weni: cada plano recebe cópia independente.
        contacts[1]["fields"]["cpf"] = contacts[0]["fields"]["cpf"]
        plans = self.plans(contacts, workers=1)
        self.assertEqual(plans[0]["order_id"], plans[1]["order_id"])
        directory = CustomerDirectory(deepcopy(self.base))
        self.assertIsNotNone(directory.latest_by_cpf(contacts[0]["fields"]["cpf"]))

    def test_observation_failure_does_not_mark_directory_as_recorded(self):
        record, _ = entry(1)
        directory = CustomerDirectory([record])
        calls = []

        def failing(current):
            calls.append(current)
            raise OSError("synthetic storage failure")

        with self.assertRaises(OSError):
            directory.record_observations_once(failing)
        self.assertTrue(
            directory.record_observations_once(lambda current: calls.append(current))
        )
        self.assertFalse(
            directory.record_observations_once(lambda current: calls.append(current))
        )
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
