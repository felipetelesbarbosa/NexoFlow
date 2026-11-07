"""Benchmark sintético reproduzível, sem rede, credenciais ou dados comerciais.

PYTHONPATH=app:. python tests/benchmark_history_publication.py
"""

import json
from pathlib import Path
from time import perf_counter

from history_publication import Publication
from sheets_continuation import allocated_cells
from tests.test_history_publication import fixture, stream
from tests.test_history_sheets_transport import TransportTests


def benchmark(count):
    case = TransportTests()
    case.setUp()
    db = None
    try:
        case.store._continuity.index.config["max_part_rows"] = 250
        case.store._continuity.sheet.values = case.store._continuity.index.values()
        db, data = fixture(count)
        publisher = Publication(case.remote, "FARMA", Path(case.tmp.name))
        start = perf_counter()
        review = publisher.prepare(stream(data))
        prepared = perf_counter()
        result = publisher.apply(review)
        applied = perf_counter()
        report = publisher.check(review)
        closed = perf_counter()
        files = list(Path(review["journal"]).parent.glob("lote_*.json"))
        written = sum(b.data_writes for b in case.store.client.books.values())
        publisher.apply(review)
        repeated = (
            sum(b.data_writes for b in case.store.client.books.values()) - written
        )
        return dict(
            orders=count,
            planned_rows=review["changed_rows"],
            batches=review["batches"],
            parts=case.provider.creations,
            prepare_seconds=round(prepared - start, 3),
            apply_seconds=round(applied - prepared, 3),
            conference_seconds=round(closed - applied, 3),
            read_attempts=case.store._read_requests,
            write_attempts=case.store._write_requests,
            cell_write_calls=written,
            backup_bytes=sum(f.stat().st_size for f in files),
            largest_backup_bytes=max(f.stat().st_size for f in files),
            repeat_cell_writes=repeated,
            financial_difference_cents=report["conference"][
                "diferenca_pedidos_ltv_centavos"
            ],
            remaining_batches=result["remaining_batches"],
            root_history_grid=18_413_260,
            projected_capacity=review["capacity"]["books"],
            observed_grids=sorted(
                allocated_cells(b.fetch_sheet_metadata())
                for b in case.store.client.books.values()
            ),
        )
    finally:
        if db is not None:
            db.close()
        case.doCleanups()


if __name__ == "__main__":
    print(json.dumps([benchmark(n) for n in (100, 1200)], indent=2))
