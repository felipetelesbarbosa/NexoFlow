"""Regressões de cursor/cache incremental: somente fontes e mutações simuladas."""

import os
import tempfile
import unittest
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from farmalider_customers import CustomerDirectory
from recompra import apply_review, atomic_json, load_state, make_review, propose
from recompra_incremental import (
    annotate_plans,
    collect_contacts,
    remember_plan,
    select_contacts,
)
from tests.test_farmalider_customers import CPF, customer_snapshot
from tests.test_recompra import NOW, STRUCTURE, fixture


class IncrementalSafetyRegressionTests(unittest.TestCase):
    def case(self):
        contact, order, items = fixture(35)
        contact["fields"].update(
            propose(contact, order, items, STRUCTURE, now=NOW)["fields"]
        )
        farm = SimpleNamespace(
            customer_directory=CustomerDirectory([customer_snapshot()])
        )
        return contact, order, items, farm

    def cached_state(self, contact, *, segment="FARMA", cursor=NOW):
        return {
            "schema": 1,
            "segment": segment,
            "contacts": {},
            "incremental": {
                "segment": segment,
                "ready": True,
                "cursor": cursor.isoformat(),
                "contacts": {contact["uuid"]: {"snapshot": deepcopy(contact)}},
            },
        }

    def test_malformed_cpf_cannot_hide_valid_contact_new_order(self):
        contact, order, items, farm = self.case()
        malformed = deepcopy(contact)
        malformed["uuid"] = "malformed"
        malformed["fields"]["cpf"] = CPF + "abc"
        state = {"schema": 1, "contacts": {}}
        _, sources, selection = select_contacts(
            [malformed, contact], farm, STRUCTURE, state, NOW
        )
        plan = propose(contact, order, items, STRUCTURE, now=NOW)
        annotate_plans([plan], sources, selection)
        remember_plan(state, plan, STRUCTURE, NOW)
        changed = customer_snapshot()
        changed["ultimoPedido"]["id"] = 99
        changed["itens"][0]["codPedido"] = 99
        farm.customer_directory = CustomerDirectory([changed])
        selected, _, _ = select_contacts(
            [malformed, contact], farm, STRUCTURE, state, NOW
        )
        self.assertIn(contact, selected)

    def test_incremental_keeps_all_conflicting_uuid_versions_for_pagination_audit(self):
        contact, order, items, farm = self.case()
        state = {"schema": 1, "contacts": {}}
        _, sources, selection = select_contacts([contact], farm, STRUCTURE, state, NOW)
        plan = propose(contact, order, items, STRUCTURE, now=NOW)
        annotate_plans([plan], sources, selection)
        remember_plan(state, plan, STRUCTURE, NOW)
        changed = deepcopy(contact)
        changed["fields"]["marketing_opt_in"] = "recusado"
        selected, _, _ = select_contacts(
            [contact, changed], farm, STRUCTURE, state, NOW
        )
        self.assertEqual(selected, [contact, changed])

    def test_copied_other_segment_state_never_drives_delta(self):
        contact, _, _, _ = self.case()
        state = self.cached_state(contact, segment="FARMA")
        weni = Mock()
        weni.iter_contacts.return_value = iter([])
        with patch.dict(os.environ, NEXOFLOW_PERFIL="PET"):
            with self.assertRaisesRegex(RuntimeError, "segmento"):
                collect_contacts(weni, state, NOW)
        weni.iter_contacts.assert_not_called()

    def test_unbound_legacy_cache_requires_full_read(self):
        contact, _, _, _ = self.case()
        state = self.cached_state(contact)
        state.pop("segment")
        state["incremental"].pop("segment")
        weni = Mock()
        weni.iter_contacts.return_value = iter([contact])
        collect_contacts(weni, state, NOW)
        weni.iter_contacts.assert_called_once_with()

    def test_future_cursor_falls_back_to_full_read(self):
        contact, _, _, _ = self.case()
        state = self.cached_state(contact, cursor=NOW + timedelta(days=1))
        weni = Mock()
        weni.iter_contacts.return_value = iter([contact])
        collect_contacts(weni, state, NOW)
        weni.iter_contacts.assert_called_once_with()

    def test_partial_apply_keeps_pending_uuid_retryable_after_cursor_advance(self):
        contact, order, items, farm = self.case()
        contact["fields"].clear()
        contact["fields"]["cpf"] = CPF
        state = {"schema": 1, "contacts": {}}
        _, sources, selection = select_contacts([contact], farm, STRUCTURE, state, NOW)
        plan = propose(contact, order, items, STRUCTURE, now=NOW)
        self.assertTrue(plan["fields"])
        annotate_plans([plan], sources, selection)
        review = make_review([plan], STRUCTURE, now=NOW, state=state)
        review["selection"] = {
            **selection,
            "complete": True,
            "cursor": NOW.isoformat(),
            "full_refresh": True,
            "contact_uuids": [contact["uuid"]],
        }
        from weni_client import WeniError

        weni = Mock()
        weni.get_contact.side_effect = WeniError("synthetic timeout")
        with (
            tempfile.TemporaryDirectory() as folder,
            patch("recompra.inspect_structure", return_value=STRUCTURE),
        ):
            path = Path(folder) / "state.json"
            atomic_json(path, state)
            result = apply_review(
                review,
                weni,
                farm,
                state_path=path,
                audit_path=Path(folder) / "audit.jsonl",
                now_fn=lambda: NOW,
            )
            persisted = load_state(path)
        self.assertEqual(result, {"consultas_pendentes": 1})
        self.assertTrue(persisted["incremental"]["ready"])
        self.assertTrue(persisted["incremental"]["contacts"][contact["uuid"]]["retry"])
        self.assertEqual(persisted["incremental"]["cursor"], NOW.isoformat())
        weni.update_contact_fields.assert_not_called()
        weni.iter_contacts.return_value = iter([])
        merged, _ = collect_contacts(weni, persisted, NOW + timedelta(minutes=1))
        selected, _, _ = select_contacts(
            merged, farm, STRUCTURE, persisted, NOW + timedelta(minutes=1)
        )
        self.assertEqual([c["uuid"] for c in selected], [contact["uuid"]])

    def test_full_refresh_prunes_deleted_contact_cache_but_preserves_admission_history(
        self,
    ):
        contact, order, items, farm = self.case()
        ghost = deepcopy(contact)
        ghost["uuid"] = "ghost"
        state = self.cached_state(ghost)
        state["contacts"]["ghost"] = {"orders": {"100": {"admitted": True}}}
        weni = Mock()
        weni.iter_contacts.return_value = iter([contact])
        contacts, loading = collect_contacts(weni, state, NOW, full=True)
        selected, sources, selection = select_contacts(
            contacts, farm, STRUCTURE, state, NOW, full=True
        )
        selection.update(loading)
        if loading.get("full_refresh"):
            selection["contact_uuids"] = sorted(sources)
        plan = propose(selected[0], order, items, STRUCTURE, now=NOW)
        annotate_plans([plan], sources, selection)
        review = make_review([plan], STRUCTURE, now=NOW, state=state)
        review["selection"] = selection
        with (
            tempfile.TemporaryDirectory() as folder,
            patch("recompra.inspect_structure", return_value=STRUCTURE),
        ):
            path = Path(folder) / "state.json"
            atomic_json(path, state)
            apply_review(
                review,
                weni,
                farm,
                state_path=path,
                audit_path=Path(folder) / "audit.jsonl",
                now_fn=lambda: NOW,
            )
            persisted = load_state(path)
        self.assertNotIn("ghost", persisted["incremental"]["contacts"])
        self.assertTrue(persisted["contacts"]["ghost"]["orders"]["100"]["admitted"])
