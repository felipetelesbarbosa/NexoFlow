"""Contrato real de events.json, com dados sintéticos e nenhuma API externa."""

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from meta_events import event_message, meta_event_state, read_meta_events
from weni_client import WeniClient, WeniError
from weni_update import (
    ALLOWED_WRITE_FIELDS,
    _build_contact_plan,
    audit_plans,
    run_update,
)

NOW = datetime(2026, 10, 30, 18, tzinfo=UTC)
URN = "whatsapp:5511999990000"


def ctwa(when="2026-10-30T10:45:02Z", identifier="first"):
    return {
        "event_name": "ctwa",
        "key": "capi",
        "date": when,
        "contact_urn": URN,
        "value_type": "string",
        "value": "conversation_started",
        "metadata": {
            "campaign_source": "120000000000001",
            "channel": "channel-example",
            "ctwa_id": "click-" + identifier,
            "external_msg_id": "message-" + identifier,
            "waba_id": "waba-example",
        },
    }


def contact():
    return {
        "uuid": "contact-meta",
        "name": "Cliente de teste",
        "urns": [URN],
        "fields": {},
        "groups": [],
    }


def collect(events, *, contacts=None, days=1, error=None):
    client = Mock()
    client.list_ctwa_events.side_effect = error if error else lambda **kw: events
    result = read_meta_events(
        client,
        [contact()] if contacts is None else contacts,
        [],
        before=NOW,
        state={"meta_events_next_after_utc": (NOW - timedelta(days=days)).isoformat()},
        full=False,
        initial_days=90,
        overlap_minutes=0,
    )
    return result, client


