"""Somente fixtures; diagnóstico não altera READY, recibos ou o corte."""

import json
from contextlib import closing
from uuid import uuid4

import pytest

from ds_backend.contract import StorageError, digest
from ds_backend.migration import Export
from integrations.datastudio.reader import Reader
from integrations.datastudio.sales_diagnostic import diagnose, file_hash
from looker_bi import build_looker_tables
from tests.datastudio.test_contract import row
from tests.datastudio.test_ds_database import DSN, batch, begin, finish
from tests.datastudio.test_ds_database import store as store
from tests.test_looker_bi import item, order, records

pytestmark = pytest.mark.skipif(not DSN, reason="PostgreSQL descartável")


def broken(store, tmp_path):
    o = row("Pedidos_FarmaLider", **order(1, day="2026-11-09", revenue="10"))
    i = row("Itens_Pedidos_FarmaLider", **item(1, revenue="10"))
    tables = build_looker_tables(
        [],
        [o],
        [],
        snapshot_date="2026-11-09",
        updated_at="",
        period_start="2026-11-09",
        period_end="2026-11-09",
    )
    sale = records(tables, "BI_Clientes_Vendas")
    assert len(sale) == 1 and not tables["BI_Itens"]
    datasets = {
        "Pedidos_FarmaLider": [o],
        "Itens_Pedidos_FarmaLider": [i],
        "BI_Clientes_Vendas": sale,
    }
    path = tmp_path / "corte.sqlite"
    with closing(Export(path, create=True)) as cut:
        for table, rows in datasets.items():
            cut.add(table, rows, "FARMA")
        manifest = cut.seal(
            "FARMA",
            {"scope": "CORTE_COMPLETO", "state": "READY", "revision": "synthetic"},
        )
    rev = store.begin(str(uuid4()), "teste", {"source_hash": digest(manifest)})[
        "revision"
    ]
    for table, rows in datasets.items():
        batch(store, rev, table, rows)
    # Reproduz a lacuna existente; não muda o publicador nem refaz READY real.
    finish(store, rev)
    return rev, path


def test_private_dry_run_tracks_layers_and_preserves_ready(store, tmp_path):
    rev, path = broken(store, tmp_path)
    original = file_hash(path)
    with pytest.raises(StorageError, match="DS_ABC_BASE_INCOMPLETA"):
        Reader(DSN, "homologacao", "FARMA").abc(
            "resumo", ["skus_distintos"], "2026-11-09", "2026-11-09"
        )
    report = diagnose(store, rev, 1, "2026-11-09", "2026-11-12", export=path)
    assert report == diagnose(store, rev, 1, "2026-11-09", "2026-11-12", export=path)
    assert report["export_unchanged"] and original == file_hash(path)
    assert (
        not report["recorte_sem_vendas_incompletas"]
        and report["dry_run"]
        and not report["escrita_real"]
    )
    assert report["por_dia"]["2026-11-09"]["produtos_centavos"] == 1000
    case = report["pedidos"][0]
    assert case["causa"] == "INCONSISTENCIA_JA_NO_CORTE_ORIGEM_OU_EXTRACAO_PENDENTE"
    assert case["camadas"]["BI_Itens"]["corte"]["count"] == 0
    plan = case["recuperacao"]
    assert plan["action"] == "CANDIDATO_REPROJETAR_PEDIDO_COMPLETO"
    assert (
        plan["inseridos"] == 1
        and not plan["aplicavel"]
        and plan["remocoes_autorizadas"] == 0
    )
    assert store.rows("BI_Itens")["rows"] == []
    assert "Nome igual" not in json.dumps(report)
    assert store.inspect(rev)["state"] == "READY"
    # Aplicação apenas na fixture, em revisão nova: prova a re-projeção oficial.
    new = begin(store)
    batch(store, new, "BI_Itens", plan["items"])
    finish(store, new)
    with pytest.raises(StorageError, match="REVISAO_DIVERGENTE"):
        diagnose(store, rev, 1, "2026-11-09", "2026-11-12")
    assert diagnose(store, new, 2, "2026-11-09", "2026-11-12")[
        "recorte_sem_vendas_incompletas"
    ]


