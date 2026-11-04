"""Modelo nativo Meta: grãos, exclusividade e vendas confirmadas, sem rede."""

import unittest
from copy import deepcopy

from meta_ads_model import SCHEMAS, build_native_tables
from tests.test_recompra import fixture


class NativeMetaModelTests(unittest.TestCase):
    def setUp(self):
        c, order, _ = fixture(5)
        order.update(contact_uuid="c1", data_hora="2026-11-03T11:00:00-03:00")
        self.order = order
        self.fact = {
            "account_id": "10",
            "ad_id": "20",
            "date_start": "2026-11-03",
            "date_stop": "2026-11-03",
            "spend": "12.50",
            "impressions": "100",
            "clicks": "5",
            "reach": "80",
            "frequency": "1.25",
            "attribution_policy": "7d_click/1d_view",
        }
        self.event = {
            "segment": "FARMA",
            "event_id": "e1",
            "ad_id": "20",
            "date": "2026-11-03T10:00:00-03:00",
            "contact_uuid": "c1",
            "urn": "whatsapp:synthetic",
            "channel": "whatsapp",
        }
        self.args = {
            "segment": "FARMA",
            "facts": [self.fact],
            "catalogs": {},
            "evidence": [self.event],
            "contacts": [],
            "orders": [order],
            "items": [],
            "account_meta": {
                "10": {"currency": "BRL", "timezone_name": "America/Belem"}
            },
            "updated_at": "2026-11-04T10:00:00-03:00",
            "coverage": {"segments": {"FARMA": True, "PET": True}},
        }

    def build(self, **changes):
        return build_native_tables(**{**deepcopy(self.args), **changes})

    def test_schemas_exact_and_keys_stable_without_mutating_inputs(self):
        before = deepcopy(self.args)
        a = self.build()
        b = self.build()
        self.assertEqual(a, b)
        self.assertEqual(self.args, before)
        for name, rows in a.items():
            for row in rows:
                self.assertEqual(set(row), set(SCHEMAS[name]))

    def test_exclusive_known_evidence_allocates_cost_and_confirmed_sales(self):
        r = self.build()["BI_Meta_Resultados"][0]
        self.assertEqual(r["classificacao"], "FARMA")
        self.assertEqual(r["investimento_atribuivel"], "12.50")
        self.assertEqual(r["pedidos_confirmados"], 1)
        self.assertEqual(r["receita_confirmada"], "10.00")
        self.assertEqual(r["ctr_pct"], "5.00")
        self.assertEqual(r["cpc"], "2.50")
        self.assertEqual(r["cac"], "")
        self.assertEqual(r["conversas"], "")
        self.assertEqual(r["eventos_ctwa"], 1)

    def test_shared_cost_not_allocated_to_either_segment(self):
        other = {**self.event, "segment": "PET", "event_id": "ep", "contact_uuid": "p1"}
        for segment in ("FARMA", "PET"):
            rows = self.build(segment=segment, evidence=[self.event, other])
            r = rows["BI_Meta_Resultados"][0]
            self.assertEqual(r["classificacao"], "COMPARTILHADO")
            self.assertEqual(r["investimento_original"], "12.50")
            for key in ["investimento_atribuivel", "cpa_confirmado", "roas_confirmado"]:
                self.assertEqual(r[key], "")

    def test_names_do_not_classify_and_partial_coverage_blocks_cost(self):
        for evidence, coverage in [
            ([], self.args["coverage"]),
            ([self.event], {"segments": {"FARMA": True, "PET": False}}),
        ]:
            r = self.build(
                evidence=evidence,
                coverage=coverage,
                catalogs={
                    "ads": [
                        {"id": "20", "account_id": "10", "name": "FarmaLíder oficial"}
                    ]
                },
            )["Meta_Ads_Diario"][0]
            self.assertEqual(r["classificacao"], "NAO_CLASSIFICADO")
            self.assertEqual(r["investimento_atribuivel"], "")

    def test_other_exclusive_segment_never_populates_current_profile(self):
        self.assertEqual(self.build(segment="PET")["Meta_Ads_Diario"], [])

    def test_last_observed_event_before_order_without_future_attribution(self):
        older = {**self.event, "event_id": "old", "date": "2026-11-03T09:00:00-03:00"}
        future = {
            **self.event,
            "event_id": "future",
            "date": "2026-11-03T12:00:00-03:00",
        }
        r = self.build(evidence=[older, self.event, future])["BI_Meta_Conversoes"][0]
        self.assertEqual(r["evento_id"], "e1")
        self.assertEqual(r["metodo_atribuicao"], "ULTIMO_TOQUE_OBSERVADO")

    def test_no_contact_link_no_sale_and_no_arbitrary_phone_match(self):
        order = {**self.order, "contact_uuid": "another"}
        self.assertEqual(self.build(orders=[order])["BI_Meta_Conversoes"], [])

    def test_cancelled_unvalidated_and_payment_zero_orders_never_count(self):
        for change in [
            {"farmalider_status_pedido": "3"},
            {"farmalider_forma_pagamento": "0"},
            {"status_confirmacao": "ERRO_API"},
        ]:
            self.assertEqual(
                self.build(orders=[{**self.order, **change}])["BI_Meta_Conversoes"], []
            )

    def test_same_order_and_same_event_count_once(self):
        r = self.build(
            orders=[self.order, self.order], evidence=[self.event, self.event]
        )["BI_Meta_Resultados"][0]
        self.assertEqual(r["pedidos_confirmados"], 1)
        self.assertEqual(r["eventos_ctwa"], 1)

    def test_monthly_fact_and_conflicting_same_key_refused(self):
        with self.assertRaises(ValueError):
            self.build(facts=[{**self.fact, "date_stop": "2026-11-04"}])
        with self.assertRaises(ValueError):
            self.build(facts=[self.fact, {**self.fact, "spend": "15"}])

    def test_purchase_aliases_not_summed_and_meta_purchase_never_creates_sale(self):
        fact = {
            **self.fact,
            "actions": [
                {"action_type": "purchase", "value": "3"},
                {"action_type": "omni_purchase", "value": "3"},
            ],
        }
        r = self.build(facts=[fact], orders=[])["BI_Meta_Resultados"][0]
        self.assertEqual(r["compras_atribuidas_meta"], "3.00")
        self.assertEqual(r["pedidos_confirmados"], 0)

    def test_ambiguous_latest_ads_do_not_choose_arbitrarily(self):
        other = {**self.event, "ad_id": "21", "event_id": "e2", "account_id": "10"}
        self.assertEqual(
            self.build(evidence=[self.event, other])["BI_Meta_Conversoes"], []
        )

    def test_unknown_attribution_window_does_not_claim_confirmed_roas(self):
        fact = deepcopy(self.fact)
        fact.pop("attribution_policy")
        r = self.build(facts=[fact])["BI_Meta_Resultados"][0]
        self.assertEqual(r["politica_atribuicao"], "DESCONHECIDA")
        self.assertEqual(r["roas_confirmado"], "")

    def test_different_currency_preserves_brl_revenue_but_disables_ratios(self):
        meta = {"10": {"currency": "USD", "timezone_name": "America/Belem"}}
        result = self.build(account_meta=meta)["BI_Meta_Resultados"][0]
        self.assertEqual(result["moeda_receita"], "BRL")
        self.assertEqual(result["moeda"], "USD")
        self.assertEqual(result["roas_confirmado"], "")
        self.assertEqual(result["cpa_confirmado"], "")

    def test_same_event_id_with_different_identity_is_rejected(self):
        with self.assertRaises(ValueError):
            self.build(evidence=[self.event, {**self.event, "contact_uuid": "other"}])

    def test_accounts_and_days_have_distinct_fact_keys(self):
        next_day = {**self.fact, "date_start": "2026-11-04", "date_stop": "2026-11-04"}
        another = {**self.fact, "account_id": "11"}
        tables = self.build(
            facts=[self.fact, next_day, another],
            account_meta={
                "10": {"currency": "BRL", "timezone_name": "America/Belem"},
                "11": {"currency": "BRL", "timezone_name": "America/Belem"},
            },
        )
        self.assertEqual(len({r["chave"] for r in tables["Meta_Ads_Diario"]}), 3)
        self.assertEqual(tables["BI_Meta_Conversoes"], [])

    def test_same_order_conflicting_cancellation_is_not_attributed(self):
        cancelled = {**self.order, "farmalider_status_pedido": "3"}
        self.assertEqual(
            self.build(orders=[self.order, cancelled])["BI_Meta_Conversoes"], []
        )

    def test_unmatched_official_event_classifies_segment_without_inventing_contact(
        self,
    ):
        result = self.build(evidence=[{**self.event, "contact_uuid": ""}])
        row = result["BI_Meta_Resultados"][0]
        self.assertEqual(row["classificacao"], "FARMA")
        self.assertEqual(row["contatos"], 0)
        self.assertEqual(row["eventos_ctwa"], 1)
        self.assertEqual(result["BI_Meta_Conversoes"], [])

    def test_new_catalog_and_metric_fields_preserve_sources(self):
        fact = {
            **self.fact,
            "campaign_id": "30",
            "adset_id": "40",
            "inline_link_clicks": "4",
            "cost_per_action_type": [{"action_type": "purchase", "value": "6.25"}],
            "results": [{"indicator": "purchase", "value": "2"}],
            "result_type": "purchase",
            "actions": [
                {
                    "action_type": "onsite_conversion.messaging_conversation_started_7d",
                    "value": "2",
                }
            ],
            "action_values": [{"action_type": "purchase", "value": "50"}],
        }
        catalog = {
            "campaigns": [
                {
                    "id": "30",
                    "account_id": "10",
                    "name": "Campanha",
                    "status": "ACTIVE",
                    "objective": "OUTCOME_SALES",
                }
            ],
            "adsets": [
                {"id": "40", "account_id": "10", "name": "Conjunto", "status": "PAUSED"}
            ],
            "ads": [
                {
                    "id": "20",
                    "account_id": "10",
                    "campaign_id": "30",
                    "adset_id": "40",
                    "name": "Anúncio",
                    "status": "ACTIVE",
                }
            ],
        }
        t = self.build(facts=[fact], catalogs=catalog)
        raw = t["Meta_Ads_Diario"][0]
        self.assertEqual(raw["cliques_link"], "4.00")
        self.assertEqual(raw["campanha_nome"], "Campanha")
        self.assertEqual(raw["conjunto_nome"], "Conjunto")
        self.assertEqual(raw["objetivo"], "OUTCOME_SALES")
        self.assertEqual(raw["valor_compras_atribuido_meta"], "50.00")
        self.assertIn("purchase", raw["custos_acoes_meta_json"])
        result = t["BI_Meta_Resultados"][0]
        self.assertEqual(result["custo_conversa_meta"], "6.25")
        self.assertEqual(result["custo_conversa_weni_confirmada"], "")

    def test_confirmed_conversation_cost_never_inferred_from_ctwa_alone(self):
        event = {**self.event, "conversation_id": "conversation-1"}
        result = self.build(evidence=[event])["BI_Meta_Resultados"][0]
        self.assertEqual(result["custo_conversa_weni_confirmada"], "12.50")
        self.assertEqual(result["taxa_conversao_contatos_pct"], "100.00")

    def test_conversion_retains_order_day_after_exposure_and_products(self):
        order = {**self.order, "data_hora": "2026-11-04T10:00:00-03:00"}
        item = {
            "item_chave": "i1",
            "pedido_chave": order["pedido_chave"],
            "pedido_id": "100",
            "contact_uuid": "c1",
            "produto_nome": "Produto",
            "produto_codigo": "7",
            "quantidade": "2",
            "valor_unitario": "5",
            "valor_total": "10",
        }
        t = self.build(orders=[order], items=[item, item])
        row = t["BI_Meta_Conversoes"][0]
        self.assertEqual(row["data_pedido"], "2026-11-04")
        self.assertTrue(row["data_exposicao"].startswith("2026-11-03"))
        self.assertEqual(row["pedido_id"], "100")
        self.assertEqual(row["contact_uuid"], "c1")
        self.assertEqual(row["quantidade_itens"], "2.00")
        self.assertIn("Produto", row["produtos_json"])
        self.assertEqual(t["BI_Meta_Resultados"][0]["pedidos_confirmados"], 1)

    def test_daily_payload_roundtrip_preserves_metrics_but_not_unknown_secrets(self):
        import json

        fact = {
            **self.fact,
            "inline_link_clicks": "4",
            "account_name": "Conta",
            "access_token": "SECRET_TOKEN",
            "headers": {"Authorization": "SECRET_TOKEN"},
            "actions": [
                {
                    "action_type": "purchase",
                    "value": "2",
                    "7d_click": "2",
                    "access_token": "SECRET_TOKEN",
                    "unknown": {"secret": "SECRET_TOKEN"},
                }
            ],
        }
        original = self.build(facts=[fact])
        encoded = original["Meta_Ads_Diario"][0]["payload_api_json"]
        self.assertNotIn("SECRET_TOKEN", encoded)
        self.assertNotIn("access_token", encoded)
        restored = json.loads(encoded)
        repeated = self.build(facts=[restored])
        self.assertEqual(original["Meta_Ads_Diario"], repeated["Meta_Ads_Diario"])
        self.assertEqual(restored["inline_link_clicks"], "4")
        self.assertEqual(restored["actions"][0]["7d_click"], "2")

    def test_schema_has_no_names_cpf_phone_and_preserves_conversion_dates(self):
        forbidden = {"cpf", "telefone", "nome", "urn"}
        self.assertTrue(
            all(not forbidden.intersection(cols) for cols in SCHEMAS.values())
        )
        c = self.build()["BI_Meta_Conversoes"][0]
        self.assertEqual(c["venda_valida"], "Sim")
        self.assertEqual(c["status_vinculo"], "ATIVO")
        self.assertEqual(c["data_pedido"], "2026-11-03")
        self.assertIn("T10:00:", c["data_exposicao"])