class MetaEventsTests(unittest.TestCase):
    def test_actual_api_contract_links_by_exact_native_urn_deduplicates_and_sorts_in_plan(
        self,
    ):
        early = ctwa()
        late = ctwa("2026-10-30T17:56:39Z", "last")
        batch, _ = collect([late, early, early])
        self.assertEqual(batch.report["linked"], 2)
        plan = _build_contact_plan(
            contact(),
            context_messages=batch.by_contact["contact-meta"],
            candidate_message_ids=set(),
            farm_client=None,
            opt_out_group_name="Opt-Out LGPD",
            opt_out_group_uuid="out",
            captured_at=NOW.isoformat(),
            available_weni_fields=set(ALLOWED_WRITE_FIELDS),
        )
        audit_plans([plan], opt_out_group_available=True)
        self.assertEqual(plan.fields["primeiro_anuncio_clique_id"], "click-first")
        self.assertEqual(plan.fields["ultimo_anuncio_clique_id"], "click-last")
        self.assertNotIn("primeiro_anuncio_titulo", plan.fields)
        self.assertNotIn("ultimo_anuncio_url", plan.fields)
        self.assertEqual(plan.guards["__native_urns"], [URN])
        self.assertIn("fonte=events.json", plan.evidence["ultimo_anuncio_id"]["reason"])

    def test_same_external_message_with_conflicting_ad_is_blocked(self):
        first = ctwa()
        bad = copy.deepcopy(first)
        bad["metadata"]["campaign_source"] = "120000000000002"
        batch, _ = collect([first, bad])
        self.assertEqual(batch.by_contact, {})
        self.assertEqual(batch.report["invalid"], 1)
        self.assertTrue(batch.report["pending_from"])

    def test_unmatched_and_ambiguous_urns_stay_pending_without_guessing_number(self):
        for contacts, reason in (
            ([], "unmatched"),
            ([contact(), dict(contact(), uuid="other")], "ambiguous"),
        ):
            batch, _ = collect([ctwa()], contacts=contacts)
            self.assertEqual(batch.by_contact, {})
            self.assertEqual(batch.report[reason], 1)
            self.assertEqual(batch.report["pending_from"], "2026-10-30T10:45:02+00:00")
        malformed = ctwa()
        malformed["contact_urn"] = "+5511999990000"
        with self.assertRaises(ValueError):
            event_message(malformed)

    def test_other_events_are_not_ads_and_missing_metadata_is_pending(self):
        other = dict(ctwa(), event_name="conversion_conversation_started")
        malformed = ctwa()
        malformed["metadata"] = None
        batch, _ = collect([other, malformed])
        self.assertEqual(batch.report["invalid"], 1)
        self.assertFalse(batch.by_contact)
        future = ctwa("2026-10-31T10:00:00Z")
        self.assertFalse(collect([future])[0].by_contact)

    def test_failed_window_does_not_discard_other_windows_and_cursor_retries(self):
        calls = []

        def source(**kw):
            calls.append(kw)
            if len(calls) == 1:
                raise WeniError("Timeout de teste")
            return [ctwa()]

        batch, _ = collect([], days=8, error=source)
        self.assertEqual(batch.report["failed_batches"], 1)
        self.assertEqual(batch.report["linked"], 1)
        state = meta_event_state(batch.report, {}, [], [])
        self.assertEqual(state["meta_events_next_after_utc"], batch.report["after"])
        for status in (401, 403):
            with self.assertRaises(WeniError):
                collect([], error=WeniError("Sem acesso", status_code=status))

    def test_bad_response_shape_is_pending_without_aborting_other_data(self):
        batch, _ = collect(None)
        self.assertEqual(batch.report["failed_batches"], 1)
        self.assertTrue(batch.report["pending_from"])

    def test_read_filters_and_org_validation_use_same_http_client(self):
        client = WeniClient("synthetic-token")
        self.addCleanup(client.close)
        with (
            patch.object(client, "_check_profile_org") as check,
            patch.object(client, "_get_json", return_value=[ctwa()]) as read,
        ):
            result = client.list_ctwa_events(after=NOW - timedelta(days=1), before=NOW)
        self.assertEqual(result, [ctwa()])
        check.assert_called_once()
        self.assertTrue(read.call_args.args[0].endswith("/api/v2/events.json"))
        self.assertEqual(
            read.call_args.kwargs["params"],
            {
                "date_start": "2026-10-29T18:00:00.000Z",
                "date_end": "2026-10-30T18:00:00.000Z",
                "event_name": "ctwa",
            },
        )

    def test_clear_stale_ad_metadata_reaches_http_and_unrelated_fields_cannot_be_cleared(
        self,
    ):
        client = WeniClient("synthetic-token")
        self.addCleanup(client.close)
        with patch.object(client, "_post_json", return_value={}) as post:
            client.update_contact_fields(
                "contact-meta",
                {
                    "ultimo_anuncio_url": "",
                    "cpf": "",
                    "primeiro_anuncio_id": "",
                    "ultimo_anuncio_origem": "Meta Ads",
                },
            )
        self.assertEqual(
            post.call_args.kwargs["json_body"],
            {"fields": {"ultimo_anuncio_url": "", "ultimo_anuncio_origem": "Meta Ads"}},
        )

    def test_core_pipeline_profiles_dry_review_apply_conflict_and_retry(self):
        for profile in ("FARMA", "PET"):
            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import tests; tests.settings.PERFIS = {"
                    "'FARMA': {'WENI_API_TOKEN':'synthetic-farma', 'GOOGLE_SPREADSHEET_ID':'farma'},"
                    "'PET': {'WENI_API_TOKEN':'synthetic-pet', 'FARMALIDER_API_TOKEN':'synthetic-api-pet', 'GOOGLE_SPREADSHEET_ID':'pet'}}; "
                    "from tests.test_meta_events import exercise_pipeline; exercise_pipeline()",
                ],
                cwd=Path(__file__).resolve().parents[1],
                env={**os.environ, "NEXOFLOW_PERFIL": profile},
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(
                completed.returncode, 0, completed.stdout + completed.stderr
            )


