"""Enriquecimento por segmento: executar regras reais sem rede."""

import os
import unittest
from datetime import date
from unittest.mock import Mock, patch

from farmalider_customers import enrichment
from tests.test_farmalider_customers import CPF, customer
from weni_update import ContactUpdatePlan, _apply_customer_enrichment, audit_plans


class SegmentEnrichmentRegressionTests(unittest.TestCase):
    def test_pet_enrichment_has_no_adulthood_in_changes_guards_or_evidence(self):
        contact = {
            "uuid": "synthetic",
            "name": "Pessoa Sintética",
            "fields": {"cpf": CPF},
            "urns": [],
        }
        with (
            patch.dict(os.environ, NEXOFLOW_PERFIL="PET"),
            patch("weni_update.selected_customer", return_value=customer()),
        ):
            plan = ContactUpdatePlan("synthetic")
            _apply_customer_enrichment(
                plan, contact, Mock(), "2026-11-03T10:00:00-03:00", None
            )
            self.assertIn("idade", plan.fields)
            for section in (
                plan.fields,
                plan.evidence,
                plan.guards,
                plan.guards["__farmalider_cadastro"]["contact"]["fields"],
            ):
                self.assertNotIn("maior_de_18_anos", section)
            audit_plans([plan], opt_out_group_available=True)

    def test_pet_legacy_adulthood_does_not_block_age(self):
        with patch.dict(os.environ, NEXOFLOW_PERFIL="PET"):
            result = enrichment(
                {"maior_de_18_anos": "Não"}, customer(), date(2026, 11, 3)
            )
        self.assertEqual(result["idade"], "36")
        self.assertNotIn("maior_de_18_anos", result)

    def test_farma_retains_adulthood(self):
        with patch.dict(os.environ, NEXOFLOW_PERFIL="FARMA"):
            result = enrichment({}, customer(), date(2026, 11, 3))
        self.assertEqual(result["idade"], "36")
        self.assertEqual(result["maior_de_18_anos"], "Sim")
