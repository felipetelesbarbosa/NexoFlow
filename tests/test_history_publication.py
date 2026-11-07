"""SQLite real e transporte Sheets isolado; nenhum recurso comercial."""

import json
import sqlite3
import tempfile
import unittest
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

from history_publication import Publication
from order_history import HistoryError, HistoryQuery, digest
from order_history_sheets import SCHEMAS, tables
from order_history_store import HistoryStore, collect
from tests.test_order_history import NOW, Source, order


class Sheets:
    def __init__(self, segment="FARMA"):
        self.segment = segment
        self.parts = []
        self.rows = {}
        self.version = 0
        self.operation = None
        self.writes = 0
        self.scans = 0
        self.lost = False
        self.before_failure = False
        self.can_create = True
        self.foreign = False
        self.phase = "READY"
        self.before = lambda value: None
        self.after = lambda value: None

    def context(self):
        return dict(
            segment=self.segment, history="hist", operations="ops", dashboard="dash"
        )

    def manifest(self):
        return digest(
            [self.version, self.parts, self.phase, self.operation, self.foreign]
        )

    def bind(self, *, before, after):
        self.before, self.after = before, after

    def change(self, action):
        action()
        self.version += 1
        value = self.manifest()
        self.before(value)
        self.writes += 1
        self.after(value)

    def describe(self, schemas):
        return dict(
            context=self.context(),
            manifest=self.manifest(),
            parts=deepcopy(self.parts),
            books={"hist": 900, "ops": 0, "dash": 0},
            roots={"historico": "hist", "operacao": "ops", "dashboard": "dash"},
            threshold=1000,
            max_rows=5,
        )

    def preflight(self, capacity, metadata):
        if capacity["creations"] and not self.can_create:
            raise HistoryError("OAUTH_AUSENTE")

    def acquire(self):
        pass

    def begin(self, operation, schemas):
        if self.operation == operation and self.phase == "WRITING":
            return

        def act():
            self.operation = operation
            self.phase = "WRITING"

        self.change(act)

    def ensure_part(self, planned, headers):
        for p in self.parts:
            if (p["title"], p["number"]) == (planned["title"], planned["number"]):
                return deepcopy(p)
        part = deepcopy(planned)
        if part["book"].startswith("new:"):
            part["book"] = "extra_" + part["title"] + str(part["number"])
        part["sheet"] = len(self.parts) + 1
        part["allocated_rows"] = 1
        part["used_rows"] = 1
        self.rows[(part["title"], part["number"])] = {}
        self.change(lambda: self.parts.append(part))
        return deepcopy(part)

    def scan(self, part, headers):
        self.scans += 1
        for position, row in sorted(self.rows[(part["title"], part["number"])].items()):
            if row is not None:
                yield position, [row[h] for h in headers]

    def read_rows(self, part, headers, positions):
        return [
            deepcopy(self.rows[(part["title"], part["number"])].get(p))
            for p in positions
        ]

    def write_rows(self, part, headers, entries, *, field):
        if self.before_failure:
            self.before_failure = False
            raise TimeoutError("falha sintética antes do POST")
        self.writes += 1
        for e in entries:
            self.rows[(part["title"], part["number"])][e["row"]] = deepcopy(e[field])
        if self.lost:
            self.lost = False
            raise TimeoutError("resposta sintética perdida após escrita")

    def finish(self, operation, parts):
        self.change(lambda: setattr(self, "phase", "READY"))
        for part in self.parts:
            filled = [
                p for p, r in self.rows[(part["title"], part["number"])].items() if r
            ]
            part["used_rows"] = max(filled, default=1)
            part["allocated_rows"] = max(part["allocated_rows"], part["used_rows"])
        # Dimensões são metadados físicos, não fazem parte do manifesto fake.
        self.after(self.manifest())


def fixture(count, segment="FARMA"):
    db = sqlite3.connect(":memory:")
    history = HistoryStore(db, segment)
    collect(
        Source([order(n, segment=segment) for n in range(1, count + 1)]),
        history,
        HistoryQuery(segment, "2026-11-01", "2026-11-06", 500),
        now=NOW,
    )
    return db, tables(history)


