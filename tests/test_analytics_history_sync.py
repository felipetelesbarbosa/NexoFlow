"""Analytics real, SQLite temporário e protocolo Sheets simulado, sem produção."""

import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from analytics_history_sync import requested_period, synchronize
from duration_display import duration, humanize
from history_sheets_bulk import BulkHistorySheets
from history_snapshot import sha256
from order_history import HistoryError
from tests.test_history_publication import Sheets, fixture


class CompleteSheets(Sheets):
    def describe(self, schemas):
        result = super().describe(schemas)
        for part in self.parts:
            result["books"].setdefault(part["book"], 0)
            if part["book"].startswith("extra_"):
                result["books"][part["book"]] += part["allocated_rows"] * part["width"]
        return result


class AutomationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.directory = self.root / "publicacoes"
        self.source = self.root / "source.sqlite"
        source, _ = fixture(9)
        with closing(source), closing(sqlite3.connect(self.source)) as db:
            source.backup(db)
            db.execute("CREATE TABLE profile(segment TEXT NOT NULL)")
            db.execute("INSERT INTO profile VALUES('FARMA')")
            db.commit()
        self.original = sha256(self.source)
        self.remote = CompleteSheets()
        self.adapter = BulkHistorySheets(self.remote, "FARMA", self.directory)

    def sync(self, percent=100):
        publication = dict(state=self.remote.phase, revision=self.remote.operation)
        return synchronize(
            self.adapter,
            self.source,
            self.directory,
            "FARMA",
            publication,
            percent=percent,
        )

    def test_four_fractions_resume_same_snapshot_then_idempotent(self):
        first = self.sync(25)
        self.assertTrue(first["partial"])
        state = json.loads((self.directory / "analytics_estado.json").read_text())
        revision = state["review"]["revision"]
        result = first
        while result["remaining_batches"]:
            result = self.sync(25)
            current = json.loads((self.directory / "analytics_estado.json").read_text())
            self.assertEqual(current["review"]["revision"], revision)
        self.assertEqual(result["remaining_batches"], 0)
        self.assertTrue(result["resumed"])
        writes = self.remote.writes
        final = self.sync()
        self.assertEqual(final["applied_rows"], 0)
        self.assertEqual(self.remote.writes, writes)
        self.assertFalse(final["partial"])
        self.assertEqual(sha256(self.source), self.original)

    def test_lost_response_keeps_review_and_reconciles_without_duplicate(self):
        self.remote.lost = True
        with self.assertRaises(TimeoutError):
            self.sync()
        state = json.loads((self.directory / "analytics_estado.json").read_text())
        self.assertEqual(state["status"], "preparada")
        revision = state["review"]["revision"]
        self.remote.lost = False
        result = self.sync()
        self.assertEqual(result["remaining_batches"], 0)
        self.assertTrue(result["resumed"])
        report = self.adapter.check(state["review"])
        self.assertEqual(report["conference"]["diferencas"], [])
        self.assertEqual(state["review"]["revision"], revision)

    def test_manual_active_revision_not_adopted_and_foreign_profile_blocks(self):
        from analytics_history_sync import prepare

        review = prepare(self.adapter, self.source, self.directory, "FARMA")
        self.adapter.apply(None, review, max_batches=1)
        writes = self.remote.writes
        with self.assertRaisesRegex(HistoryError, "MANUAL_PENDENTE"):
            self.sync()
        self.assertEqual(self.remote.writes, writes)
        self.assertEqual(sha256(self.source), self.original)
        with self.assertRaisesRegex(HistoryError, "OUTRO_SEGMENTO"):
            prepare(
                BulkHistorySheets(Sheets("PET"), "PET", self.directory),
                self.source,
                self.directory,
                "PET",
            )

    def test_source_changes_during_pause_do_not_change_plan(self):
        first = self.sync(25)
        from order_history import normalize_order
        from order_history_store import HistoryStore
        from tests.test_order_history import NOW, order

        with closing(sqlite3.connect(self.source)) as db:
            HistoryStore(db, "FARMA").upsert(
                normalize_order(order(99, segment="FARMA"), "FARMA", NOW),
                now=NOW,
                mode="historica",
            )
            db.commit()
        result = first
        while result["remaining_batches"]:
            result = self.sync(25)
        self.assertEqual(result["remaining_batches"], 0)
        state = json.loads((self.directory / "analytics_estado.json").read_text())
        report = self.adapter.check(state["review"])
        self.assertEqual(
            report["conference"]["observado"]["recortes"][-1]["pedidos"], 9
        )
        result = self.sync()
        self.assertGreater(result["applied_rows"], 0)

    def test_exclusions_preserved_only_on_copy_and_changed_fact_blocks(self):
        from analytics_history_sync import prepare
        from history_exclusions import derive

        derived = derive(
            self.source,
            sha256(self.source),
            self.root / "filtered",
            "FARMA",
            ["1"],
            "Fixture autorizada",
            "Operador sintético",
        )
        # Contrato público devolve evidência da cópia e recibo, sem alterar original.
        filtered = derived["banco_publicacao"]
        review = prepare(self.adapter, filtered, self.directory, "FARMA")
        self.adapter.apply(None, review)
        result = self.sync()
        self.assertEqual(result["applied_rows"], 0)
        self.assertEqual(sha256(self.source), self.original)
        with closing(sqlite3.connect(self.source)) as db:
            raw = json.loads(
                db.execute("SELECT record FROM history_orders WHERE id='1'").fetchone()[
                    0
                ]
            )
            raw["revenue_cents"] += 1
            db.execute(
                "UPDATE history_orders SET record=? WHERE id='1'", (json.dumps(raw),)
            )
            db.commit()
        with self.assertRaisesRegex(HistoryError, "EXCLUSAO_ALTERADA"):
            self.sync()


