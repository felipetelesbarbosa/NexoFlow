import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from farmalider_client import FarmaliderClient, FarmaliderError
from recompra_group_audit import audit_group
from tests.test_recompra import NOW, STRUCTURE, fixture


class GroupAuditTests(unittest.TestCase):
    def test_only_reads_and_reports_cancelled_invalid_and_pending(self):
        contacts = []
        orders = {}
        for uid, status, payment in [
            ("valid", "2", "3"),
            ("cancelled", "3", "3"),
            ("invalid", "2", "99"),
            ("pending", "2", "3"),
        ]:
            c, o, i = fixture(24, grouped=True, status=status, payment=payment)
            c["uuid"] = uid
            contacts.append(c)
            orders[uid] = (o, i)
        w = Mock()
        w.iter_group_contacts.return_value = iter(contacts)

        def resolve(c, *args):
            if c["uuid"] == "pending":
                raise FarmaliderError("Falha sintética")
            return orders[c["uuid"]]

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("recompra_group_audit.resolve_latest", side_effect=resolve),
        ):
            path = Path(tmp) / "audit.json"
            result = audit_group(w, Mock(), STRUCTURE, path, now=NOW)
            self.assertEqual(
                result["classificacoes"],
                {"DENTRO_DA_REGRA": 1, "REVISAR": 2, "CONSULTA_PENDENTE": 1},
            )
            self.assertEqual(len(json.loads(path.read_text())["contacts"]), 4)
            self.assertTrue(path.with_suffix(".csv").exists())
            self.assertTrue(path.with_suffix(".xlsx").exists())
        w.update_contact_fields.assert_not_called()
        w.contact_group_action.assert_not_called()

    def test_api_timeout_distinguishes_connect_and_response(self):
        farm = FarmaliderClient("TOKEN_SINTETICO")
        response = requests.Response()
        response.status_code = 404
        with (
            patch.object(
                farm,
                "_request_route",
                return_value=("https://example.invalid/pedido/1", {}),
            ),
            patch.object(farm.session, "get", return_value=response) as get,
        ):
            self.assertIsNone(farm.get_pedido("1"))
            self.assertEqual(get.call_args.kwargs["timeout"], (10, 90))
        farm.close()
