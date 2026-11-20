"""Guarda de corte novo e transação; o legado READY continua auditável."""

from contextlib import closing
from types import SimpleNamespace

import pytest

from ds_backend.contract import StorageError
from ds_backend.migration import Export, prepare
from tests.datastudio.test_contract import row
from tests.datastudio.test_ds_database import DSN, batch, begin, finish
from tests.datastudio.test_ds_database import store as store
from tests.datastudio.test_migration import ready_sheets as ready_sheets


def stale_cut(path):
    with closing(Export(path, create=True)) as cut:
        cut.add(
            "BI_Clientes_Vendas",
            [
                row(
                    "BI_Clientes_Vendas",
                    venda_chave="sale",
                    cliente_chave="customer",
                    data="2026-11-09",
                    faturamento_produtos="10",
                    frete="2",
                    faturamento="12",
                )
            ],
            "FARMA",
        )
        return cut.seal(
            "FARMA", dict(scope="CORTE_COMPLETO", state="READY", revision="legacy")
        )


def test_prepare_rejects_legacy_stale_cut_without_changing_it(tmp_path):
    from integrations.datastudio.sales_diagnostic import file_hash

    path = tmp_path / "cut.sqlite"
    stale_cut(path)
    before = file_hash(path)
    client = SimpleNamespace(
        config={"environment": "producao", "segment": "FARMA"},
        expected_target="nexoflow_datastudio.farma",
        info={},
    )
    with pytest.raises(StorageError, match="DS_BI_ITENS_DEFASADOS"):
        prepare(path, tmp_path / "plan.json", client)
    assert not (tmp_path / "plan.json").exists() and file_hash(path) == before


@pytest.mark.skipif(not DSN, reason="PostgreSQL descartável")
def test_finish_missing_operational_items_rolls_back_all_changes(store):
    previous = begin(store)
    previous_receipt = finish(store, previous)
    rev = begin(store)
    batch(
        store,
        rev,
        "BI_Clientes_Vendas",
        [
            row(
                "BI_Clientes_Vendas",
                venda_chave="sale",
                cliente_chave="customer",
                data="2026-11-09",
                faturamento_produtos="10",
                frete="2",
                faturamento="12",
            )
        ],
    )
    with pytest.raises(StorageError, match="DS_BI_ITENS_DEFASADOS"):
        finish(store, rev)
    assert store.inspect(rev)["state"] == "WRITING"
    assert finish(store, previous) == previous_receipt
    assert store.rows("BI_Clientes_Vendas")["rows"] == []
    batch(
        store,
        rev,
        "BI_Itens",
        [
            row(
                "BI_Itens",
                item_chave="item",
                venda_chave="sale",
                cliente_chave="customer",
                data="2026-11-09",
                quantidade="1",
                receita_item="10",
            )
        ],
    )
    receipt = finish(store, rev)
    assert receipt["state"] == "READY" and finish(store, rev) == receipt


def test_export_stale_physical_bi_blocks_before_seal_and_keeps_evidence(
    ready_sheets, tmp_path
):
    import json

    from ds_backend.contract import REGISTRY
    from ds_backend.sheets_export import export_sheets
    from sheets_partitions import role_for, roots_for

    s, revision, exclusions = ready_sheets
    name = "BI_Clientes_Vendas"
    columns = REGISTRY[name]["columns"]
    sale = row(
        name,
        venda_chave="outside-history",
        data="2026-11-09",
        cliente_chave="c",
        faturamento_produtos="10",
        frete="2",
        faturamento="12",
    )
    book = s._continuity._book(roots_for(s)[role_for(name)])
    book.add(name, [columns, [sale[c] for c in columns]], cols=len(columns))
    path = tmp_path / "blocked.sqlite"
    with pytest.raises(StorageError, match="DS_BI_ITENS_DEFASADOS"):
        export_sheets(s, path, "FARMA", revision, exclusions)
    diagnostic = json.loads(path.with_suffix(".diagnostico.json").read_text())
    assert diagnostic["por_dia"] == [dict(data="2026-11-09", pedidos=1)]
    assert "outside-history" not in json.dumps(diagnostic)
    with closing(Export(path)) as cut:
        assert (
            cut.db.execute(
                "SELECT count(*) FROM linhas WHERE t='BI_Clientes_Vendas'"
            ).fetchone()[0]
            == 1
        )
        with pytest.raises(StorageError, match="INCOMPLETA"):
            cut.manifest()