class EntryTests(unittest.TestCase):
    def test_recent_dates_and_explicit_full_and_invalid_period(self):
        settings = SimpleNamespace()
        with patch.dict(os.environ, {}, clear=True):
            query, full = requested_period(
                settings, datetime(2026, 11, 10, 12, tzinfo=UTC), "FARMA"
            )
            self.assertEqual(
                (query.start, query.end, query.limit, full),
                ("2026-10-21", "2026-11-10", 500, False),
            )
            os.environ["FORCE_FULL_SYNC"] = "1"
            self.assertFalse(requested_period(settings, datetime.now(UTC), "FARMA")[1])
            os.environ["NEXOFLOW_HISTORY_INICIO"] = "2020-04-20"
            with self.assertRaises(HistoryError):
                requested_period(settings, datetime.now(UTC), "FARMA")
            os.environ["NEXOFLOW_HISTORY_FIM"] = "2026-11-07"
            self.assertTrue(requested_period(settings, datetime.now(UTC), "FARMA")[1])

    def test_invalid_inherited_fraction_blocks_before_network(self):
        with patch.dict(os.environ, {"NEXOFLOW_HISTORY_PERCENTUAL": "10"}):
            with self.assertRaisesRegex(HistoryError, "PERCENTUAL_INVALIDO"):
                requested_period(SimpleNamespace(), datetime.now(UTC), "FARMA")

    def test_cli_propagates_period_and_fraction_and_restores_environment(self):
        from nexo_cli import run

        with patch.dict(os.environ, {}, clear=True):

            def child(_):
                self.assertEqual(os.environ["NEXOFLOW_HISTORY_INICIO"], "2020-04-20")
                self.assertEqual(os.environ["NEXOFLOW_HISTORY_PERCENTUAL"], "25")
                return 3

            with patch("nexo_cli._run_windows_target", side_effect=child):
                self.assertEqual(
                    run(
                        [
                            "analytics",
                            "--historico-inicio",
                            "2020-04-20",
                            "--historico-fim",
                            "2026-11-07",
                            "--percentual",
                            "25",
                        ]
                    ),
                    3,
                )
            self.assertNotIn("NEXOFLOW_HISTORY_INICIO", os.environ)
            with patch(
                "nexo_cli._run_windows_target",
                side_effect=AssertionError("não executar"),
            ):
                self.assertEqual(
                    run(["analytics", "--historico-inicio", "2020-04-20"]), 1
                )

    def test_durations_human_and_numeric_values_unchanged(self):
        for value, expected in [
            (59, "59.0s"),
            (61, "1min 1s"),
            (3601, "1h 0min 1s"),
            (68079.443, "18h 54min 39s"),
        ]:
            self.assertEqual(duration(value), expected)
        self.assertEqual(
            humanize("espera preventiva=45445.0s; CPF 12345678901"),
            "espera preventiva=12h 37min 25s; CPF 12345678901",
        )


