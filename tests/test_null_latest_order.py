"""Último pedido explicitamente nulo não é falha nem autoriza pedido legado."""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import requests

from farmalider_client import FarmaliderClient, FarmaliderLookupError
from farmalider_customers import ExecutionReadCache
from farmalider_integration import resolve_contact_order, select_cliente_response
from main import FarmaliderSettings, build_orders, validate_contacts
from recompra import (
    apply_review,
    build_plans,
    incomplete_query_summary,
    load_state,
    make_review,
    resolve_latest,
)
from recompra_profiles import PetRecompraClient
from tests.test_farmalider_customers import CPF, customer
from tests.test_pedido_resolution import legacy_raw
from tests.test_recompra import NOW, STRUCTURE
from tests.test_recompra_prevention import weni_fixture
from weni_update import UpdateStats, _build_contact_plan, _record_validated_order


def no_order():
    return {"cliente": customer(), "ultimoPedido": None, "itens": []}


def contact():
    return {
        "uuid": "synthetic-no-order",
        "name": "Pessoa Sintética",
        "groups": [],
        "fields": {"cpf": CPF, "pedido_id": "777", "ultimo_pedido": legacy_raw()},
    }


class NullLatestOrderTests(unittest.TestCase):
    def test_real_http200_parser_accepts_null_without_segment_failure(self):
        farm = self.client("FARMA")
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps(no_order()).encode()
        with patch.object(farm.session, "get", return_value=response) as get:
            result = farm.get_cliente_by_cpf(CPF)
        self.assertIsNone(result["ultimoPedido"])
        self.assertEqual(select_cliente_response(CPF, result)[0][0], "SEM_PEDIDO_API")
        self.assertEqual(farm.metrics_snapshot()["responses_200"], 1)
        self.assertFalse(farm._lookup_diagnostics)
        self.assertEqual(get.call_count, 1)

    def test_repeated_null_loads_preserve_previously_verified_customer_details(self):
        farm = self.client("FARMA")
        old = {
            "contact_uuid": contact()["uuid"],
            "cpf": CPF,
            "cpf_normalizado": CPF,
            "farmalider_cliente_status": "CPF_CONFIRMADO",
            "farmalider_cliente_id": "17",
            "farmalider_cliente_nome": "Pessoa Sintética",
            "farmalider_cliente_consultado_em": "2026-01-01T12:00:00Z",
        }
        with patch.object(farm, "_request_json", return_value=no_order()):
            for _ in range(2):
                rows = [{"contact_uuid": contact()["uuid"], "cpf": CPF}]
                stats = validate_contacts(
                    rows,
                    farm_client=farm,
                    farm_settings=FarmaliderSettings(True, "SYNTHETIC", False),
                    sync_time=NOW.isoformat(),
                    existing_by_uuid={old["contact_uuid"]: old},
                )
                self.assertEqual(stats.api_errors, 0)
                self.assertEqual(rows[0]["farmalider_cliente_status"], "SEM_PEDIDO_API")
                self.assertEqual(rows[0]["farmalider_cliente_id"], "17")
                self.assertEqual(rows[0]["farmalider_cliente_nome"], "Pessoa Sintética")
                old = rows[0]

    def test_no_order_does_not_authorize_cross_segment_customer_deduplication(self):
        from weni_dedup import unique_customer

        for segment in ("FARMA", "PET"):
            farm = self.client(segment)
            with patch.object(farm, "_request_json", return_value=no_order()):
                self.assertIsNone(unique_customer(farm, CPF))
            farm.reset_execution_reads()
            farm._directory_attempted = True
            payload = no_order()
            payload["segmento"] = segment
            with patch.object(farm, "_request_json", return_value=payload):
                self.assertIsNotNone(unique_customer(farm, CPF))

    def test_recompra_apply_removes_ineligible_member_and_next_review_is_noop(self):
        for segment in ("FARMA", "PET"):
            with self.subTest(segment=segment), TemporaryDirectory() as folder:
                person = contact()
                person["groups"] = [
                    {"uuid": STRUCTURE["group_uuid"], "name": "Recompra"}
                ]
                weni, live = weni_fixture(segment, [person])
                farm = self.client(segment)
                structure = {**STRUCTURE, "segment": segment}
                path, audit = Path(folder) / "state.json", Path(folder) / "audit.jsonl"
                with (
                    patch.object(farm, "_request_json", return_value=no_order()),
                    patch("recompra.inspect_structure", return_value=structure),
                ):
                    state = load_state(path)
                    plans = build_plans([person], farm, structure, state, now=NOW)
                    self.assertEqual(plans[0]["action"], "remove")
                    review = make_review(plans, structure, now=NOW, state=state)
                    self.assertEqual(
                        apply_review(
                            review,
                            weni,
                            farm,
                            state_path=path,
                            audit_path=audit,
                            now_fn=lambda: NOW,
                        ),
                        {"aplicados": 1},
                    )
                    self.assertFalse(live[person["uuid"]]["groups"])
                    state = load_state(path)
                    plans = build_plans(
                        [live[person["uuid"]]], farm, structure, state, now=NOW
                    )
                    review = make_review(plans, structure, now=NOW, state=state)
                    self.assertEqual(
                        apply_review(
                            review,
                            weni,
                            farm,
                            state_path=path,
                            audit_path=audit,
                            now_fn=lambda: NOW,
                        ),
                        {"sem_mudanca": 1},
                    )
                    self.assertTrue(
                        all(
                            c.kwargs["action"] == "remove"
                            for c in weni.contact_group_action.call_args_list
                        )
                    )

    def test_null_ignores_orphan_items_without_treating_them_as_sale_or_cancellation(
        self,
    ):
        payload = no_order()
        payload["itens"] = [{"codPedido": 777, "descricao": "Órfão", "valor": 10}]
        farm = self.client("FARMA")
        with (
            patch.object(farm, "_request_json", return_value=payload),
            patch.object(farm, "get_pedido") as get,
        ):
            self.assertEqual(
                resolve_contact_order(
                    contact(), farm_client=farm, captured_at=NOW.isoformat()
                ),
                (None, []),
            )
            get.assert_not_called()

    def client(self, segment):
        client = (PetRecompraClient if segment == "PET" else FarmaliderClient)(
            "SYNTHETIC"
        )
        client._directory_attempted = True
        client._execution_cache = ExecutionReadCache()
        self.addCleanup(client.close)
        return client

    def test_null_without_segment_is_cached_as_normal_absence(self):
        for segment in ("FARMA", "PET"):
            with self.subTest(segment=segment):
                client = self.client(segment)
                with patch.object(
                    client, "_request_json", return_value=no_order()
                ) as request:
                    payload = client.get_cliente_by_cpf(CPF)
                    self.assertEqual(
                        select_cliente_response(CPF, payload)[0][0], "SEM_PEDIDO_API"
                    )
                    self.assertEqual(client.get_cliente_by_cpf(CPF), payload)
                self.assertEqual(request.call_count, 1)
                self.assertFalse(client._lookup_diagnostics)

    def test_null_never_reconstructs_legacy_order_or_requests_order_id(self):
        for segment in ("FARMA", "PET"):
            client = self.client(segment)
            with (
                patch.object(client, "_request_json", return_value=no_order()),
                patch.object(client, "get_pedido") as get,
            ):
                self.assertEqual(
                    resolve_contact_order(
                        contact(), farm_client=client, captured_at=NOW.isoformat()
                    ),
                    (None, []),
                )
                self.assertEqual(
                    resolve_latest(contact(), client, NOW.isoformat()), (None, [])
                )
                get.assert_not_called()

    def test_analytics_weni_recompra_do_not_queue_or_admit_null_order(self):
        for segment in ("FARMA", "PET"):
            client = self.client(segment)
            with patch.object(client, "_request_json", return_value=no_order()):
                rows = [{"contact_uuid": contact()["uuid"], "cpf": CPF}]
                statuses, responses = {}, {}
                stats = validate_contacts(
                    rows,
                    farm_client=client,
                    farm_settings=FarmaliderSettings(True, "SYNTHETIC", False),
                    sync_time=NOW.isoformat(),
                    cliente_lookup_status_by_cpf=statuses,
                    cliente_responses_by_cpf=responses,
                )
                self.assertEqual(stats.api_errors, 0)
                self.assertEqual(rows[0]["farmalider_cliente_status"], "SEM_PEDIDO_API")
                orders, items, order_stats = build_orders(
                    [contact()],
                    rows_by_uuid={contact()["uuid"]: rows[0]},
                    farm_client=client,
                    sync_time=NOW.isoformat(),
                    cliente_lookup_status_by_cpf=statuses,
                    cliente_responses_by_cpf=responses,
                )
                self.assertEqual((orders, items), ([], []))
                self.assertEqual(
                    (order_stats.api_errors, order_stats.parse_errors), (0, 0)
                )
                plans = build_plans(
                    [contact()],
                    client,
                    {**STRUCTURE, "segment": segment},
                    {"schema": 1, "contacts": {}},
                    now=NOW,
                )
                self.assertEqual(plans[0]["reason"], "SEM_PEDIDO_CONFIRMADO")
                self.assertNotIn(plans[0]["action"], ("add", "replace"))
                self.assertEqual(incomplete_query_summary(plans)["contatos"], 0)
                plan = _build_contact_plan(
                    contact(),
                    context_messages=[],
                    candidate_message_ids=set(),
                    farm_client=client,
                    opt_out_group_name="Opt-Out LGPD",
                    opt_out_group_uuid="out",
                    captured_at=NOW.isoformat(),
                )
                weni_stats = UpdateStats()
                _record_validated_order(weni_stats, plan)
                self.assertEqual(weni_stats.orders_api_failed, 0)
                self.assertFalse(any(k.startswith("pedido_") for k in plan.fields))

    def test_null_preserves_identity_checks_and_existing_orders_still_require_segment(
        self,
    ):
        from tests.test_farmalider_customers import customer_snapshot

        payload = no_order()
        payload["cliente"]["cpf"] = "16899535009"
        self.assertEqual(
            select_cliente_response(CPF, payload)[0][0], "CPF_DIVERGENTE_API"
        )
        for segment in ("FARMA", "PET"):
            client = self.client(segment)
            for missing in (False, True):
                payload = customer_snapshot()
                payload["ultimoPedido"].pop("segmento", None)
                if missing:
                    payload.pop("ultimoPedido")
                with patch.object(client, "_request_json", return_value=payload):
                    with self.assertRaises(FarmaliderLookupError):
                        client.get_cliente_by_cpf(CPF)

    def test_ambiguous_null_customers_are_not_collapsed_into_one_identity(self):
        first, second = no_order(), no_order()
        second["cliente"]["id"] = 999
        self.assertEqual(
            select_cliente_response(CPF, [first, second])[0][0],
            "CPF_IDENTIDADE_AMBIGUA",
        )

    def test_real_order_wins_over_another_customer_without_order_in_same_response(self):
        from tests.test_farmalider_customers import customer_snapshot

        for segment in ("FARMA", "PET"):
            client = self.client(segment)
            full = customer_snapshot()
            full["ultimoPedido"]["segmento"] = segment
            empty = no_order()
            empty["cliente"]["id"] = 999
            with (
                patch.object(client, "_request_json", return_value=[empty, full]),
                patch("customer_observations.record_directory"),
            ):
                payload = client.get_cliente_by_cpf(CPF)
            result, selected = select_cliente_response(CPF, payload)
            self.assertEqual(result[0], "CPF_CONFIRMADO")
            self.assertEqual(selected["ultimoPedido"]["id"], 8)
