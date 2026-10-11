"""Evidências privadas bloqueiam D+25 sem inventar o pedido oficial."""

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch

from farmalider_client import FarmaliderError
from purchase_checks import (
    PENDING_PURCHASE_FIELD,
    contact_pending_purchase_check,
    infer_pending_purchase_check,
    load_pending_purchase_checks,
    official_order_resolves_check,
    register_pending_purchase_checks,
)
from recompra import apply_review, build_plans, load_state, make_review, propose
from tests.test_pedido_resolution import client, cliente_payload, pedido_payload
from tests.test_recompra import NOW, STRUCTURE, fixture
from weni_update import (
    UpdateStats,
    _build_contact_plan,
    _prepare_frozen_plan_for_apply,
    _purchase_check_state_payload,
    _save_state,
    load_review_snapshot,
    write_review_snapshot,
)

CHECK = {"observed_at": "2026-10-09T16:00:00-03:00", "source": "TICKET_REVISADO"}


class PurchaseChecksTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source_path = Path(self.temp.name) / "weni_state.json"
        self.state_path = Path(self.temp.name) / "recompra_state.json"

    def messages(self, *, confirmation="Seu pedido foi finalizado com sucesso."):
        return [
            {
                "id": "m1",
                "direction": "in",
                "created_on": "2026-10-09T10:00:00-03:00",
                "text": "Quero fazer um novo pedido",
            },
            {
                "id": "m2",
                "direction": "out",
                "created_on": "2026-10-09T11:00:00-03:00",
                "text": confirmation,
            },
        ]

    def register(self, check=CHECK):
        register_pending_purchase_checks({"u1": check}, path=self.source_path)

    def state(self):
        return load_state(self.state_path, purchase_checks_path=self.source_path)

    def old_purchase(self):
        contact, order, items = fixture(grouped=True)
        order["data_hora"] = "2026-09-18T12:21:00-03:00"
        contact["fields"].update(
            pedido_data="18/09/26 12:21:00", pedido_id=order["pedido_id"]
        )
        return contact, order, items

    def test_registered_check_is_private_and_preserves_checkpoint(self):
        self.source_path.write_text(
            json.dumps({"last_success_utc": "2026-10-08T12:00:00Z"}), encoding="utf-8"
        )
        self.register()
        state = json.loads(self.source_path.read_text(encoding="utf-8"))
        self.assertEqual(state["last_success_utc"], "2026-10-08T12:00:00Z")
        self.assertEqual(state["pending_purchase_checks"], {"u1": CHECK})
        self.assertEqual(
            set(state["pending_purchase_checks"]["u1"]), {"observed_at", "source"}
        )

    def test_resolution_does_not_clear_newer_concurrent_evidence(self):
        self.register()
        newer = {**CHECK, "observed_at": "2026-10-10T16:00:00-03:00"}
        self.register(newer)
        register_pending_purchase_checks(
            {}, path=self.source_path, resolved={"u1": CHECK}
        )
        self.assertEqual(load_pending_purchase_checks(self.source_path), {"u1": newer})

    def test_malformed_private_state_blocks_instead_of_ignoring_restriction(self):
        self.source_path.write_text("invalid", encoding="utf-8")
        with self.assertRaises(RuntimeError):
            self.state()

    def test_new_request_and_confirmation_in_same_day_create_only_restriction(self):
        check = infer_pending_purchase_check(
            self.messages(), captured_at=NOW.isoformat()
        )
        self.assertEqual(check["observed_at"], "2026-10-09T11:00:00-03:00")
        self.assertEqual(set(check), {"observed_at", "source"})

    def test_late_delivery_or_confirmation_without_new_request_is_insufficient(self):
        for text in (
            "Seu pedido está em rota",
            "Seu pedido saiu para entrega",
            "Seu pedido não foi finalizado",
        ):
            with self.subTest(text=text):
                self.assertIsNone(
                    infer_pending_purchase_check(
                        self.messages(confirmation=text), captured_at=NOW.isoformat()
                    )
                )
        messages = self.messages()
        self.assertIsNone(
            infer_pending_purchase_check(messages[1:], captured_at=NOW.isoformat())
        )
        messages[0]["created_on"] = "2026-10-08T10:00:00-03:00"
        self.assertIsNone(
            infer_pending_purchase_check(messages, captured_at=NOW.isoformat())
        )

    def test_invalid_or_future_message_times_are_not_purchase_evidence(self):
        for emitted in ("invalid", "2026-10-10T10:00:00-03:00"):
            messages = self.messages()
            messages[1]["created_on"] = emitted
            self.assertIsNone(
                infer_pending_purchase_check(messages, captured_at=NOW.isoformat())
            )

    def test_yes_after_specific_new_order_offer_is_purchase_request(self):
        messages = self.messages()
        messages[0]["text"] = "SIM"
        offer = {
            "id": "m0",
            "direction": "out",
            "created_on": "2026-10-09T09:59:00-03:00",
            "text": "Gostaria de fazer um novo pedido?",
        }
        check = infer_pending_purchase_check(
            [messages[1], messages[0], offer], captured_at=NOW.isoformat()
        )
        self.assertEqual(check["observed_at"], "2026-10-09T11:00:00-03:00")

    def test_yes_to_lgpd_age_delivery_or_older_offer_is_not_new_order(self):
        for text in (
            "Você aceita a LGPD para fazer um pedido?",
            "Você é maior de idade e gostaria de fazer um pedido?",
            "Deseja acompanhar o status ou fazer um pedido?",
            "Gostaria de fazer um pedido com entrega?",
        ):
            messages = self.messages()
            messages[0]["text"] = "SIM"
            messages.insert(
                0,
                {
                    "id": "m0",
                    "direction": "out",
                    "created_on": "2026-10-09T09:59:00-03:00",
                    "text": text,
                },
            )
            with self.subTest(text=text):
                self.assertIsNone(
                    infer_pending_purchase_check(messages, captured_at=NOW.isoformat())
                )

    def test_automatic_check_is_not_created_when_weni_reference_covers_day(self):
        customer = cliente_payload()
        pedido = pedido_payload()
        customer["ultimoPedido"]["emissao"] = pedido["capa"]["emissao"] = (
            "2026-09-18T12:21:00"
        )
        for reference in ("09/10/26 08:00:00", "10/10/26 08:00:00"):
            contact, _, _ = self.old_purchase()
            contact["fields"]["pedido_data"] = reference
            plan = _build_contact_plan(
                contact,
                context_messages=self.messages(),
                candidate_message_ids={"m1", "m2"},
                farm_client=client(cliente=customer, pedido=pedido),
                opt_out_group_name="Opt-Out LGPD",
                opt_out_group_uuid="g-out",
                captured_at=NOW.isoformat(),
            )
            with self.subTest(reference=reference):
                self.assertNotIn("__pending_purchase_check", plan.guards)
                self.assertNotIn("__pending_purchase_check_resolved", plan.guards)
                self.assertNotIn(PENDING_PURCHASE_FIELD, plan.fields)

    def test_explicit_check_is_not_cleared_by_newer_weni_reference_alone(self):
        customer = cliente_payload()
        pedido = pedido_payload()
        customer["ultimoPedido"]["emissao"] = pedido["capa"]["emissao"] = (
            "2026-09-18T12:21:00"
        )
        contact, _, _ = self.old_purchase()
        contact["fields"]["pedido_data"] = "10/10/26 08:00:00"
        plan = _build_contact_plan(
            contact,
            context_messages=self.messages(),
            candidate_message_ids={"m1", "m2"},
            farm_client=client(cliente=customer, pedido=pedido),
            opt_out_group_name="Opt-Out LGPD",
            opt_out_group_uuid="g-out",
            captured_at=NOW.isoformat(),
            pending_purchase_check=CHECK,
        )
        self.assertIn("__pending_purchase_check", plan.guards)
        self.assertEqual(plan.fields[PENDING_PURCHASE_FIELD], CHECK["observed_at"])

    def test_automatic_check_is_not_created_when_official_purchase_covers_day(self):
        customer = cliente_payload()
        pedido = pedido_payload()
        customer["ultimoPedido"]["emissao"] = pedido["capa"]["emissao"] = (
            "2026-10-09T08:00:00"
        )
        contact, _, _ = self.old_purchase()
        plan = _build_contact_plan(
            contact,
            context_messages=self.messages(),
            candidate_message_ids={"m1", "m2"},
            farm_client=client(cliente=customer, pedido=pedido),
            opt_out_group_name="Opt-Out LGPD",
            opt_out_group_uuid="g-out",
            captured_at=NOW.isoformat(),
        )
        self.assertNotIn("__pending_purchase_check", plan.guards)
        self.assertNotIn("__pending_purchase_check_resolved", plan.guards)
        self.assertNotIn(PENDING_PURCHASE_FIELD, plan.fields)
        self.assertEqual(plan.fields["pedido_data"], "09/10/26 08:00:00")

    def test_old_official_order_removes_group_without_changing_fields(self):
        contact, order, items = self.old_purchase()
        plan = propose(
            contact, order, items, STRUCTURE, {"pending_purchase_check": CHECK}, now=NOW
        )
        self.assertEqual(plan["reason"], "PEDIDO_POSTERIOR_PENDENTE_API")
        self.assertEqual(plan["action"], "remove")
        self.assertEqual(plan["fields"], {})
        self.assertEqual(plan["event_at"], "")

    def test_portable_weni_field_blocks_without_any_local_state(self):
        contact, order, items = self.old_purchase()
        contact["fields"][PENDING_PURCHASE_FIELD] = {"value": CHECK["observed_at"]}
        check = contact_pending_purchase_check(contact)
        self.assertEqual(check["source"], "WENI_PEDIDO_REVISAO_PENDENTE")
        plan = propose(contact, order, items, STRUCTURE, now=NOW)
        self.assertEqual(plan["reason"], "PEDIDO_POSTERIOR_PENDENTE_API")
        self.assertEqual(plan["action"], "remove")
        self.assertEqual(plan["fields"], {})
        self.assertEqual(
            plan["guard"]["fields"][PENDING_PURCHASE_FIELD], CHECK["observed_at"]
        )

    def test_portable_weni_field_keeps_block_when_api_fails(self):
        contact, _, _ = self.old_purchase()
        contact["fields"][PENDING_PURCHASE_FIELD] = CHECK["observed_at"]
        with patch("recompra.resolve_latest", side_effect=FarmaliderError("synthetic")):
            plans = build_plans(
                [contact],
                Mock(),
                STRUCTURE,
                {"schema": 1, "contacts": {}},
                now=NOW,
                workers=1,
            )
        self.assertEqual(plans[0]["reason"], "PEDIDO_POSTERIOR_PENDENTE_API")
        self.assertEqual(plans[0]["action"], "remove")

    def test_resolved_portable_marker_has_no_pending_check(self):
        contact, _, _ = self.old_purchase()
        contact["fields"][PENDING_PURCHASE_FIELD] = "resolvido"
        self.assertIsNone(contact_pending_purchase_check(contact))

    def test_same_day_official_purchase_resolves_portable_field_without_writing_it(
        self,
    ):
        contact, order, items = fixture(0, grouped=True)
        contact["fields"][PENDING_PURCHASE_FIELD] = CHECK["observed_at"]
        plan = propose(contact, order, items, STRUCTURE, now=NOW)
        self.assertTrue(plan["purchase_check_resolved"])
        self.assertEqual(plan["reason"], "JANELA_0_A_25")
        self.assertNotIn(PENDING_PURCHASE_FIELD, plan["fields"])

    def test_invalid_portable_marker_blocks_instead_of_ignoring_it(self):
        contact, _, _ = self.old_purchase()
        contact["fields"][PENDING_PURCHASE_FIELD] = "sim"
        with self.assertRaises(RuntimeError):
            contact_pending_purchase_check(contact)

    def test_weni_clears_portable_marker_only_after_official_day_catches_up(self):
        contact, _, _ = self.old_purchase()
        contact["fields"][PENDING_PURCHASE_FIELD] = CHECK["observed_at"]
        customer = cliente_payload()
        pedido = pedido_payload()
        customer["ultimoPedido"]["emissao"] = pedido["capa"]["emissao"] = (
            "2026-10-09T08:00:00"
        )
        plan = _build_contact_plan(
            contact,
            context_messages=[],
            candidate_message_ids=set(),
            farm_client=client(cliente=customer, pedido=pedido),
            opt_out_group_name="Opt-Out LGPD",
            opt_out_group_uuid="g-out",
            captured_at=NOW.isoformat(),
            available_weni_fields={
                PENDING_PURCHASE_FIELD,
                "pedido_data",
                "pedido_id",
                "pedido_status",
                "pedido_produtos",
                "pedido_quantidade_itens",
                "pedido_valor_produtos",
                "pedido_valor",
                "pedido_forma_pagamento",
            },
        )
        self.assertEqual(plan.fields[PENDING_PURCHASE_FIELD], "resolvido")
        self.assertEqual(plan.fields["pedido_data"], "09/10/26 08:00:00")
        self.assertIn("__pending_purchase_check_resolved", plan.guards)

    def test_optional_portable_field_does_not_become_required(self):
        customer = cliente_payload()
        pedido = pedido_payload()
        customer["ultimoPedido"]["emissao"] = pedido["capa"]["emissao"] = (
            "2026-09-18T12:21:00"
        )
        contact, _, _ = self.old_purchase()
        plan = _build_contact_plan(
            contact,
            context_messages=[],
            candidate_message_ids=set(),
            farm_client=client(cliente=customer, pedido=pedido),
            opt_out_group_name="Opt-Out LGPD",
            opt_out_group_uuid="g-out",
            captured_at=NOW.isoformat(),
            pending_purchase_check=CHECK,
            available_weni_fields=set(),
        )
        self.assertNotIn(PENDING_PURCHASE_FIELD, plan.fields)
        self.assertIn("__pending_purchase_check", plan.guards)

    def test_portable_marker_change_after_review_conflicts_before_write(self):
        self.register()
        contact, order, items = self.old_purchase()
        contact["fields"][PENDING_PURCHASE_FIELD] = CHECK["observed_at"]
        review = self.review(contact, order, items)
        changed = deepcopy(contact)
        changed["fields"][PENDING_PURCHASE_FIELD] = "2026-10-10T00:00:00-03:00"
        weni = Mock()
        weni.get_contact.return_value = changed
        with patch("recompra.inspect_structure", return_value=STRUCTURE):
            result = apply_review(
                review,
                weni,
                Mock(),
                state_path=self.state_path,
                purchase_checks_path=self.source_path,
                now_fn=lambda: NOW,
                audit_path=Path(self.temp.name) / "audit.jsonl",
            )
        self.assertEqual(result["conflitos"], 1)
        weni.contact_group_action.assert_not_called()
        weni.update_contact_fields.assert_not_called()

    def test_only_valid_official_order_same_or_later_day_resolves_check(self):
        _, order, _ = self.old_purchase()
        self.assertFalse(official_order_resolves_check(CHECK, order))
        order["data_hora"] = "2026-10-09T08:00:00-03:00"
        self.assertTrue(official_order_resolves_check(CHECK, order))
        order["status_validacao"] = "ERRO"
        self.assertFalse(official_order_resolves_check(CHECK, order))

    def test_api_failure_keeps_pending_removal(self):
        self.register()
        contact, _, _ = self.old_purchase()
        with patch("recompra.resolve_latest", side_effect=FarmaliderError("synthetic")):
            plans = build_plans(
                [contact], Mock(), STRUCTURE, self.state(), now=NOW, workers=1
            )
        self.assertEqual(plans[0]["reason"], "PEDIDO_POSTERIOR_PENDENTE_API")
        self.assertEqual(plans[0]["action"], "remove")

    def review(self, contact, order, items):
        state = self.state()
        with patch("recompra.resolve_latest", return_value=(order, items)):
            plans = build_plans([contact], Mock(), STRUCTURE, state, now=NOW, workers=1)
        return make_review(plans, STRUCTURE, now=NOW, state=state)

    def test_review_integrity_blocks_newer_evidence_before_writes(self):
        self.register()
        contact, order, items = self.old_purchase()
        review = self.review(contact, order, items)
        self.register({**CHECK, "observed_at": "2026-10-10T16:00:00-03:00"})
        weni = Mock()
        with patch("recompra.inspect_structure", return_value=STRUCTURE):
            with self.assertRaisesRegex(RuntimeError, "Estado mudou"):
                apply_review(
                    review,
                    weni,
                    Mock(),
                    state_path=self.state_path,
                    purchase_checks_path=self.source_path,
                    now_fn=lambda: NOW,
                )
        weni.update_contact_fields.assert_not_called()
        weni.contact_group_action.assert_not_called()

    def test_apply_removes_old_campaign_and_keeps_pending_check(self):
        self.register()
        contact, order, items = self.old_purchase()
        review = self.review(contact, order, items)
        removed = deepcopy(contact)
        removed["groups"] = []
        weni = Mock()
        weni.get_contact.side_effect = [contact, removed]
        with (
            patch("recompra.inspect_structure", return_value=STRUCTURE),
            patch("recompra.resolve_latest", return_value=(order, items)),
        ):
            result = apply_review(
                review,
                weni,
                Mock(),
                state_path=self.state_path,
                purchase_checks_path=self.source_path,
                now_fn=lambda: NOW,
                audit_path=Path(self.temp.name) / "audit.jsonl",
            )
        self.assertEqual(result["aplicados"], 1)
        weni.contact_group_action.assert_called_once_with(
            "u1", action="remove", group=STRUCTURE["group_uuid"]
        )
        weni.update_contact_fields.assert_not_called()
        self.assertEqual(load_pending_purchase_checks(self.source_path), {"u1": CHECK})

    def test_confirmed_same_day_order_clears_check_after_verified_apply(self):
        self.register()
        contact, order, items = fixture(0, grouped=True)
        contact["fields"].update(
            pedido_data=order["data_hora"],
            pedido_produtos='"Produto sintético, 30 cápsulas"',
        )
        review = self.review(contact, order, items)
        self.assertTrue(review["plans"][0]["purchase_check_resolved"])
        weni = Mock()
        weni.get_contact.return_value = contact
        with (
            patch("recompra.inspect_structure", return_value=STRUCTURE),
            patch("recompra.resolve_latest", return_value=(order, items)),
        ):
            apply_review(
                review,
                weni,
                Mock(),
                state_path=self.state_path,
                purchase_checks_path=self.source_path,
                now_fn=lambda: NOW,
                audit_path=Path(self.temp.name) / "audit.jsonl",
            )
        self.assertEqual(load_pending_purchase_checks(self.source_path), {})
        self.assertEqual(self.state().get("pending_purchase_checks"), {})

    def test_weni_frozen_review_preserves_pending_restriction_and_group_removal(self):
        customer = cliente_payload()
        pedido = pedido_payload()
        customer["ultimoPedido"]["emissao"] = pedido["capa"]["emissao"] = (
            "2026-09-18T12:21:00"
        )
        contact, _, _ = self.old_purchase()
        plan = _build_contact_plan(
            contact,
            context_messages=self.messages(),
            candidate_message_ids={"m1", "m2"},
            farm_client=client(cliente=customer, pedido=pedido),
            opt_out_group_name="Opt-Out LGPD",
            opt_out_group_uuid="g-out",
            captured_at=NOW.isoformat(),
        )
        self.assertIn("__pending_purchase_check", plan.guards)
        self.assertNotIn("pedido_data", plan.fields)
        self.assertTrue(
            any(
                action.action == "remove" and action.group == STRUCTURE["group_uuid"]
                for action in plan.group_actions
            )
        )
        path = Path(self.temp.name) / "full_review.json"
        write_review_snapshot(
            [plan],
            UpdateStats(),
            full=True,
            json_path=path,
            captured_at_utc=NOW.isoformat(),
        )
        loaded, _, _ = load_review_snapshot(full=True, json_path=path)
        prepared, reason = _prepare_frozen_plan_for_apply(
            loaded[0],
            contact,
            opt_in_group_name="Opt-In LGPD",
            opt_in_group_uuid="g-in",
            opt_out_group_name="Opt-Out LGPD",
            opt_out_group_uuid="g-out",
        )
        self.assertEqual(reason, "")
        self.assertIsNotNone(prepared)
        _save_state(_purchase_check_state_payload(loaded), path=self.source_path)
        self.assertIn("u1", load_pending_purchase_checks(self.source_path))


if __name__ == "__main__":
    unittest.main()
