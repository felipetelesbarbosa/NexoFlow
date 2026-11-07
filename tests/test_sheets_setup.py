"""Ativação do armazenamento sem migrar/gravar dados de negócio."""

import json
import shutil
import subprocess
import time
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from requests import Timeout

from run_sheets_continuation import StorageSetup
from sheets_continuation import (
    FILE_MARKER_KEY,
    INDEX_TITLE,
    ContinuationError,
    stamp_book,
)
from sheets_provisioning import MyDriveProvisioner
from sheets_storage import STORAGE_SHEET, SheetsStorage
from tests.sheets_memory import Book, Client, Provisioner

ROOT = Path(__file__).resolve().parents[1]


class StorageSetupTests(unittest.TestCase):
    def make(self, segment="FARMA"):
        books = {key: Book(key) for key in ("dashboard", "operations", "history")}
        layout = SheetsStorage("dashboard", "operations", "history")
        books["dashboard"].add(STORAGE_SHEET, layout.values())
        books["dashboard"].add("BI_Publico", [["chave"], ["existing"]])
        books["operations"].add("Base_Contatos", [["contact_uuid"], ["untouched"]])
        books["history"].add("Historico_Alteracoes", [["contact_uuid"], ["untouched"]])
        client = Client(books)
        return StorageSetup(client, "dashboard", segment), Provisioner(client), books

    def test_configuration_creates_one_index_and_preserves_business_data(self):
        setup, provider, books = self.make()
        self.assertTrue(setup.configure(provider))
        self.assertEqual(setup.index.config["roots"]["operacao"], "operations")
        self.assertEqual(provider.creations, 0)
        self.assertEqual(
            books["operations"].worksheet("Base_Contatos").get_all_values(),
            [["contact_uuid"], ["untouched"]],
        )
        self.assertEqual(
            books["history"].worksheet("Historico_Alteracoes").get_all_values(),
            [["contact_uuid"], ["untouched"]],
        )
        self.assertEqual(
            books["dashboard"].worksheet("BI_Publico").get_all_values(),
            [["chave"], ["existing"]],
        )
        setup.close()
        again = StorageSetup(setup.client, "dashboard", "FARMA")
        self.assertFalse(again.configure(provider))
        self.assertEqual(
            sum(ws.title == INDEX_TITLE for ws in books["dashboard"].sheets), 1
        )
        self.assertEqual(
            sum(
                m.get("metadataKey") == FILE_MARKER_KEY
                for m in books["dashboard"].metadata.values()
            ),
            1,
        )
        again.close()

    def test_fresh_configuration_proves_all_three_origins(self):
        setup, provider, books = self.make()
        self.addCleanup(setup.close)
        self.assertTrue(all(not b.metadata for b in books.values()))
        setup.configure(provider)
        for role, key in setup.roots.items():
            tags = [
                m
                for m in books[key].metadata.values()
                if m["metadataKey"] == FILE_MARKER_KEY
            ]
            self.assertEqual(len(tags), 1, role)
            self.assertEqual(
                json.loads(tags[0]["metadataValue"]),
                dict(hub="dashboard", segment="FARMA", role=role),
            )

    def test_lost_configuration_response_is_verified_without_recreating_index(self):
        setup, provider, books = self.make()
        books["dashboard"].lose_data_response = True
        setup.configure(provider)
        self.assertEqual(books["dashboard"].data_writes, 1)
        self.assertTrue(setup.status()["ativo"])
        setup.close()

    def test_activation_requires_known_bi_table_and_index(self):
        setup, provider, _ = self.make()
        with self.assertRaises(ContinuationError):
            setup.activate_connector(["BI_Publico"])
        setup.configure(provider)
        with self.assertRaises(ContinuationError):
            setup.activate_connector(["Base_Contatos"])
        setup.activate_connector(["BI_Publico"])
        setup.activate_connector(["BI_Itens", "BI_Publico"])
        self.assertEqual(
            setup.index.config["connector_tables"], ["BI_Itens", "BI_Publico"]
        )
        setup.close()

    def test_segment_changed_on_reopening_rejects_index_before_write(self):
        setup, provider, _ = self.make()
        setup.configure(provider)
        setup.close()
        with self.assertRaises(ContinuationError):
            StorageSetup(setup.client, "dashboard", "PET")

    def test_all_markers_preflighted_before_any_origin_write(self):
        for target in ("operations", "history"):
            for conflict in (
                dict(segment="PET"),
                dict(role="dashboard"),
                dict(hub="other"),
            ):
                with self.subTest(target=target, conflict=conflict):
                    setup, provider, books = self.make()
                    self.addCleanup(setup.close)
                    args = dict(
                        hub="dashboard",
                        segment="FARMA",
                        role="operacao" if target == "operations" else "historico",
                    )
                    stamp_book(books[target], **(args | conflict))
                    previous = deepcopy({k: b.metadata for k, b in books.items()})
                    with self.assertRaises(ContinuationError):
                        setup.configure(provider)
                    setup.close()
                    self.assertEqual(
                        {k: b.metadata for k, b in books.items()}, previous
                    )
                    self.assertNotIn(
                        INDEX_TITLE, [w.title for w in setup.hub.worksheets()]
                    )

    def test_partial_initialization_and_lost_marker_response_resume_without_duplicates(
        self,
    ):
        setup, provider, books = self.make()
        self.addCleanup(setup.close)
        # Índice/Dashboard gravados; resposta de Operação perdida depois do commit.
        books["operations"].lose_response = True
        with self.assertRaises(Timeout):
            setup.configure(provider)
        setup.close()
        again = StorageSetup(setup.client, "dashboard", "FARMA")
        self.addCleanup(again.close)
        again.lease.now = lambda: time.time() + 301
        self.assertFalse(again.configure(provider))
        before = deepcopy({k: b.metadata for k, b in books.items()})
        self.assertFalse(again.configure(provider))
        self.assertEqual({k: b.metadata for k, b in books.items()}, before)
        for book in books.values():
            self.assertEqual(
                sum(
                    m["metadataKey"] == FILE_MARKER_KEY for m in book.metadata.values()
                ),
                1,
            )

    def test_same_id_two_roles_rejected_before_marker_write(self):
        setup, provider, books = self.make()
        self.addCleanup(setup.close)
        setup.roots["historico"] = setup.roots["operacao"]
        with self.assertRaisesRegex(ContinuationError, "diferentes"):
            setup.configure(provider)
        self.assertFalse(any(b.metadata for b in books.values()))

    def test_real_provider_decisions_check_all_permissions_before_stamping(self):
        for failure in ("service", "oauth", "public_folder", "drive_timeout", None):
            with self.subTest(failure=failure):
                setup, _, books = self.make()
                self.addCleanup(setup.close)
                provider = MyDriveProvisioner.__new__(MyDriveProvisioner)
                provider.source, provider.owner = object(), object()
                reads = []

                def get(
                    session,
                    path,
                    failure=failure,
                    reads=reads,
                    provider=provider,
                    **kwargs,
                ):
                    reads.append((session, path))
                    if failure == "drive_timeout" and path == "/files/history":
                        raise Timeout("synthetic")
                    if path.endswith("/permissions"):
                        return dict(
                            permissions=[
                                dict(
                                    type="anyone"
                                    if failure == "public_folder" and "folder" in path
                                    else "user",
                                    role="owner",
                                    emailAddress="fake@example.invalid",
                                )
                            ]
                        )
                    key = path.rsplit("/", 1)[-1]
                    allowed = not (
                        key == "history"
                        and (
                            failure == "service"
                            and session is provider.source
                            or failure == "oauth"
                            and session is provider.owner
                        )
                    )
                    return dict(
                        id=key,
                        name="Synthetic",
                        mimeType="application/vnd.google-apps.spreadsheet",
                        parents=["folder"],
                        capabilities=dict(canEdit=allowed),
                    )

                with patch.object(provider, "_get", side_effect=get):
                    if failure:
                        with self.assertRaises((ContinuationError, Timeout)):
                            setup.configure(provider)
                        self.assertFalse(
                            any(
                                m["metadataKey"] == FILE_MARKER_KEY
                                for b in books.values()
                                for m in b.metadata.values()
                            )
                        )
                    else:
                        self.assertTrue(setup.configure(provider))
                        self.assertTrue(
                            all(
                                any(
                                    m["metadataKey"] == FILE_MARKER_KEY
                                    for m in b.metadata.values()
                                )
                                for b in books.values()
                            )
                        )
                self.assertTrue(reads)

    def test_duplicate_or_malformed_marker_blocks_before_index(self):
        for duplicate in (False, True):
            setup, provider, books = self.make()
            self.addCleanup(setup.close)
            stamp_book(
                books["history"], hub="dashboard", segment="FARMA", role="historico"
            )
            tag = next(iter(books["history"].metadata.values()))
            if duplicate:
                books["history"].metadata[999] = deepcopy(tag)
            else:
                tag["location"] = {"sheetId": 1}
            with self.assertRaises(ContinuationError):
                setup.configure(provider)
            self.assertFalse(books["operations"].metadata)


