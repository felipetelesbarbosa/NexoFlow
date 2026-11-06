"""Bootstrap Meta real em fontes sintéticas, sem credenciais ou rede externa."""

import json
import os
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import meta_ads_native
from meta_ads_model import SCHEMAS
from tests.test_meta_ads_native import ACCOUNT, NOW, Client, evidence
from tests.test_meta_ads_sheets import MemoryStore, MemoryWorksheet


class NativeMetaBootstrapTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="meta_bootstrap_")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def sync(self, store, segment="FARMA", *, apply=True):
        with (
            patch.dict(os.environ, NEXOFLOW_PERFIL=segment),
            patch("meta_ads_sheets.PRIVATE_ROOT", self.root / segment / "backup"),
        ):
            store.profile = segment
            return meta_ads_native.sync_native_meta(
                store,
                {"META_ADS_ENABLED": True},
                segment,
                [],
                [],
                [],
                now=NOW,
                apply=apply,
                state_dir=self.root / segment / "state",
                client_factory=Client,
                evidence_collector=evidence,
            )

    def assert_native_tabs(self, store):
        for book_id, titles in (
            ("ops", {title for title in SCHEMAS if not title.startswith("BI_")}),
            ("dash", {title for title in SCHEMAS if title.startswith("BI_")}),
        ):
            self.assertEqual(set(store._storage_books[book_id].tabs), titles)
            for title in titles:
                self.assertEqual(
                    store._storage_books[book_id].tabs[title].values[0],
                    SCHEMAS[title],
                )

    def test_enabled_native_apply_bootstraps_both_profiles_and_replays_without_writes(
        self,
    ):
        atomic = meta_ads_native._atomic
        for segment in ("FARMA", "PET"):
            with self.subTest(segment=segment):
                store = MemoryStore()
                historical = store._storage_books["hist"]
                old = MemoryWorksheet("historico_existente", historical, [["legado"]])
                historical.tabs[old.title] = old
                baseline = deepcopy(old.values)
                checkpoint = self.root / segment / "state" / f"{segment}-{ACCOUNT}.json"
                checkpoints = []

                def confirmed_before_checkpoint(
                    path,
                    state,
                    store=store,
                    checkpoint=checkpoint,
                    old=old,
                    baseline=baseline,
                    checkpoints=checkpoints,
                ):
                    self.assert_native_tabs(store)
                    self.assertGreater(store.writes, 0)
                    self.assertFalse(checkpoint.exists())
                    self.assertEqual(old.values, baseline)
                    checkpoints.append(path)
                    return atomic(path, state)

                with patch(
                    "meta_ads_native._atomic", side_effect=confirmed_before_checkpoint
                ):
                    result = self.sync(store, segment)
                self.assertEqual(result["status"], "concluido", result)
                self.assertTrue(result["applied"])
                self.assertEqual(checkpoints, [checkpoint])
                self.assertEqual(json.loads(checkpoint.read_text())["segment"], segment)
                self.assertEqual(set(historical.tabs), {old.title})
                self.assertEqual(old.values, baseline)
                self.assertEqual(
                    len(list((self.root / segment / "backup").glob("*.json"))), 5
                )
                writes = store.writes
                again = self.sync(store, segment)
                self.assertEqual(again["status"], "concluido", again)
                self.assertEqual(store.writes, writes)
                self.assert_native_tabs(store)

    def test_dry_run_does_not_create_or_adopt_missing_or_blank_tabs(self):
        for blank in (False, True):
            with self.subTest(blank=blank):
                store = MemoryStore()
                sheet = None
                if blank:
                    sheet = store.put("Meta_Ads_Diario", headers=[])
                    sheet.values = [[], ["", ""], []]
                before = deepcopy(sheet.values) if sheet is not None else None
                result = self.sync(store, apply=False)
                self.assertEqual(result["status"], "simulacao", result)
                self.assertEqual(store.writes, 0)
                self.assertFalse((self.root / "FARMA" / "state").exists())
                self.assertFalse((self.root / "FARMA" / "backup").exists())
                if sheet is not None:
                    self.assertEqual(sheet.values, before)

    def test_apply_adopts_only_blank_native_tabs_without_recreating_them(self):
        store = MemoryStore()
        daily = store.put("Meta_Ads_Diario", headers=[])
        daily.values = [[], ["", ""], []]
        conversions = store.put("BI_Meta_Conversoes", headers=[])
        identities = daily.id, conversions.id
        result = self.sync(store)
        self.assertEqual(result["status"], "concluido", result)
        self.assert_native_tabs(store)
        self.assertIs(store._storage_books["ops"].tabs[daily.title], daily)
        self.assertIs(store.book.tabs[conversions.title], conversions)
        self.assertEqual((daily.id, conversions.id), identities)
        writes = store.writes
        self.assertEqual(self.sync(store)["status"], "concluido")
        self.assertEqual(store.writes, writes)

    def test_nonempty_divergent_native_header_blocks_all_writes_and_checkpoint(self):
        for values in ([["cabecalho_divergente"]], [[], ["dado_existente"]], [[" "]]):
            with self.subTest(values=values):
                store = MemoryStore()
                sheet = store.put("Meta_Ads_Diario", headers=[])
                sheet.values = deepcopy(values)
                result = self.sync(store)
                self.assertTrue(result["partial"], result)
                self.assertFalse(result["applied"])
                self.assertEqual(store.writes, 0)
                self.assertEqual(sheet.values, values)
                self.assertFalse((self.root / "FARMA" / "state").exists())

    def test_failed_initial_header_is_resumable_and_does_not_checkpoint(self):
        store = MemoryStore()
        original = MemoryWorksheet.update
        failed = False

        def fail_first_header(sheet, **kwargs):
            nonlocal failed
            if sheet.title == "Meta_Ads_Diario" and not failed:
                failed = True
                raise RuntimeError("falha sintética após criação da aba")
            return original(sheet, **kwargs)

        with patch.object(MemoryWorksheet, "update", new=fail_first_header):
            result = self.sync(store)
        self.assertTrue(result["partial"], result)
        self.assertFalse(result["applied"])
        self.assertFalse((self.root / "FARMA" / "state").exists())
        self.assertIn("Meta_Ads_Diario", store._storage_books["ops"].tabs, result)
        orphan = store._storage_books["ops"].tabs["Meta_Ads_Diario"]
        self.assertEqual(orphan.values, [])
        recovered = self.sync(store)
        self.assertEqual(recovered["status"], "concluido", recovered)
        self.assertIs(store._storage_books["ops"].tabs[orphan.title], orphan)
        self.assertEqual(len(orphan.values) - 1, 4)
        self.assert_native_tabs(store)
        writes = store.writes
        self.assertEqual(self.sync(store)["status"], "concluido")
        self.assertEqual(store.writes, writes)


if __name__ == "__main__":
    unittest.main()
