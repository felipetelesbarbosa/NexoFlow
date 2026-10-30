"""Campos essenciais persistidos antes/depois da admissão, nos dois perfis."""

import json
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from recompra import (
    apply_review,
    campaign_fields,
    inspect_structure,
    load_state,
    make_review,
    propose,
)
from tests.test_recompra import NOW, fixture
from tests.test_recompra_prevention import weni_fixture


class CampaignFieldsTests(unittest.TestCase):
    def test_missing_fields_are_filled_before_group_in_both_segments(self):
        for segment in ("FARMA", "PET"):
            with self.subTest(segment=segment), TemporaryDirectory() as folder:
                contact, order, items = fixture(24)
                client, live = weni_fixture(segment, [contact])
                structure = inspect_structure(client, segment=segment)
                self.assertFalse(structure["errors"])
                plan = propose(contact, order, items, structure, now=NOW)
                self.assertEqual(set(plan["fields"]), campaign_fields(segment))
                path = Path(folder) / "state.json"
                original = client.contact_group_action.side_effect

                def add(
                    uid, *, action, group, live=live, segment=segment, original=original
                ):
                    if action == "add":
                        self.assertTrue(
                            all(
                                live[uid]["fields"].get(key)
                                for key in campaign_fields(segment)
                            )
                        )
                    original(uid, action=action, group=group)

                client.contact_group_action.side_effect = add
                review = make_review([plan], structure, now=NOW, state=load_state(path))
                with patch("recompra.resolve_latest", return_value=(order, items)):
                    result = apply_review(
                        review,
                        client,
                        Mock(),
                        state_path=path,
                        audit_path=Path(folder) / "audit.jsonl",
                        now_fn=lambda: NOW,
                    )
                self.assertEqual(result, {"aplicados": 1})

    def test_silently_ignored_field_write_never_adds_contact(self):
        for segment in ("FARMA", "PET"):
            with self.subTest(segment=segment), TemporaryDirectory() as folder:
                contact, order, items = fixture(24)
                client, _ = weni_fixture(segment, [contact])
                client.update_contact_fields.side_effect = lambda *_: None
                structure = inspect_structure(client, segment=segment)
                path = Path(folder) / "state.json"
                review = make_review(
                    [propose(contact, order, items, structure, now=NOW)],
                    structure,
                    now=NOW,
                    state=load_state(path),
                )
                with patch("recompra.resolve_latest", return_value=(order, items)):
                    result = apply_review(
                        review,
                        client,
                        Mock(),
                        state_path=path,
                        audit_path=Path(folder) / "audit.jsonl",
                        now_fn=lambda: NOW,
                    )
                self.assertEqual(result, {"conflitos": 1})
                client.contact_group_action.assert_not_called()

    def test_field_cleared_after_add_is_removed_and_other_contact_continues(self):
        for segment in ("FARMA", "PET"):
            for key in campaign_fields(segment):
                with (
                    self.subTest(segment=segment, key=key),
                    TemporaryDirectory() as folder,
                ):
                    broken, order, items = fixture(24)
                    healthy = deepcopy(broken)
                    healthy["uuid"] = "healthy"
                    client, live = weni_fixture(segment, [broken, healthy])
                    original = client.contact_group_action.side_effect

                    def add(
                        uid,
                        *,
                        action,
                        group,
                        original=original,
                        broken=broken,
                        live=live,
                        key=key,
                    ):
                        original(uid, action=action, group=group)
                        if uid == broken["uuid"] and action == "add":
                            live[uid]["fields"][key] = ""

                    client.contact_group_action.side_effect = add
                    structure = inspect_structure(client, segment=segment)
                    path, audit = (
                        Path(folder) / "state.json",
                        Path(folder) / "audit.jsonl",
                    )
                    review = make_review(
                        [
                            propose(c, order, items, structure, now=NOW)
                            for c in (broken, healthy)
                        ],
                        structure,
                        now=NOW,
                        state=load_state(path),
                    )
                    with patch("recompra.resolve_latest", return_value=(order, items)):
                        result = apply_review(
                            review,
                            client,
                            Mock(),
                            state_path=path,
                            audit_path=audit,
                            now_fn=lambda: NOW,
                        )
                    self.assertEqual(result, {"conflitos": 1, "aplicados": 1})
                    self.assertFalse(live[broken["uuid"]]["groups"])
                    self.assertTrue(live["healthy"]["groups"])
                    saved = load_state(path)["contacts"][broken["uuid"]]["orders"][
                        "100"
                    ]
                    self.assertTrue(saved["pending"])
                    entries = [
                        json.loads(line) for line in audit.read_text().splitlines()
                    ]
                    pending = next(
                        e
                        for e in entries
                        if e["status"] == "CAMPOS_PENDENTES_APOS_INCLUSAO"
                    )
                    self.assertEqual(pending["changed_fields"], [key])


class ProductFieldComparisonTests(unittest.TestCase):
    def test_order_is_irrelevant_but_missing_or_extra_products_are_not(self):
        from pedido_utils import serialize_weni_order_list
        from recompra import field_guard

        first = serialize_weni_order_list(
            ["Produto, com vírgula", "Outro produto", "Outro produto"]
        )
        reordered = serialize_weni_order_list(
            ["Outro produto", "Produto, com vírgula", "Outro produto"]
        )
        self.assertEqual(
            field_guard("pedido_produtos", first),
            field_guard("pedido_produtos", reordered),
        )
        self.assertEqual(
            field_guard("pedido_produtos", field_guard("pedido_produtos", first)),
            field_guard("pedido_produtos", first),
        )
        self.assertNotEqual(
            field_guard("pedido_produtos", first),
            field_guard(
                "pedido_produtos",
                serialize_weni_order_list(["Produto, com vírgula", "Outro produto"]),
            ),
        )