def stream(data):
    return ((t, r) for t in SCHEMAS for r in data[t])


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.remote = Sheets()
        self.pub = Publication(self.remote, "FARMA", Path(self.tmp.name))
        db, self.data = fixture(12)
        self.addCleanup(db.close)

    def prepare(self):
        return self.pub.prepare(stream(self.data))

    def test_cross_parts_pilot_resume_and_idempotence(self):
        review = self.prepare()
        self.assertEqual(self.remote.writes, 0)
        first = self.pub.apply(review, max_batches=1)
        self.assertEqual(first["applied_batches"], 1)
        self.assertEqual(first["applied_rows"], 4)
        self.assertEqual(self.remote.phase, "WRITING")
        final = self.pub.apply(review)
        self.assertEqual(final["remaining_batches"], 0)
        self.assertEqual(self.remote.phase, "READY")
        writes = self.remote.writes
        self.assertEqual(self.pub.apply(self.prepare())["applied_rows"], 0)
        self.assertEqual(self.remote.writes, writes)
        self.assertTrue(list(Path(review["journal"]).parent.glob("lote_*.json")))

    def test_lost_response_confirms_without_repeating_post(self):
        review = self.prepare()
        self.remote.lost = True
        with self.assertRaises(TimeoutError):
            self.pub.apply(review, max_batches=1)
        writes = self.remote.writes
        result = self.pub.apply(review, max_batches=1)
        self.assertEqual(self.remote.writes, writes)
        self.assertEqual(result["applied_batches"], 1)
        self.pub.apply(review)

    def test_failure_before_write_can_resume_same_coordinates(self):
        review = self.prepare()
        self.remote.before_failure = True
        with self.assertRaises(TimeoutError):
            self.pub.apply(review, max_batches=1)
        self.assertEqual(self.pub.apply(review)["remaining_batches"], 0)

    def test_manifest_and_foreign_segment_block_before_write(self):
        review = self.prepare()
        self.remote.foreign = True
        with self.assertRaisesRegex(HistoryError, "MANIFESTO"):
            self.pub.apply(review)
        self.assertEqual(self.remote.writes, 0)
        with self.assertRaises(HistoryError):
            Publication(self.remote, "PET", Path(self.tmp.name)).apply(review)

    def test_oauth_missing_blocks_prepare_before_first_write(self):
        self.remote.can_create = False
        with self.assertRaisesRegex(HistoryError, "OAUTH"):
            self.prepare()
        self.assertEqual(self.remote.writes, 0)

    def test_exact_completed_revision_is_read_only_on_repeat(self):
        review = self.prepare()
        self.pub.apply(review)
        writes = self.remote.writes
        self.assertEqual(self.pub.apply(review)["applied_rows"], 0)
        self.assertEqual(self.remote.writes, writes)

    def test_journal_coordinates_and_baseline_cannot_be_changed(self):
        review = self.prepare()
        with sqlite3.connect(review["journal"]) as db:
            db.execute("UPDATE operations SET r=r+100")
        with self.assertRaisesRegex(HistoryError, "PLANO_LOCAL_ALTERADO"):
            self.pub.apply(review)
        self.assertEqual(self.remote.writes, 0)

    def test_conference_reports_cent_difference_and_part_batch_without_customer_data(
        self,
    ):
        review = self.prepare()
        self.pub.apply(review)
        row = self.remote.rows[("Historico_Pedidos", 0)][2]
        row["faturamento"] = str(Decimal(row["faturamento"]) + Decimal("0.01"))
        result = self.pub.check(review)
        self.assertEqual(result["status"], "divergente")
        self.assertEqual(result["interval_differences"][0]["part"], 0)
        self.assertEqual(result["interval_differences"][0]["examples"][0]["batch"], 1)
        self.assertEqual(result["conference"]["diferenca_pedidos_ltv_centavos"], -1)
        self.assertNotIn("cliente_id", json.dumps(result["conference"]))

    def test_deleted_unchanged_row_blocks_application(self):
        self.pub.apply(self.prepare())
        review = self.prepare()
        del self.remote.rows[("Historico_Pedidos", 0)][2]
        with self.assertRaisesRegex(HistoryError, "LINHA_REMOVIDA"):
            self.pub.apply(review)

    def test_pilot_report_has_explicit_subset_and_no_full_ltv_claim(self):
        review = self.prepare()
        self.pub.apply(review, max_batches=1)
        result = self.pub.check(review)
        self.assertEqual(result["confirmed_batches"], 1)
        self.assertEqual(
            result["conference"]["observado"]["recortes"][-1]["pedidos"], 4
        )
        self.assertIn("indisponível", result["conference"]["ltv_conference"])

    def test_rollback_lost_response_recovers_without_second_write(self):
        review = self.prepare()
        self.pub.apply(review)
        self.remote.lost = True
        with self.assertRaises(TimeoutError):
            self.pub.rollback(review, 1)
        writes = self.remote.writes
        self.assertEqual(self.pub.rollback(review, 1)["rows"], 4)
        self.assertEqual(self.remote.writes, writes)
        self.assertEqual(self.pub.apply(review)["remaining_batches"], 0)

    def test_manifest_response_lost_between_remote_write_and_local_receipt(self):
        review = self.prepare()
        bind = self.remote.bind
        failed = False

        def unreliable_bind(*, before, after):
            def confirm(value):
                nonlocal failed
                if not failed:
                    failed = True
                    raise TimeoutError("manifesto gravado, recibo local interrompido")
                after(value)

            bind(before=before, after=confirm)

        self.remote.bind = unreliable_bind
        with self.assertRaises(TimeoutError):
            self.pub.apply(review)
        self.assertEqual(self.pub.apply(review)["remaining_batches"], 0)

    def test_rollback_is_specific_and_checks_later_edits(self):
        review = self.prepare()
        self.pub.apply(review)
        restored = self.pub.rollback(review, 1)
        self.assertEqual(restored["rows"], 4)
        self.pub.apply(review)
        rows = self.remote.rows[("Historico_Pedidos", 0)]
        rows[2]["motivo"] = "edição sintética posterior"
        with self.assertRaisesRegex(HistoryError, "EDICAO_POSTERIOR"):
            self.pub.rollback(review, 1)

    def test_active_remote_order_missing_locally_blocks_derived_inactivation(self):
        self.pub.apply(self.prepare())
        self.data["Historico_Pedidos"] = self.data["Historico_Pedidos"][1:]
        with self.assertRaisesRegex(HistoryError, "BASE_LOCAL_INCOMPLETA"):
            self.prepare()

    def test_read_and_backup_cost_not_full_snapshot_per_batch(self):
        db, data = fixture(50)
        self.addCleanup(db.close)
        self.remote = Sheets()
        self.pub = Publication(self.remote, "FARMA", Path(self.tmp.name))
        self.data = data
        review = self.prepare()
        self.pub.apply(review)
        parts = len(self.remote.parts)
        self.assertLessEqual(self.remote.scans, 2 * parts)
        for path in Path(review["journal"]).parent.glob("lote_*.json"):
            body = json.loads(path.read_text())
            self.assertLessEqual(len(body["entries"]), 200)
            self.assertNotIn("snapshot", body)
            self.assertLess(path.stat().st_size, 100_000)

    def test_pet_only_synthetic_isolation(self):
        db, data = fixture(3, "PET")
        self.addCleanup(db.close)
        remote = Sheets("PET")
        pub = Publication(remote, "PET", Path(self.tmp.name))
        plan = pub.prepare(stream(data))
        pub.apply(plan)
        self.assertTrue(
            all(
                r["segmento"] == "PET"
                for rows in remote.rows.values()
                for r in rows.values()
                if r
            )
        )
