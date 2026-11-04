"""Coleta de evidências offline, com transporte simulado por projeto."""

import copy
import os
import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from meta_ads_evidence import (
    PROJECT_NAMES,
    ReadOnlyEvidenceClient,
    collect_weni_evidence,
)
from weni_client import WeniError

START = datetime(2026, 10, 1, tzinfo=UTC)
URN = "whatsapp:5511999990000"


def event(identifier="one", **overrides):
    result = {
        "event_name": "ctwa",
        "date": START.isoformat(),
        "contact_urn": URN,
        "metadata": {
            "campaign_source": "123456",
            "channel": "channel",
            "ctwa_id": "click-" + identifier,
            "external_msg_id": "message-" + identifier,
        },
    }
    result.update(overrides)
    return result


class Client:
    def __init__(self, segment, events=None):
        self.org = {"name": PROJECT_NAMES[segment], "uuid": segment}
        self.events = [event()] if events is None else events
        self.contacts = [{"uuid": segment + "-contact", "urns": [URN]}]
        self.calls = []
        self.closed = False

    def get_org(self):
        return self.org

    def list_contacts(self):
        self.calls.append("contacts")
        return self.contacts

    def list_ctwa_events(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.events, Exception):
            raise self.events
        return copy.deepcopy(self.events)

    def close(self):
        self.closed = True


class EvidenceTests(unittest.TestCase):
    def collect(self, clients=None, **kwargs):
        clients = clients or {s: Client(s) for s in PROJECT_NAMES}
        settings = SimpleNamespace(
            PERFIS={s: {"WENI_API_TOKEN": "private-" + s} for s in clients}
        )
        return collect_weni_evidence(
            settings,
            start=START,
            end=kwargs.pop("end", START + timedelta(days=1)),
            client_factory=lambda token, segment: clients[segment],
            **kwargs,
        )

    def test_separate_projects_shared_ad_and_no_global_profile_switch(self):
        with patch.dict(os.environ, {"NEXOFLOW_PERFIL": "PET"}):
            rows, coverage = self.collect()
            self.assertEqual(os.environ["NEXOFLOW_PERFIL"], "PET")
        self.assertEqual(coverage["segments"], {"FARMA": True, "PET": True})
        self.assertEqual({r["segment"] for r in rows}, {"FARMA", "PET"})
        self.assertEqual({r["ad_id"] for r in rows}, {"123456"})
        self.assertNotIn("conversation_id", rows[0])
        self.assertFalse(coverage["history_complete"])
        self.assertNotIn("private-", str(coverage))

    def test_wrong_project_missing_token_and_uuid_guard(self):
        client = Client("FARMA")
        client.org["name"] = PROJECT_NAMES["PET"]
        rows, coverage = self.collect({"FARMA": client})
        self.assertEqual(rows, [])
        self.assertFalse(any(coverage["segments"].values()))
        self.assertEqual(client.calls, [])
        self.assertTrue(client.closed)
        settings = SimpleNamespace(
            PERFIS={"FARMA": {"WENI_API_TOKEN": "x", "WENI_ORG_UUID": "wrong"}}
        )
        client.org["name"] = PROJECT_NAMES["FARMA"]
        _, coverage = collect_weni_evidence(
            settings,
            start=START,
            end=START + timedelta(days=1),
            client_factory=lambda **kwargs: client,
        )
        self.assertEqual(coverage["details"]["FARMA"]["status"], "projeto_divergente")

    def test_windows_boundaries_and_idempotent_duplicates(self):
        first = event()
        last = event("two", date=(START + timedelta(days=7)).isoformat())
        client = Client("FARMA", [first, first, last])
        rows, coverage = self.collect({"FARMA": client}, end=START + timedelta(days=8))
        self.assertEqual(len(rows), 2)
        self.assertEqual(coverage["details"]["FARMA"]["batches"], 2)
        windows = [call for call in client.calls if isinstance(call, dict)]
        self.assertTrue(
            all(c["before"] - c["after"] <= timedelta(days=7) for c in windows)
        )

    def test_only_exact_native_unique_urn_links(self):
        client = Client("FARMA")
        contacts = [{"uuid": "a", "fields": {"contact_urn_whatsapp": URN}}]
        rows, coverage = self.collect(
            {"FARMA": client}, contacts_by_segment={"FARMA": contacts}
        )
        self.assertEqual(rows[0]["contact_uuid"], "")
        self.assertEqual(rows[0]["link_status"], "unmatched")
        self.assertTrue(coverage["segments"]["FARMA"])
        self.assertNotIn("contacts", client.calls)
        contacts = [{"uuid": "a", "urns": [URN]}, {"uuid": "b", "urns": [URN]}]
        rows, coverage = self.collect(
            {"FARMA": client}, contacts_by_segment={"FARMA": contacts}
        )
        self.assertEqual(rows[0]["link_status"], "ambiguous")
        self.assertFalse(coverage["segments"]["FARMA"])

    def test_invalid_and_conflicting_events_preserve_other_valid_evidence(self):
        duplicate = event()
        duplicate["metadata"]["campaign_source"] = "789"
        client = Client(
            "FARMA", [event(), duplicate, event("valid"), event("bad", metadata={})]
        )
        rows, coverage = self.collect({"FARMA": client})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["clique_id"], "click-valid")
        self.assertFalse(coverage["segments"]["FARMA"])
        self.assertEqual(coverage["details"]["FARMA"]["conflicts"], 1)
        self.assertEqual(coverage["details"]["FARMA"]["invalid"], 1)

    def test_auth_failure_is_explicit_and_other_project_continues(self):
        client = Client("FARMA", WeniError("private detail", status_code=401))
        rows, coverage = self.collect({"FARMA": client, "PET": Client("PET")})
        self.assertEqual(coverage["auth_failed"], ["FARMA"])
        self.assertTrue(coverage["segments"]["PET"])
        self.assertEqual([r["segment"] for r in rows], ["PET"])
        self.assertNotIn("private detail", str(coverage))

    def test_default_transport_rejects_mutations_before_network(self):
        client = ReadOnlyEvidenceClient("synthetic", segment="PET")
        try:
            with self.assertRaisesRegex(ValueError, "somente GET"):
                client._request_json(
                    "POST", "https://flows.weni.ai/api/v2/contacts.json"
                )
        finally:
            client.close()

    def test_bad_interval_does_not_open_client(self):
        with self.assertRaises(ValueError):
            self.collect(end=START)


if __name__ == "__main__":
    unittest.main()