def test_old_prepared_plan_rejected_before_any_http(tmp_path):
    import json

    from ds_backend.contract import digest
    from ds_backend.migration import apply

    path = tmp_path / "cut.sqlite"
    manifest = stale_cut(path)
    plan = tmp_path / "plan.json"
    plan.write_text(
        json.dumps(
            dict(
                target="nexoflow_datastudio.farma",
                source=str(path),
                source_hash=digest(manifest),
            )
        )
    )
    client = SimpleNamespace(
        expected_target="nexoflow_datastudio.farma",
        call=lambda *a: pytest.fail("HTTP não permitido"),
    )
    with pytest.raises(StorageError, match="DS_BI_ITENS_DEFASADOS"):
        apply(plan, client, simulate=True)


@pytest.mark.parametrize("change", ["amount", "date", "owner", "quantity"])
def test_cut_partial_stale_values_are_rejected(tmp_path, change):
    from ds_backend.item_consistency import assert_export_items

    path = tmp_path / "cut.sqlite"
    stale_cut(path)
    # Novo corte sintético privado, não modificar uma evidência comercial.
    import json
    import sqlite3

    from ds_backend.contract import record_key

    i = row(
        "BI_Itens",
        item_chave="i",
        venda_chave="sale",
        cliente_chave="customer",
        data="2026-11-09",
        quantidade="1",
        receita_item="10",
    )
    field, value = {
        "amount": ("receita_item", "9.99"),
        "date": ("data", "2026-11-10"),
        "owner": ("cliente_chave", "other"),
        "quantity": ("quantidade", "0"),
    }[change]
    i[field] = value
    with closing(sqlite3.connect(path)) as db:
        db.execute(
            "INSERT INTO linhas VALUES(?,?,?)",
            ("BI_Itens", record_key("BI_Itens", i), json.dumps(i)),
        )
        db.commit()
        db.execute("PRAGMA query_only=ON")
        with pytest.raises(StorageError, match="DS_BI_ITENS_DEFASADOS"):
            assert_export_items(db)


@pytest.mark.skipif(not DSN, reason="PostgreSQL descartável")
def test_guard_volume_sqlite_and_postgres_60003_items(store, tmp_path):
    from ds_backend.item_consistency import assert_export_items
    from integrations.datastudio.financial_views import assert_financial
    from tests.datastudio.test_abc_reader import seed

    items, sales = seed(store)
    with store.connect(readonly=True) as conn:
        assert_financial(conn, "farma")
    path = tmp_path / "volume.sqlite"
    with closing(Export(path, create=True)) as cut:
        for name, rows in (("BI_Clientes_Vendas", sales), ("BI_Itens", items)):
            for start in range(0, len(rows), 1000):
                cut.add(name, rows[start : start + 1000], "FARMA")
        cut.db.commit()
        cut.db.execute("PRAGMA query_only=ON")
        steps = 0

        def bounded_work():
            nonlocal steps
            steps += 1
            return int(steps > 12000)  # 12 milhões de instruções, não tempo arbitrário.

        cut.db.set_progress_handler(bounded_work, 1000)
        assert_export_items(cut.db)
        cut.db.set_progress_handler(None, 0)
        assert steps < 12000
    # Uma perda entre 60 mil linhas não passa como carga completa.
    with store.connect() as conn:
        conn.execute(
            "DELETE FROM farma.nf_atuais WHERE tabela='BI_Itens' AND registro->>'item_chave'='i60002'"
        )
    with store.connect(readonly=True) as conn:
        with pytest.raises(StorageError, match="DS_BI_ITENS_DEFASADOS"):
            assert_financial(conn, "farma")