def exercise_pipeline():
    from weni_update import _load_state, _save_state

    current = contact()
    client = Mock()
    client.list_fields.return_value = [{"key": k} for k in ALLOWED_WRITE_FIELDS]
    client.list_groups.return_value = [
        {"name": "Opt-In LGPD", "uuid": "in"},
        {"name": "Opt-Out LGPD", "uuid": "out"},
    ]
    client.list_contacts.side_effect = lambda **kw: [copy.deepcopy(current)]
    client.get_contact.side_effect = lambda **kw: copy.deepcopy(current)
    client.list_messages.return_value = []
    events = [ctwa(), ctwa("2026-10-30T17:56:39Z", "last")]

    def source(**kw):
        return [
            copy.deepcopy(e)
            for e in events
            if kw["after"]
            <= datetime.fromisoformat(e["date"].replace("Z", "+00:00"))
            < kw["before"]
        ]

    client.list_ctwa_events.side_effect = source

    def update(uid, fields):
        assert uid == current["uuid"]
        current["fields"].update(fields)
        return {"fields": copy.deepcopy(current["fields"])}

    client.update_contact_fields.side_effect = update
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        state = root / "state.json"
        review = root / "review.json"
        with (
            patch("weni_update.WeniClient", return_value=client),
            patch("weni_update._open_farmalider", return_value=None),
            patch("weni_update.utc_now", return_value=NOW),
            patch("weni_update._load_state", side_effect=lambda: _load_state(state)),
            patch(
                "weni_update._save_state",
                side_effect=lambda data: _save_state(data, state),
            ),
            patch("weni_update._append_audit") as audit,
            patch("weni_update.secrets.WENI_API_TOKEN", "synthetic-token"),
        ):
            result = run_update(apply=False, full=False, review_out=review)
            assert result.meta_events_report["linked"] == 2
            client.update_contact_fields.assert_not_called()
            assert not state.exists()
            payload = json.loads(review.read_text())
            ad_plan = next(
                p for p in payload["plans"] if p["contact_uuid"] == "contact-meta"
            )
            assert ad_plan["changes"]["primeiro_anuncio_clique_id"] == "click-first"
            assert ad_plan["changes"]["ultimo_anuncio_clique_id"] == "click-last"
            reads = client.list_ctwa_events.call_count
            applied = run_update(apply=True, full=False, require_review=review)
            assert applied.contacts_updated == 1
            assert client.list_ctwa_events.call_count == reads
            saved = json.loads(state.read_text())
            assert datetime.fromisoformat(saved["meta_events_next_after_utc"]) == NOW
            posts = client.update_contact_fields.call_count
            retry = run_update(apply=True, full=False, require_review=review)
            assert retry.contacts_already_satisfied == 1
            assert client.update_contact_fields.call_count == posts
            assert audit.call_count >= 3
            # Uma edição externa depois da revisão bloqueia apenas este contato.
            current["fields"]["ultimo_anuncio_id"] = "120000000000003"
            conflict = run_update(apply=True, full=False, require_review=review)
            assert conflict.contacts_conflicted == 1
            assert client.update_contact_fields.call_count == posts
            saved = json.loads(state.read_text())
            assert datetime.fromisoformat(saved["meta_events_next_after_utc"]) < NOW
            assert saved["pending_conflict_uuids"] == ["contact-meta"]
            # O Noturno deve usar as mesmas funções, sem uma cópia da lógica.
            import run_noturno

            current["fields"] = {}
            analytics_calls = []

            def runner(arguments, **kwargs):
                if arguments[0] == "app/run_update_weni.py":
                    if "--dry-run" in arguments:
                        run_update(
                            apply=False,
                            review_out=Path(
                                arguments[arguments.index("--review-out") + 1]
                            ),
                        )
                    elif "--apply" in arguments:
                        run_update(
                            apply=True,
                            require_review=Path(
                                arguments[arguments.index("--require-review") + 1]
                            ),
                        )
                elif arguments[0] == "app/run_main.py":
                    exercise_analytics(current)
                    analytics_calls.append(True)
                return 0

            assert run_noturno.execute(root, runner=runner) == 0
            assert len(analytics_calls) == 2


