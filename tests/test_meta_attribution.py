import copy
import unittest

from ad_attribution import extract_meta_ads_attribution
from weni_update import (
    ALLOWED_WRITE_FIELDS,
    ContactUpdatePlan,
    PlanAuditError,
    _build_contact_plan,
    audit_plans,
)


def incoming(ad_id="120000000000001", *, when="2026-10-30T10:45:02Z"):
    return {
        "id": "message-meta-1",
        "contact": {"uuid": "contact-meta"},
        "direction": "in",
        "created_on": when,
        "urn": "whatsapp:5511999990000",
        "text": "Olá! Posso ter mais informações sobre isso?",
        "metadata": {
            "referral": {
                "source_type": "ad",
                "source_id": ad_id,
                "source_url": "https://www.instagram.com/p/example/",
                "headline": "api.whatsapp.com",
                "ctwa_clid": "click-example",
            }
        },
    }


def plan_for(messages, fields=None):
    return _build_contact_plan(
        {
            "uuid": "contact-meta",
            "urns": ["whatsapp:5511999990000"],
            "fields": fields or {},
            "groups": [],
        },
        context_messages=messages,
        candidate_message_ids={str(m["id"]) for m in messages},
        farm_client=None,
        opt_out_group_name="Opt-Out LGPD",
        opt_out_group_uuid="out",
        captured_at="2026-10-30T12:00:00Z",
        available_weni_fields=set(ALLOWED_WRITE_FIELDS),
    )


