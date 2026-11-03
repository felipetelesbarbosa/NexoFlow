"""Perfis do mesmo CPF mantêm pedidos diferentes, sem atribuição cruzada."""

import tempfile
import unittest
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from recompra import apply_review, make_review, propose
from tests.test_recompra import NOW, STRUCTURE, fixture
from weni_update import PURCHASE_FIELDS, _build_contact_plan, audit_plans


class DistinctOrderUpdateTests(unittest.TestCase):
    def test_weni_preserves_order_fields_but_still_enriches_contact(self):
        contact, _, _ = fixture(10)
        contact["fields"].update(
            {"pedido_id": "55", "pedido_data": (NOW - timedelta(days=10)).isoformat()}
        )
        with (
            patch("weni_update.selected_customer", return_value=None),
            patch("weni_update._apply_purchase_candidate") as purchase,
        ):
            plan = _build_contact_plan(
                contact,
                context_messages=[],
                candidate_message_ids=set(),
                farm_client=None,
                opt_out_group_name="Opt-Out LGPD",
                opt_out_group_uuid="",
                captured_at=NOW.isoformat(),
                preserve_distinct_orders=True,
            )
        purchase.assert_not_called()
        self.assertFalse(set(plan.fields) & PURCHASE_FIELDS)
        self.assertEqual(plan.guards["pedido_id"], "55")
        self.assertEqual(plan.order_resolution_status, "CPF_IDENTIDADE_AMBIGUA")
        audit_plans([plan], opt_out_group_available=True)

    def test_newer_official_order_removes_old_schedule_without_overwriting_reference(
        self,
    ):
        contact, order, items = fixture(5, grouped=True)
        contact["fields"].update(
            {"pedido_id": "55", "pedido_data": (NOW - timedelta(days=10)).isoformat()}
        )
        contact["_distinct_order_refs"] = ["55"]
        plan = propose(contact, order, items, STRUCTURE, now=NOW)
        self.assertEqual(plan["action"], "remove")
        self.assertEqual(plan["reason"], "PEDIDO_ANTIGO_BLOQUEADO")
        self.assertEqual(plan["fields"], {})
        live = deepcopy(contact)
        live.pop("_distinct_order_refs")
        weni = Mock()
        weni.get_contact.side_effect = lambda **kw: deepcopy(live)
        weni.contact_group_action.side_effect = lambda *a, **kw: live.update(groups=[])
        with (
            tempfile.TemporaryDirectory() as folder,
            patch("recompra.inspect_structure", return_value=STRUCTURE),
            patch("recompra._resolve_checked_contact", return_value=(order, items)),
        ):
            result = apply_review(
                make_review([plan], STRUCTURE, now=NOW),
                weni,
                Mock(),
                state_path=Path(folder) / "state.json",
                audit_path=Path(folder) / "audit.jsonl",
                now_fn=lambda: NOW,
            )
        self.assertEqual(result.get("aplicados"), 1)
        weni.update_contact_fields.assert_not_called()
        weni.contact_group_action.assert_called_once_with(
            "u1", action="remove", group=STRUCTURE["group_uuid"]
        )

    def test_matching_reference_still_allows_valid_campaign(self):
        contact, order, items = fixture(24)
        contact["fields"]["pedido_id"] = "100"
        contact["_distinct_order_refs"] = ["100"]
        self.assertEqual(
            propose(contact, order, items, STRUCTURE, now=NOW)["action"], "add"
        )
