"""Coleta, atribuição, adapter e upsert reais com APIs e Sheets em memória."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from meta_ads_model import SCHEMAS
from meta_ads_native import sync_native_meta
from tests.test_meta_ads_native import ACCOUNT, NOW, Client
from tests.test_meta_ads_sheets import MemoryStore
from tests.test_recompra import fixture


class NativeMetaPipelineTests(unittest.TestCase):
    def test_preview_apply_replay_and_cancelled_order_in_both_segments(self):
        for segment in ("FARMA", "PET"):
            with self.subTest(segment=segment), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                store = MemoryStore()
                store.profile = segment
                _, order, _ = fixture(5)
                order.update(
                    contact_uuid="synthetic-contact",
                    data_hora="2026-11-03T11:00:00-03:00",
                )
                event = {
                    "segment": segment,
                    "event_id": "official-event",
                    "ad_id": "123",
                    "date": "2026-11-03T10:00:00-03:00",
                    "contact_uuid": "synthetic-contact",
                    "conversation_id": "official-conversation",
                    "channel": "whatsapp",
                }

                def collect(*args, event=event, **kwargs):
                    return [event], {
                        "segments": {"FARMA": True, "PET": True},
                        "auth_failed": [],
                    }

                def sync(
                    apply,
                    store=store,
                    segment=segment,
                    order=order,
                    root=root,
                    collect=collect,
                    **kwargs,
                ):
                    return sync_native_meta(
                        store,
                        {"META_ADS_ENABLED": True, "META_ADS_SCHEMA_APPROVED": True},
                        segment,
                        [],
                        [order],
                        [],
                        now=NOW,
                        apply=apply,
                        client_factory=Client,
                        evidence_collector=collect,
                        state_dir=root / "state",
                        **kwargs,
                    )

                with (
                    patch.dict(os.environ, NEXOFLOW_PERFIL=segment),
                    patch("meta_ads_sheets.PRIVATE_ROOT", root / "backup"),
                ):
                    preview = sync(False)
                    self.assertEqual(preview["status"], "simulacao", preview)
                    self.assertEqual(store.writes, 0)
                    self.assertFalse((root / "state").exists())
                    applied = sync(True, expected_manifest=preview["schema_manifest"])
                    self.assertEqual(applied["status"], "concluido", applied)
                    self.assertTrue(
                        (root / "state" / f"{segment}-{ACCOUNT}.json").is_file()
                    )
                    count = store.writes
                    replay = sync(True)
                    self.assertEqual(replay["status"], "concluido", replay)
                    self.assertEqual(
                        store.writes, count, "Repetição enviou gravações idênticas"
                    )
                    detail = store.book.tabs["BI_Meta_Conversoes"]
                    headers = SCHEMAS["BI_Meta_Conversoes"]
                    self.assertEqual(len(detail.values), 2)
                    self.assertEqual(
                        detail.values[1][headers.index("venda_valida")], "Sim"
                    )
                    order["farmalider_status_pedido"] = "3"
                    cancelled = sync(True)
                    self.assertEqual(cancelled["status"], "concluido", cancelled)
                    self.assertEqual(
                        detail.values[1][headers.index("venda_valida")], "Não"
                    )
                    self.assertEqual(
                        detail.values[1][headers.index("receita_confirmada")], 0
                    )


if __name__ == "__main__":
    unittest.main()
