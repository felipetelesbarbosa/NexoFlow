"""Duas autoridades reais de decisão, sem credenciais ou acesso comercial."""

import io
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from requests import HTTPError, Response

from history_publication import get
from order_history import digest
from scripts import diagnosticar_acessos_historico as audit
from tests import test_history_sheets_transport as transport_fixture
from tests.test_history_publication import fixture, stream


class AccessDiagnosticTests(unittest.TestCase):
    setUp = transport_fixture.TransportTests.setUp

    def prepared(self):
        db, data = fixture(9)
        self.addCleanup(db.close)
        plan = self.pub.prepare(stream(data))
        self.pub.apply(plan, max_batches=1)
        self.store._continuity.close()
        with closing(self.pub._open_local(plan)) as journal:
            return plan, get(journal, "metadata"), get(journal, "manifest")

    def test_collects_both_authorities_without_writes_or_private_fields(self):
        plan, metadata, manifest = self.prepared()
        before = deepcopy(
            [
                [b.data_writes for b in self.store.client.books.values()],
                self.provider.permissions,
                self.provider.shared,
                self.provider.creations,
            ]
        )
        result = audit.inspect_access(
            self.remote, metadata, plan, {"pending": 10}, manifest
        )
        self.assertEqual(
            before,
            [
                [b.data_writes for b in self.store.client.books.values()],
                self.provider.permissions,
                self.provider.shared,
                self.provider.creations,
            ],
        )
        self.assertFalse(result["autoriza_aplicacao"])
        self.assertTrue(result["manifesto_confere"])
        created = [f for f in result["arquivos"] if f["tipo"] == "continuacao_nova"]
        self.assertTrue(created)
        for file in created:
            self.assertTrue(file["pastas"]["oauth_confere"])
            self.assertFalse(file["pastas"]["comparacao_cruzada_1_5_27_confere"])
            self.assertTrue(file["pastas"]["visoes_diferentes_com_oauth_confirmado"])
            self.assertTrue(file["compartilhamento_privado_confere"])
        text = json.dumps(result)
        for forbidden in (
            self.provider.owner_email,
            self.provider.service_email,
            "emailAddress",
            "access_token",
        ):
            self.assertNotIn(forbidden, text)
        with self.assertRaisesRegex(audit.DiagnosticError, "BLOQUEOU_ESCRITA"):
            self.provider.owner.request("POST", "https://example.invalid")

    def test_collects_real_folder_change_and_next_acl_guard_in_one_pass(self):
        plan, metadata, manifest = self.prepared()
        target = next(
            book
            for book in self.store._continuity.index.files
            if book not in metadata["books"]
        )
        self.provider.owner_parents[target] = ["moved"]
        self.provider.permissions[target].append(dict(type="anyone", role="reader"))
        result = audit.inspect_access(
            self.remote, metadata, plan, {"pending": 10}, manifest
        )
        item = next(i for i in result["arquivos"] if i["arquivo"] == target)
        self.assertFalse(item["pastas"]["oauth_confere"])
        self.assertFalse(item["pastas"]["visoes_diferentes_com_oauth_confirmado"])
        self.assertFalse(item["compartilhamento_privado_confere"])
        self.assertEqual(item["falha_compartilhamento"]["tipo"], "ContinuationError")
        self.assertGreaterEqual(len(result["arquivos"]), 4)

    def test_prepared_headers_and_native_structure_are_audited_without_data_dump(self):
        plan, metadata, manifest = self.prepared()
        manager = self.store._continuity
        target = next(
            p
            for p in manager.index.parts.values()
            if manager.worksheet(p).row_count == 1
        )
        manager.worksheet(target).native_cells[0, 0] = {
            "note": "NOTA_PRIVADA_SINTETICA"
        }
        result = audit.inspect_access(self.remote, metadata, plan, {}, manifest)
        item = next(
            p
            for p in result["partes_preparadas"]
            if p["arquivo"] == target.book_id and p["aba_id"] == target.sheet_id
        )
        self.assertTrue(item["cabecalho_exato"])
        self.assertIn("falha_leitura_ou_estrutura", item)
        self.assertNotIn("NOTA_PRIVADA_SINTETICA", json.dumps(result))
        self.assertTrue(result["manifesto_estavel_durante_diagnostico"])

    def test_failed_reads_are_not_classified_as_folder_changes_or_leak_errors(self):
        plan, metadata, manifest = self.prepared()
        response = Response()
        response.status_code = 403
        failure = HTTPError(
            "https://example.invalid?access_token=SEGREDO_SINTETICO", response=response
        )
        with patch.object(self.remote, "_drive", side_effect=failure):
            result = audit.inspect_access(self.remote, metadata, plan, {}, manifest)
        self.assertTrue(
            all(i["falha_leitura"]["http"] == 403 for i in result["arquivos"])
        )
        self.assertNotIn("SEGREDO_SINTETICO", json.dumps(result))
        self.assertIsNone(
            audit.error_summary(ValueError("TOKEN_PRIVADO_SINTETICO"))["codigo"]
        )

    def test_terminal_cli_reads_journal_without_changes_and_refuses_overwrite(self):
        plan, _, _ = self.prepared()
        private = Path(self.tmp.name)
        # Reutilizar o journal real do publicador em uma instalação temporária.
        root = private / "installed"
        folder = root / "logs" / "privado" / "historico_publicacoes"
        folder.mkdir(parents=True)
        source_journal = Path(plan["journal"])
        target = folder / "journal.sqlite"
        with (
            closing(sqlite3.connect(source_journal)) as src,
            closing(sqlite3.connect(target)) as dst,
        ):
            src.backup(dst)
        plan["journal"] = str(target)
        plan.pop("digest")
        plan["digest"] = digest(plan)
        with closing(sqlite3.connect(target)) as db:
            db.execute("UPDATE meta SET v=? WHERE k='review'", (json.dumps(plan),))
            db.commit()
        review = root / "logs" / "privado" / "review.json"
        review.write_text(json.dumps(plan), encoding="utf-8")
        output = review.with_name("diagnostico.json")
        before = audit.sha256(target)
        args = [
            "--instalacao",
            str(root),
            "--perfil",
            "FARMA",
            "--revisao",
            str(review),
            "--saida",
            str(output),
        ]
        store = SimpleNamespace(close=lambda: None)
        with (
            patch.dict(os.environ, NEXOFLOW_PERFIL="FARMA"),
            patch.object(audit, "validate_installation"),
            patch("project_paths.ROOT", root),
            patch(
                "project_paths.load_private_settings",
                return_value=SimpleNamespace(GOOGLE_SPREADSHEET_ID="dashboard"),
            ),
            patch("proxy_config.configure_proxy"),
            patch(
                "google_sheets.GoogleSheetsStore.open_native_readonly",
                return_value=store,
            ),
            patch("history_sheets_transport.SheetsTransport", return_value=self.remote),
            redirect_stdout(io.StringIO()) as text,
        ):
            self.assertEqual(audit.main(args), 0)
            self.assertEqual(audit.main(args), 1)
        self.assertIn("RELATORIO_JA_EXISTE", text.getvalue())
        result = json.loads(output.read_text(encoding="utf-8"))
        self.assertTrue(result["journal_inalterado"])
        self.assertEqual(audit.sha256(target), before)
        self.assertEqual(json.loads(review.read_text(encoding="utf-8")), plan)
        with closing(sqlite3.connect(target)) as db:
            self.assertEqual(
                json.loads(
                    db.execute("SELECT v FROM meta WHERE k='review'").fetchone()[0]
                ),
                plan,
            )

    def test_installation_validation_normalizes_crlf_and_refuses_modified_modules(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app").mkdir()
            (root / "VERSION").write_text("1.5.27\n", encoding="utf-8")
            module = root / "app" / "module.py"
            module.write_bytes(b"# synthetic\r\n")
            import hashlib

            expected = {"module.py": hashlib.sha256(b"# synthetic\n").hexdigest()}
            with patch.object(audit, "INSTALLED_HASHES", expected):
                audit.validate_installation(root)
                module.write_bytes(b"# changed\n")
                with self.assertRaisesRegex(
                    audit.DiagnosticError, "MODULOS_INSTALADOS"
                ):
                    audit.validate_installation(root)
