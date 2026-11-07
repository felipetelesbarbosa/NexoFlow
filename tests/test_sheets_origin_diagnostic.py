"""Origem oficial Google: leitura sanitizada, pré-voo e compatibilidade legada."""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from gspread.exceptions import APIError
from requests import Response, Timeout

from run_sheets_continuation import diagnose_origins, run
from scripts.armazenamento_1_5_22 import source_hash, validate_installation
from sheets_continuation import (
    FILE_MARKER_KEY,
    INDEX_TITLE,
    ContinuationError,
    ContinuationIndex,
    origin_diagnostic,
    stamp_book,
    verify_book_stamp,
)
from sheets_provisioning import MyDriveProvisioner
from tests import test_sheets_setup
from tests.sheets_memory import Book


class OriginTests(unittest.TestCase):
    def make(self):
        setup, provider, books = test_sheets_setup.StorageSetupTests().make()
        self.addCleanup(setup.close)
        return setup, provider, books

    def test_semantic_json_and_google_response_location_are_idempotent(self):
        setup, provider, books = self.make()
        for role, key in setup.roots.items():
            books[key].metadata[1] = dict(
                metadataKey=FILE_MARKER_KEY,
                metadataValue=json.dumps(
                    dict(segment="FARMA", role=role, hub="dashboard"),
                    separators=(",", ":"),
                ),
                location=dict(locationType="SPREADSHEET", spreadsheet=True),
                visibility="DOCUMENT",
            )
        before = deepcopy({k: b.metadata for k, b in books.items()})
        setup.configure(provider)
        setup.close()
        self.assertEqual(before, {k: b.metadata for k, b in books.items()})

    def test_real_conflicts_report_file_role_and_field_without_remote_values(self):
        for changes, field in [
            (
                {
                    "metadataValue": '{"hub":"dashboard","role":"historico","segment":"PET"}'
                },
                "segment",
            ),
            (
                {
                    "metadataValue": '{"hub":"SECRET_TOKEN_SYNTHETIC","role":"historico","segment":"FARMA"}'
                },
                "hub",
            ),
            (
                {
                    "metadataValue": '{"hub":"dashboard","role":"operacao","segment":"FARMA"}'
                },
                "role",
            ),
            ({"location": {"sheetId": 1}}, "location"),
            ({"location": {"spreadsheet": True, "locationType": "ROW"}}, "location"),
            ({"visibility": "PROJECT"}, "visibility"),
            (
                {"metadataValue": '{"hub":"dashboard","hub":"other"}'},
                "metadataValue.json",
            ),
            ({"metadataValue": "[]"}, "metadataValue.json"),
            ({"metadataValue": "SECRET_TOKEN_SYNTHETIC"}, "metadataValue.json"),
        ]:
            with self.subTest(field=field, changes=changes):
                setup, provider, books = self.make()
                stamp_book(
                    books["history"], hub="dashboard", segment="FARMA", role="historico"
                )
                next(iter(books["history"].metadata.values())).update(changes)
                before = {k: b.writes for k, b in books.items()}
                with self.assertRaises(ContinuationError) as error:
                    setup.configure(provider)
                self.assertIn("arquivo=history; papel=historico", str(error.exception))
                self.assertIn(field, str(error.exception))
                self.assertNotIn("SECRET_TOKEN_SYNTHETIC", str(error.exception))
                self.assertEqual(before, {k: b.writes for k, b in books.items()})
                report = origin_diagnostic(
                    books["history"].fetch_sheet_metadata(),
                    hub="dashboard",
                    segment="FARMA",
                    role="historico",
                )
                self.assertNotIn("SECRET_TOKEN_SYNTHETIC", json.dumps(report))

    def test_legitimate_continuation_marker_is_preserved(self):
        book = Book("continuation")
        stamp_book(book, hub="dashboard", segment="FARMA", role="historico")
        next(iter(book.metadata.values()))["location"]["locationType"] = "SPREADSHEET"
        before = deepcopy(book.metadata)
        writes = book.writes
        self.assertTrue(
            verify_book_stamp(book, hub="dashboard", segment="FARMA", role="historico")
        )
        stamp_book(book, hub="dashboard", segment="FARMA", role="historico")
        self.assertEqual(book.metadata, before)
        self.assertEqual(book.writes, writes)

    def test_primary_cannot_adopt_a_continuation_or_conflicting_drive_property(self):
        provider = MyDriveProvisioner.__new__(MyDriveProvisioner)
        for properties in (
            {"nexoflow_operation": "a" * 32},
            {"nexoflow_segment": "PET"},
            {"nexoflow_role": "operacao"},
        ):
            with patch.object(
                provider, "source_info", return_value={"properties": properties}
            ):
                with self.assertRaisesRegex(ContinuationError, "continuação"):
                    provider.prepare_intent(
                        "history",
                        "b" * 32,
                        hub="dashboard",
                        segment="FARMA",
                        role="historico",
                        number=1,
                        primary=True,
                    )

    def client(self, setup, *, failure=None):
        def request(method, url, **kwargs):
            self.assertEqual(method, "get")
            key = url.rsplit("/", 1)[-1]
            return SimpleNamespace(
                json=lambda: dict(
                    id=key,
                    mimeType="application/vnd.google-apps.spreadsheet",
                    capabilities={"canEdit": True},
                    properties=setup.client.properties.get(key, {}),
                    parents=["folder"],
                )
            )

        setup.client.http_client.request = request
        return setup.client

    def test_diagnostic_reports_three_roots_and_continuation_without_writes(self):
        setup, _, books = self.make()
        index = ContinuationIndex("dashboard", "FARMA", setup.roots)
        index.files["part"] = dict(role="historico", number=1, source="history")
        books["dashboard"].add(INDEX_TITLE, index.values())
        books["part"] = Book("part")
        stamp_book(books["part"], hub="dashboard", segment="FARMA", role="historico")
        setup.client.properties["part"] = dict(
            nexoflow_hub="dashboard",
            nexoflow_role="historico",
            nexoflow_segment="FARMA",
            nexoflow_operation="a" * 32,
        )
        before = {k: b.writes for k, b in books.items()}
        report = diagnose_origins(self.client(setup), "dashboard", "FARMA")
        self.assertTrue(report["origens_compativeis"])
        self.assertEqual(
            [r["resultado"] for r in report["arquivos"]], ["AUSENTE"] * 3 + ["APROVADO"]
        )
        self.assertEqual(report["arquivos"][-1]["tipo"], "continuacao")
        self.assertEqual(before, {k: b.writes for k, b in books.items()})

    def test_diagnostic_preserves_primary_with_continuation_intent_even_if_empty(self):
        setup, _, books = self.make()
        setup.client.properties["operations"] = {"nexoflow_operation": ""}
        report = diagnose_origins(self.client(setup), "dashboard", "FARMA")
        self.assertFalse(report["origens_compativeis"])
        self.assertEqual(report["arquivos"][1]["resultado"], "BLOQUEADO")
        self.assertIn(
            "principal_tem_intencao_de_continuacao",
            report["arquivos"][1]["drive"]["campos_divergentes"],
        )
        self.assertTrue(all(b.writes == 0 for b in books.values()))

    def test_diagnostic_continues_after_permission_or_transport_failure(self):
        response = Response()
        response.status_code = 403
        response._content = b'{"error":{"code":403,"message":"SECRET_TOKEN_SYNTHETIC"}}'
        for error, expected in (
            (APIError(response), "LEITURA_NEGADA"),
            (Timeout("SECRET_TOKEN_SYNTHETIC"), "FALHA_DE_LEITURA"),
        ):
            setup, _, books = self.make()
            with patch.object(
                books["operations"], "fetch_sheet_metadata", side_effect=error
            ):
                report = diagnose_origins(self.client(setup), "dashboard", "FARMA")
            self.assertFalse(report["origens_compativeis"])
            self.assertEqual(len(report["arquivos"]), 3)
            self.assertEqual(report["arquivos"][1]["resultado"], expected)
            self.assertNotIn("quantidade_marcadores", report["arquivos"][1])
            self.assertNotIn("SECRET_TOKEN_SYNTHETIC", json.dumps(report))
            self.assertTrue(all(b.writes == 0 for b in books.values()))

    def test_cli_readonly_has_no_oauth_no_setup_no_lease_and_returns_pending(self):
        for allowed in (True, False):
            client = Mock()
            with (
                patch("proxy_config.configure_proxy"),
                patch("gspread.service_account", return_value=client) as auth,
                patch(
                    "run_sheets_continuation.diagnose_origins",
                    return_value={"origens_compativeis": allowed},
                ),
                patch("run_sheets_continuation.StorageSetup") as setup,
                patch("sheets_provisioning.authorize_user") as oauth,
                redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(run(["diagnosticar-origens"]), 0 if allowed else 3)
            self.assertTrue(
                all(
                    scope.endswith("readonly")
                    for scope in auth.call_args.kwargs["scopes"]
                )
            )
            oauth.assert_not_called()
            setup.assert_not_called()
            client.http_client.session.close.assert_called_once()

    def test_terminal_routes_the_diagnostic_to_the_real_parser(self):
        import nexo_cli

        client = Mock()
        with (
            patch("proxy_config.configure_proxy"),
            patch("gspread.service_account", return_value=client),
            patch(
                "run_sheets_continuation.diagnose_origins",
                return_value={"origens_compativeis": True},
            ) as read,
            patch("sys.argv", ["nexo", "armazenamento", "diagnosticar-origens"]),
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(nexo_cli.main(), 0)
        read.assert_called_once()

    def test_auxiliary_refuses_wrong_version_and_changed_installed_modules(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "app").mkdir()
            (root / "VERSION").write_text("1.5.22", encoding="utf-8")
            source = root / "app" / "example.py"
            source.write_bytes(b"# fixture\r\n")
            expected = {"example": source_hash(source)}
            validate_installation(root, expected)
            source.write_text("# fixture\n", encoding="utf-8")
            validate_installation(root, expected)
            source.write_text("# changed", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "divergem"):
                validate_installation(root, expected)
            (root / "VERSION").write_text("1.5.23", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "original"):
                validate_installation(root, expected)
