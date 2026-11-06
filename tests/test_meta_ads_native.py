"""Orquestração nativa real com transporte e armazenamento em memória."""

import json
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo

from connectors.meta_ads_mcp.client import MetaReadError
from meta_ads_model import SCHEMAS
from meta_ads_native import POLICY, sync_native_meta

NOW = datetime(2026, 11, 4, 12, tzinfo=ZoneInfo("America/Belem"))
ACCOUNT = "898435729140540"


class Client:
    def __init__(self, accounts=(ACCOUNT,), fail=None, partial=False):
        self.settings = SimpleNamespace(
            allowed_account_ids=accounts, api_version="v26.0"
        )
        self.windows = []
        self.fail = fail
        self.partial = partial
        self.closed = False

    def close(self):
        self.closed = True

    def account_details(self, account):
        if self.fail and account == self.fail:
            raise MetaReadError("TOKEN_MUST_NOT_LEAK", status_code=403, critical=True)
        return {
            "account_id": account,
            "currency": "BRL",
            "timezone_name": "America/Noronha",
        }

    def campaigns(self, account, **kwargs):
        return {"dados": [], "parcial": False}

    adsets = campaigns
    ads = campaigns

    def daily_insights(self, account, start, end, **kwargs):
        self.windows.append((account, start, end))
        rows = []
        cursor = datetime.fromisoformat(start).date()
        stop = datetime.fromisoformat(end).date()
        while cursor <= stop:
            rows.append(
                {
                    "account_id": account,
                    "ad_id": "123",
                    "date_start": cursor.isoformat(),
                    "date_stop": cursor.isoformat(),
                    "spend": "10",
                    "impressions": "100",
                    "clicks": "5",
                }
            )
            cursor += timedelta(days=1)
        return {
            "dados": rows,
            "parcial": self.partial,
            "time_increment": 1,
            "api_version": "v26.0",
            "attribution": {
                "mode": "explicit_windows",
                "action_report_time": "impression",
                "action_attribution_windows": ["7d_click", "1d_view"],
            },
        }


class Store:
    def __init__(self, exists=True, success=True):
        self.tables = {title: [] for title in SCHEMAS}
        self.exists = exists
        self.success = success
        self.writes = 0

    def load_tables(self):
        return deepcopy(self.tables)

    def schema_manifest(self):
        return {
            "tables": {title: {"exists": self.exists} for title in SCHEMAS},
            "segment": "FARMA",
        }

    def plan_tables(self, tables):
        self.planned = deepcopy(tables)
        return {"pending_tabs": {}, "schema_manifest": self.schema_manifest()}

    def apply_tables(self, tables, *, expected_manifest):
        self.writes += 1
        if self.success:
            self.tables = deepcopy(tables)
        return {
            "applied": self.success,
            "pending_tabs": {} if self.success else {"Meta_Ads_Diario": "Unconfirmed"},
        }


def evidence(*args, **kwargs):
    return [], {"segments": {"FARMA": True, "PET": True}, "auth_failed": []}


