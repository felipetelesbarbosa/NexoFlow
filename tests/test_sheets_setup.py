"""Ativação do armazenamento sem migrar/gravar dados de negócio."""

import json
import shutil
import subprocess
import unittest
from pathlib import Path

from run_sheets_continuation import StorageSetup
from sheets_continuation import FILE_MARKER_KEY, INDEX_TITLE, ContinuationError
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
            ],
            cwd=ROOT,
            capture_output=True,
            encoding="utf-8",
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
