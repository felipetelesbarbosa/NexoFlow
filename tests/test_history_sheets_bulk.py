"""Frações e redução de HTTP preservam validações e dados por intervalo."""

import unittest
from unittest.mock import patch

from history_sheets_bulk import BulkTransport, batch_budget
from order_history import HistoryError
from order_history_sheets import SCHEMAS
from tests import test_history_sheets_transport as fixtures


class BulkTests(unittest.TestCase):
    setUp = fixtures.TransportTests.setUp

    def setup_part(self):
        headers = SCHEMAS["Historico_Pedidos"]
        book = self.store._storage_books["history"]
        ws = book.add(
            "Historico_Pedidos", [headers, ["k", "FARMA"]], rows=3, cols=len(headers)
        )
        part = dict(
            number=0,
            title=ws.title,
            book=book.id,
            sheet=ws.id,
            cols=len(headers),
            width=len(headers),
        )
        self.store._continuity.require = lambda: None
        return headers, book, ws, part

    def test_fresh_header_and_rows_share_one_call_with_same_values(self):
        headers, book, ws, part = self.setup_part()
        old = self.remote
        new = BulkTransport(self.store)
        with patch.object(
            book, "values_batch_get", wraps=book.values_batch_get
        ) as reads:
            expected = old.read_rows(part, headers, [2, 3, 4])
            reads.reset_mock()
            actual = new.read_rows(part, headers, [2, 3, 4])
            self.assertEqual(actual, expected)
            self.assertEqual(reads.call_count, 1)
        # Uma leitura física do cabeçalho a menos, sem dispensar a geometria.
        before = self.store._read_requests
        old.read_rows(part, headers, [2])
        old_reads = self.store._read_requests - before
        before = self.store._read_requests
        new.read_rows(part, headers, [2])
        self.assertEqual(self.store._read_requests - before, old_reads - 1)
        ws.values[0][0] = "alterado"
        with self.assertRaisesRegex(HistoryError, "CABECALHO"):
            new.read_rows(part, headers, [2])

    def test_future_rows_still_validate_header_without_read_outside_grid(self):
        headers, book, ws, part = self.setup_part()
        new = BulkTransport(self.store)
        self.assertEqual(new.read_rows(part, headers, [9]), [None])
        ws.values[0][0] = "alterado"
        with self.assertRaisesRegex(HistoryError, "CABECALHO"):
            new.read_rows(part, headers, [9])

    def test_partial_response_columns_and_invalid_positions_block(self):
        headers, book, ws, part = self.setup_part()
        new = BulkTransport(self.store)
        with patch.object(book, "values_batch_get", return_value={"valueRanges": []}):
            with self.assertRaisesRegex(HistoryError, "INCOMPLETA"):
                new.read_rows(part, headers, [2])
        with self.assertRaisesRegex(HistoryError, "POSICAO"):
            new.read_rows(part, headers, [0])
        ws.col_count += 1
        with self.assertRaisesRegex(HistoryError, "COLUNAS"):
            new.read_rows(part, headers, [2])

    def test_fraction_is_original_total_not_remaining(self):
        review = dict(batches=4301)
        self.assertEqual(batch_budget(review, 25, None), 1076)
        self.assertEqual(batch_budget(review, 50, None), 2151)
        self.assertEqual(batch_budget(review, 75, None), 3226)
        self.assertIsNone(batch_budget(review, 100, None))
        self.assertEqual(batch_budget(review, None, 1), 1)
        for fraction, maximum in [(0, None), (True, None), (25, 1)]:
            with self.assertRaises(HistoryError):
                batch_budget(review, fraction, maximum)