class ConnectorContractTests(unittest.TestCase):
    def test_exported_schema_matches_current_bi_headers_and_csv_fields_are_text(self):
        from google_sheets import GoogleSheetsStore

        source = (ROOT / "connectors/continuacoes/Schemas.js").read_text(
            encoding="utf-8"
        )
        specs = json.loads(source[source.index("= ") + 2 : source.index(";\nif")])
        expected = GoogleSheetsStore.bi_schemas()
        self.assertEqual({t: [v[0] for v in h] for t, h in specs.items()}, expected)
        self.assertEqual(dict(specs["BI_Pedidos"])["pedido_quantidade_itens"], "text")
        self.assertEqual(dict(specs["BI_Pedidos"])["pedido_valor_produtos"], "text")
        self.assertEqual(dict(specs["BI_Publico"])["idade"], "number_dimension")

    @unittest.skipUnless(
        shutil.which("node"),
        "Node.js disponível somente na validação de desenvolvimento/CI.",
    )
    def test_actual_connector_readers_and_abc_with_synthetic_apis(self):
        result = subprocess.run(
            [
                "node",
                "--test",
                "tests/test_continuation_connector.cjs",
                "tests/test_looker_abc_connector.cjs",
                "tests/test_history_connector.cjs",
            ],
            cwd=ROOT,
            capture_output=True,
            encoding="utf-8",
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
