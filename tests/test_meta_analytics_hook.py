"""Integração nativa opcional não invalida a sincronização principal."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from main import _sync_optional_native_meta


class NativeMetaHookTests(unittest.TestCase):
    def setUp(self):
        self.diagnostic = patch("dedup_io.save_private")
        self.diagnostic.start()
        self.addCleanup(self.diagnostic.stop)

    def test_disabled_preserves_old_operation_without_import_or_network(self):
        result = _sync_optional_native_meta(Mock(), SimpleNamespace(), [], [], [])
        self.assertEqual(result, {"status": "desativado"})

    def test_enabled_passes_real_current_segment_and_validated_records(self):
        store, contacts, orders, items = Mock(), [{"uuid": "synthetic"}], [], []
        settings = SimpleNamespace(META_ADS_ENABLED=True)
        with patch(
            "meta_ads_native.sync_native_meta", return_value={"status": "sucesso"}
        ) as sync:
            result = _sync_optional_native_meta(
                store, settings, contacts, orders, items
            )
        self.assertEqual(result["status"], "sucesso")
        self.assertIs(sync.call_args.args[0], store)
        self.assertIs(sync.call_args.kwargs["contacts"], contacts)
        self.assertIs(sync.call_args.kwargs["orders"], orders)

    def test_external_failure_does_not_escape_or_expose_message(self):
        with (
            patch(
                "meta_ads_native.sync_native_meta",
                side_effect=RuntimeError("private-secret"),
            ),
            patch("main.logging.error") as log_error,
        ):
            result = _sync_optional_native_meta(
                Mock(), SimpleNamespace(META_ADS_ENABLED=True), [], [], []
            )
        self.assertEqual(result["status"], "falha")
        log_error.assert_called_once()
        self.assertNotIn("private-secret", str(log_error.call_args_list))


if __name__ == "__main__":
    unittest.main()
