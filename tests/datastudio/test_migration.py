"""Corte real do código sobre Sheets/Drive simulados e SQLite privado sintético."""

import json
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from ds_backend.audit import audit
from ds_backend.contract import StorageError
from ds_backend.exclusions import extract
from ds_backend.migration import Export, pilot
from ds_backend.sheets_export import export_sheets


def test_export_reads_all_parts_bounded_on_500000_row_grid_and_rejects_change(tmp_path):
    from tests.test_history_publication import fixture, stream
    from tests.test_history_sheets_transport import TransportTests

    case = TransportTests(methodName="runTest")
    case.setUp()
    try:
        db, data = fixture(4)
        try:
            review = case.pub.prepare(stream(data))
            assert case.pub.apply(review)["status"] == "conferida"
            manager = case.store._continuity
            manager.lease.release()
            part = manager.index.table_parts("Historico_Pedidos")[0]
            ws = manager.worksheet(part)
            ws.row_count = 500000
            calls = []
            original = ws.get

            def bounded(area, **kwargs):
                import re

                numbers = [int(x) for x in re.findall(r"[A-Z]+(\d+)", area)]
                assert len(numbers) == 2 and numbers[1] - numbers[0] < 1000
                calls.append(area)
                return original(area, **kwargs)

            ws.get = bounded
            # A exportação nunca usa get_all_values para os fatos volumosos.
            ws.get_all_values = lambda **_: pytest.fail("leitura integral de fatos")
            old = case.store.client.http_client.request
            versions = {"changed": False}
            read_count = {"n": 0}

            def request(method, url, **kwargs):
                if "version" in kwargs.get("params", {}).get("fields", ""):
                    read_count["n"] += 1
                    return SimpleNamespace(
                        json=lambda: dict(
                            id=url.rsplit("/", 1)[-1],
                            version="2"
                            if versions["changed"]
                            and read_count["n"] > len(manager.books)
                            else "1",
                            trashed=False,
                        )
                    )
                return old(method, url, **kwargs)

            case.store.client.http_client.request = request
            exclusions = dict(
                segment="FARMA",
                revision=review["revision"],
                source_sha256="0" * 64,
                rows=[],
            )
            manifest = export_sheets(
                case.store,
                tmp_path / "export.sqlite",
                "FARMA",
                review["revision"],
                exclusions,
            )
            assert manifest["tables"]["Historico_Pedidos"]["count"] == 4
            assert len(calls) >= 500
            assert audit(tmp_path / "export.sqlite")["financial_equal"]
            cut = pilot(tmp_path / "export.sqlite", tmp_path / "pilot.sqlite", "1")
            assert cut["evidence"]["scope"] == "PILOTO_PEDIDO"
            assert cut["tables"]["Historico_Pedidos"]["count"] == 1
            assert audit(tmp_path / "pilot.sqlite")["financial_equal"]
            # Uma mudança do destino durante o corte não produz um manifesto READY.
            read_count["n"] = 0
            versions["changed"] = True
            with pytest.raises(StorageError, match="ORIGEM_ALTERADA"):
                export_sheets(
                    case.store,
                    tmp_path / "changed.sqlite",
                    "FARMA",
                    review["revision"],
                    exclusions,
                )
            with closing(Export(tmp_path / "changed.sqlite")) as result:
                with pytest.raises(StorageError, match="INCOMPLETA"):
                    result.manifest()
        finally:
            db.close()
    finally:
        case.doCleanups()


def test_extract_exclusions_uses_exact_published_review_hash_and_never_migrates_original(
    tmp_path,
):
    from history_snapshot import sha256
    from order_history import digest as legacy_digest
    from tests.test_history_exclusions import HistoryExclusionsTests

    case = HistoryExclusionsTests(methodName="runTest")
    case.setUp()
    try:
        derived = case.derive()
        source = Path(derived["banco_publicacao"])
        before = sha256(source)
        review = dict(
            revision="synthetic-ready",
            segment="FARMA",
            evidence=dict(path=str(source), sha256=before),
        )
        review["digest"] = legacy_digest(review)
        path = tmp_path / "review.json"
        path.write_text(json.dumps(review))
        result = extract(
            path, source, "FARMA", "synthetic-ready", tmp_path / "exclusions.json"
        )
        assert result["exclusions"] == 2
        assert sha256(source) == before
        proof = json.loads((tmp_path / "exclusions.json").read_text())
        assert len(proof["rows"]) == 2 and all(
            len(r["original_sha256"]) == 64 for r in proof["rows"]
        )
        with pytest.raises(StorageError):
            extract(
                path, case.source, "FARMA", "synthetic-ready", tmp_path / "wrong.json"
            )
    finally:
        case.doCleanups()
