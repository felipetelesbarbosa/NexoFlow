"""Retomada após quota com revisão antiga já aplicada, sem reconciliação nova."""

import io
import json
import sqlite3
import unittest
from contextlib import closing, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import gspread
import requests
from google.auth.credentials import AnonymousCredentials

from history_publication import get, publisher_signature
from history_reconciliation import RECEIPT_KEY, reconcile
from history_sheets_quota import QuotaAdapter, QuotaGate
from history_snapshot import sha256
from tests import test_history_reconciliation as fixtures
from tests.test_history_sheets_quota import Clock, Google


class QuotaResumeTests(unittest.TestCase):
    setUp = fixtures.ReconciliationTests.setUp
    legacy = fixtures.ReconciliationTests.legacy
    command = fixtures.ReconciliationTests.command

    def test_legacy_review_after_pilot_quota_uncertain_response_and_rollback(self):
        review = self.legacy()
        receipt = reconcile(self.pub, review)
        source_hash = sha256(review["evidence"]["path"])
        signature = publisher_signature()
        clock = Clock()
        server = Google(clock)
        session = requests.Session()
        session.trust_env = False
        self.addCleanup(session.close)
        session.mount("https://", server)
        gate = QuotaGate(
            Path(self.tmp.name) / "network_quota.sqlite",
            user="synthetic@example.invalid",
            project="test-project",
            now=clock.now,
            sleep=clock.sleep,
        )
        session.mount("https://sheets.googleapis.com/", QuotaAdapter(server, gate))
        client = gspread.Client(auth=AnonymousCredentials(), session=session)
        read, write, geometry = (
            self.remote.read_rows,
            self.remote.write_rows,
            self.remote.geometry,
        )

        def request(method):
            return client.http_client.request(
                method,
                "https://sheets.googleapis.com/v4/spreadsheets/synthetic:batchUpdate",
            )

        def paced_read(*args, **kwargs):
            self.store._read_with_retry(
                "conferir intervalos do lote", lambda: request("get")
            )
            return read(*args, **kwargs)

        def paced_geometry(*args, **kwargs):
            self.store._read_with_retry(
                "conferir estrutura do backup de lote", lambda: request("get")
            )
            return geometry(*args, **kwargs)

        def paced_write(*args, **kwargs):
            request("post")  # Nenhum retry de POST no adaptador.
            return write(*args, **kwargs)

        def batches():
            with closing(sqlite3.connect(review["journal"])) as db:
                return dict(
                    db.execute("SELECT state,count(*) FROM batches GROUP BY state")
                )

        with (
            patch.object(self.remote, "read_rows", side_effect=paced_read),
            patch.object(self.remote, "geometry", side_effect=paced_geometry),
            patch.object(self.remote, "write_rows", side_effect=paced_write),
            patch("google_sheets.time.sleep", clock.sleep),
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(self.command("aplicar", "--max-lotes", "1")[0], 3)
            self.assertEqual(batches()["done"], 1)
            server.status = 429
            with (
                redirect_stderr(io.StringIO()) as errors,
                self.assertLogs(level="WARNING"),
            ):
                self.assertEqual(self.command("aplicar")[0], 1)
            self.assertIn("SHEETS_QUOTA", errors.getvalue())
            self.assertEqual(batches()["done"], 1)
            server.status = 200
            # Uma escrita foi efetivada, mas a resposta se perdeu: manter
            # sending e reconhecer os valores antes de qualquer reenvio.
            books = self.store.client.books
            with closing(self.pub._open(review)) as db:
                title, number = db.execute(
                    "SELECT t,p FROM batches WHERE state='pending' ORDER BY n LIMIT 1"
                ).fetchone()
            pending = next(
                p
                for p in self.store._continuity.index.parts.values()
                if p.title == title and p.number == number
            )
            target = books[pending.book_id]
            target.lose_data_response = True
            self.assertEqual(self.command("aplicar", "--max-lotes", "1")[0], 1)
            self.assertEqual(batches()["sending"], 1)
            from sheets_continuation import SheetsLease

            # Nova execução após expirar o bloqueio preservado pela resposta
            # perdida; não apagar lease nem forçar states para pending.
            lease = self.store._continuity.lease
            expires = json.loads(lease._lookup())["expires"]
            self.store._continuity.lease = SheetsLease(
                self.store.book, now=lambda: expires + 1
            )
            posts = sum(r.method == "POST" for _, r, _ in server.calls)
            self.assertEqual(self.command("aplicar", "--max-lotes", "1")[0], 3)
            self.assertEqual(sum(r.method == "POST" for _, r, _ in server.calls), posts)
            self.assertEqual(self.command("aplicar")[0], 0)
            self.assertEqual(self.command("conferir")[0], 0)
            self.assertEqual(self.pub.rollback(review, 1)["status"], "restaurado")
            self.assertEqual(self.command("aplicar")[0], 0)
            self.assertEqual(self.command("conferir")[0], 0)
            before = sum(r.method == "POST" for _, r, _ in server.calls)
            self.assertEqual(self.command("aplicar")[0], 0)
            self.assertEqual(
                sum(r.method == "POST" for _, r, _ in server.calls), before
            )
        self.assertEqual(self.review_path.read_bytes(), self.original_review)
        self.assertEqual(sha256(review["evidence"]["path"]), source_hash)
        self.assertEqual(publisher_signature(), signature)
        with closing(self.pub._open(review)) as db:
            self.assertEqual(get(db, RECEIPT_KEY), receipt)
            self.assertTrue(get(db, "finished"))
        self.assertEqual(
            self.pub.check(review)["conference"]["diferenca_pedidos_ltv_centavos"], 0
        )
