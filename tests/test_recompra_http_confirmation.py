"""HTTP real contado e checkpoint dependente da confirmação dos campos."""

import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from farmalider_customers import CustomerDirectory
from recompra import apply_review, load_state, make_review, propose
from recompra_incremental import annotate_plans, select_contacts
from tests.test_farmalider_customers import customer_snapshot
from tests.test_recompra import NOW, STRUCTURE, fixture
from weni_client import WeniClient


class HttpConfirmationTests(unittest.TestCase):
    def test_metrics_count_attempts_and_retries_per_service_without_payload(self):
        client = WeniClient("synthetic-token")
        self.addCleanup(client.close)
        response = Mock(status_code=200)
        response.json.return_value = {"results": []}
        limited = Mock(status_code=429)
        with (
            patch.object(client.session, "request", side_effect=[limited, response]),
            patch("weni_client.time.sleep"),
        ):
            client._get_json("https://flows.weni.ai/api/v2/contacts.json")
        metrics = client.metrics_snapshot()
        self.assertEqual(metrics["GET"], 2)
        self.assertEqual(metrics["HTTP_429"], 1)
        self.assertEqual(metrics["retries"], 1)
        self.assertNotIn("POST", metrics)
        self.assertFalse(any("token" in str(v) for v in metrics.values()))

    def test_ack_without_field_write_keeps_contact_pending_for_next_incremental(self):
        c, order, items = fixture(35)
        c["fields"].update(propose(c, order, items, STRUCTURE, now=NOW)["fields"])
        c["fields"].pop("ultimo_pedido")
        farm = SimpleNamespace(
            customer_directory=CustomerDirectory([customer_snapshot()])
        )
        state = {"schema": 1, "contacts": {}}
        _, sources, selection = select_contacts([c], farm, STRUCTURE, state, NOW)
        plan = propose(c, order, items, STRUCTURE, now=NOW)
        annotate_plans([plan], sources, selection)
        weni = Mock()
        weni.get_contact.side_effect = lambda **kw: deepcopy(c)
        weni.update_contact_fields.return_value = {"ok": True}
        with (
            tempfile.TemporaryDirectory() as folder,
            patch("recompra.inspect_structure", return_value=STRUCTURE),
            patch("recompra._resolve_checked_contact", return_value=(order, items)),
        ):
            path = Path(folder) / "state.json"
            result = apply_review(
                make_review([plan], STRUCTURE, now=NOW, state=state),
                weni,
                farm,
                state_path=path,
                audit_path=Path(folder) / "audit.jsonl",
                now_fn=lambda: NOW,
            )
            self.assertEqual(result.get("conflitos"), 1)
            saved = load_state(path)
            self.assertTrue(saved["incremental"]["contacts"]["u1"]["retry"])
            self.assertEqual(select_contacts([c], farm, STRUCTURE, saved, NOW)[0], [c])
        weni.contact_group_action.assert_not_called()
