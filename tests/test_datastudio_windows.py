"""Contrato Windows executado por unittest nas quatro combinações do CI."""

import os
import unittest
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from ds_backend.adapter import PostgresStore
from ds_backend.client import Client
from ds_backend.contract import (
    REGISTRY,
    SCHEMA_HASH,
    StorageError,
    digest,
    normalize,
    record_key,
)
from runtime_profile import select_settings


class ClientMemory:
    def __init__(self):
        self.tables = {}
        self.config = {"segment": "FARMA"}
        self.expected_target = "synthetic.farma"
        self.reads = self.writes = 0
        self.receipts = {}

    def begin(self, *_args):
        return {"revision": str(uuid4())}

    def rows(self, name, _revision):
        yield from deepcopy(self.tables.get(name, []))

    def send(self, revision, name, rows, remove=None):
        current = {record_key(name, r): r for r in self.tables.get(name, [])}
        current.update({record_key(name, r): r for r in rows})
        for key in remove or []:
            current.pop(key, None)
        self.tables[name] = list(current.values())
        receipt = {"state": "CONFIRMADO", "id": str(uuid4()), "hash": digest(rows)}
        self.receipts[receipt["id"]] = receipt["hash"]
        return receipt

    def call(self, path, data):
        if path == "/v1/selar":
            return {"state": "SELADA"}
        if path == "/v1/confirmar":
            if data["manifest"]["batches"] != self.receipts:
                raise AssertionError("recibos divergentes")
            return {"state": "READY", "revision": data["revision"], "version": 2,
                    "manifest_hash": digest(data["manifest"])}
        return {}

    def close(self):
        pass


