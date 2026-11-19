"""Entrada Meta autônoma: perfil, simulação offline e barreiras de escrita."""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import run_meta_ads


class NativeMetaCliTests(unittest.TestCase):
    def test_offline_simulation_does_not_construct_clients_or_load_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "synthetic.json"
            fixture.write_text(
                json.dumps({"segment": "PET", "facts": [], "evidence": []}),
                encoding="utf-8",
            )
            output = io.StringIO()
            with (
                patch.dict(os.environ),
                patch("run_meta_ads._real", side_effect=AssertionError("network")),
                contextlib.redirect_stdout(output),
            ):
                code = run_meta_ads.run(["--perfil", "PET", "--input", str(fixture)])
                self.assertEqual(os.environ["NEXOFLOW_PERFIL"], "PET")
            self.assertEqual(code, 0)
            result = json.loads(output.getvalue())
            self.assertEqual(result["mode"], "offline_dry_run")
            self.assertIn("Meta_Ads_Diario", result["tables"])

    def test_apply_requires_explicit_schema_confirmation(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            run_meta_ads.run(["--apply"])

    def test_fixture_cannot_write_even_with_confirmation(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            run_meta_ads.run(
                ["--input", "anything.json", "--apply", "--confirm-schema"]
            )

    def test_invalid_dates_do_not_start_operation(self):
        for args in (
            ["--start", "2026-10-01"],
            ["--start", "2026-10-02", "--end", "2026-10-01"],
            ["--start", "invalid", "--end", "2026-10-01"],
        ):
            with (
                self.subTest(args=args),
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit),
            ):
                run_meta_ads.run(args)

    def test_real_defaults_to_no_apply_and_selects_profile_first(self):
        def fake(args):
            self.assertEqual(os.environ["NEXOFLOW_PERFIL"], "PET")
            self.assertFalse(args.apply)
            return {"partial": True}

        with (
            patch.dict(os.environ),
            patch("run_meta_ads._real", side_effect=fake),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(run_meta_ads.run(["--perfil", "PET"]), 3)

    def test_real_uses_readonly_factory_and_never_operational_constructor(self):
        store = Mock()
        store.native_meta_inputs.return_value = {
            "contacts": [],
            "orders": [],
            "items": [],
        }
        sheets = Mock()
        sheets.open_native_readonly.return_value = store
        sync = Mock(
            return_value={"partial": False, "schema_manifest": {"hash": "synthetic"}}
        )
        modules = {
            "google_sheets": SimpleNamespace(GoogleSheetsStore=sheets),
            "meta_ads_native": SimpleNamespace(sync_native_meta=sync),
            "project_paths": SimpleNamespace(
                load_private_settings=lambda: SimpleNamespace(
                    GOOGLE_SPREADSHEET_ID="authorized",
                    PERFIS={"PET": {"META_ADS_START_DATE": "2026-09-01"}},
                )
            ),
            "proxy_config": SimpleNamespace(configure_proxy=Mock()),
        }
        args = SimpleNamespace(
            start="2026-10-01",
            end="2026-10-02",
            apply=False,
            review=None,
            perfil="PET",
            confirm_schema=False,
        )
        with patch.dict(sys.modules, modules):
            result = run_meta_ads._real(args)
        self.assertFalse(result["partial"])
        sheets.assert_not_called()
        sheets.open_native_readonly.assert_called_once_with("authorized")
        self.assertFalse(sync.call_args.kwargs["apply"])
        self.assertEqual(sync.call_args.args[1].META_ADS_START_DATE, "2026-10-01")
        self.assertEqual(
            sync.call_args.args[1].PERFIS["PET"]["META_ADS_START_DATE"],
            "2026-10-01",
        )
        store.close.assert_called_once()

    def test_external_error_message_does_not_leak_private_data(self):
        output = io.StringIO()
        with (
            patch.dict(os.environ),
            patch(
                "run_meta_ads._real",
                side_effect=RuntimeError("token=secret customer=private"),
            ),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(run_meta_ads.run([]), 1)
        self.assertNotIn("secret", output.getvalue())
        self.assertNotIn("customer=", output.getvalue())

    def test_meta_divergence_aborts_its_own_empty_postgres_revision(self):
        from ds_backend.adapter import PostgresStore

        store = Mock(spec=PostgresStore, revision="synthetic-revision", client=Mock())
        store.native_meta_inputs.return_value = dict(contacts=[], orders=[], items=[])
        store.client.call.return_value = {"state": "ABORTADA"}
        report = dict(
            status="conversas_meta_pendentes", applied=False, partial=True, errors=[]
        )
        modules = {
            "ds_backend.runtime": SimpleNamespace(
                open_store=Mock(return_value=store), complete=Mock()
            ),
            "meta_ads_native": SimpleNamespace(
                sync_native_meta=Mock(return_value=report)
            ),
            "project_paths": SimpleNamespace(
                load_private_settings=lambda: SimpleNamespace(
                    ARMAZENAMENTO_BACKEND="postgres"
                )
            ),
            "proxy_config": SimpleNamespace(configure_proxy=Mock()),
        }
        with tempfile.TemporaryDirectory() as tmp:
            review = Path(tmp) / "revisao.json"
            review.write_text(
                json.dumps(
                    dict(segment="FARMA", start=None, end=None, schema_manifest={})
                ),
                encoding="utf-8",
            )
            with patch.dict(sys.modules, modules):
                result = run_meta_ads._real(
                    SimpleNamespace(
                        start=None,
                        end=None,
                        apply=True,
                        review=review,
                        perfil="FARMA",
                        confirm_schema=True,
                    )
                )
        self.assertEqual(result, report)
        store.client.call.assert_called_once_with(
            "/v1/abortar", {"revision": "synthetic-revision"}
        )
        modules["ds_backend.runtime"].complete.assert_not_called()
        store.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
