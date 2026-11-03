"""Índice incremental por segmento, incluindo relógio e confirmação persistida."""

import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from farmalider_customers import CustomerDirectory
from recompra import apply_review, load_state, make_review, propose
from recompra_incremental import annotate_plans, remember_plan, select_contacts
from tests.test_farmalider_customers import customer_snapshot
from tests.test_recompra import NOW, STRUCTURE, fixture


class IncrementalSelectionTests(unittest.TestCase):
    def setup_case(self, segment="FARMA", days=35):
        c, order, items = fixture(days)
        structure = {**STRUCTURE, "segment": segment}
        payload = customer_snapshot()
        payload["ultimoPedido"]["segmento"] = segment
        farm = SimpleNamespace(
            customer_directory=CustomerDirectory([payload], segment=segment)
        )
        state = {"schema": 1, "contacts": {}}
        c["fields"].update(propose(c, order, items, structure, now=NOW)["fields"])
        return c, order, items, structure, farm, state

    def baseline(self, segment="FARMA", days=35):
        c, order, items, structure, farm, state = self.setup_case(segment, days)
        selected, sources, selection = select_contacts([c], farm, structure, state, NOW)
        self.assertEqual(selected, [c])
        plan = propose(c, order, items, structure, now=NOW)
        annotate_plans([plan], sources, selection)
        remember_plan(state, plan, structure, NOW)
        return c, order, items, structure, farm, state, plan

    def test_unchanged_customers_are_skipped_but_full_always_selects(self):
        for segment in ("FARMA", "PET"):
            with self.subTest(segment=segment):
                c, _, _, structure, farm, state, _ = self.baseline(segment)
                self.assertEqual(
                    select_contacts([c], farm, structure, state, NOW)[0], []
                )
                self.assertEqual(
                    select_contacts([c], farm, structure, state, NOW, full=True)[0], [c]
                )

    def test_changed_customer_order_status_consent_and_new_contact_are_selected(self):
        for change in ("order", "cancel", "consent", "new"):
            c, _, _, structure, farm, state, _ = self.baseline()
            if change in {"order", "cancel"}:
                snapshot = customer_snapshot()
                snapshot["ultimoPedido"]["id" if change == "order" else "status"] = (
                    99 if change == "order" else 3
                )
                if change == "order":
                    snapshot["itens"][0]["codPedido"] = 99
                farm.customer_directory = CustomerDirectory([snapshot])
            elif change == "consent":
                c["fields"]["marketing_opt_in"] = "recusado"
            else:
                c["uuid"] = "new"
            self.assertEqual(select_contacts([c], farm, structure, state, NOW)[0], [c])

    def test_calendar_expiry_and_pending_checks_are_never_skipped(self):
        c, _, _, structure, farm, state, _ = self.baseline(days=24)
        # Na baseline há inclusão proposta; simular somente campos físicos,
        # nunca afirmar confirmação real de um POST neste teste de seleção.
        c["groups"] = [{"uuid": structure["group_uuid"]}]
        self.assertEqual(
            select_contacts([c], farm, structure, state, NOW + timedelta(days=1))[0],
            [c],
        )
        state["pending_purchase_checks"] = {c["uuid"]: {"pending": True}}
        self.assertEqual(select_contacts([c], farm, structure, state, NOW)[0], [c])

    def test_missing_or_incomplete_source_never_uses_negative_cache(self):
        c, _, _, structure, farm, state, _ = self.baseline()
        payload = customer_snapshot()
        payload.pop("itens")
        for directory in (None, CustomerDirectory([]), CustomerDirectory([payload])):
            farm.customer_directory = directory
            self.assertEqual(select_contacts([c], farm, structure, state, NOW)[0], [c])

    def test_wrong_segment_state_is_refused(self):
        c, _, _, structure, farm, state, _ = self.baseline()
        state["segment"] = "PET"
        with self.assertRaisesRegex(RuntimeError, "segmento"):
            select_contacts([c], farm, structure, state, NOW)

    def test_local_only_apply_checkpoints_once_and_next_incremental_selects_zero(self):
        c, order, items, structure, farm, state = self.setup_case()
        _, sources, selection = select_contacts([c], farm, structure, state, NOW)
        plan = propose(c, order, items, structure, now=NOW)
        self.assertFalse(plan["fields"])
        self.assertFalse(plan["action"])
        annotate_plans([plan], sources, selection)
        review = make_review([plan], structure, now=NOW, state=state)
        weni = Mock()
        with (
            tempfile.TemporaryDirectory() as folder,
            patch("recompra.inspect_structure", return_value=structure),
        ):
            path = Path(folder) / "state.json"
            result = apply_review(
                review,
                weni,
                farm,
                state_path=path,
                audit_path=Path(folder) / "audit.jsonl",
                now_fn=lambda: NOW,
            )
            self.assertEqual(result, {"estado_local": 1})
            persisted = load_state(path)
            self.assertEqual(
                select_contacts([c], farm, structure, persisted, NOW)[0], []
            )
        weni.get_contact.assert_not_called()
        weni.update_contact_fields.assert_not_called()
        weni.contact_group_action.assert_not_called()