class DatastudioWindowsTests(unittest.TestCase):
    def test_backend_does_not_open_google_and_preserves_contact_and_control(self):
        with patch(
            "google_sheets.GoogleSheetsStore.__init__",
            side_effect=AssertionError("Google proibido"),
        ):
            client = ClientMemory()
            store = PostgresStore(client)
            first = store.upsert_contacts_detailed(
                [{"contact_uuid": "synthetic-contact", "weni_name": "Sintético"}]
            )
            self.assertEqual(first.inserted, 1)
            self.assertEqual(
                store.upsert_contacts_detailed(
                    [{"contact_uuid": "synthetic-contact", "weni_name": "Sintético"}]
                ).unchanged,
                1,
            )
            store.set_controls(
                {"ultima_sincronizacao_sucesso_utc": "2026-11-02T12:00:00Z"}
            )
            self.assertEqual(
                store.get_control("ultima_sincronizacao_sucesso_utc"),
                "2026-11-02T12:00:00Z",
            )
            self.assertEqual(store.finish(complete=True)["state"], "READY")

    def test_pet_profile_requires_own_publisher_and_does_not_require_sheets(self):
        settings = SimpleNamespace(
            PERFIS={
                "FARMA": {
                    "WENI_API_TOKEN": "synthetic-farma",
                    "ARMAZENAMENTO_BACKEND": "postgres",
                    "DATASTUDIO_CREDENTIALS_FILE": "credentials/datastudio/FARMA/homologacao/publicacao.json",
                },
                "PET": {
                    "WENI_API_TOKEN": "synthetic-pet",
                    "FARMALIDER_API_TOKEN": "synthetic-delivery",
                    "ARMAZENAMENTO_BACKEND": "postgres",
                    "DATASTUDIO_CREDENTIALS_FILE": "credentials/datastudio/PET/homologacao/publicacao.json",
                },
            }
        )
        with patch.dict(os.environ, {"NEXOFLOW_PERFIL": "PET"}):
            selected = select_settings(settings)
            self.assertFalse(hasattr(selected, "GOOGLE_SPREADSHEET_ID"))
            self.assertIn("/PET/", selected.DATASTUDIO_CREDENTIALS_FILE)
            settings.PERFIS["PET"]["DATASTUDIO_CREDENTIALS_FILE"] = settings.PERFIS[
                "FARMA"
            ]["DATASTUDIO_CREDENTIALS_FILE"]
            with self.assertRaises(ValueError):
                select_settings(settings)

    def test_item_text_identifiers_and_exact_decimal_no_nan(self):
        fields = REGISTRY["BI_Itens"]["columns"]
        record = {name: "" for name in fields}
        record.update(
            item_chave="synthetic",
            produto_codigo="0001",
            quantidade="2",
            receita_item="0.20",
            sku_informado="1",
        )
        normalized = normalize("BI_Itens", [record], "FARMA")[0]
        self.assertEqual(normalized["produto_codigo"], "0001")
        self.assertEqual(Decimal(normalized["receita_item"]), Decimal("0.20"))
        with self.assertRaises(StorageError):
            normalize("BI_Itens", [dict(record, quantidade="NaN")], "FARMA")

    def test_unconfirmed_receipt_never_becomes_success_and_no_redirect(self):
        from ds_backend.contract import PROTOCOL

        class Session:
            headers = {}

            def request(self, method, url, **kwargs):
                if kwargs["allow_redirects"] is not False:
                    raise AssertionError("redirecionamento")
                payload = (
                    {
                        "protocol": PROTOCOL,
                        "target": "nexoflow_datastudio_homologacao.farma",
                        "segment": "FARMA",
                        "environment": "homologacao",
                        "schema_hash": SCHEMA_HASH,
                    }
                    if url.endswith("/destino")
                    else {"state": "CONFIRMADO", "revision": str(uuid4())}
                )
                return SimpleNamespace(status_code=200, json=lambda: payload)

            def close(self):
                pass

        client = Client(
            dict(
                protocol=PROTOCOL,
                segment="FARMA",
                environment="homologacao",
                endpoint="https://synthetic.example.invalid",
                api_token="synthetic-token",
                access_client_id="synthetic.access",
                access_client_secret="synthetic-secret",
            ),
            session=Session(),
        )
        with self.assertRaises(StorageError):
            client.send(str(uuid4()), "BI_Itens", [])

    def test_configuration_keeps_secrets_does_not_execute_and_has_private_backup(self):
        import tempfile
        from pathlib import Path

        from ds_backend.configuration import configure

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "secrets_config.py"
            original = 'WENI_API_TOKEN = "synthetic-secret-retained"\nPERFIS = {"PET": {"WENI_API_TOKEN": "synthetic-pet"}}\nraise RuntimeError("não executar configuração ao editar")\n'
            path.write_bytes(original.replace("\n", "\r\n").encode("utf-8"))
            original_bytes = path.read_bytes()
            result = configure(
                path,
                "FARMA",
                "homologacao",
                "credentials/datastudio/FARMA/homologacao/publicacao.json",
            )
            self.assertFalse(result["activated"])
            text = path.read_text(encoding="utf-8-sig")
            self.assertIn("synthetic-secret-retained", text)
            self.assertIn('"PET": {"WENI_API_TOKEN": "synthetic-pet"}', text)
            self.assertEqual(
                next(
                    Path(temp).glob("credentials/datastudio/backup-configuracao/*.bak")
                ).read_bytes(),
                original_bytes,
            )
            with self.assertRaises(StorageError):
                configure(path, "FARMA", "producao", "private.json", backend="postgres")

    def test_invalid_history_input_does_not_open_postgres_or_query_sources(self):
        import run_order_history

        with (
            patch("ds_backend.runtime.configured", return_value=True),
            patch(
                "ds_backend.runtime.open_store",
                side_effect=AssertionError("não abrir armazenamento"),
            ),
        ):
            with self.assertRaises(ValueError):
                run_order_history.run(["--inicio", "data-inválida"])
            with self.assertRaises(SystemExit):
                run_order_history.run(["--opcao-inexistente"])