def test_diagnostic_distinguishes_current_projection_from_persisted_facts(
    store, tmp_path
):
    rev, _ = broken(store, tmp_path)
    with store.connect() as conn:
        conn.execute(
            "DELETE FROM farma.nf_atuais WHERE tabela='Itens_Pedidos_FarmaLider'"
        )
    r = diagnose(store, rev, 1, "2026-11-09", "2026-11-12")
    assert r["pedidos"][0]["causa"] == "PROJECAO_ATUAL_DIVERGE_FATOS"
    assert not r["pedidos"][0]["recuperacao"]["items"]


def test_diagnostic_wrong_cut_rejected_no_mutation(store, tmp_path):
    rev, path = broken(store, tmp_path)
    other = tmp_path / "outro.sqlite"
    with closing(Export(other, create=True)) as cut:
        cut.seal(
            "PET",
            {"scope": "CORTE_COMPLETO", "state": "READY", "revision": "synthetic"},
        )
    with pytest.raises(StorageError, match="CORTE_DIVERGENTE"):
        diagnose(store, rev, 1, "2026-11-09", "2026-11-12", export=other)
    with closing(Export(path)) as cut:
        assert cut.manifest()["state"] == "READY"


@pytest.mark.parametrize("status,amount", [("3", "10"), ("2", "9")])
def test_candidate_does_not_restore_cancelled_or_financially_incomplete_order(
    status, amount
):
    from collections import defaultdict

    from integrations.datastudio.sales_diagnostic import TABLES, candidate
    from looker_bi import opaque_key

    key = opaque_key("venda", "FARMALIDER:1")
    source = {t: defaultdict(list) for t in TABLES}
    source["Pedidos_FarmaLider"][key] = [
        order(1, day="2026-11-09", revenue="10", status=status)
    ]
    source["Itens_Pedidos_FarmaLider"][key] = [item(1, revenue=amount)]
    sale = dict(
        venda_chave=key,
        cliente_chave=opaque_key("farmalider", "10"),
        data="2026-11-09",
        faturamento_produtos="10",
        frete="0",
        faturamento="10",
    )
    assert not candidate(sale, source, "FARMA")["items"]


def test_diagnostic_cli_hash_private_file_and_nonzero_block(
    store, tmp_path, monkeypatch, capsys
):
    import sys

    from integrations.datastudio.sales_diagnostic import main

    rev, path = broken(store, tmp_path)
    dsn = tmp_path / "dsn"
    dsn.write_text(DSN)
    out = tmp_path / "diagnostico.json"
    argv = [
        "diagnostico",
        "--dsn-file",
        str(dsn),
        "--segment",
        "FARMA",
        "--environment",
        "homologacao",
        "--revision",
        rev,
        "--version",
        "1",
        "--start",
        "2026-11-09",
        "--end",
        "2026-11-12",
        "--export",
        str(path),
        "--output",
        str(out),
    ]
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(StorageError, match="TRANSFERENCIA_NAO_CONFERIDA"):
        main()
    assert not out.exists()
    monkeypatch.setattr(sys, "argv", argv + ["--export-sha256", file_hash(path)])
    assert main() == 3
    stdout = capsys.readouterr().out
    assert (
        "Nome igual" not in stdout and "venda_chave" not in stdout and DSN not in stdout
    )
    assert out.stat().st_mode & 0o777 == 0o600
    report = json.loads(out.read_text())
    assert report["camadas_por_dia"]["2026-11-09"]["BI_Itens"] == dict(
        atuais=0, fatos=0, corte=0
    )
    with pytest.raises(StorageError, match="SAIDA_JA_EXISTE"):
        main()
    assert store.rows("BI_Itens")["rows"] == []
