"""Reconciliação oficial com SQLite, CLI e transporte Sheets reais sem rede."""

import io
import json
import os
import sqlite3
import unittest
from contextlib import closing, redirect_stdout
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from history_publication import get, publisher_signature, put
from history_reconciliation import (
    LEGACY_SIGNATURE,
    LEGACY_SIGNATURES,
    PREVIOUS_SIGNATURES,
    RECEIPT_KEY,
    compatible,
    reconcile,
)
from history_snapshot import sha256
from nexo_cli import run
from order_history import HistoryError, digest
from order_history_sheets import SCHEMAS, HistorySheets
from sheets_continuation import ContinuationError
from tests import test_history_sheets_transport as transport_fixture
from tests.sheets_memory import GspreadSheet
from tests.test_history_publication import fixture


class ReconciliationTests(unittest.TestCase):
    setUp = transport_fixture.TransportTests.setUp

    def legacy(self, signature=LEGACY_SIGNATURE, *, baseline=False, factory=None):
        self.root = Path(self.tmp.name)
        source = self.root / "fonte.sqlite"
        original, data = factory() if factory is not None else fixture(9)
        with closing(original), closing(sqlite3.connect(source)) as db:
            original.backup(db)
            db.execute("CREATE TABLE profile(segment TEXT NOT NULL)")
            db.execute("INSERT INTO profile VALUES('FARMA')")
            db.commit()
        if baseline:
            title = "Historico_Pedidos"
            self.store._storage_books["history"].add(
                title,
                [SCHEMAS[title], [data[title][0][h] for h in SCHEMAS[title]]],
                rows=2,
                cols=len(SCHEMAS[title]),
            )
        self.review_path = self.root / "privado" / "revisao.json"

        def adapter(_, segment, directory):
            result = HistorySheets(self.remote, segment, directory)
            self.pub = result.engine
            return result

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
                    open_native_readonly=lambda _: SimpleNamespace(
                        close=self.store._continuity.close
                    )
                ),
            ),
            patch("history_publish_cli.HistorySheets", side_effect=adapter),
            patch("tests.sheets_memory.Sheet", GspreadSheet),
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
        with patch("history_publication.publisher_signature", return_value=signature):
            code, _ = self.command("preparar", "--banco", str(source))
            self.assertEqual(code, 0)
        review = json.loads(self.review_path.read_text(encoding="utf-8"))
        self.original_review = self.review_path.read_bytes()
        # Estrutura exata do incidente: intenção persistida, cabeçalho 1×15,
        # nenhum lote iniciado e nenhuma parte ativada. Falha antes do stamp.
        with (
            patch("history_publication.publisher_signature", return_value=signature),
            patch(
                "sheets_partitions.stamp_book",
                side_effect=ContinuationError("interrupção estrutural sintética"),
            ),
        ):
            with self.assertRaisesRegex(ContinuationError, "interrupção"):
                self.pub.apply(review, max_batches=1)
        self.store._continuity.close()
        self.remote.manifest()  # Nova execução parte do índice persistido.
        self.candidate = next(iter(self.store._continuity.index.intents.values()))[
            "file_id"
        ]
        self.assertEqual(self.provider.creations, 1)
        with closing(self.pub._open_local(review)) as db:
            self.assertEqual(
                db.execute("SELECT DISTINCT state FROM batches").fetchall(),
                [("pending",)],
            )
            self.assertEqual(get(db, "parts"), get(db, "metadata")["parts"])
        return review

    def command(self, action, *args):
        with redirect_stdout(io.StringIO()) as output:
            code = run(
                [
                    "historico",
                    "--planilhas",
                    action,
                    "--revisao",
                    str(self.review_path),
                    *args,
                ]
            )
        return code, output.getvalue()

    def test_legacy_review_integrity_with_windows_cp1252_default(self):
        read_text = Path.read_text

        def windows_default(path, encoding=None, errors=None):
            return read_text(
                path,
                encoding="cp1252" if encoding is None else encoding,
                errors=errors,
            )

        with patch.object(Path, "read_text", windows_default):
            review = self.legacy()
            receipt = reconcile(self.pub, review)
        self.store._continuity.close()
        self.assertEqual(json.loads(self.original_review.decode("utf-8")), review)
        self.assertEqual(receipt["review_digest"], review["digest"])

    def test_cli_reconcile_same_revision_pilot_resume_and_financial_closure(self):
        review = self.legacy()
        before = sha256(review["evidence"]["path"])

        def physical_state():
            manager = self.store._continuity
            candidate = self.store.client.books[self.candidate].sheets[0]
            return deepcopy(
                [
                    manager.sheet.values,
                    manager.index.values(),
                    candidate.values,
                    (candidate.row_count, candidate.col_count, candidate.writes),
                    [b.data_writes for b in self.store.client.books.values()],
                ]
            )

        physical_before = physical_state()
        with (
            patch.object(self.provider, "create", side_effect=AssertionError("criar")),
            patch.object(
                self.provider, "share", side_effect=AssertionError("compartilhar")
            ),
            patch(
                "history_publication.Publication._binding",
                side_effect=AssertionError("binding"),
            ),
            patch.object(
                self.remote, "ensure_part", side_effect=AssertionError("adotar")
            ),
        ):
            code, out = self.command("reconciliar")
        self.assertEqual(code, 0)
        self.assertIn("Nenhum lote de fatos", out)
        self.assertEqual(physical_state(), physical_before)
        self.assertEqual(self.review_path.read_bytes(), self.original_review)
        self.assertEqual(sha256(review["evidence"]["path"]), before)
        with closing(self.pub._open(review)) as db:
            receipt = get(db, RECEIPT_KEY)
            self.assertEqual(get(db, "review"), review)
        self.assertEqual(self.command("aplicar", "--max-lotes", "1")[0], 3)
        self.assertEqual(self.command("conferir")[0], 3)
        # O comprovante continua válido após o piloto, sem all-pending de novo.
        self.assertEqual(reconcile(self.pub, review), receipt)
        self.store._continuity.close()
        self.assertEqual(self.command("aplicar")[0], 0)
        self.assertEqual(self.command("conferir")[0], 0)
        first = self.store._continuity.index.table_parts("Historico_Pedidos")[0]
        self.assertEqual(first.book_id, self.candidate)
        self.assertEqual(self.review_path.read_bytes(), self.original_review)

    def test_windows_legacy_signature_and_reexport_after_export_failure(self):
        review = self.legacy(
            next(s for s in LEGACY_SIGNATURES if s != LEGACY_SIGNATURE)
        )
        with patch(
            "history_reconciliation.save_private", side_effect=OSError("sintético")
        ):
            with self.assertRaises(OSError):
                reconcile(self.pub, review)
        with closing(self.pub._open(review)) as db:
            committed = get(db, RECEIPT_KEY)
        self.assertEqual(reconcile(self.pub, review), committed)
        self.assertTrue(
            (
                Path(review["journal"]).parent / "compatibilidade_codigo_v1.json"
            ).is_file()
        )
        self.store._continuity.close()

    def test_any_nonpending_or_uncertain_state_blocks_receipt(self):
        review = self.legacy()
        with closing(sqlite3.connect(review["journal"])) as db:
            for state in ("done", "sending", "restoring", "failed", "unknown", None):
                with self.subTest(state=state):
                    db.execute("UPDATE batches SET state=? WHERE n=1", (state,))
                    db.commit()
                    with self.assertRaisesRegex(HistoryError, "ZERO_LOTES"):
                        reconcile(self.pub, review)
                    self.assertIsNone(get(db, RECEIPT_KEY))
            db.execute("UPDATE batches SET state='pending'")
            db.commit()
            for key, value, original in (
                ("finished", True, None),
                ("started", "unknown", True),
                ("manifest_pending", "incerto", None),
            ):
                with self.subTest(key=key):
                    put(db, key, value)
                    with self.assertRaisesRegex(HistoryError, "ZERO_LOTES"):
                        reconcile(self.pub, review)
                    self.assertIsNone(get(db, RECEIPT_KEY))
                    put(db, key, original)
        backup = Path(review["journal"]).parent / "lote_001.json"
        backup.write_text("{}")
        with self.assertRaisesRegex(HistoryError, "ZERO_LOTES"):
            reconcile(self.pub, review)

    def test_transformation_change_and_lease_loss_block_without_receipt(self):
        import history_reconciliation

        review = self.legacy()
        real_iter = history_reconciliation.iter_tables

        def changed(history):
            for title, row in real_iter(history):
                altered = dict(row)
                if title == "Historico_Pedidos":
                    altered["faturamento"] = str(
                        Decimal(altered["faturamento"]) + Decimal("0.01")
                    )
                yield title, altered

        with patch("history_reconciliation.iter_tables", side_effect=changed):
            with self.assertRaisesRegex(HistoryError, "TRANSFORMACAO"):
                reconcile(self.pub, review)
        real_acquire = self.remote.acquire
        calls = 0

        def lost():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise ContinuationError("lease perdida")
            return real_acquire()

        with patch.object(self.remote, "acquire", side_effect=lost):
            with self.assertRaisesRegex(ContinuationError, "lease perdida"):
                reconcile(self.pub, review)
        self.store._continuity.close()
        with closing(self.pub._open_local(review)) as db:
            self.assertIsNone(get(db, RECEIPT_KEY))

    def test_candidate_formula_structure_extra_sheet_and_missing_operation_block(self):
        review = self.legacy()
        book = self.store.client.books[self.candidate]
        ws = book.sheets[0]
        before = [list(r) for r in ws.values]
        ws.values.append(['=""'])
        with self.assertRaisesRegex(HistoryError, "FATOS_OU_FORMULAS"):
            reconcile(self.pub, review)
        ws.values = before
        for field, value in (
            ("note", "nota sintética"),
            ("dataValidation", {"strict": True}),
            ("userEnteredFormat", {"wrapStrategy": "WRAP"}),
        ):
            with self.subTest(field=field):
                ws.native_cells[0, 0] = {field: value}
                with self.assertRaisesRegex(ContinuationError, "estrutura inesperada"):
                    reconcile(self.pub, review)
                ws.native_cells.clear()
        book.add("Inesperada", [["fato"]])
        with self.assertRaisesRegex(HistoryError, "ABAS_INESPERADAS"):
            reconcile(self.pub, review)
        book.sheets.pop()
        with patch.object(self.provider, "locate", return_value=None):
            with self.assertRaisesRegex(HistoryError, "OPERACAO_NAO_COMPROVADO"):
                reconcile(self.pub, review)
        with patch.object(
            self.provider, "locate", side_effect=ContinuationError("duplicada")
        ):
            with self.assertRaisesRegex(ContinuationError, "duplicada"):
                reconcile(self.pub, review)
        self.store._continuity.close()
        with closing(self.pub._open_local(review)) as db:
            self.assertIsNone(get(db, RECEIPT_KEY))

    def test_new_root_sheet_is_not_adopted_by_reconciliation(self):
        review = self.legacy()
        planned = next(
            p
            for p in review["capacity"]["creations"]
            if not p["book"].startswith("new:")
        )
        self.store.client.books[planned["book"]].add(
            planned["title"],
            [SCHEMAS[planned["title"]], ["fato externo"]],
            rows=2,
            cols=len(SCHEMAS[planned["title"]]),
        )
        with self.assertRaisesRegex(HistoryError, "NAO_ACEITA_ABAS_NOVAS"):
            reconcile(self.pub, review)
        self.store._continuity.close()

    def test_local_integrity_and_evidence_tampering_block_receipt(self):
        review = self.legacy()
        original_review = deepcopy(review)
        review["revision"] = "alterada"
        with self.assertRaisesRegex(HistoryError, "REVISAO_ALTERADA"):
            reconcile(self.pub, review)
        review = original_review
        for table, column, value in (
            ("meta", "v", '"alterado"'),
            ("incoming", "v", "{}"),
            ("batches", "body", "alterado"),
        ):
            for target in ("metadata", "review") if table == "meta" else (None,):
                with self.subTest(table=table, target=target):
                    with closing(sqlite3.connect(review["journal"])) as db:
                        where = (
                            "k=?"
                            if target
                            else "rowid=(SELECT min(rowid) FROM " + table + ")"
                        )
                        args = (target,) if target else ()
                        saved = db.execute(
                            f"SELECT {column} FROM {table} WHERE {where}", args
                        ).fetchone()[0]
                        db.execute(
                            f"UPDATE {table} SET {column}=? WHERE {where}",
                            (value, *args),
                        )
                        db.commit()
                        with self.assertRaisesRegex(
                            HistoryError, "PLANO_LOCAL_ALTERADO"
                        ):
                            reconcile(self.pub, review)
                        db.execute(
                            f"UPDATE {table} SET {column}=? WHERE {where}",
                            (saved, *args),
                        )
                        db.commit()
        snapshot = Path(review["evidence"]["path"])
        original = snapshot.read_bytes()
        snapshot.write_bytes(original + b"alteracao sintetica")
        with self.assertRaisesRegex(HistoryError, "COPIA_SQLITE_ALTERADA"):
            reconcile(self.pub, review)
        snapshot.write_bytes(original)
        with closing(self.pub._open_local(review)) as db:
            self.assertIsNone(get(db, RECEIPT_KEY))

    def test_intent_context_and_source_permissions_mismatch_block(self):
        review = self.legacy()
        intent = next(iter(self.store._continuity.index.intents.values()))
        for field in (
            "table",
            "schema",
            "source",
            "hub",
            "segment",
            "role",
            "create_state",
        ):
            with self.subTest(field=field):
                saved = intent[field]
                intent[field] = "divergente"
                # O índice remoto e o esperado são mantidos iguais no teste;
                # a validação dedicada ainda deve recusar a proveniência.
                with patch.object(
                    self.remote, "manifest", return_value=self._manifest(review)
                ):
                    with self.assertRaisesRegex(
                        HistoryError, "INTENCAO_NAO_COMPROVADA"
                    ):
                        reconcile(self.pub, review)
                intent[field] = saved
        original = self.provider.prepare_intent

        def changed(*args, **kwargs):
            proof = original(*args, **kwargs)
            proof["permissions"] = [
                {
                    "type": "user",
                    "emailAddress": "external@example.invalid",
                    "role": "reader",
                }
            ]
            return proof

        with patch.object(self.provider, "prepare_intent", side_effect=changed):
            with self.assertRaisesRegex(HistoryError, "PERMISSOES_ALTERADAS"):
                reconcile(self.pub, review)
        self.store._continuity.close()

    def _manifest(self, review):
        with closing(self.pub._open_local(review)) as db:
            return get(db, "manifest")

    def test_changed_baseline_blocks(self):
        review = self.legacy(baseline=True)
        ws = self.store._storage_books["history"].worksheet("Historico_Pedidos")
        column = SCHEMAS["Historico_Pedidos"].index("faturamento")
        ws.values[1][column] = str(Decimal(ws.values[1][column]) + Decimal("0.01"))
        with self.assertRaisesRegex(HistoryError, "BASELINE_REMOTA"):
            reconcile(self.pub, review)
        self.store._continuity.close()

    def test_transaction_rechecks_local_hashes_after_open(self):
        review = self.legacy()
        original_open = self.pub._open_local

        def changed_between_open_and_begin(review):
            result = original_open(review)
            with closing(sqlite3.connect(review["journal"])) as changed:
                changed.execute(
                    "UPDATE incoming SET v='{}' WHERE rowid=(SELECT min(rowid) FROM incoming)"
                )
                changed.commit()
            return result

        with patch.object(
            self.pub, "_open_local", side_effect=changed_between_open_and_begin
        ):
            with self.assertRaisesRegex(HistoryError, "PLANO_LOCAL_ALTERADO"):
                reconcile(self.pub, review)
        with closing(sqlite3.connect(review["journal"])) as db:
            self.assertIsNone(get(db, RECEIPT_KEY))

    def test_receipt_tampering_unknown_origin_and_future_code_rejected(self):
        review = self.legacy()
        with patch("history_reconciliation.LEGACY_SIGNATURES", {"desconhecida"}):
            with self.assertRaisesRegex(HistoryError, "LEGADO_NAO_SUPORTADO"):
                reconcile(self.pub, review)
        reconcile(self.pub, review)
        self.store._continuity.close()
        with closing(sqlite3.connect(review["journal"])) as db:
            receipt = get(db, RECEIPT_KEY)
            incomplete = dict(receipt)
            del incomplete["to_signature"]
            del incomplete["digest"]
            incomplete["digest"] = digest(incomplete)
            for malformed in (
                "broken",
                [],
                {},
                incomplete,
                dict(receipt, digest="alterado"),
            ):
                put(db, RECEIPT_KEY, malformed)
                self.assertFalse(compatible(db, review, receipt["to_signature"]))
                with self.assertRaisesRegex(HistoryError, "PUBLICADOR_ALTERADO"):
                    self.pub._open(review)
                with self.assertRaisesRegex(HistoryError, "COMPATIBILIDADE_INVALIDO"):
                    reconcile(self.pub, review)
            put(db, RECEIPT_KEY, receipt)
        with patch("history_publication.publisher_signature", return_value="futuro"):
            with self.assertRaisesRegex(HistoryError, "PUBLICADOR_ALTERADO"):
                self.pub._open(review)

    def test_receipt_binds_creation_guards_and_reconciliation_code(self):
        review = self.legacy()
        reconcile(self.pub, review)
        self.store._continuity.close()
        before = publisher_signature()
        read_bytes = Path.read_bytes
        for module in (
            "history_reconciliation.py",
            "sheets_partitions.py",
            "sheets_provisioning.py",
            "google_sheets.py",
        ):
            with self.subTest(module=module):

                def altered(path, module=module):
                    raw = read_bytes(path)
                    return (
                        raw + b"\n# synthetic code change\n"
                        if path.name == module
                        else raw
                    )

                with patch("history_publication.Path.read_bytes", altered):
                    self.assertNotEqual(publisher_signature(), before)
                    with self.assertRaisesRegex(HistoryError, "PUBLICADOR_ALTERADO"):
                        self.pub._open(review)