class ExportItemConsistencyWindowsTests(unittest.TestCase):
    """Guarda executada em Python 3.11/3.14 e ambas as codificações Windows."""

    def test_legacy_cut_is_readable_but_cannot_prepare_or_send_without_items(self):
        import hashlib
        import json
        import tempfile
        from contextlib import closing
        from pathlib import Path

        from ds_backend.migration import Export, apply, prepare

        with tempfile.TemporaryDirectory() as folder:
            cut_path = Path(folder) / "corte.sqlite"
            plan_path = Path(folder) / "plano.json"
            sale = dict.fromkeys(REGISTRY["BI_Clientes_Vendas"]["columns"], "")
            sale.update(
                venda_chave="sale",
                cliente_chave="c",
                data="2026-11-09",
                faturamento_produtos="10",
                frete="2",
                faturamento="12",
            )
            with closing(Export(cut_path, create=True)) as cut:
                cut.add("BI_Clientes_Vendas", [sale], "FARMA")
                manifest = cut.seal(
                    "FARMA",
                    dict(scope="CORTE_COMPLETO", state="READY", revision="legacy"),
                )
            before = hashlib.sha256(cut_path.read_bytes()).hexdigest()
            client = ClientMemory()
            client.config["environment"] = "producao"
            client.info = {}
            with patch.object(
                client, "call", side_effect=AssertionError("HTTP não autorizado")
            ):
                with self.assertRaisesRegex(StorageError, "DS_BI_ITENS_DEFASADOS"):
                    prepare(cut_path, plan_path, client)
                self.assertFalse(plan_path.exists())
                plan_path.write_text(
                    json.dumps(
                        dict(
                            target=client.expected_target,
                            source=str(cut_path),
                            source_hash=digest(manifest),
                        )
                    ),
                    encoding="utf-8",
                )
                for simulate in (True, False):
                    with self.subTest(simulate=simulate):
                        with self.assertRaisesRegex(
                            StorageError, "DS_BI_ITENS_DEFASADOS"
                        ):
                            apply(plan_path, client, simulate=simulate)
            with closing(Export(cut_path)) as cut:
                self.assertEqual(cut.manifest(), manifest)
            self.assertEqual(hashlib.sha256(cut_path.read_bytes()).hexdigest(), before)

    def test_exact_products_and_owner_with_freight_separate(self):
        import tempfile
        from contextlib import closing
        from pathlib import Path

        from ds_backend.item_consistency import assert_export_items
        from ds_backend.migration import Export

        for amount, customer, valid in [
            ("10.00", "c", True),
            ("9.99", "c", False),
            ("12.00", "c", False),
            ("10.00", "other", False),
        ]:
            with (
                self.subTest(amount=amount, customer=customer),
                tempfile.TemporaryDirectory() as folder,
            ):
                with closing(Export(Path(folder) / "corte.sqlite", create=True)) as cut:
                    sale = dict.fromkeys(REGISTRY["BI_Clientes_Vendas"]["columns"], "")
                    sale.update(
                        venda_chave="sale",
                        cliente_chave="c",
                        data="2026-11-09",
                        faturamento_produtos="10",
                        frete="2",
                        faturamento="12",
                    )
                    item = dict.fromkeys(REGISTRY["BI_Itens"]["columns"], "")
                    item.update(
                        item_chave="i",
                        venda_chave="sale",
                        cliente_chave=customer,
                        data="2026-11-09",
                        quantidade="1",
                        receita_item=amount,
                    )
                    cut.add("BI_Clientes_Vendas", [sale], "FARMA")
                    cut.add("BI_Itens", [item], "FARMA")
                    cut.db.commit()
                    cut.db.execute("PRAGMA query_only=ON")
                    if valid:
                        assert_export_items(cut.db)
                    else:
                        with self.assertRaisesRegex(
                            StorageError, "DS_BI_ITENS_DEFASADOS"
                        ):
                            assert_export_items(cut.db)
