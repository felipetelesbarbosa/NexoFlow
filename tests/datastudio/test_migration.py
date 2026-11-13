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


@pytest.fixture
def ready_sheets():
    from tests.test_history_publication import fixture, stream
    from tests.test_history_sheets_transport import TransportTests

    case = TransportTests(methodName="runTest")
    case.setUp()
    db, data = fixture(8)
    try:
        review = case.pub.prepare(stream(data))
        assert case.pub.apply(review)["status"] == "conferida"
        manager = case.store._continuity
        manager.lease.release()
        old = case.store.client.http_client.request

        def request(method, url, **kwargs):
            if "version" in kwargs.get("params", {}).get("fields", ""):
                return SimpleNamespace(json=lambda: dict(version="1", trashed=False))
            return old(method, url, **kwargs)

        case.store.client.http_client.request = request
        exclusions = dict(
            segment="FARMA",
            revision=review["revision"],
            source_sha256="0" * 64,
            rows=[],
        )
        yield case.store, review["revision"], exclusions
    finally:
        db.close()
        case.doCleanups()


def alter_headers(store, mutation, *, stamp=True):
    from dataclasses import replace

    from sheets_continuation import fingerprint

    manager = store._continuity
    for part in list(manager.index.parts.values()):
        ws = manager.worksheet(part)
        mutation(ws, part)
        if stamp:
            manager.index.parts[part.key] = replace(
                part, schema=fingerprint(ws.values[0])
            )
    manager.sheet.values = manager.index.values()


def test_export_reordered_headers_per_part_preserves_all_rows_and_cents(
    ready_sheets, tmp_path
):
    store, revision, exclusions = ready_sheets
    baseline = tmp_path / "canonical.sqlite"
    export_sheets(store, baseline, "FARMA", revision, exclusions)

    def reorder(ws, part):
        # Ordem física comprovada por tabela e por parte no manifesto existente.
        n = len(ws.values[0])
        order = (
            list(reversed(range(n)))
            if part.title == "Historico_Pedidos"
            else list(range(1, n)) + [0]
        )
        ws.values = [[(r + [""] * n)[i] for i in order] for r in ws.values]
        ws.col_count += 2  # grade reservada não é coluna do schema

    alter_headers(store, reorder)
    output = tmp_path / "reordered.sqlite"
    export_sheets(store, output, "FARMA", revision, exclusions)
    with closing(Export(baseline)) as a, closing(Export(output)) as b:
        assert a.manifest()["tables"] == b.manifest()["tables"]
    a, b = audit(baseline), audit(output)
    assert a["ltv_centavos"] == b["ltv_centavos"]
    assert a["history"]["recortes"] == b["history"]["recortes"]


@pytest.mark.parametrize(
    "kind", ["missing", "extra", "duplicate", "blank", "unknown", "hash"]
)
def test_export_invalid_physical_headers_never_seals(ready_sheets, tmp_path, kind):
    store, revision, exclusions = ready_sheets

    def corrupt(ws, part):
        if part.title != "Historico_Itens" or (kind == "hash" and part.number != 1):
            return
        if kind == "missing":
            ws.values[0].pop()
        elif kind == "extra":
            ws.values[0].append("campo_extra")
            ws.col_count += 1
        elif kind == "duplicate":
            ws.values[0][-1] = ws.values[0][0]
        elif kind == "blank":
            ws.values[0][1] = ""
        elif kind == "unknown":
            ws.values[0][-1] = "campo_desconhecido"
        else:
            ws.values[0].reverse()  # mesmos nomes, hash físico não corresponde

    assert len(store._continuity.index.table_parts("Historico_Itens")) > 1
    alter_headers(store, corrupt, stamp=kind != "hash")
    path = tmp_path / "invalid.sqlite"
    with pytest.raises(StorageError, match="DS_SCHEMA_ORIGEM_DIVERGENTE"):
        export_sheets(store, path, "FARMA", revision, exclusions)
    with closing(Export(path)) as result:
        with pytest.raises(StorageError, match="INCOMPLETA"):
            result.manifest()


def test_export_legacy_table_reorders_short_rows_without_losing_field_identity(
    ready_sheets, tmp_path
):
    from ds_backend.contract import REGISTRY
    from sheets_partitions import role_for, roots_for

    store, revision, exclusions = ready_sheets
    name = "Metricas_Diarias"
    canonical = list(REGISTRY[name]["columns"])
    header = ["contatos", "data"] + [
        f for f in reversed(canonical) if f not in ("contatos", "data")
    ]
    book = store._continuity._book(roots_for(store)[role_for(name)])
    book.add(name, [header, [7, "2026-11-02"]], cols=len(header) + 3)
    path = tmp_path / "legacy.sqlite"
    export_sheets(store, path, "FARMA", revision, exclusions)
    with closing(Export(path)) as cut:
        value = json.loads(
            cut.db.execute("SELECT v FROM linhas WHERE t=?", (name,)).fetchone()[0]
        )
    assert value == {
        f: "7" if f == "contatos" else "2026-11-02" if f == "data" else ""
        for f in canonical
    }
    assert REGISTRY[name]["columns"] == canonical


@pytest.mark.parametrize("change", ["revision", "manifest"])
def test_export_still_rejects_revision_or_manifest_changes(
    ready_sheets, tmp_path, change
):
    store, revision, exclusions = ready_sheets
    manager = store._continuity
    if change == "revision":
        manager.index.config["history_publication"]["revision"] = "other"
        manager.sheet.values = manager.index.values()
        error = "DS_REVISAO_ORIGEM_DIVERGENTE"
    else:
        original = manager.sheet.get_all_values
        calls = 0

        def changing():
            nonlocal calls
            calls += 1
            if calls == 2:
                manager.index.config["threshold"] += 1
                manager.sheet.values = manager.index.values()
            return original()

        manager.sheet.get_all_values = changing
        error = "DS_MANIFESTO_ORIGEM_ALTERADO"
    with pytest.raises(StorageError, match=error):
        export_sheets(store, tmp_path / "changed.sqlite", "FARMA", revision, exclusions)


def test_export_cli_accepts_reordered_existing_manifest(
    ready_sheets, tmp_path, monkeypatch
):
    import run_datastudio
    from google_sheets import GoogleSheetsStore

    store, revision, exclusions = ready_sheets

    def reverse(ws, _part):
        n = len(ws.values[0])
        ws.values = [list(reversed(r + [""] * (n - len(r)))) for r in ws.values]

    alter_headers(store, reverse)
    monkeypatch.setattr(
        run_datastudio,
        "load_private_settings",
        lambda: SimpleNamespace(GOOGLE_SPREADSHEET_ID="dashboard"),
    )
    monkeypatch.setattr(GoogleSheetsStore, "open_native_readonly", lambda _id: store)
    monkeypatch.setattr(store, "close", lambda: None)
    proof = tmp_path / "exclusoes.json"
    proof.write_text(json.dumps(exclusions))
    original = proof.read_bytes()
    assert (
        run_datastudio.run(
            [
                "exportar-sheets",
                "--origem-revisao",
                revision,
                "--exclusoes",
                str(proof),
                "--exportacao",
                str(tmp_path / "corte.sqlite"),
                "--saida",
                str(tmp_path / "manifesto.json"),
            ]
        )
        == 0
    )
    assert proof.read_bytes() == original
    assert json.loads((tmp_path / "manifesto.json").read_text())["state"] == "READY"