class NativeSyncTests(unittest.TestCase):
    def run_sync(
        self,
        store,
        client,
        path,
        apply=True,
        settings=None,
        collector=evidence,
        **kwargs,
    ):
        return sync_native_meta(
            store,
            settings or {"META_ADS_ENABLED": True, "META_ADS_SCHEMA_APPROVED": True},
            "FARMA",
            [],
            [],
            [],
            now=NOW,
            apply=apply,
            state_dir=path,
            client_factory=lambda: client,
            evidence_collector=collector,
            **kwargs,
        )

    def test_disabled_makes_no_api_store_or_state_operations(self):
        with tempfile.TemporaryDirectory() as tmp:
            factory = Mock()
            store = Mock()
            result = sync_native_meta(
                store,
                {},
                "PET",
                [],
                [],
                [],
                client_factory=factory,
                state_dir=Path(tmp) / "absent",
            )
            self.assertEqual(result["status"], "desativado")
            factory.assert_not_called()
            self.assertEqual(store.mock_calls, [])
            self.assertFalse((Path(tmp) / "absent").exists())

    def test_dry_run_reads_and_plans_without_creating_any_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "absent"
            store = Store()
            client = Client()
            result = self.run_sync(store, client, path, apply=False)
            self.assertEqual(result["status"], "simulacao", result)
            self.assertIsNotNone(result["schema_manifest"])
            self.assertFalse(path.exists())
            self.assertEqual(store.writes, 0)
            self.assertEqual(len(store.planned["Meta_Ads_Diario"]), 4)
            self.assertTrue(client.closed)

    def test_success_checkpoint_and_replay_are_segment_account_scoped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            store = Store()
            client = Client()
            result = self.run_sync(store, client, path)
            self.assertEqual(result["status"], "concluido", result)
            state = json.loads((path / f"FARMA-{ACCOUNT}.json").read_text())
            self.assertEqual(state["through"], "2026-11-04")
            self.assertEqual(state["segment"], "FARMA")
            self.assertEqual(state["from"], "2026-11-01")
            self.assertEqual(state["policy"], POLICY)
            count = len(store.tables["Meta_Ads_Diario"])
            again = self.run_sync(store, Client(), path)
            self.assertEqual(again["status"], "concluido", again)
            self.assertEqual(len(store.tables["Meta_Ads_Diario"]), count)

    def test_partial_source_or_unconfirmed_write_never_advances_checkpoint(self):
        for client, store in (
            (Client(partial=True), Store()),
            (Client(), Store(success=False)),
        ):
            with (
                self.subTest(partial=client.partial),
                tempfile.TemporaryDirectory() as tmp,
            ):
                result = self.run_sync(store, client, Path(tmp))
                self.assertTrue(result["partial"])
                self.assertFalse(list(Path(tmp).glob("*.json")))
                if client.partial:
                    self.assertEqual(store.writes, 0)

    def test_auth_error_is_critical_sanitized_and_blocks_all_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store()
            result = self.run_sync(store, Client(fail=ACCOUNT), Path(tmp))
            self.assertTrue(result["critical"])
            self.assertEqual(store.writes, 0)
            self.assertNotIn("TOKEN_MUST_NOT_LEAK", json.dumps(result))

    def test_missing_tabs_bootstrap_and_manifest_change_still_blocks_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(exists=False)
            result = self.run_sync(
                store, Client(), Path(tmp), settings={"META_ADS_ENABLED": True}
            )
            self.assertEqual(result["status"], "concluido", result)
            self.assertEqual(store.writes, 1)
            result = self.run_sync(
                store, Client(), Path(tmp), expected_manifest={"changed": True}
            )
            self.assertEqual(result["status"], "erro")
            self.assertEqual(store.writes, 1)

    def test_incomplete_or_auth_failed_weni_coverage_does_not_invalidate_old_sales(
        self,
    ):
        for coverage in (
            {"segments": {"FARMA": True, "PET": False}},
            {"auth_failed": ["PET"], "segments": {}},
        ):
            with tempfile.TemporaryDirectory() as tmp:
                store = Store()

                def collector(*args, result=coverage, **kwargs):
                    return [], result

                result = self.run_sync(store, Client(), Path(tmp), collector=collector)
                self.assertTrue(result["partial"])
                self.assertEqual(store.writes, 0)
                self.assertFalse(list(Path(tmp).glob("*.json")))

    def test_evidence_covers_noronha_first_hour_and_explicit_raw_contacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            collector = Mock(side_effect=evidence)
            result = self.run_sync(
                Store(),
                Client(),
                Path(tmp),
                apply=False,
                collector=collector,
                weni_contacts=[],
            )
            self.assertEqual(result["status"], "simulacao", result)
            args = collector.call_args.kwargs
            self.assertEqual(args["start"].isoformat(), "2026-11-01T02:00:00+00:00")
            self.assertEqual(args["end"].isoformat(), "2026-11-05T03:00:00+00:00")
            self.assertEqual(args["contacts_by_segment"], {"FARMA": [], "PET": []})

    def test_backfill_does_not_regress_watermark_and_batches_are_at_most_seven_days(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            store = Store()
            self.assertEqual(
                self.run_sync(store, Client(), path)["status"], "concluido"
            )
            client = Client()
            result = self.run_sync(
                store,
                client,
                path,
                settings={
                    "META_ADS_ENABLED": True,
                    "META_ADS_SCHEMA_APPROVED": True,
                    "META_ADS_START_DATE": "2026-10-01",
                    "META_ADS_END_DATE": "2026-10-15",
                },
            )
            self.assertEqual(result["status"], "concluido", result)
            self.assertEqual(client.windows[0][1], "2026-10-01")
            for _, start, end in client.windows:
                self.assertLessEqual(
                    (datetime.fromisoformat(end) - datetime.fromisoformat(start)).days,
                    6,
                )
            state = json.loads((path / f"FARMA-{ACCOUNT}.json").read_text())
            self.assertEqual(state["through"], "2026-11-04")
            self.assertEqual(state["from"], "2026-10-01")

    def test_changed_policy_requires_migration_instead_of_duplicate_spend(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            store = Store()
            self.run_sync(store, Client(), path)
            for row in store.tables["Meta_Ads_Diario"]:
                row["politica_atribuicao"] = "OLD_POLICY"
            writes = store.writes
            result = self.run_sync(store, Client(), path)
            self.assertTrue(result["partial"])
            self.assertEqual(store.writes, writes)
            self.assertEqual(result["errors"][0]["error_type"], "MetaMigrationRequired")

    def test_confirmed_cancelled_conversion_gets_zero_value_tombstone(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store()
            store.tables["BI_Meta_Conversoes"] = [
                {
                    "chave": "old-conversion",
                    "conta_id": ACCOUNT,
                    "receita_confirmada": "100",
                    "venda_valida": "Sim",
                    "status_vinculo": "ATIVO",
                }
            ]
            result = self.run_sync(store, Client(), Path(tmp))
            self.assertEqual(result["status"], "concluido", result)
            row = store.tables["BI_Meta_Conversoes"][0]
            self.assertEqual(row["chave"], "old-conversion")
            self.assertEqual(row["receita_confirmada"], "0")
            self.assertEqual(row["venda_valida"], "Não")
            self.assertEqual(row["status_vinculo"], "INVALIDADO")

    def test_manifest_change_during_api_collection_blocks_writes(self):
        class ChangedStore(Store):
            def plan_tables(self, tables):
                result = super().plan_tables(tables)
                result["schema_manifest"] = {"changed": True}
                return result

        with tempfile.TemporaryDirectory() as tmp:
            store = ChangedStore()
            result = self.run_sync(store, Client(), Path(tmp))
            self.assertEqual(result["status"], "erro", result)
            self.assertEqual(store.writes, 0)
            self.assertFalse(list(Path(tmp).glob("*.json")))

    def test_incremental_uses_configured_overlap(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store()
            path = Path(tmp)
            self.run_sync(store, Client(), path)
            client = Client()
            result = sync_native_meta(
                store,
                {
                    "META_ADS_ENABLED": True,
                    "META_ADS_SCHEMA_APPROVED": True,
                    "META_ADS_OVERLAP_DAYS": 2,
                },
                "FARMA",
                [],
                [],
                [],
                now=NOW + timedelta(days=16),
                state_dir=path,
                client_factory=lambda: client,
                evidence_collector=evidence,
            )
            self.assertEqual(result["status"], "concluido", result)
            self.assertEqual(client.windows[0][1], "2026-11-02")

    def test_canonical_credentials_follow_selected_configuration_root(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            config = SimpleNamespace(
                __file__=str(path / "secrets_config.py"), META_ADS_ENABLED=True
            )
            with (
                patch("meta_ads_native.load_settings") as loader,
                patch("meta_ads_native.MetaAdsClient", return_value=Client()),
            ):
                result = sync_native_meta(
                    Store(),
                    config,
                    "FARMA",
                    [],
                    [],
                    [],
                    now=NOW,
                    apply=False,
                    state_dir=path / "state",
                    evidence_collector=evidence,
                )
            self.assertEqual(result["status"], "simulacao", result)
            loader.assert_called_once_with(
                path.resolve() / "credentials/mcp/meta_ads_credentials.json"
            )
            self.assertFalse((path / "state").exists())

    def test_ad_that_moves_to_other_segment_does_not_keep_old_owned_spend(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            store = Store()
            self.run_sync(store, Client(), Path(tmp))
            for title in ("Meta_Ads_Diario", "BI_Meta_Resultados"):
                for row in store.tables[title]:
                    row["classificacao"] = row["segmento"] = "FARMA"
                    row["investimento_atribuivel"] = "10"
            empty = {title: [] for title in SCHEMAS}
            with patch("meta_ads_native.build_native_tables", return_value=empty):
                result = self.run_sync(store, Client(), Path(tmp))
            self.assertEqual(result["status"], "concluido", result)
            for title in ("Meta_Ads_Diario", "BI_Meta_Resultados"):
                self.assertTrue(store.tables[title])
                for row in store.tables[title]:
                    self.assertEqual(row["classificacao"], "NAO_CLASSIFICADO")
                    self.assertEqual(row["investimento_atribuivel"], "")
                    self.assertEqual(row["investimento_original"], "10.00")
