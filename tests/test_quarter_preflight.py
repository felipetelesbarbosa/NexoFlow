"""Falhas de sequência são locais e não devem iniciar consultas ou gravações."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import analytics
import main


class QuarterPreflightTests(unittest.TestCase):
    def test_missing_previous_part_fails_before_opening_any_service(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(
                analytics, "FULL_LOAD_25_MANIFEST", Path(temporary) / "manifest.json"
            ),
            patch.dict(os.environ, {"FORCE_FULL_SYNC": "1", "FULL_SYNC_QUARTER": "2"}),
            patch.object(main, "configure_logging"),
            patch.object(main, "validate_configuration"),
            patch.object(main, "open_farmalider_client") as farm,
            patch.object(main, "GoogleSheetsStore") as sheets,
            patch.object(main, "WeniClient") as weni,
        ):
            self.assertEqual(main.main(), 1)
            farm.assert_not_called()
            sheets.assert_not_called()
            weni.assert_not_called()

    def test_partial_part_and_other_component_do_not_release_analytics(self):
        contacts = [{"uuid": f"u{i}"} for i in range(8)]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "manifest.json"
            with patch.object(analytics, "FULL_LOAD_25_MANIFEST", path):
                first = analytics.prepare_full_load_quarter(
                    contacts, part=1, component="weni"
                )
                analytics.mark_full_load_quarter_complete(
                    component="weni", part=1, campaign_id=first["campaign_id"]
                )
                before = path.read_bytes()
                with self.assertRaisesRegex(
                    RuntimeError, "analytics.*antes da Parte 2"
                ):
                    analytics.validate_full_load_quarter(part=2, component="analytics")
                self.assertEqual(path.read_bytes(), before)
                analytics.mark_full_load_quarter_complete(
                    component="analytics", part=1, campaign_id=first["campaign_id"]
                )
                analytics.validate_full_load_quarter(part=2, component="analytics")

    def test_manifest_location_is_independent_of_the_current_directory(self):
        import config

        self.assertEqual(
            analytics.FULL_LOAD_25_MANIFEST,
            config.LOG_DIR / "full_load_25_manifest.json",
        )


class CancellationClassificationTests(unittest.TestCase):
    def test_a_cancelled_label_alone_never_bypasses_api_validation(self):
        from observed_orders import verified_order_cancellation

        self.assertFalse(
            verified_order_cancellation(
                {"status_confirmacao": "CANCELADO_API", "farmalider_status_pedido": "3"}
            )
        )
        self.assertFalse(
            verified_order_cancellation(
                {
                    "_farmalider_cabecalho_verificado": "1",
                    "status_confirmacao": "CANCELADO_API",
                    "farmalider_status_pedido": "0",
                    "farmalider_forma_pagamento": "3",
                }
            )
        )
        self.assertTrue(
            verified_order_cancellation(
                {
                    "_farmalider_cabecalho_verificado": "1",
                    "farmalider_status_pedido": "3",
                }
            )
        )
        self.assertTrue(
            verified_order_cancellation(
                {
                    "_farmalider_cabecalho_verificado": "1",
                    "farmalider_status_pedido": "0",
                    "farmalider_forma_pagamento": "0",
                }
            )
        )