class NativeCollectionTests(unittest.TestCase):
    def test_incremental_collects_new_and_recent_then_rechecks_cancellation(self):
        from contextlib import contextmanager

        from order_history_store import analytics_history
        from tests.test_order_history import NOW, Source, order

        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "test.sqlite"

            @contextmanager
            def connection():
                with closing(sqlite3.connect(database)) as db:
                    yield db

            settings = SimpleNamespace(FARMALIDER_HISTORY_ENABLED=True)
            for profile in ("FARMA", "PET"):
                database = Path(directory) / (profile + ".sqlite")
                with (
                    patch.dict(
                        os.environ,
                        {
                            "NEXOFLOW_PERFIL": profile,
                            "NEXOFLOW_HISTORY_INICIO": "",
                            "NEXOFLOW_HISTORY_FIM": "",
                        },
                    ),
                    patch("config.LOG_DIR", Path(directory) / profile),
                    patch("customer_observations.connect", connection),
                    patch("farmalider_customers.directory_for", return_value=None),
                ):
                    client = Source([order(1, segment=profile)])
                    _, _, result = analytics_history(
                        client, [], [], [], now=NOW, settings=settings
                    )
                    self.assertEqual(result["status"], "extraida")
                    self.assertEqual(
                        client.calls[0][:4], (profile, "2026-10-17", "2026-11-06", 500)
                    )
                    client = Source(
                        [order(1, segment=profile, status=3), order(2, segment=profile)]
                    )
                    _, _, result = analytics_history(
                        client, [], [], [], now=NOW, settings=settings
                    )
                    self.assertEqual(result["pedidos_validos"], 1)
                    with connection() as db:
                        rows = [
                            json.loads(r[0])
                            for r in db.execute("SELECT record FROM history_orders")
                        ]
                    self.assertEqual({r["segment"] for r in rows}, {profile})
                    self.assertEqual(
                        {r["state"] for r in rows}, {"valido", "cancelado"}
                    )


class NativePublisherTests(unittest.TestCase):
    from tests import test_history_sheets_transport as fixtures

    setUp = fixtures.TransportTests.setUp

    def test_entry_uses_real_transport_on_three_destinations_and_confirms(self):
        from analytics_history_sync import run
        from tests.sheets_memory import GspreadSheet

        root = Path(self.tmp.name)
        source, _ = fixture(3)
        (root / "privado").mkdir()
        with (
            closing(source),
            closing(
                sqlite3.connect(root / "privado" / "clientes_observados.sqlite")
            ) as db,
        ):
            source.backup(db)
            db.execute("CREATE TABLE profile(segment TEXT NOT NULL)")
            db.execute("INSERT INTO profile VALUES('FARMA')")
            db.commit()

        def adapter(store, segment, directory):
            result = BulkHistorySheets(store, segment, directory)
            result.engine.remote._drive = self.remote._drive
            return result

        self.store.close = lambda: None
        settings = SimpleNamespace(
            FARMALIDER_HISTORY_ENABLED=True, GOOGLE_SPREADSHEET_ID="dashboard"
        )
        with (
            patch("config.LOG_DIR", root),
            patch("customer_observations.DB_ROOT", None),
            patch.dict(
                os.environ,
                {"NEXOFLOW_PERFIL": "FARMA", "NEXOFLOW_HISTORY_PERCENTUAL": "100"},
            ),
            patch("analytics_history_sync.BulkHistorySheets", side_effect=adapter),
            patch(
                "history_sheets_quota.google_store_type",
                return_value=SimpleNamespace(open_native_readonly=lambda _: self.store),
            ),
            patch("tests.sheets_memory.Sheet", GspreadSheet),
        ):
            first = run(settings)
            self.assertEqual(first["status"], "conferida", first)
            self.assertFalse(first["partial"])
            written = self.store._write_requests
            second = run(settings)
            self.assertEqual(second["status"], "conferida", second)
            self.assertEqual(second["applied_rows"], 0)
            self.assertEqual(self.store._write_requests, written)
