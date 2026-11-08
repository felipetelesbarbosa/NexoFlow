"""Exclusões locais com SQLite real e transporte externo simulado."""

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock, patch

from history_conference import summarize
from history_exclusions import derive, exclusion_audit
from history_publication import Publication
from history_snapshot import readonly, sha256
from order_history import HistoryError, normalize_order
from order_history_sheets import iter_tables
from order_history_store import HistoryStore
from run_order_history import run
from tests.test_history_publication import Sheets
from tests.test_order_history import NOW, order


class HistoryExclusionsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.make_source("FARMA")
        self.source_hash = sha256(self.source)

    def make_source(self, segment):
        path = self.root / (segment + ".sqlite")
        with closing(sqlite3.connect(path)) as db:
            db.execute("CREATE TABLE profile(segment TEXT NOT NULL)")
            db.execute("INSERT INTO profile VALUES(?)", (segment,))
            store = HistoryStore(db, segment)
            inputs = [
                order(1, amount=110, segment=segment, owner=10, day="2026-10-01"),
                order(2, amount=220, segment=segment, owner=20, day="2026-11-01"),
                order(3, amount=30, segment=segment, owner=10, day="2026-11-02"),
                order(4, amount=40, segment=segment, owner=40, day="2026-10-03"),
                order(5, amount=50, segment=segment, owner=50, status=3),
            ]
            for raw in inputs:
                store.upsert(
                    normalize_order(raw, segment, NOW), now=NOW, mode="reconciliacao"
                )
            row = normalize_order(order(6, segment=segment), segment, NOW)
            row.update(
                state="pendente",
                reason="SEM_EMISSAO",
                date="",
                items=[],
                products_cents=0,
                freight_cents=0,
                revenue_cents=0,
            )
            store.upsert(row, now=NOW, mode="reconciliacao")
            db.commit()
        return path

    def derive(self, **changes):
        args = dict(
            source=self.source,
            expected_hash=self.source_hash,
            output_root=self.root / "copies",
            segment="FARMA",
            ids=["1", "2"],
            reason="Pedidos sintéticos inválidos autorizados pelo operador",
            authorized_by="Operador de teste",
        )
        args.update(changes)
        with patch("builtins.print"):
            return derive(**args)

    def load_rows(self, path):
        with readonly(path, "FARMA") as history:
            return list(iter_tables(history)), summarize(history.records(), "FARMA")

    def test_source_unchanged_and_all_tables_pilot_resume_closure_idempotence(self):
        result = self.derive()
        self.assertEqual(sha256(self.source), self.source_hash)
        total = result["total"]
        self.assertEqual(
            (
                total["pedidos"],
                total["validos"],
                total["cancelados"],
                total["pendentes"],
            ),
            (4, 2, 1, 1),
        )
        self.assertEqual(total["faturamento_centavos"], 7000)
        self.assertEqual(total["clientes_com_compra_valida"], 2)
        with readonly(result["banco_publicacao"], "FARMA") as history:
            audit = exclusion_audit(history.db, "FARMA")
            self.assertEqual([r["pedido_id"] for r in audit], ["1", "2"])
            self.assertEqual(
                history.db.execute("SELECT count(*) FROM history_issues").fetchone()[0],
                1,
            )
            originals = [
                json.loads(row[0])
                for row in history.db.execute(
                    "SELECT original_row_json FROM history_publication_exclusions"
                )
            ]
            self.assertEqual(len(originals), 2)
            self.assertTrue(
                all(json.loads(row[3])["state"] == "valido" for row in originals)
            )
        data, expected = self.load_rows(result["banco_publicacao"])
        self.assertFalse(any(row.get("pedido_id") in ("1", "2") for _, row in data))
        remote = Sheets()
        publisher = Publication(remote, "FARMA", self.root / "publication")
        review = publisher.prepare(
            iter(data),
            evidence=dict(
                path=result["banco_publicacao"],
                sha256=result["sha256"],
                conference=expected,
            ),
        )
        publisher.apply(review, max_batches=1)
        pilot = publisher.check(review)
        self.assertEqual(pilot["confirmed_batches"], 1)
        self.assertGreater(pilot["remaining_batches"], 0)
        self.assertFalse(pilot["interval_differences"])
        publisher.apply(review)
        checked = publisher.check(review)
        self.assertEqual(remote.phase, "READY")
        self.assertEqual(checked["status"], "conferida")
        self.assertEqual(checked["remaining_batches"], 0)
        self.assertEqual(checked["conference"]["diferencas"], [])
        self.assertEqual(checked["conference"]["diferenca_pedidos_ltv_centavos"], 0)
        again = publisher.prepare(iter(data), evidence=dict(conference=expected))
        self.assertEqual((again["changed_rows"], again["batches"]), (0, 0))

    def test_exclusions_inactivate_previous_rows_without_losing_other_buyers(self):
        remote = Sheets()
        publisher = Publication(remote, "FARMA", self.root / "publication")
        data, expected = self.load_rows(self.source)
        publisher.apply(
            publisher.prepare(iter(data), evidence=dict(conference=expected))
        )
        result = self.derive()
        data, expected = self.load_rows(result["banco_publicacao"])
        with readonly(result["banco_publicacao"], "FARMA") as history:
            audit = exclusion_audit(history.db, "FARMA")
        with self.assertRaisesRegex(HistoryError, "BASE_LOCAL_INCOMPLETA"):
            publisher.prepare(iter(data), evidence=dict(conference=expected))
        unrelated_missing = [
            (t, r)
            for t, r in data
            if not (t == "Historico_Pedidos" and r["pedido_id"] == "4")
        ]
        with self.assertRaisesRegex(HistoryError, "BASE_LOCAL_INCOMPLETA"):
            publisher.prepare(
                iter(unrelated_missing),
                evidence=dict(conference=expected, publication_exclusions=audit),
            )
        wrong_audit = json.loads(json.dumps(audit))
        wrong_audit[0]["pedido_original"]["faturamento"] = "999999"
        with self.assertRaisesRegex(HistoryError, "BASE_LOCAL_INCOMPLETA"):
            publisher.prepare(
                iter(data),
                evidence=dict(conference=expected, publication_exclusions=wrong_audit),
            )
        review = publisher.prepare(
            iter(data), evidence=dict(conference=expected, publication_exclusions=audit)
        )
        self.assertEqual(review["table_stats"]["Historico_Pedidos"]["inactivated"], 2)
        self.assertEqual(review["table_stats"]["Historico_Itens"]["inactivated"], 2)
        self.assertEqual(review["table_stats"]["BI_LTV_Clientes"]["inactivated"], 1)
        publisher.apply(review)
        self.assertEqual(publisher.check(review)["status"], "conferida")

    def test_repeated_run_is_independent_and_projection_cannot_be_reused_as_source(
        self,
    ):
        first, second = self.derive(), self.derive()
        self.assertNotEqual(first["banco_publicacao"], second["banco_publicacao"])
        self.assertEqual(first["total"], second["total"])
        self.assertEqual(sha256(first["banco_publicacao"]), first["sha256"])
        with self.assertRaisesRegex(HistoryError, "FONTE_JA_TEM_EXCLUSOES"):
            self.derive(source=first["banco_publicacao"], expected_hash=first["sha256"])

    def test_hash_and_missing_order_fail_before_creating_output(self):
        for changes in ({"expected_hash": "0" * 64}, {"ids": ["999"]}):
            with self.subTest(changes=changes), self.assertRaises(HistoryError):
                self.derive(**changes)
        self.assertFalse((self.root / "copies").exists())

    def test_wrong_segment_blocks_and_pet_uses_own_copy(self):
        pet = self.make_source("PET")
        with self.assertRaisesRegex(HistoryError, "OUTRO_SEGMENTO"):
            self.derive(source=pet, expected_hash=sha256(pet))
        result = self.derive(source=pet, expected_hash=sha256(pet), segment="PET")
        with readonly(result["banco_publicacao"], "PET") as history:
            self.assertEqual(len(exclusion_audit(history.db, "PET")), 2)
            with self.assertRaisesRegex(HistoryError, "OUTRO_SEGMENTO"):
                exclusion_audit(history.db, "FARMA")
        self.assertEqual(sha256(self.source), self.source_hash)

    def test_invalid_ids_and_missing_authorization_are_rejected(self):
        for changes in (
            {"ids": ["1", "1"]},
            {"ids": []},
            {"ids": ["abc"]},
            {"ids": ["0"]},
            {"reason": None},
            {"reason": " "},
            {"authorized_by": None},
            {"authorized_by": ""},
        ):
            with self.subTest(changes=changes), self.assertRaises(HistoryError):
                self.derive(**changes)

    def test_cancelled_or_pending_order_is_not_silently_removed(self):
        for oid in ("5", "6"):
            with (
                self.subTest(oid=oid),
                self.assertRaisesRegex(HistoryError, "COMPRA_VALIDA"),
            ):
                self.derive(ids=[oid])

    def test_pending_target_and_external_wal_are_rejected(self):
        with closing(sqlite3.connect(self.source)) as db:
            db.execute("INSERT INTO history_issues VALUES('FARMA','1','PENDENCIA')")
            db.commit()
        self.source_hash = sha256(self.source)
        with self.assertRaisesRegex(HistoryError, "COM_PENDENCIA"):
            self.derive()
        self.source.with_name(self.source.name + "-wal").write_bytes(b"nao usar")
        with self.assertRaisesRegex(HistoryError, "WAL_EXTERNO"):
            self.derive()

    def test_existing_summary_cannot_overwrite_backup_or_other_file(self):
        with self.assertRaisesRegex(HistoryError, "CAMINHO_INEDITO"):
            self.derive(summary_path=self.source)
        self.assertEqual(sha256(self.source), self.source_hash)

    def test_cli_routes_explicit_exclusions_without_network_or_live_database(self):
        args = [
            "--excluir-pedidos",
            "1",
            "2",
            "--banco",
            str(self.source),
            "--sha256-banco",
            self.source_hash,
            "--motivo-exclusao",
            "Erro operacional sintético",
            "--responsavel-exclusao",
            "Operador de teste",
        ]
        fake = Mock(return_value=0)
        with patch("history_exclusions.exclude", fake):
            self.assertEqual(run(args), 0)
        self.assertEqual(fake.call_args.args[0].excluir_pedidos, ["1", "2"])
        with self.assertRaisesRegex(HistoryError, "NAO_COMBINA"):
            run(args + ["--planilhas", "aplicar"])
        with self.assertRaisesRegex(HistoryError, "NAO_COMBINA"):
            run(args + ["--inicio", "2026-11-01"])
        with self.assertRaisesRegex(HistoryError, "EXIGEM_EXCLUIR"):
            run(["--sha256-banco", self.source_hash])

    def test_real_cli_creates_audited_copy_and_respects_segment_lock(self):
        logs = self.root / "logs"
        logs.mkdir()
        args = [
            "--excluir-pedidos",
            "1",
            "2",
            "--banco",
            str(self.source),
            "--sha256-banco",
            self.source_hash,
            "--motivo-exclusao",
            "Erro sintético",
            "--responsavel-exclusao",
            "Operador de teste",
        ]
        with (
            patch("config.LOG_DIR", logs),
            patch("runtime_profile.segment", return_value="FARMA"),
            patch("builtins.print"),
            patch(
                "nexo_cli._make_farmalider_client",
                side_effect=AssertionError("Sem API"),
            ),
            patch("nexo_cli._make_weni_client", side_effect=AssertionError("Sem Weni")),
        ):
            self.assertEqual(run(args), 0)
        proofs = list(logs.rglob("comprovante-exclusoes.json"))
        self.assertEqual(len(proofs), 1)
        proof = json.loads(proofs[0].read_text())
        self.assertEqual(proof["depois"]["faturamento_centavos"], 7000)
        self.assertEqual(sha256(self.source), self.source_hash)


if __name__ == "__main__":
    unittest.main()
