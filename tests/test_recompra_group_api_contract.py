"""Contrato real de métodos HTTP Weni, porém somente com transporte sintético."""
import json
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from config import WENI_CONTACT_ACTIONS_API_URL, WENI_CONTACTS_API_URL
from recompra import (
    GROUP,
    TZ,
    apply_review,
    cancelled_order_reason,
    load_state,
    make_review,
    propose,
)
from tests.test_recompra import STRUCTURE, fixture
from weni_client import WeniClient

NOW = datetime(2026, 10, 10, 11, 30, tzinfo=TZ)


class FakeResponse:
    status_code = 200
    content = b'{"ok":true}'

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return deepcopy(self.payload)

    def raise_for_status(self):
        return None


class FakeWeniTransport:
    """Simula os mesmos GET/POST e parâmetros usados pelo WeniClient real."""

    def __init__(self, contact, *, make_add_visible=True):
        self.contact = deepcopy(contact)
        self.make_add_visible = make_add_visible
        self.calls = []
        self.pending_checked = False
        self.state_path = None

    def request(self, method, url, *, params=None, json=None, timeout=None):
        self.calls.append((method, url, deepcopy(params), deepcopy(json)))
        if method == "GET" and url == WENI_CONTACTS_API_URL:
            assert params["uuid"] == self.contact["uuid"]
            return FakeResponse({"results": [self.contact]})
        if method == "POST" and url == WENI_CONTACTS_API_URL:
            assert params["uuid"] == self.contact["uuid"]
            self.contact["fields"].update(deepcopy(json["fields"]))
            return FakeResponse({"ok": True})
        if method == "POST" and url == WENI_CONTACT_ACTIONS_API_URL:
            assert json["contacts"] == [self.contact["uuid"]]
            assert json["group"] == STRUCTURE["group_uuid"]
            if json["action"] == "add":
                if self.state_path is not None:
                    saved = load_state(self.state_path)["contacts"][self.contact["uuid"]]
                    self.pending_checked = saved["orders"]["100"]["pending"]
                if self.make_add_visible:
                    self.contact["groups"].append({"uuid": json["group"], "name": GROUP})
            elif json["action"] == "remove":
                self.contact["groups"] = [group for group in self.contact["groups"]
                                           if group.get("uuid") != json["group"]]
            return FakeResponse({"ok": True})
        raise AssertionError(f"Chamada não simulada: {method} {url}")


class RecompraGroupApiContractTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state_path = Path(tmp.name) / "recompra_state.json"
        self.audit_path = Path(tmp.name) / "recompra_audit.jsonl"

    def test_validated_order_reaches_real_weni_client_post_and_verified_get(self):
        contact, order, items = fixture(24)
        order["data_hora"] = "2026-10-09T11:30:00-03:00"
        state = load_state(self.state_path)
        plan = propose(contact, order, items, STRUCTURE, now=NOW)
        self.assertEqual(plan["action"], "add")
        review = make_review([plan], STRUCTURE, now=NOW, state=state)
        transport = FakeWeniTransport(contact)
        transport.state_path = self.state_path
        client = WeniClient("TOKEN_SINTETICO_WENI", retry_mutations=False)
        self.addCleanup(client.close)
        with patch.object(client.session, "request", side_effect=transport.request), \
             patch("recompra.inspect_structure", return_value=STRUCTURE), \
             patch("recompra.resolve_latest", return_value=(order, items)):
            result = apply_review(review, client, object(), state_path=self.state_path,
                                  audit_path=self.audit_path, now_fn=lambda: NOW)
        self.assertEqual(result, {"aplicados": 1})
        posts = [(url, data) for method, url, _, data in transport.calls if method == "POST"]
        self.assertEqual(len(posts), 2)
        self.assertEqual(posts[0][0], WENI_CONTACTS_API_URL)
        self.assertEqual(set(posts[0][1]["fields"]), {"pedido_data", "pedido_produtos"})
        self.assertEqual(posts[1][0], WENI_CONTACT_ACTIONS_API_URL)
        self.assertEqual(posts[1][1]["action"], "add")
        self.assertTrue(transport.pending_checked)
        self.assertGreaterEqual(sum(method == "GET" for method, *_ in transport.calls), 3)
        saved = load_state(self.state_path)["contacts"][contact["uuid"]]["orders"]["100"]
        self.assertTrue(saved["admitted"])
        self.assertFalse(saved["pending"])
        event = json.loads(self.audit_path.read_text(encoding="utf-8").splitlines()[-1])
        self.assertTrue(event["group_confirmed"])

    def test_successful_post_without_visible_membership_never_confirms_or_repeats_add(self):
        contact, order, items = fixture(24)
        order["data_hora"] = "2026-10-09T11:30:00-03:00"
        plan = propose(contact, order, items, STRUCTURE, now=NOW)
        review = make_review([plan], STRUCTURE, now=NOW, state=load_state(self.state_path))
        transport = FakeWeniTransport(contact, make_add_visible=False)
        client = WeniClient("TOKEN_SINTETICO_WENI", retry_mutations=False)
        self.addCleanup(client.close)
        with patch.object(client.session, "request", side_effect=transport.request), \
             patch("recompra.inspect_structure", return_value=STRUCTURE), \
             patch("recompra.resolve_latest", return_value=(order, items)), \
             patch("recompra.sleep", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "confirmar_inclusao_no_grupo"):
                apply_review(review, client, object(), state_path=self.state_path,
                             audit_path=self.audit_path, now_fn=lambda: NOW)
        posts = [(url, data) for method, url, _, data in transport.calls if method == "POST"]
        self.assertEqual(sum(url == WENI_CONTACT_ACTIONS_API_URL and data["action"] == "add"
                             for url, data in posts), 1)
        state = load_state(self.state_path)["contacts"][contact["uuid"]]["orders"]["100"]
        self.assertTrue(state["pending"])
        self.assertFalse(state.get("admitted", False))

    def test_all_three_blocking_conditions_prevent_group_add(self):
        cases = {
            "recusado": {"marketing": "recusado"},
            "status_API_3": {"status": "3"},
            "pagamento_API_0": {"payment": "0"},
            "status_Weni_3": {"weni_status": "3"},
            "pagamento_Weni_0": {"weni_payment": "0"},
        }
        for name, settings in cases.items():
            with self.subTest(name=name):
                contact, order, items = fixture(24)
                order["data_hora"] = "2026-10-09T11:30:00-03:00"
                contact["fields"]["marketing_opt_in"] = settings.get("marketing", "")
                contact["fields"]["pedido_status"] = settings.get("weni_status", "")
                contact["fields"]["pedido_forma_pagamento"] = settings.get("weni_payment", "")
                order["farmalider_status_pedido"] = settings.get("status", "2")
                order["farmalider_forma_pagamento"] = settings.get("payment", "3")
                plan = propose(contact, order, items, STRUCTURE, now=NOW)
                self.assertEqual(plan["action"], "")
                self.assertEqual(plan["fields"], {})
                self.assertNotEqual(plan["reason"], "JANELA_0_A_25")
                self.assertFalse(plan["within_window"])
                self.assertFalse(cancelled_order_reason(order, contact) == "" and name != "recusado")
                review = make_review([plan], STRUCTURE, now=NOW,
                                     state=load_state(self.state_path))
                transport = FakeWeniTransport(contact)
                client = WeniClient("TOKEN_SINTETICO_WENI", retry_mutations=False)
                with client.session:
                    with patch.object(client.session, "request", side_effect=transport.request), \
                         patch("recompra.inspect_structure", return_value=STRUCTURE), \
                         patch("recompra.resolve_latest", return_value=(order, items)):
                        result = apply_review(review, client, object(),
                                              state_path=self.state_path,
                                              audit_path=self.audit_path, now_fn=lambda: NOW)
                self.assertEqual(result, {"sem_mudanca": 1})
                self.assertFalse(transport.calls)