class MetaAttributionTests(unittest.TestCase):
    def test_structured_referral_maps_verified_ad_and_whatsapp_destination(self):
        msg = incoming()
        result = extract_meta_ads_attribution(msg)
        self.assertIsNotNone(result)
        self.assertEqual(result.origin, "Meta Ads")
        self.assertEqual(result.ad_id, "120000000000001")
        self.assertEqual(result.click_id, "click-example")
        self.assertEqual(result.destination_channel, "whatsapp")
        self.assertEqual(result.occurred_at, msg["created_on"])
        self.assertEqual(result.campaign_type, "")
        plan = plan_for([msg])
        for prefix in ("primeiro", "ultimo"):
            self.assertEqual(plan.fields[prefix + "_anuncio_origem"], "Meta Ads")
            self.assertEqual(plan.fields[prefix + "_anuncio_id"], result.ad_id)
            self.assertEqual(plan.fields[prefix + "_anuncio_canal_destino"], "whatsapp")
            self.assertEqual(
                plan.evidence[prefix + "_anuncio_id"]["message_id"], msg["id"]
            )
        audit_plans([plan], opt_out_group_available=True)

    def test_referral_can_be_in_message_root(self):
        msg = incoming()
        msg["referral"] = msg.pop("metadata")["referral"]
        self.assertIsNotNone(extract_meta_ads_attribution(msg))

    def test_normal_messages_api_without_metadata_does_not_invent_ad(self):
        msg = incoming()
        del msg["metadata"]
        self.assertIsNone(extract_meta_ads_attribution(msg))
        self.assertFalse(any("anuncio" in key for key in plan_for([msg]).fields))

    def test_outgoing_organic_malformed_missing_id_and_free_text_are_ignored(self):
        base = incoming()
        cases = []
        msg = copy.deepcopy(base)
        msg["direction"] = "out"
        cases.append(msg)
        msg = copy.deepcopy(base)
        msg["metadata"]["referral"]["source_type"] = "post"
        cases.append(msg)
        msg = copy.deepcopy(base)
        del msg["metadata"]["referral"]["source_id"]
        cases.append(msg)
        msg = copy.deepcopy(base)
        msg["metadata"]["referral"] = "ad"
        cases.append(msg)
        msg = copy.deepcopy(base)
        msg["text"] = str(msg.pop("metadata"))
        cases.append(msg)
        msg = copy.deepcopy(base)
        msg["created_on"] = ""
        cases.append(msg)
        for msg in cases:
            with self.subTest(msg=msg):
                self.assertFalse(
                    any("anuncio" in key for key in plan_for([msg]).fields)
                )

    def test_conflicting_referrals_are_ignored(self):
        msg = incoming()
        msg["referral"] = dict(msg["metadata"]["referral"], source_id="120000000000002")
        self.assertIsNone(extract_meta_ads_attribution(msg))

    def test_first_ad_preserved_last_ad_updates_and_retry_is_idempotent(self):
        fields = {
            "primeiro_anuncio_origem": "Google Ads",
            "primeiro_anuncio_id": "old-google",
            "primeiro_anuncio_data": "2026-10-01 07:00:00",
            "ultimo_anuncio_origem": "Google Ads",
            "ultimo_anuncio_id": "old-google",
            "ultimo_anuncio_data": "2026-10-01 07:00:00",
        }
        msg = incoming()
        plan = plan_for([msg], fields)
        self.assertNotIn("primeiro_anuncio_origem", plan.fields)
        self.assertEqual(plan.fields["ultimo_anuncio_origem"], "Meta Ads")
        persisted = dict(fields, **plan.fields)
        retry = plan_for([msg], persisted)
        self.assertFalse(any("anuncio" in key for key in retry.fields))
        older = incoming("120000000000003", when="2026-10-20T10:00:00Z")
        older["metadata"]["referral"]["ctwa_clid"] = "old-click"
        self.assertFalse(
            any("anuncio" in key for key in plan_for([older], persisted).fields)
        )

    def test_google_and_meta_events_share_one_chronological_timeline(self):
        meta = incoming()
        google = dict(
            meta,
            id="google-1",
            created_on="2026-10-29T10:00:00Z",
            metadata={"source_url": "https://example.com/?gclid=old-click"},
        )
        plan = plan_for([meta, google])
        self.assertEqual(plan.fields["primeiro_anuncio_origem"], "Google Ads")
        self.assertEqual(plan.fields["ultimo_anuncio_origem"], "Meta Ads")
        newer_google = dict(google, id="google-2", created_on="2026-10-30T11:00:00Z")
        plan = plan_for([newer_google, meta])
        self.assertEqual(plan.fields["primeiro_anuncio_origem"], "Meta Ads")
        self.assertEqual(plan.fields["ultimo_anuncio_origem"], "Google Ads")

    def test_meta_origin_without_message_evidence_is_blocked_by_audit(self):
        plan = ContactUpdatePlan(
            contact_uuid="contact-meta", fields={"ultimo_anuncio_origem": "Meta Ads"}
        )
        with self.assertRaises(PlanAuditError):
            audit_plans([plan], opt_out_group_available=True)

    def test_manager_wrong_id_and_date_are_corrected_by_verified_click(self):
        msg = incoming()
        fields = {}
        for prefix in ("primeiro", "ultimo"):
            fields.update(
                {
                    prefix + "_anuncio_origem": "Meta Ads",
                    prefix + "_anuncio_id": "wrong-id",
                    prefix + "_anuncio_clique_id": "click-example",
                    prefix + "_anuncio_data": "2026-11-01T12:00:00Z",
                    prefix + "_anuncio_titulo": "Título que não foi retornado pela API",
                    prefix + "_anuncio_url": "https://www.instagram.com/p/known/",
                }
            )
        del msg["metadata"]["referral"]["headline"]
        del msg["metadata"]["referral"]["source_url"]
        plan = plan_for([msg], fields)
        for prefix in ("primeiro", "ultimo"):
            self.assertEqual(plan.fields[prefix + "_anuncio_id"], "120000000000001")
            self.assertIn(prefix + "_anuncio_data", plan.fields)
            self.assertNotIn(prefix + "_anuncio_titulo", plan.fields)
            self.assertNotIn(prefix + "_anuncio_url", plan.fields)
        audit_plans([plan], opt_out_group_available=True)

    def test_manager_correct_values_with_equivalent_date_format_are_not_rewritten(self):
        msg = incoming()
        plan = plan_for([msg])
        fields = dict(plan.fields)
        fields["primeiro_anuncio_data"] = msg["created_on"]
        fields["ultimo_anuncio_data"] = msg["created_on"]
        retry = plan_for([msg], fields)
        self.assertFalse(any("anuncio" in k for k in retry.fields))

    def test_partial_event_history_does_not_freeze_an_incorrect_first_ad(self):
        msg = incoming()
        plan = _build_contact_plan(
            {"uuid": "contact-meta", "urns": [msg["urn"]], "fields": {}, "groups": []},
            context_messages=[msg],
            candidate_message_ids=set(),
            farm_client=None,
            opt_out_group_name="Opt-Out LGPD",
            opt_out_group_uuid="out",
            captured_at="2026-10-30T12:00:00Z",
            ads_history_complete=False,
        )
        self.assertFalse(any(k.startswith("primeiro_anuncio") for k in plan.fields))
        self.assertEqual(plan.fields["ultimo_anuncio_id"], "120000000000001")

    def test_partial_manager_write_is_completed_from_official_event(self):
        fields = {
            "primeiro_anuncio_origem": "Meta Ads",
            "ultimo_anuncio_origem": "Meta Ads",
            "ultimo_anuncio_id": "120000000000001",
        }
        plan = plan_for([incoming()], fields)
        self.assertIn("primeiro_anuncio_id", plan.fields)
        self.assertIn("primeiro_anuncio_data", plan.fields)
        self.assertIn("ultimo_anuncio_data", plan.fields)
        audit_plans([plan], opt_out_group_available=True)

    def test_utc_event_is_written_with_timezone_and_daily_metric_uses_local_date(self):
        from analytics import build_daily_metrics, normalize_contact

        msg = incoming(when="2026-10-31T01:00:00Z")
        plan = plan_for([msg])
        self.assertEqual(plan.fields["primeiro_anuncio_data"], "2026-10-31T01:00:00Z")
        row = normalize_contact(
            {"uuid": "contact-meta", "fields": plan.fields}, "2026-10-31T02:00:00Z"
        )
        self.assertEqual(row["primeiro_anuncio_data"], "2026-10-30T22:00:00-03:00")
        self.assertTrue(all(r[0] == "2026-10-30" for r in build_daily_metrics([row])))

    def test_sale_before_ad_cannot_be_credited_to_later_click(self):
        from analytics import build_bi_ads_rows
        from tests.test_bi_layer import BILayerTests

        base, order, _ = BILayerTests().order_fixture()
        order["primeiro_anuncio_data"] = "2026-10-30T10:45:02Z"
        ads = build_bi_ads_rows(
            base, [order], snapshot_date="2026-10-30", updated_at="2026-10-30T15:00:00Z"
        )
        self.assertTrue(all(r[10] == 0 for r in ads))
