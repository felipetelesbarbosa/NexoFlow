"""Variações do nono dígito bloqueiam criação duplicada, sem autorizar identidade."""

import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from customer_discovery import ContactIndex, CreationSession, build_new_customer_plans
from tests.test_customer_bridge import NOW, farm_for
from tests.test_farmalider_customers import CPF, customer_snapshot
from weni_update import REQUIRED_ORDER_FIELDS


class CustomerPhoneVariantsTests(unittest.TestCase):
    def test_legacy_whatsapp_number_blocks_new_contact_with_ninth_digit(self):
        for old_cpf in ("", "0", "16899535009", CPF):
            with self.subTest(cpf=old_cpf):
                contact = {
                    "uuid": "existing",
                    "name": "Pessoa",
                    "urns": ["whatsapp:559187654321"],
                    "fields": {"cpf": old_cpf},
                }
                before = deepcopy(contact)
                plans, reasons = build_new_customer_plans(
                    farm_for(customer_snapshot(celular=91987654321)),
                    [contact],
                    captured_at=NOW,
                    available_fields=REQUIRED_ORDER_FIELDS | {"cpf"},
                )
                self.assertFalse(plans)
                self.assertEqual(contact, before)
                if old_cpf in ("", "0"):
                    self.assertEqual(reasons, {"CONTATO_EXISTENTE_SEM_CPF": 1})
                elif old_cpf != CPF:
                    self.assertEqual(
                        reasons, {"CONTATO_EXISTENTE_COM_CPF_DIVERGENTE": 1}
                    )

    def test_both_forms_and_cpf_match_do_not_duplicate_same_uuid(self):
        contact = {
            "uuid": "existing",
            "fields": {"cpf": CPF},
            "urns": ["whatsapp:559187654321", "tel:+5591987654321"],
        }
        self.assertEqual(len(ContactIndex([contact]).matches(CPF, "5591987654321")), 1)

    def test_two_existing_contacts_remain_ambiguous_without_merging(self):
        contacts = [
            {"uuid": "a", "fields": {}, "urns": ["whatsapp:559187654321"]},
            {"uuid": "b", "fields": {}, "urns": ["whatsapp:5591987654321"]},
        ]
        plans, reasons = build_new_customer_plans(
            farm_for(customer_snapshot(celular=91987654321)),
            contacts,
            captured_at=NOW,
            available_fields=REQUIRED_ORDER_FIELDS | {"cpf"},
        )
        self.assertFalse(plans)
        self.assertEqual(reasons, {"IDENTIDADE_AMBIGUA": 1})

    def test_alias_appearing_after_review_prevents_post_and_does_not_claim_identity(
        self,
    ):
        from customer_discovery import CreationError

        with (
            TemporaryDirectory() as folder,
            patch("customer_observations.DB_ROOT", Path(folder)),
        ):
            farm = farm_for(customer_snapshot(celular=91987654321))
            plan = build_new_customer_plans(
                farm,
                [],
                captured_at=NOW,
                available_fields=REQUIRED_ORDER_FIELDS | {"cpf"},
            )[0][0]
            weni = Mock()
            weni.list_contacts.return_value = []
            existing = {
                "uuid": "existing",
                "fields": {},
                "urns": ["whatsapp:559187654321"],
            }
            weni.get_contact.side_effect = lambda *, urn: (
                existing if urn == "whatsapp:559187654321" else None
            )
            with self.assertRaises(CreationError):
                CreationSession(weni, farm).apply(plan)
            weni.create_contact.assert_not_called()

    def test_landlines_and_different_area_codes_do_not_become_aliases(self):
        contact = {"uuid": "existing", "fields": {}, "urns": ["whatsapp:559132345678"]}
        self.assertFalse(ContactIndex([contact]).matches("", "5591932345678"))
        self.assertFalse(ContactIndex([contact]).matches("", "559232345678"))

    def test_concurrent_existing_contact_with_same_cpf_is_reconciled_without_post(self):
        with (
            TemporaryDirectory() as folder,
            patch("customer_observations.DB_ROOT", Path(folder)),
        ):
            farm = farm_for(customer_snapshot(celular=91987654321))
            plan = build_new_customer_plans(
                farm,
                [],
                captured_at=NOW,
                available_fields=REQUIRED_ORDER_FIELDS | {"cpf"},
            )[0][0]
            weni = Mock()
            weni.list_contacts.return_value = []
            existing = {
                "uuid": "existing",
                "fields": {"cpf": CPF},
                "urns": ["whatsapp:559187654321"],
            }
            weni.get_contact.side_effect = lambda *, urn: (
                existing if urn == "whatsapp:559187654321" else None
            )
            self.assertEqual(
                CreationSession(weni, farm).apply(plan), ("already_exists", "existing")
            )
            weni.create_contact.assert_not_called()

    def test_api_customers_sharing_mobile_variants_are_not_created(self):
        from farmalider_customers import CustomerDirectory

        payload = customer_snapshot(celular=91987654321)
        other = customer_snapshot(id=18, cpf=16899535009, celular=9187654321)
        other["ultimoPedido"]["id"] = 9
        other["ultimoPedido"]["codCliente"] = 18
        for item in other["itens"]:
            item["codPedido"] = 9
        farm = farm_for(payload)
        farm.customer_directory = CustomerDirectory([payload, other])
        plans, reasons = build_new_customer_plans(
            farm, [], captured_at=NOW, available_fields=REQUIRED_ORDER_FIELDS | {"cpf"}
        )
        self.assertFalse(plans)
        self.assertEqual(reasons, {"IDENTIDADE_AMBIGUA": 2})