def exercise_analytics(current):
    """Decisões reais de pedido, upsert e BI; somente transportes são sintéticos."""
    from analytics import (
        BASE_COLUMNS,
        BI_ADS_COLUMNS,
        build_bi_ads_rows,
        normalize_contact,
    )
    from main import build_orders
    from runtime_profile import segment
    from tests.test_farmalider_customers import CPF, customer_snapshot
    from tests.test_sheets_partitions import SheetsPartitionTests

    person = copy.deepcopy(current)
    person["fields"]["cpf"] = CPF
    payload = customer_snapshot()
    payload["ultimoPedido"].update(segmento=segment(), emissao="2026-10-30T14:59:00")
    farm = Mock()
    farm.get_cliente_by_cpf.return_value = payload
    farm.get_pedido.return_value = {
        "capa": payload["ultimoPedido"],
        "itens": payload["itens"],
    }
    # O anúncio não substitui a confirmação oficial do pedido na Weni.
    plan = _build_contact_plan(
        person,
        context_messages=[],
        candidate_message_ids=set(),
        farm_client=farm,
        opt_out_group_name="Opt-Out LGPD",
        opt_out_group_uuid="out",
        captured_at=NOW.isoformat(),
        available_weni_fields=set(ALLOWED_WRITE_FIELDS),
    )
    assert plan.purchase_confirmed and plan.order_validated
    assert plan.fields["pedido_id"] == "8"
    assert plan.fields["pedido_produtos"]
    person["fields"].update(plan.fields)
    normalized = normalize_contact(person, NOW.isoformat())
    orders, items, stats = build_orders(
        [person],
        rows_by_uuid={person["uuid"]: normalized},
        farm_client=farm,
        sync_time=NOW.isoformat(),
    )
    assert stats.confirmed_api == 1 and len(orders) == 1
    assert orders[0]["ultimo_anuncio_id"] == "120000000000001"
    assert orders[0]["ultimo_anuncio_clique_id"] == "click-last"
    assert orders[0]["status_confirmacao"] == "CONFIRMADO_API"
    assert items
    farm.get_cliente_by_cpf.assert_called()
    # Cancelamento/pagamento zero continuam excluindo a venda mesmo com anúncio.
    bad = copy.deepcopy(payload)
    bad["ultimoPedido"].update(status=3, formaPagamento=0)
    farm.get_cliente_by_cpf.return_value = bad
    farm.get_pedido.return_value = {"capa": bad["ultimoPedido"], "itens": bad["itens"]}
    blocked = _build_contact_plan(
        person,
        context_messages=[],
        candidate_message_ids=set(),
        farm_client=farm,
        opt_out_group_name="Opt-Out LGPD",
        opt_out_group_uuid="out",
        captured_at=NOW.isoformat(),
    )
    assert not blocked.purchase_confirmed
    ads = build_bi_ads_rows(
        [normalized], orders, snapshot_date="2026-10-30", updated_at=NOW.isoformat()
    )
    assert {row[1] for row in ads} == {"Primeiro anúncio", "Último anúncio"}
    assert all(row[5] == "120000000000001" and row[10] == 1 for row in ads)
    factory = SheetsPartitionTests()
    factory.setUp()
    try:
        store, ws, _ = factory.make("Base_Contatos", BASE_COLUMNS, segment=segment())
        store.base = ws
        bi = store.book.add("BI_Ads", [BI_ADS_COLUMNS])
        store.bi_ads = bi
        store._headers_cache["BI_Ads"] = BI_ADS_COLUMNS
        saved = store.upsert_contacts_detailed([normalized])
        assert saved.inserted == 1
        repeated = store.upsert_contacts_detailed([normalized])
        assert repeated.unchanged == 1
        store.replace_bi_ads(ads)
        loaded = store._table_values(ws)
        by_name = dict(zip(loaded[0], loaded[1], strict=False))
        assert by_name["ultimo_anuncio_clique_id"] == "click-last"
        assert by_name["primeiro_anuncio_id"] == "120000000000001"
        assert store._book_for_title("Base_Contatos").id == "operations"
        assert store._book_for_title("BI_Ads").id == "dashboard"
        saved_ads = store._table_values(bi)
        assert saved_ads[0] == BI_ADS_COLUMNS
        assert len(saved_ads) == 3
        assert all(row[5] == "120000000000001" for row in saved_ads[1:])
    finally:
        factory.doCleanups()


class MetaEventsMalformedResponseTests(unittest.TestCase):
    def test_invalid_record_in_http_200_does_not_advance_as_empty_success(self):
        client = WeniClient("synthetic-token")
        self.addCleanup(client.close)
        client._profile_verified = True
        with patch.object(client, "_get_json", return_value=[ctwa(), "malformed"]):
            with self.assertRaises(WeniError):
                client.list_ctwa_events(after=NOW - timedelta(days=1), before=NOW)
