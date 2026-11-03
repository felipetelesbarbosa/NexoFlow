"""Política por pedidos: exclusões revisadas, partições e renomeação idempotente."""

import os
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import weni_dedup as dedup
from contact_dedup_guard import distinct_order_contacts, partition_cpf_contacts
from tests import test_weni_dedup_routine as fixtures
from tests.test_weni_dedup_routine import CAN, CPF, DUP, OTHER, table


class OrderPolicyTests(unittest.TestCase):
    setUp = fixtures.Fixtures.setUp
    prepare = fixtures.Fixtures.prepare

    def set_different_orders(self):
        self.duplicate["fields"]["pedido_id"] = "456"
        self.farm.get_pedido.side_effect = lambda oid: {
            "capa": {"id": int(oid), "codCliente": 99}
        }
        self.current = {c["uuid"]: deepcopy(c) for c in self.contacts}

    def test_only_contact_with_order_wins_even_if_other_has_api_phone(self):
        self.canonical["fields"].pop("pedido_id")
        result = self.prepare()
        self.assertEqual(len(result["pairs"]), 1)
        self.assertEqual(result["pairs"][0]["canonical_uuid"], DUP)
        self.assertEqual(result["pairs"][0]["duplicate_uuid"], CAN)
        self.assertFalse(result["renames"])

    def test_same_order_is_deduplicated_without_numbering(self):
        result = self.prepare()
        self.assertEqual(len(result["pairs"]), 1)
        self.assertEqual(result["pairs"][0]["canonical_uuid"], CAN)
        self.assertFalse(result["renames"])

    def test_different_orders_are_preserved_and_numbered(self):
        self.set_different_orders()
        result = self.prepare()
        self.assertFalse(result["pairs"])
        self.assertFalse(result["pending"])
        self.assertEqual(
            [r["name"] for r in result["renames"]],
            ["Cliente oficial 1", "Cliente oficial 2"],
        )
        self.assertEqual({r["contact_uuid"] for r in result["renames"]}, {CAN, DUP})

    def test_different_historical_orders_prevent_merge_even_if_latest_is_same(self):
        self.tables["Historico_Alteracoes"]["cells"]["3"] = table(
            self.tables["Historico_Alteracoes"]["headers"], [[DUP, "456", "99", CPF]]
        )["cells"]["2"]
        self.store.capture.return_value = (self.tables, {"123", "456"})
        self.farm.get_pedido.side_effect = lambda oid: {
            "capa": {"id": int(oid), "codCliente": 99}
        }
        result = self.prepare()
        self.assertFalse(result["pairs"])
        self.assertEqual(len(result["renames"]), 2)

    def test_inconsistent_historical_owner_blocks_renames_too(self):
        self.set_different_orders()
        self.tables["Historico_Alteracoes"]["cells"]["2"][2]["userEnteredValue"][
            "stringValue"
        ] = "100"
        result = self.prepare()
        self.assertFalse(result["pairs"])
        self.assertFalse(result["renames"])
        self.assertIn("HISTORICO_DE_OUTRO_CLIENTE", result["pending"][0]["reason"])

    def test_unverified_order_blocks_entire_group_without_delete_or_rename(self):
        self.set_different_orders()
        self.farm.get_pedido.side_effect = lambda oid: {
            "capa": {"id": int(oid), "codCliente": 100}
        }
        result = self.prepare()
        self.assertFalse(result["pairs"])
        self.assertFalse(result["renames"])
        self.weni.delete_contact.assert_not_called()

    def test_new_order_after_review_blocks_deletion_on_either_contact(self):
        for uid in (CAN, DUP):
            with self.subTest(uid=uid):
                self.setUp()
                pair = self.prepare()["pairs"][0]
                self.current[uid]["fields"]["pedido_id"] = "456"
                with tempfile.TemporaryDirectory() as folder:
                    removed, skipped = dedup.apply_batch(
                        [pair],
                        self.weni,
                        self.farm,
                        self.store,
                        self.contacts,
                        {},
                        folder,
                    )
                self.assertFalse(removed)
                self.assertEqual(skipped, 1)
                self.weni.delete_contact.assert_not_called()

    def test_new_history_after_review_blocks_deletion(self):
        pair = self.prepare()["pairs"][0]
        self.tables["Historico_Alteracoes"]["cells"]["3"] = table(
            self.tables["Historico_Alteracoes"]["headers"], [[CAN, "456", "99", CPF]]
        )["cells"]["2"]
        self.store.capture.return_value = (self.tables, {"123", "456"})
        with tempfile.TemporaryDirectory() as folder:
            removed, skipped = dedup.apply_batch(
                [pair], self.weni, self.farm, self.store, self.contacts, {}, folder
            )
        self.assertFalse(removed)
        self.assertEqual(skipped, 1)
        self.weni.delete_contact.assert_not_called()

    def test_rename_confirmation_and_repeat_send_no_additional_post(self):
        self.set_different_orders()
        changes = self.prepare()["renames"]

        def rename(uid, name):
            self.current[uid]["name"] = name

        self.weni.rename_contact.side_effect = rename
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(
                dedup.apply_renames(changes, self.weni, self.farm, folder), (2, 0)
            )
            self.assertEqual(
                dedup.apply_renames(changes, self.weni, self.farm, folder), (0, 0)
            )
            self.assertEqual(len(list(Path(folder).glob("nome-*.json"))), 2)
        self.assertEqual(self.weni.rename_contact.call_count, 2)
        self.weni.update_contact_fields.assert_not_called()
        self.weni.delete_contact.assert_not_called()

    def test_rename_does_not_overwrite_external_name_or_new_order(self):
        for change_type in ("name", "order"):
            with self.subTest(change_type=change_type):
                self.setUp()
                self.set_different_orders()
                changes = self.prepare()["renames"]
                if change_type == "name":
                    self.current[CAN]["name"] = "Nome corrigido pelo atendimento"
                    changes = [c for c in changes if c["contact_uuid"] == CAN]
                else:
                    self.current[CAN]["fields"]["pedido_id"] = "789"
                with tempfile.TemporaryDirectory() as folder:
                    _, pending = dedup.apply_renames(
                        changes, self.weni, self.farm, folder
                    )
                self.assertGreater(pending, 0)
                self.weni.rename_contact.assert_not_called()

    def test_numbering_is_stable_with_same_order_duplicates_and_empty_contacts(self):
        self.set_different_orders()
        empty = deepcopy(self.canonical)
        empty["uuid"] = OTHER
        empty["fields"].pop("pedido_id")
        same = deepcopy(self.duplicate)
        same["uuid"] = "44444444-4444-4444-8444-444444444444"
        contacts = self.contacts + [empty, same]
        order_ids = {CAN: {"123"}, DUP: {"456"}, OTHER: set(), same["uuid"]: {"456"}}
        first = partition_cpf_contacts(contacts, self.customer, order_ids)
        reversed_result = partition_cpf_contacts(
            list(reversed(contacts)), self.customer, order_ids
        )
        self.assertEqual(first, reversed_result)
        self.assertEqual(len(first[0]), 2)
        self.assertEqual(len(first[1]), 2)

    def test_distinct_reference_helper_accepts_existing_history(self):
        self.assertEqual(distinct_order_contacts(self.contacts), set())
        self.assertEqual(
            distinct_order_contacts(self.contacts, {DUP: {"456"}}), {CAN, DUP}
        )

    def test_pet_refusal_is_preserved_as_no_and_group_removed_before_delete(self):
        with patch.dict(os.environ, NEXOFLOW_PERFIL="PET"):
            self.duplicate["fields"]["opt_in_lgpd"] = "Não"
            self.duplicate["fields"]["opt_in_marketing"] = "Não"
            self.canonical["groups"] = [{"uuid": "rec", "name": "Recompra Pets Líder"}]
            self.current = {c["uuid"]: deepcopy(c) for c in self.contacts}
            pair = self.prepare()["pairs"][0]

            def fields(uid, values):
                self.current[uid]["fields"].update(values)

            def groups(uid, *, action, group):
                self.assertEqual(action, "remove")
                self.current[uid]["groups"] = []

            self.weni.update_contact_fields.side_effect = fields
            self.weni.contact_group_action.side_effect = groups
            with tempfile.TemporaryDirectory() as folder, patch("dedup_bi.refresh"):
                removed, skipped = dedup.apply_batch(
                    [pair],
                    self.weni,
                    self.farm,
                    self.store,
                    self.contacts,
                    {"rec": "Recompra Pets Líder"},
                    folder,
                )
            self.assertEqual(removed, {DUP})
            self.assertEqual(skipped, 0)
            self.assertEqual(self.current[CAN]["fields"]["opt_in_lgpd"], "Não")
            self.assertEqual(self.current[CAN]["fields"]["opt_in_marketing"], "Não")
            self.weni.contact_group_action.assert_called_with(
                CAN, action="remove", group="rec"
            )