class FractionCLITests(unittest.TestCase):
    from tests import test_history_reconciliation as fixtures

    setUp = fixtures.ReconciliationTests.setUp
    legacy = fixtures.ReconciliationTests.legacy
    command = fixtures.ReconciliationTests.command

    def test_four_quarters_cli_resume_same_review_and_no_duplicate(self):
        from history_reconciliation import reconcile
        from history_sheets_bulk import BulkHistorySheets
        from tests.test_history_publication import fixture

        # FARMA e PET usam os mesmos limites; o contrato do perfil não muda.
        drive = self.remote._drive
        self.remote = BulkTransport(self.store)
        self.remote._drive = drive
        review = self.legacy(factory=lambda: fixture(9))
        reconcile(self.pub, review)
        budget = batch_budget(review, 25, None)
        confirmed = 0
        for _ in range(4):
            code, out = self.command("aplicar", "--percentual", "25")
            self.assertIn(code, (0, 3))
            self.assertIn("[FRAÇÃO]", out)
            report = self.pub.check(review)
            confirmed = min(review["batches"], confirmed + budget)
            self.assertEqual(report["confirmed_batches"], confirmed)
            self.assertEqual(report.get("uncertain_batches", 0), 0)
            self.assertEqual(report["interval_differences"], [])
        self.assertEqual(report["remaining_batches"], 0)
        self.assertEqual(report["conference"]["diferencas"], [])
        self.assertEqual(report["conference"]["diferenca_pedidos_ltv_centavos"], 0)
        writes = self.store._write_requests
        self.assertEqual(self.command("aplicar", "--percentual", "100")[0], 0)
        self.assertEqual(self.store._write_requests, writes)
        self.assertEqual(self.review_path.read_bytes(), self.original_review)
        # Garante que a fachada de produção instala o transporte agrupado.
        adapter = BulkHistorySheets(self.store, "FARMA", self.root / "check")
        self.assertIsInstance(adapter.engine.remote, BulkTransport)

    def test_invalid_fraction_rejected_before_connections(self):
        from nexo_cli import run

        with patch("history_publish_cli._publish", side_effect=AssertionError("rede")):
            self.assertEqual(run(["historico", "--percentual", "25"]), 1)
            self.assertEqual(
                run(
                    [
                        "historico",
                        "--planilhas",
                        "aplicar",
                        "--percentual",
                        "25",
                        "--max-lotes",
                        "1",
                    ]
                ),
                1,
            )

    def test_failed_lot_has_private_cursor_and_targeted_safe_resume(self):
        import json
        import sqlite3
        from contextlib import closing

        from history_reconciliation import reconcile
        from order_history import HistoryError

        review = self.legacy()
        reconcile(self.pub, review)
        self.assertEqual(self.command("aplicar", "--max-lotes", "1")[0], 3)
        with patch.object(
            self.remote, "write_rows", side_effect=HistoryError("FALHA_SINTETICA")
        ):
            self.assertEqual(self.command("aplicar", "--max-lotes", "1")[0], 1)
        path = (
            __import__("pathlib").Path(review["journal"]).parent
            / "ultima_interrupcao.json"
        )
        report = json.loads(path.read_text())
        self.assertTrue(
            (path.parent / ("interrupcao_" + report["event"] + ".json")).is_file()
        )
        cursor = report["cursor"]
        self.assertEqual(cursor["state"], "sending")
        with closing(sqlite3.connect(review["journal"])) as db:
            before = db.execute(
                "SELECT count(*) FROM batches WHERE state='done'"
            ).fetchone()[0]
        self.assertEqual(
            self.command("aplicar", "--retomar-lote", str(cursor["batch"] + 1))[0], 1
        )
        self.assertEqual(
            self.command("aplicar", "--retomar-lote", str(cursor["batch"]))[0], 3
        )
        with closing(sqlite3.connect(review["journal"])) as db:
            self.assertEqual(
                db.execute(
                    "SELECT count(*) FROM batches WHERE state='done'"
                ).fetchone()[0],
                before + 1,
            )
        self.assertEqual(self.review_path.read_bytes(), self.original_review)


class BulkQuotaResumeTests(unittest.TestCase):
    from tests import test_history_reconciliation as fixtures
    from tests import test_history_sheets_quota_resume as quota_fixtures

    legacy = fixtures.ReconciliationTests.legacy
    command = fixtures.ReconciliationTests.command
    test_quota_lost_response_resume_and_rollback = quota_fixtures.QuotaResumeTests.test_legacy_review_after_pilot_quota_uncertain_response_and_rollback

    def setUp(self):
        self.fixtures.ReconciliationTests.setUp(self)
        drive = self.remote._drive
        self.remote = BulkTransport(self.store)
        self.remote._drive = drive
