"""Prazo autorizado: remover do grupo após sete dias do pedido sem validação."""

import unittest
from contextlib import closing
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from farmalider_client import FarmaliderClient
from recompra import (
    apply_review,
    build_plans,
    load_state,
    make_review,
    propose,
)
from tests.test_farmalider_customers import customer_snapshot
from tests.test_recompra import NOW, STRUCTURE, fixture
from tests.test_recompra_prevention import weni_fixture

REASON = "PEDIDO_PENDENTE_7_DIAS"


class PendingDeadlineTests(unittest.TestCase):
    def person(self, age=timedelta(days=8), *, grouped=True):
        person = fixture(grouped=grouped)[0]
        person["fields"]["pedido_data"] = (NOW - age).isoformat()
        return person

    def test_exact_seven_day_threshold_for_both_profiles(self):
        for segment in ("FARMA", "PET"):
            for age, due in (
                (timedelta(days=7, seconds=-1), False),
                (timedelta(days=7), True),
                (timedelta(days=8), True),
            ):
                with self.subTest(segment=segment, age=age):
                    plan = propose(
                        self.person(age),
                        {"status_confirmacao": "CPF_NAO_CONFIRMADO_BASE_GERAL"},
                        [],
                        {**STRUCTURE, "segment": segment},
                        now=NOW,
                    )
                    self.assertEqual(plan["action"], "remove" if due else "")
                    self.assertEqual(plan["reason"] == REASON, due)
                    self.assertEqual(plan["fields"], {})
                    self.assertIsNone(plan["purchase"])

    def test_all_incomplete_queries_keep_the_same_preventive_deadline(self):
        for code in (
            "ERRO_API",
            "ERRO_BASE_GERAL_INCOMPLETA",
            "CPF_NAO_CONFIRMADO_BASE_GERAL",
            "PEDIDO_NAO_CONFIRMADO_BASE_GERAL",
        ):
            with self.subTest(code=code):
                plan = propose(
                    self.person(), {"status_confirmacao": code}, [], STRUCTURE, now=NOW
                )
                self.assertEqual(plan["action"], "remove")
                self.assertEqual(plan["reason"], REASON)
                self.assertEqual(plan["order_resolution_status"], code)

    def test_missing_invalid_or_future_order_date_does_not_guess_a_deadline(self):
        for date in ("", "invalid", (NOW + timedelta(days=1)).isoformat()):
            person = self.person()
            person["fields"]["pedido_data"] = date
            plan = propose(
                person,
                {"status_confirmacao": "PEDIDO_NAO_CONFIRMADO_BASE_GERAL"},
                [],
                STRUCTURE,
                {"purchase": {"data_hora": (NOW - timedelta(days=100)).isoformat()}},
                now=NOW,
            )
            self.assertEqual(plan["action"], "")
            self.assertNotEqual(plan["reason"], REASON)

    def test_contact_outside_group_is_never_admitted_by_expired_pending(self):
        plan = propose(
            self.person(grouped=False),
            {"status_confirmacao": "ERRO_API"},
            [],
            STRUCTURE,
            now=NOW,
        )
        self.assertEqual(plan["action"], "")
        self.assertEqual(plan["fields"], {})

    def test_apply_removes_only_group_and_keeps_audit_state_and_pending_report(self):
        import json

        from recompra import atomic_json

        person = self.person()
        weni, live = weni_fixture("FARMA", [person])
        with (
            TemporaryDirectory() as folder,
            closing(FarmaliderClient("synthetic")) as farm,
            patch.object(farm, "_request_json", return_value=[]) as request,
            patch("recompra.inspect_structure", return_value=STRUCTURE),
        ):
            state_path = Path(folder) / "state.json"
            state = load_state(state_path)
            previous = {"orders": {"8": {"admitted": True, "pending": False}}}
            state["contacts"][person["uuid"]] = deepcopy(previous)
            atomic_json(state_path, state)
            plans = build_plans([person], farm, STRUCTURE, state, now=NOW)
            self.assertEqual(plans[0]["action"], "remove")
            weni.contact_group_action.assert_not_called()
            review = make_review(plans, STRUCTURE, now=NOW, state=state)
            audit = Path(folder) / "audit.jsonl"
            report = Path(folder) / "application.json"
            result = apply_review(
                review,
                weni,
                farm,
                state_path=state_path,
                audit_path=audit,
                pending_report_path=report,
                now_fn=lambda: NOW,
            )
            self.assertEqual(result, {"aplicados": 1, "consultas_pendentes": 1})
            self.assertEqual(live[person["uuid"]]["fields"], person["fields"])
            self.assertEqual(live[person["uuid"]]["groups"], [])
            self.assertEqual(
                load_state(state_path)["contacts"][person["uuid"]], previous
            )
            weni.update_contact_fields.assert_not_called()
            weni.contact_group_action.assert_called_once_with(
                person["uuid"], action="remove", group=STRUCTURE["group_uuid"]
            )
            events = [json.loads(line) for line in audit.read_text().splitlines()]
            applied = next(e for e in events if e["status"] == "APLICADO")
            self.assertEqual(applied["reason"], REASON)
            self.assertTrue(applied["revalidation_pending"])
            self.assertTrue(applied["group_removal_confirmed"])
            self.assertEqual(applied["order_date"], person["fields"]["pedido_data"])
            self.assertTrue(
                json.loads(report.read_text())["pendencias"][0][
                    "group_removal_confirmed"
                ]
            )
            self.assertEqual(request.call_count, 2)
            # A nova revisão revalida, sem repetir a remoção do grupo já vazio.
            farm.reset_execution_reads()
            state = load_state(state_path)
            plans = build_plans(list(live.values()), farm, STRUCTURE, state, now=NOW)
            review = make_review(plans, STRUCTURE, now=NOW, state=state)
            result = apply_review(
                review,
                weni,
                farm,
                state_path=state_path,
                audit_path=audit,
                now_fn=lambda: NOW,
            )
            self.assertEqual(result, {"consultas_pendentes": 1})
            self.assertEqual(weni.contact_group_action.call_count, 1)

    def test_confirmation_during_apply_cancels_old_removal_proposal(self):
        person = self.person()
        weni, live = weni_fixture("FARMA", [person])
        with (
            TemporaryDirectory() as folder,
            closing(FarmaliderClient("synthetic")) as farm,
            patch.object(farm, "_request_json", return_value=[]) as request,
            patch("recompra.inspect_structure", return_value=STRUCTURE),
        ):
            path = Path(folder) / "state.json"
            state = load_state(path)
            plans = build_plans([person], farm, STRUCTURE, state, now=NOW)
            review = make_review(plans, STRUCTURE, now=NOW, state=state)
            payload = customer_snapshot()
            payload["ultimoPedido"]["emissao"] = person["fields"]["pedido_data"]
            request.return_value = [payload]
            result = apply_review(
                review,
                weni,
                farm,
                state_path=path,
                audit_path=Path(folder) / "audit.jsonl",
                now_fn=lambda: NOW,
            )
            self.assertEqual(result, {"conflitos": 1})
            self.assertTrue(live[person["uuid"]]["groups"])
            weni.contact_group_action.assert_not_called()
            weni.update_contact_fields.assert_not_called()

    def test_date_changed_after_review_blocks_removal(self):
        person = self.person()
        weni, live = weni_fixture("FARMA", [person])
        with (
            TemporaryDirectory() as folder,
            closing(FarmaliderClient("synthetic")) as farm,
            patch.object(farm, "_request_json", return_value=[]),
            patch("recompra.inspect_structure", return_value=STRUCTURE),
        ):
            path = Path(folder) / "state.json"
            state = load_state(path)
            plans = build_plans([person], farm, STRUCTURE, state, now=NOW)
            review = make_review(plans, STRUCTURE, now=NOW, state=state)
            live[person["uuid"]]["fields"]["pedido_data"] = NOW.isoformat()
            result = apply_review(
                review,
                weni,
                farm,
                state_path=path,
                audit_path=Path(folder) / "audit.jsonl",
                now_fn=lambda: NOW,
            )
            self.assertEqual(result, {"conflitos": 1})
            weni.contact_group_action.assert_not_called()

    def test_removed_contact_can_be_revalidated_and_admitted_with_existing_guards(self):
        person = self.person()
        weni, live = weni_fixture("FARMA", [person])
        with (
            TemporaryDirectory() as folder,
            closing(FarmaliderClient("synthetic")) as farm,
            patch.object(farm, "_request_json", return_value=[]) as request,
            patch("recompra.inspect_structure", return_value=STRUCTURE),
        ):
            path = Path(folder) / "state.json"
            audit = Path(folder) / "audit.jsonl"
            state = load_state(path)
            plans = build_plans([person], farm, STRUCTURE, state, now=NOW)
            review = make_review(plans, STRUCTURE, now=NOW, state=state)
            apply_review(
                review,
                weni,
                farm,
                state_path=path,
                audit_path=audit,
                now_fn=lambda: NOW,
            )
            payload = customer_snapshot()
            payload["ultimoPedido"]["emissao"] = person["fields"]["pedido_data"]
            request.return_value = [payload]
            farm.reset_execution_reads()
            state = load_state(path)
            plans = build_plans(list(live.values()), farm, STRUCTURE, state, now=NOW)
            self.assertEqual(plans[0]["action"], "add")
            review = make_review(plans, STRUCTURE, now=NOW, state=state)
            result = apply_review(
                review,
                weni,
                farm,
                state_path=path,
                audit_path=audit,
                now_fn=lambda: NOW,
            )
            self.assertEqual(result, {"aplicados": 1})
            self.assertTrue(live[person["uuid"]]["groups"])
            self.assertTrue(
                load_state(path)["contacts"][person["uuid"]]["orders"]["8"]["admitted"]
            )
            # Uma admissão já registrada continua bloqueando outra entrada do mesmo pedido.
            saved = load_state(path)["contacts"][person["uuid"]]
            outside = deepcopy(live[person["uuid"]])
            outside["groups"] = []
            farm.reset_execution_reads()
            plans = build_plans(
                [outside],
                farm,
                STRUCTURE,
                {"contacts": {person["uuid"]: saved}},
                now=NOW,
            )
            self.assertEqual(plans[0]["action"], "")
            self.assertEqual(plans[0]["reason"], "PEDIDO_JA_ADMITIDO_OU_INDETERMINADO")

    def test_date_change_while_general_query_is_running_blocks_removal(self):
        person = self.person()
        weni, live = weni_fixture("FARMA", [person])
        with (
            TemporaryDirectory() as folder,
            closing(FarmaliderClient("synthetic")) as farm,
            patch.object(farm, "_request_json", return_value=[]) as request,
            patch("recompra.inspect_structure", return_value=STRUCTURE),
        ):
            path = Path(folder) / "state.json"
            state = load_state(path)
            plans = build_plans([person], farm, STRUCTURE, state, now=NOW)
            review = make_review(plans, STRUCTURE, now=NOW, state=state)

            def change_date(*args, **kwargs):
                live[person["uuid"]]["fields"]["pedido_data"] = NOW.isoformat()
                return []

            request.side_effect = change_date
            result = apply_review(
                review,
                weni,
                farm,
                state_path=path,
                audit_path=Path(folder) / "audit.jsonl",
                now_fn=lambda: NOW,
            )
            self.assertEqual(result, {"conflitos": 1})
            self.assertTrue(live[person["uuid"]]["groups"])
            weni.contact_group_action.assert_not_called()

    def test_failure_of_last_contact_read_defers_only_that_contact(self):
        from weni_client import WeniError

        person = self.person()
        person["uuid"] = "pending"
        person["fields"]["cpf"] = "11144477735"
        good = fixture()[0]
        weni, live = weni_fixture("FARMA", [person, good])
        seen = 0

        def get_contact(*, uuid):
            nonlocal seen
            if uuid == person["uuid"]:
                seen += 1
                if seen == 2:
                    raise WeniError("synthetic timeout")
            return deepcopy(live.get(uuid))

        weni.get_contact.side_effect = get_contact
        with (
            TemporaryDirectory() as folder,
            closing(FarmaliderClient("synthetic")) as farm,
            patch.object(farm, "_request_json", return_value=[customer_snapshot()]),
            patch("recompra.inspect_structure", return_value=STRUCTURE),
        ):
            path = Path(folder) / "state.json"
            state = load_state(path)
            plans = build_plans([person, good], farm, STRUCTURE, state, now=NOW)
            review = make_review(plans, STRUCTURE, now=NOW, state=state)
            result = apply_review(
                review,
                weni,
                farm,
                state_path=path,
                audit_path=Path(folder) / "audit.jsonl",
                now_fn=lambda: NOW,
            )
            self.assertEqual(result, {"aplicados": 1, "consultas_pendentes": 1})
            self.assertTrue(live[person["uuid"]]["groups"])
            self.assertTrue(live[good["uuid"]]["groups"])
            self.assertTrue(
                all(
                    call.kwargs["action"] == "add"
                    for call in weni.contact_group_action.call_args_list
                )
            )
