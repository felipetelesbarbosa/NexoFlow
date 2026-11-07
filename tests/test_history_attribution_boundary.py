"""Fluxo estruturado → contato → Analytics; publicação histórica sem novo crédito."""

import unittest
from copy import deepcopy

from analytics import BI_ADS_COLUMNS, build_bi_ads_rows, normalize_contact
from tests import test_bi_layer as bi
from tests import test_meta_attribution as meta
from tests.test_history_publication import fixture


class AttributionBoundaryTests(unittest.TestCase):
    def test_meta_and_google_fields_reach_analytics_but_history_does_not_invent_them(
        self,
    ):
        cases = [meta.incoming()]
        for click in ("gclid", "gbraid", "wbraid"):
            msg = meta.incoming()
            msg["metadata"] = {
                click: "synthetic-click",
                "utm_source": "google",
                "utm_medium": "cpc",
            }
            cases.append(msg)
        for msg in cases:
            with self.subTest(source=msg["metadata"]):
                plan = meta.plan_for([msg, deepcopy(msg)])
                row = normalize_contact(
                    {"uuid": "synthetic-contact", "fields": plan.fields},
                    "2026-11-07T12:00:00Z",
                )
                expected = "Meta Ads" if "referral" in msg["metadata"] else "Google Ads"
                self.assertEqual(row["primeiro_anuncio_origem"], expected)
                ads = build_bi_ads_rows(
                    [row],
                    [],
                    snapshot_date="2026-11-07",
                    updated_at="2026-11-07T12:00:00Z",
                )
                mapped = [dict(zip(BI_ADS_COLUMNS, r, strict=True)) for r in ads]
                self.assertEqual(
                    len(mapped), 2
                )  # Dois modelos separados, não somáveis.
                self.assertTrue(all(r[2] == expected for r in ads))
                self.assertTrue(all(r[10] == 0 for r in ads))
                if expected == "Google Ads":
                    self.assertEqual(
                        plan.fields["primeiro_anuncio_id"], "synthetic-click"
                    )
                    # Fallback legado é clique, não um ID oficial de criativo.
                    self.assertEqual(
                        plan.fields["primeiro_anuncio_clique_id"], "synthetic-click"
                    )
        db, data = fixture(2)
        self.addCleanup(db.close)
        self.assertTrue(
            all(
                not any("anuncio" in key or "gclid" in key for key in row)
                for rows in data.values()
                for row in rows
            )
        )

    def test_purchase_between_touches_keeps_first_model_without_future_last_credit(
        self,
    ):
        base, order, _ = bi.BILayerTests().order_fixture()
        order.update(
            primeiro_anuncio_origem="Google Ads",
            primeiro_anuncio_data="2026-10-04T12:00:00Z",
            ultimo_anuncio_id="future-click",
            ultimo_anuncio_origem="Google Ads",
            ultimo_anuncio_data="2026-10-06T12:00:00Z",
        )
        original = deepcopy(order)
        rows = build_bi_ads_rows(
            base, [order], snapshot_date="2026-11-07", updated_at="2026-11-07T12:00:00Z"
        )
        self.assertEqual(sum(r[10] for r in rows if r[1] == "Primeiro anúncio"), 1)
        self.assertEqual(sum(r[10] for r in rows if r[1] == "Último anúncio"), 0)
        self.assertEqual(order, original)
        self.assertFalse(any(k in BI_ADS_COLUMNS for k in ("cac", "roas", "custo")))

    def test_lost_metadata_pasted_url_and_ambiguous_channel_do_not_create_origin(self):
        for mode in ("pasted", "lost"):
            msg = meta.incoming()
            msg.pop("metadata")
            msg["text"] = (
                "https://example.test/?gclid=synthetic&utm_source=google&utm_medium=cpc"
            )
            if mode == "lost":
                msg["metadata"] = {"source_url": "https://example.test/"}
            plan = meta.plan_for([msg])
            self.assertFalse(any("anuncio" in key for key in plan.fields))

    def test_multichannel_without_message_urn_preserves_only_proven_origin(self):
        from weni_update import ALLOWED_WRITE_FIELDS, _build_contact_plan

        msg = meta.incoming()
        msg.pop("urn")
        msg["metadata"] = {"gclid": "synthetic"}
        plan = _build_contact_plan(
            {
                "uuid": "contact-meta",
                "urns": ["whatsapp:5511000000000", "instagram:synthetic"],
                "fields": {},
                "groups": [],
            },
            context_messages=[msg],
            candidate_message_ids={msg["id"]},
            farm_client=None,
            opt_out_group_name="Opt-Out LGPD",
            opt_out_group_uuid="out",
            captured_at="2026-11-07T12:00:00Z",
            available_weni_fields=set(ALLOWED_WRITE_FIELDS),
        )
        self.assertEqual(plan.fields["primeiro_anuncio_origem"], "Google Ads")
        self.assertNotIn("primeiro_anuncio_canal_destino", plan.fields)
