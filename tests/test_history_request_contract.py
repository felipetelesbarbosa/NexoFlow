"""Contrato confirmado por GETs pontuais; nenhuma credencial ou payload real."""

import sqlite3
import unittest
from contextlib import closing

from order_history import SOURCE, HistoryError, HistoryQuery, digest
from order_history_store import HistoryStore, collect_windows
from tests.test_order_history import NOW, Source, order


class RequestContractTests(unittest.TestCase):
    def test_limit_range_confirmed_by_server(self):
        for invalid in (0, 501, 1000, True):
            with (
                self.subTest(limit=invalid),
                self.assertRaisesRegex(HistoryError, "LIMITE"),
            ):
                HistoryQuery("FARMA", "2026-11-01", "2026-11-06", invalid)
        for valid in (1, 100, 500):
            self.assertEqual(
                HistoryQuery("PET", "2026-11-01", "2026-11-06", valid).limit, valid
            )

    def test_civil_end_is_expanded_and_datetime_is_preserved(self):
        q = HistoryQuery("FARMA", "2026-11-06", "2026-11-06")
        self.assertEqual(q.api_end, "2026-11-06T23:59:59.999999")
        self.assertNotEqual(q.key, digest([SOURCE, q.segment, q.start, q.end, q.limit]))
        precise = HistoryQuery(
            "FARMA", "2026-11-06T00:00:00-03:00", "2026-11-06T12:00:00-03:00"
        )
        self.assertEqual(precise.api_end, precise.end)
        self.assertEqual(
            precise.key,
            digest(
                [SOURCE, precise.segment, precise.start, precise.end, precise.limit]
            ),
        )

    def test_rejected_legacy_limit_is_preserved_but_not_retried(self):
        with closing(sqlite3.connect(":memory:")) as db:
            store = HistoryStore(db, "PET")
            db.execute(
                "INSERT INTO history_windows VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "invalid-legacy",
                    "PET",
                    "2026-11-01",
                    "2026-11-06",
                    1000,
                    1,
                    None,
                    None,
                    "incompleta",
                    "FALHA_LEITURA_API",
                    NOW,
                ),
            )
            db.commit()
            source = Source([order()])
            result = collect_windows(
                source,
                store,
                HistoryQuery("PET", "2026-11-01", "2026-11-06"),
                now=NOW,
                mode="incremental",
            )
            self.assertEqual(result["rejected_legacy_windows"], 1)
            self.assertEqual(len(source.calls), 1)
            self.assertEqual(source.calls[0][3], 500)
            self.assertEqual(
                db.execute(
                    "SELECT next_page,status FROM history_windows WHERE key='invalid-legacy'"
                ).fetchone(),
                (1, "incompleta"),
            )
            self.assertEqual(result["incomplete_windows"], 0)

    def test_new_calendar_cursor_does_not_skip_old_completed_window(self):
        with closing(sqlite3.connect(":memory:")) as db:
            store = HistoryStore(db, "PET")
            q = HistoryQuery("PET", "2026-11-06", "2026-11-06")
            oldkey = digest([SOURCE, q.segment, q.start, q.end, q.limit])
            db.execute(
                "INSERT INTO history_windows VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (oldkey, "PET", q.start, q.end, 500, 1, 0, 0, "extraida", "", NOW),
            )
            db.commit()
            source = Source([order(day="2026-11-06")])
            result = collect_windows(source, store, q, now=NOW)
            self.assertEqual(len(source.calls), 1)
            self.assertEqual(result["pedidos_validos"], 1)
            self.assertEqual(
                db.execute(
                    "SELECT status FROM history_windows WHERE key=?", (oldkey,)
                ).fetchone()[0],
                "extraida",
            )

    def test_menu_reprompts_limit_above_500(self):
        import io
        from contextlib import redirect_stdout
        from unittest.mock import patch

        from run_order_history import interactive

        with (
            patch("builtins.input", side_effect=["2026-11-06", "", "1000", "500", ""]),
            patch("run_order_history.run", return_value=0) as runner,
            redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(interactive(), 0)
        self.assertIn("entre 1 e 500", output.getvalue())
        self.assertEqual(runner.call_args.args[0][-1], "500")

    def test_legacy_invalid_limit_with_receipts_requires_review(self):
        with closing(sqlite3.connect(":memory:")) as db:
            store = HistoryStore(db, "PET")
            db.execute(
                "INSERT INTO history_windows VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "legacy",
                    "PET",
                    "2026-11-01",
                    "2026-11-06",
                    1000,
                    2,
                    1200,
                    2,
                    "incompleta",
                    "",
                    NOW,
                ),
            )
            db.commit()
            source = Source([])
            with self.assertRaisesRegex(HistoryError, "REQUER_REVISAO"):
                collect_windows(
                    source,
                    store,
                    HistoryQuery("PET", "2026-11-01", "2026-11-06"),
                    now=NOW,
                    mode="incremental",
                )
            self.assertFalse(source.calls)
            self.assertEqual(
                db.execute(
                    "SELECT next_page FROM history_windows WHERE key='legacy'"
                ).fetchone()[0],
                2,
            )
