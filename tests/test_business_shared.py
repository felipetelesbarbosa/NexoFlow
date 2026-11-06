"""Extração das regras puras preserva os aplicativos Windows."""

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from analytics import _cpf_checksum_valid
from business_identity import cpf_checksum_valid
from business_recompra import timing
from recompra import refused


class SharedBusinessTests(unittest.TestCase):
    def test_optional_unrelated_fields_do_not_change_marketing_decision(self):
        contact = {"fields": {"outro_campo": {"nao_serializavel": {1, 2}}}}
        self.assertFalse(refused(contact, segment="FARMA"))
        self.assertFalse(refused(contact, segment="PET"))

    def test_cpf_interface_is_preserved(self):
        for value in (
            "52998224725",
            "11144477735",
            "00000000000",
            "123",
            "12345678901",
        ):
            self.assertEqual(_cpf_checksum_valid(value), cpf_checksum_valid(value))

    def test_delivery_hour_and_no_retroactive_admission(self):
        tz = ZoneInfo("America/Belem")
        order = datetime(2026, 1, 1, 18, tzinfo=tz)
        now = datetime(2026, 1, 26, 9, tzinfo=tz)
        out = timing(order, now, 25, 10)
        self.assertTrue(out["due_today"] and out["scheduled_future"])
        self.assertEqual(out["event_at"], "2026-01-26T10:00:00-03:00")
        self.assertFalse(
            timing(order, datetime(2026, 1, 27, tzinfo=tz), 25)["within_window"]
        )
