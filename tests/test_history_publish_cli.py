"""Comando real do Terminal com SQLite sintético e transporte Sheets sem rede."""

import io
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing, redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from history_snapshot import readonly, sha256, snapshot
from nexo_cli import run
from order_history import HistoryError, normalize_order
from order_history_store import HistoryStore
from tests.test_history_publication import Sheets, fixture
from tests.test_order_history import NOW, order


class LocalSheets(Sheets):
    def close(self):
        self.closed = True


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "fonte.sqlite"
        source, _ = fixture(9)
        with closing(sqlite3.connect(self.source)) as db:
            source.backup(db)
            db.execute("CREATE TABLE profile(segment TEXT NOT NULL)")
            db.execute("INSERT INTO profile VALUES('FARMA')")
            db.commit()
        source.close()
        self.remote = LocalSheets()
        self.review = self.root / "privado" / "revisao.json"
        patches = [
            patch.dict(os.environ, NEXOFLOW_PERFIL="FARMA"),
            patch("config.LOG_DIR", self.root),
            patch("customer_observations.DB_ROOT", None),
            patch("proxy_config.configure_proxy"),
            patch(
                "project_paths.load_private_settings",
                return_value=SimpleNamespace(GOOGLE_SPREADSHEET_ID="dashboard"),
            ),
            patch(
                "history_publish_cli.google_store_type",
                return_value=SimpleNamespace(
                    open_native_readonly=lambda _: self.remote
                ),
            ),
            patch(
                "nexo_cli._make_farmalider_client",
                side_effect=AssertionError("não consultar API comercial"),
            ),
            patch(
                "nexo_cli._make_weni_client",
                side_effect=AssertionError("não executar Weni"),
            ),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def command(self, *args):
        with redirect_stdout(io.StringIO()) as output:
            result = run(["historico", *args])
        return result, output.getvalue()

    def test_prepare_pilot_check_resume_and_rollback_without_commercial_collection(
        self,
    ):
        before = sha256(self.source)
        code, _ = self.command(
            "--planilhas",
            "preparar",
            "--banco",
            str(self.source),
            "--revisao",
            str(self.review),
        )
        self.assertEqual(code, 0)
        self.assertEqual(self.remote.writes, 0)
        saved = json.loads(self.review.read_text())
        self.assertIn("conference", saved["evidence"])
        code, out = self.command(
            "--planilhas", "aplicar", "--revisao", str(self.review), "--max-lotes", "1"
        )
        self.assertEqual(code, 3)
        self.assertIn("pausada", out)
        code, _ = self.command("--planilhas", "conferir", "--revisao", str(self.review))
        self.assertEqual(code, 3)
        code, _ = self.command("--planilhas", "aplicar", "--revisao", str(self.review))
        self.assertEqual(code, 0)
        code, _ = self.command(
            "--planilhas",
            "conferir",
            "--revisao",
            str(self.review),
            "--resumo-mensal",
            str(self.root / "mensal.json"),
        )
        self.assertEqual(code, 0)
        report = json.loads((self.root / "mensal.json").read_text())
        self.assertEqual(report["conference"]["diferenca_pedidos_ltv_centavos"], 0)
        code, _ = self.command(
            "--planilhas", "rollback", "--revisao", str(self.review), "--lote", "1"
        )
        self.assertEqual(code, 0)
        self.assertEqual(sha256(self.source), before)
        self.assertTrue(self.remote.closed)

    def test_snapshot_includes_committed_wal_and_does_not_modify_original(self):
        with closing(sqlite3.connect(self.source)) as writer:
            writer.execute("PRAGMA journal_mode=WAL")
            store = HistoryStore(writer, "FARMA")
            with writer:
                store.upsert(
                    normalize_order(order(99, segment="FARMA"), "FARMA", NOW),
                    now=NOW,
                    mode="historica",
                )
            before = sha256(self.source)
            evidence = snapshot(self.source, self.root / "copias", "FARMA")
            with readonly(evidence["path"], "FARMA") as view:
                self.assertEqual(sum(1 for _ in view.records()), 10)
                with self.assertRaises(sqlite3.OperationalError):
                    view.db.execute("DELETE FROM history_orders")
            self.assertEqual(sha256(self.source), before)
            self.assertEqual(sha256(evidence["path"]), evidence["sha256"])
        with self.assertRaises(HistoryError):
            snapshot(self.source, self.root / "pet-copias", "PET")
        self.assertFalse(list((self.root / "pet-copias").glob("*.sqlite")))

    def test_quota_auth_and_transport_errors_do_not_print_provider_payload(self):
        from gspread.exceptions import APIError
        from requests import Response

        for status in (400, 401, 403, 429, 503):
            response = Response()
            response.status_code = status
            response._content = json.dumps(
                {
                    "error": {
                        "code": status,
                        "message": "detalhe privado que não deve sair",
                    }
                }
            ).encode()
            with (
                patch(
                    "history_publish_cli.google_store_type",
                    side_effect=APIError(response),
                ),
                redirect_stderr(io.StringIO()) as errors,
            ):
                code, _ = self.command(
                    "--planilhas",
                    "preparar",
                    "--banco",
                    str(self.source),
                    "--revisao",
                    str(self.review),
                )
            self.assertEqual(code, 1)
            self.assertNotIn("detalhe privado", errors.getvalue())
            self.assertIn("SHEETS_", errors.getvalue())

    def test_grid_error_has_safe_stage_without_provider_values(self):
        from gspread.exceptions import APIError
        from requests import Response

        response = Response()
        response.status_code = 400
        response._content = json.dumps(
            {
                "error": {
                    "code": 400,
                    "message": "Range (private client token=synthetic-private) exceeds grid limits",
                }
            }
        ).encode()
        error = APIError(response)
        error.nexoflow_operation = "conferir intervalos do lote"
        with (
            patch("history_publish_cli.google_store_type", side_effect=error),
            redirect_stderr(io.StringIO()) as errors,
        ):
            code, _ = self.command(
                "--planilhas",
                "preparar",
                "--banco",
                str(self.source),
                "--revisao",
                str(self.review),
            )
        self.assertEqual(code, 1)
        text = errors.getvalue()
        self.assertIn("etapa=conferir intervalos do lote", text)
        self.assertIn("intervalo fora da grade", text)
        self.assertNotIn("private", text)

    def test_read_quota_uses_increasing_backoff_and_preserves_retry_after(self):
        from unittest.mock import Mock

        from gspread.exceptions import APIError
        from requests import Response

        from google_sheets import GoogleSheetsStore

        response = Response()
        response.status_code = 429
        response._content = b'{"error":{"code":429,"message":"synthetic"}}'
        error = APIError(response)
        store = GoogleSheetsStore.__new__(GoogleSheetsStore)
        for retry_after, expected in ((None, [5.0, 10.0, 20.0]), ("71", [71.0] * 3)):
            response.headers.clear()
            if retry_after:
                response.headers["Retry-After"] = retry_after
            operation = Mock(side_effect=[error, error, error, "ok"])
            with patch("google_sheets.time.sleep") as sleep:
                self.assertEqual(
                    store._read_with_retry("ler bloco do histórico", operation), "ok"
                )
                self.assertEqual([c.args[0] for c in sleep.call_args_list], expected)
        operation = Mock(side_effect=error)
        with (
            patch("google_sheets.time.sleep"),
            patch("google_sheets.GOOGLE_SHEETS_READ_MAX_RETRIES", 2),
        ):
            with self.assertRaises(APIError):
                store._read_with_retry("ler bloco do histórico", operation)
        self.assertEqual(operation.call_count, 2)
        self.assertEqual(error.nexoflow_operation, "ler bloco do histórico")

    def test_transport_error_does_not_print_provider_payload(self):
        from requests import Timeout

        with (
            patch(
                "history_publish_cli.google_store_type",
                side_effect=Timeout("resposta privada"),
            ),
            redirect_stderr(io.StringIO()) as errors,
        ):
            code, _ = self.command(
                "--planilhas",
                "preparar",
                "--banco",
                str(self.source),
                "--revisao",
                str(self.review),
            )
        self.assertEqual(code, 1)
        self.assertNotIn("resposta privada", errors.getvalue())
        self.assertIn("SHEETS_TRANSPORTE", errors.getvalue())