class PreparedRootRecoveryTests(unittest.TestCase):
    setUp = ReconciliationTests.setUp
    legacy = ReconciliationTests.legacy
    command = ReconciliationTests.command

    # Reutilizar os helpers sem repetir os testes da primeira reconciliação.
    def interrupted_26(self, **legacy_options):
        review = self.legacy(**legacy_options)
        signature = sorted(PREVIOUS_SIGNATURES)[0]
        ensure = self.remote.ensure_part

        def old_empty_root(planned, headers):
            if not planned["book"].startswith("new:"):
                book = self.store.client.books[planned["book"]]
                self.blank_root = book.add_worksheet(
                    title=planned["title"], rows=1, cols=len(headers)
                )
                raise HistoryError("ABA_CRIADA_COM_CONTEUDO_DIVERGENTE")
            return ensure(planned, headers)

        with patch("history_publication.publisher_signature", return_value=signature):
            old_receipt = reconcile(self.pub, review)
            with patch.object(self.remote, "ensure_part", side_effect=old_empty_root):
                with self.assertRaisesRegex(HistoryError, "ABA_CRIADA"):
                    self.pub.apply(review, max_batches=1)
        self.store._continuity.close()
        self.remote.manifest()
        with closing(self.pub._open_local(review)) as db:
            self.assertEqual(
                db.execute("SELECT DISTINCT state FROM batches").fetchall(),
                [("pending",)],
            )
            self.assertGreater(len(get(db, "parts")), len(get(db, "metadata")["parts"]))
        return review, old_receipt

    def test_upgrade_reconciled_26_with_created_parts_empty_root_and_no_facts(self):
        review, old_receipt = self.interrupted_26()
        before = sha256(review["evidence"]["path"])
        writes = sum(b.data_writes for b in self.store.client.books.values())
        receipt = reconcile(self.pub, review)
        self.assertEqual(receipt["previous_receipt"], old_receipt)
        self.assertEqual(
            sum(b.data_writes for b in self.store.client.books.values()), writes
        )
        self.assertEqual(reconcile(self.pub, review), receipt)
        self.assertEqual(self.command("aplicar", "--max-lotes", "1")[0], 3)
        self.assertEqual(self.command("conferir")[0], 3)
        self.assertEqual(self.command("aplicar")[0], 0)
        self.assertEqual(self.command("conferir")[0], 0)
        self.assertEqual(sha256(review["evidence"]["path"]), before)
        self.assertEqual(self.review_path.read_bytes(), self.original_review)

    def test_observed_shape_three_continuations_empty_ltv_and_receipt26_crlf(self):
        from order_history import HistoryQuery
        from order_history_sheets import tables
        from order_history_store import HistoryStore, collect
        from tests.test_order_history import NOW, Source, order

        def source():
            db = sqlite3.connect(":memory:")
            history = HistoryStore(db, "FARMA")
            rows = []
            for n in range(1, 4):
                item = order(n, amount=40, segment="FARMA")
                item["itens"].append(dict(item["itens"][0], id=f"second-{n}"))
                rows.append(item)
            collect(
                Source(rows),
                history,
                HistoryQuery("FARMA", "2026-11-01", "2026-11-06", 500),
                now=NOW,
            )
            return db, tables(history)

        legacy_crlf = next(s for s in LEGACY_SIGNATURES if s != LEGACY_SIGNATURE)
        review, old_receipt = self.interrupted_26(signature=legacy_crlf, factory=source)
        self.assertEqual(
            old_receipt["to_signature"],
            "25fcd2cba0b985fa7983e1dfe94e527d38185990a512b66d09b0661142c4cb16",
        )
        manager = self.store._continuity
        self.assertEqual(len(manager.index.files), 3)
        self.assertFalse(manager.index.intents)
        self.assertEqual(self.blank_root.title, "BI_LTV_Clientes")
        self.assertEqual(self.blank_root.values, [])
        counts = {}
        for part in manager.index.parts.values():
            counts[part.title] = counts.get(part.title, 0) + 1
            ws = manager.worksheet(part)
            self.assertEqual(ws.row_count, 1)
            self.assertEqual(ws.values, [SCHEMAS[part.title]])
        self.assertEqual(counts, {"Historico_Pedidos": 1, "Historico_Itens": 2})
        original_json = self.review_path.read_bytes()
        source_sha = sha256(review["evidence"]["path"])
        writes = sum(b.data_writes for b in self.store.client.books.values())
        self.assertEqual(self.command("reconciliar")[0], 0)
        self.assertEqual(
            sum(b.data_writes for b in self.store.client.books.values()), writes
        )
        self.assertEqual(self.command("aplicar", "--max-lotes", "1")[0], 3)
        self.assertEqual(self.command("conferir")[0], 3)
        self.assertEqual(self.command("aplicar")[0], 0)
        self.assertEqual(self.command("conferir")[0], 0)
        self.assertEqual(self.pub.rollback(review, 1)["status"], "restaurado")
        self.assertEqual(self.command("aplicar")[0], 0)
        self.assertEqual(self.command("conferir")[0], 0)
        self.assertEqual(self.review_path.read_bytes(), original_json)
        self.assertEqual(sha256(review["evidence"]["path"]), source_sha)
        self.assertEqual(self.provider.creations, 3)
        with closing(self.pub._open(review)) as journal:
            self.assertEqual(get(journal, RECEIPT_KEY)["previous_receipt"], old_receipt)
            self.assertEqual(get(journal, "review"), review)
            self.assertTrue(get(journal, "finished"))
            self.assertEqual(
                journal.execute("SELECT DISTINCT state FROM batches").fetchall(),
                [("done",)],
            )

    def test_upgrade_blocks_facts_formulas_structures_and_unplanned_root(self):
        review, old_receipt = self.interrupted_26()
        ws = self.blank_root
        for values in ([["fato externo"]], [['=""']], [[0]], [[False]], [[" "]]):
            with self.subTest(values=values):
                ws.values = values
                with self.assertRaisesRegex(HistoryError, "CONTEM_FATOS_OU_FORMULAS"):
                    reconcile(self.pub, review)
        ws.values = []
        ws.native_cells[0, 0] = {"note": "nota sintética"}
        with self.assertRaisesRegex(ContinuationError, "estrutura inesperada"):
            reconcile(self.pub, review)
        ws.native_cells.clear()
        ws.book.add("Não prevista", [], rows=1, cols=1)
        with self.assertRaisesRegex(HistoryError, "ABA_NAO_PREVISTA"):
            reconcile(self.pub, review)
        with closing(self.pub._open_local(review)) as db:
            self.assertEqual(get(db, RECEIPT_KEY), old_receipt)

    def test_upgrade_blocks_nonpending_uncertain_or_untrusted_receipt(self):
        review, old_receipt = self.interrupted_26()
        with closing(self.pub._open_local(review)) as db:
            db.execute("UPDATE batches SET state='sending' WHERE n=1")
            db.commit()
            with self.assertRaisesRegex(HistoryError, "ZERO_LOTES"):
                reconcile(self.pub, review)
            db.execute("UPDATE batches SET state='pending' WHERE n=1")
            db.commit()
            changed = dict(old_receipt, to_signature="código desconhecido")
            changed.pop("digest")
            changed["digest"] = digest(changed)
            put(db, RECEIPT_KEY, changed)
            with self.assertRaisesRegex(HistoryError, "COMPATIBILIDADE_INVALIDO"):
                reconcile(self.pub, review)
