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
    # Fixture de READY legado: emula exclusivamente a versão anterior à guarda.
    # A produção não tem flag/bypass; a nova guarda é exercitada em teste separado.
    from unittest.mock import patch

    with patch("integrations.datastudio.financial_views.assert_operational_items"):
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
    expected = tmp_path / "expected.json"
    expected.write_text(
        json.dumps(
            dict(
                segment="FARMA",
                revision=rev,
                version=1,
                days={
                    "2026-11-09": dict(
                        orders=1, operational_items=1, product_cents=1000
                    )
                },
            )
        )
    )
    monkeypatch.setattr(
        sys,
        "argv",
        argv
        + ["--export-sha256", file_hash(path), "--expected-summary", str(expected)],
    )
    assert main() == 3
    stdout = capsys.readouterr().out
    assert (
        "Nome igual" not in stdout and "venda_chave" not in stdout and DSN not in stdout
    )
    assert out.stat().st_mode & 0o777 == 0o600
    report = json.loads(out.read_text())
    assert report["recuperacao"]["referencia_confere"] is True
    assert report["camadas_por_dia"]["2026-11-09"]["BI_Itens"] == dict(
        atuais=0, fatos=0, corte=0
    )
    with pytest.raises(StorageError, match="SAIDA_JA_EXISTE"):
        main()
    assert store.rows("BI_Itens")["rows"] == []


def test_recovery_204_sales_579_items_exact_daily_control_dry_run(store, tmp_path):
    """Mesmas contagens de controle, com pedidos/itens inteiramente fictícios."""
    from decimal import Decimal
    from unittest.mock import patch

    expected_days = {
        "2026-11-09": dict(orders=63, operational_items=174, product_cents=1326034),
        "2026-11-10": dict(orders=63, operational_items=196, product_cents=1445984),
        "2026-11-11": dict(orders=56, operational_items=148, product_cents=895343),
        "2026-11-12": dict(orders=22, operational_items=61, product_cents=516617),
    }
    orders, items = [], []
    for day, control in expected_days.items():
        n = control["orders"]
        for index in range(n):
            number = len(orders) + 1
            amount = control["product_cents"] // n + int(
                index < control["product_cents"] % n
            )
            count = control["operational_items"] // n + int(
                index < control["operational_items"] % n
            )
            o = order(number, day=day, revenue=str(Decimal(amount) / 100))
            o.update(
                farmalider_frete="7.90",
                valor_total_faturamento=str(Decimal(amount + 790) / 100),
            )
            orders.append(row("Pedidos_FarmaLider", **o))
            for position in range(count):
                value = amount // count + int(position < amount % count)
                items.append(
                    row(
                        "Itens_Pedidos_FarmaLider",
                        **item(
                            number,
                            product="MESMO-SKU",
                            revenue=str(Decimal(value) / 100),
                            position=position + 1,
                        ),
                    )
                )
    generated = build_looker_tables(
        [],
        orders,
        [],
        snapshot_date="2026-11-12",
        updated_at="",
        period_start="2026-11-09",
        period_end="2026-11-12",
    )
    datasets = {
        "Pedidos_FarmaLider": orders,
        "Itens_Pedidos_FarmaLider": items,
        "BI_Clientes_Vendas": records(generated, "BI_Clientes_Vendas"),
    }
    path = tmp_path / "cut.sqlite"
    with closing(Export(path, create=True)) as cut:
        for table, rows in datasets.items():
            cut.add(table, rows, "FARMA")
        manifest = cut.seal(
            "FARMA", dict(scope="CORTE_COMPLETO", state="READY", revision="legacy")
        )
    rev = store.begin(str(uuid4()), "teste", {"source_hash": digest(manifest)})[
        "revision"
    ]
    for table, rows in datasets.items():
        batch(store, rev, table, rows)
    with patch("integrations.datastudio.financial_views.assert_operational_items"):
        receipt = finish(store, rev)
    proof = dict(segment="FARMA", revision=rev, version=1, days=expected_days)
    r = diagnose(store, rev, 1, "2026-11-09", "2026-11-12", export=path, expected=proof)
    assert (
        r["recuperacao"]["referencia_confere"]
        and r["recuperacao"]["todos_candidatos_conciliados"]
    )
    assert len(r["pedidos"]) == 204
    assert r == diagnose(
        store, rev, 1, "2026-11-09", "2026-11-12", export=path, expected=proof
    )
    summary = r["recuperacao"]["por_dia"]
    assert sum(v["candidate_items"] for v in summary.values()) == 579
    assert sum(v["candidate_cents"] for v in summary.values()) == 4183978
    assert sum(v["inserted"] for v in summary.values()) == 579
    assert all(v["candidate_cents"] == v["product_cents"] for v in summary.values())
    assert all(v["updated"] == v["unchanged"] == 0 for v in summary.values())
    keys = [i["item_chave"] for d in r["pedidos"] for i in d["recuperacao"]["items"]]
    assert len(set(keys)) == 579 and store.rows("BI_Itens")["rows"] == []
    assert (
        finish(store, rev) == receipt
    )  # READY legado devolve o recibo sem novo fechamento.
    proof["days"] = dict(
        expected_days, **{"2026-11-12": dict(expected_days["2026-11-12"], orders=23)}
    )
    assert not diagnose(
        store, rev, 1, "2026-11-09", "2026-11-12", export=path, expected=proof
    )["recuperacao"]["referencia_confere"]


def test_duplicate_raw_items_are_not_silently_collapsed(store, tmp_path):
    from collections import defaultdict

    from integrations.datastudio.sales_diagnostic import TABLES, candidate

    rev, path = broken(store, tmp_path)
    report = diagnose(store, rev, 1, "2026-11-09", "2026-11-12", export=path)
    key = report["pedidos"][0]["venda_chave"]
    source = {t: defaultdict(list) for t in TABLES}
    source["Pedidos_FarmaLider"][key] = [order(1, day="2026-11-09", revenue="10")]
    source["Itens_Pedidos_FarmaLider"][key] = [
        item(1, revenue="5"),
        item(1, revenue="5"),
    ]
    result = candidate(
        dict(venda_chave=key, faturamento_produtos="10"), source, "FARMA"
    )
    assert result == dict(action="DUPLICIDADE_OPERACIONAL_BLOQUEADA", items=[])


def test_candidate_key_owned_by_another_sale_is_blocked(store, tmp_path):
    from unittest.mock import patch

    rev, path = broken(store, tmp_path)
    proposal = diagnose(store, rev, 1, "2026-11-09", "2026-11-12")["pedidos"][0][
        "recuperacao"
    ]["items"][0]
    new = begin(store)
    batch(store, new, "BI_Itens", [dict(proposal, venda_chave="another-sale")])
    with patch("integrations.datastudio.financial_views.assert_operational_items"):
        finish(store, new)
    report = diagnose(store, new, 2, "2026-11-09", "2026-11-12")
    assert (
        report["pedidos"][0]["recuperacao"]["action"]
        == "CHAVE_BI_VINCULADA_A_OUTRA_VENDA"
    )
    assert not report["recuperacao"]["todos_candidatos_conciliados"]
