"""Recuperação real do código, exclusivamente no PostgreSQL descartável."""

import json
from unittest.mock import patch
from uuid import uuid4

import pytest

from ds_backend.contract import StorageError
from integrations.datastudio.reader import Reader
from integrations.datastudio.sales_diagnostic import diagnose, file_hash
from integrations.datastudio.sales_recovery import execute
from tests.datastudio.test_ds_database import DSN, begin, finish
from tests.datastudio.test_ds_database import store as store
from tests.datastudio.test_sales_diagnostic import broken, recovery_fixture_204

pytestmark = pytest.mark.skipif(not DSN, reason="PostgreSQL descartável")


def fixture_plan(store, tmp_path):
    rev, path = broken(store, tmp_path)
    proof = dict(
        segment="FARMA",
        revision=rev,
        version=1,
        days={"2026-11-09": dict(orders=1, operational_items=1, product_cents=1000)},
    )
    plan = diagnose(
        store, rev, 1, "2026-11-09", "2026-11-12", export=path, expected=proof
    )
    return rev, path, plan


def test_recover_204_in_new_revision_resume_abc_and_rollback(store, tmp_path):
    origin, path, plan = recovery_fixture_204(store, tmp_path)
    sha = file_hash(path)
    original = store.inspect(origin)
    revision = str(uuid4())

    def run(**kw):
        return execute(store, plan, plan["plan_hash"], revision, path, **kw)

    assert run()["state"] == "VERIFICADA"
    with store.connect(readonly=True) as c:
        assert (
            c.execute("SELECT count(*) AS n FROM controle.nf_execucoes").fetchone()["n"]
            == 1
        )
    assert run(action="aplicar", max_batches=1)["state"] == "PAUSADA"
    assert store.rows("BI_Itens")["rows"] == []
    assert store.inspect(revision)["base"] == 1
    with pytest.raises(StorageError, match="DS_ABC_BASE_INCOMPLETA"):
        Reader(DSN, "homologacao", "FARMA").abc(
            "resumo", ["skus_distintos"], "2026-01-01", "2026-11-15"
        )
    receipt = run(action="aplicar")
    assert (
        receipt["state"] == "READY"
        and receipt["version"] == 2
        and receipt["changed_rows"] == 579
    )
    conference = run(action="conferir", abc_start="2026-01-01", abc_end="2026-11-15")
    assert conference["state"] == "CONFERIDA" and conference["version"] == 2
    assert sum(r["itens"] for r in conference["daily"]) == 579
    assert sum(r["produtos_centavos"] for r in conference["daily"]) == 4183978
    assert run(action="aplicar") == receipt
    assert run(action="verificar") == receipt
    assert store.inspect(origin) == original and file_hash(path) == sha
    items = store.rows("BI_Itens")["rows"]
    assert len(items) == len({i["item_chave"] for i in items}) == 579
    summary = Reader(DSN, "homologacao", "FARMA").abc(
        "resumo",
        ["skus_distintos", "faturamento_produtos"],
        "2026-01-01",
        "2026-11-15",
    )
    from decimal import Decimal

    assert summary["version"] == 2 and summary["complete"]
    assert summary["rows"][0][0] == 1
    assert Decimal(summary["rows"][0][1]) == Decimal("41839.78")
    with store.connect(readonly=True) as c:
        totals = c.execute(
            "SELECT sum(frete) AS frete,sum(faturamento_produtos) AS produtos,sum(faturamento) AS total FROM farma.ds_bi_clientes_vendas"
        ).fetchone()
        assert totals["frete"] == Decimal("1611.60")
        assert totals["produtos"] == Decimal("41839.78")
        assert totals["total"] == Decimal("43451.38")
        assert (
            c.execute(
                "SELECT count(*) AS n FROM controle.nf_lotes WHERE execucao=%s",
                (revision,),
            ).fetchone()["n"]
            == 3
        )
    assert (
        run(action="reverter")
        == run(action="reverter")
        == dict(state="REVERTIDA", version=1)
    )
    assert store.rows("BI_Itens")["rows"] == [] and store.inspect(origin) == original
    with pytest.raises(StorageError, match="DS_RECUPERACAO_ENCERRADA"):
        run(action="aplicar")
    with pytest.raises(StorageError, match="DS_ABC_BASE_INCOMPLETA"):
        Reader(DSN, "homologacao", "FARMA").abc(
            "resumo", ["skus_distintos"], "2026-01-01", "2026-11-15"
        )


@pytest.mark.parametrize("failure", ["before", "after"])
def test_failure_before_or_after_commit_resumes_same_revision(store, tmp_path, failure):
    origin, path, plan = fixture_plan(store, tmp_path)
    revision = str(uuid4())
    original_finish = store.finish

    def uncertain(*args, **kwargs):
        if failure == "after":
            original_finish(*args, **kwargs)
        raise RuntimeError("Resposta perdida simulada")

    with patch.object(store, "finish", side_effect=uncertain):
        with pytest.raises(RuntimeError):
            execute(store, plan, plan["plan_hash"], revision, path, action="aplicar")
    result = execute(store, plan, plan["plan_hash"], revision, path, action="aplicar")
    assert result["state"] == "READY" and result["changed_rows"] == 1
    assert (
        len(store.rows("BI_Itens")["rows"]) == 1
        and store.inspect(origin)["state"] == "READY"
    )


def test_guards_hash_origin_cut_and_changed_source_before_writing(store, tmp_path):
    origin, path, plan = fixture_plan(store, tmp_path)
    for changed, checksum in [
        (plan, "0" * 64),
        (dict(plan, version=2), plan["plan_hash"]),
    ]:
        with pytest.raises(StorageError, match="HASH_DIVERGENTE"):
            execute(store, changed, checksum, str(uuid4()), path, action="aplicar")
    with pytest.raises(StorageError, match="REVISAO_INVALIDA"):
        execute(store, plan, plan["plan_hash"], origin, path, action="aplicar")
    other = tmp_path / "other.sqlite"
    other.write_bytes(b"different")
    with pytest.raises(StorageError, match="CORTE_DIVERGENTE"):
        execute(store, plan, plan["plan_hash"], str(uuid4()), other, action="aplicar")
    with store.connect() as c:
        c.execute(
            "UPDATE farma.nf_atuais SET registro=registro||'{\"valor_total\":\"9\"}'::jsonb WHERE tabela='Itens_Pedidos_FarmaLider'"
        )
    with pytest.raises(StorageError, match="EVIDENCIA_ALTERADA"):
        execute(store, plan, plan["plan_hash"], str(uuid4()), path, action="aplicar")
    with store.connect(readonly=True) as c:
        assert (
            c.execute("SELECT count(*) AS n FROM controle.nf_execucoes").fetchone()["n"]
            == 1
        )


def test_financial_guard_rollback_and_abort(store, tmp_path):
    origin, path, plan = fixture_plan(store, tmp_path)
    revision = str(uuid4())
    with patch(
        "integrations.datastudio.financial_views.assert_operational_items",
        side_effect=StorageError("DS_BI_ITENS_DEFASADOS"),
    ):
        with pytest.raises(StorageError, match="DEFASADOS"):
            execute(store, plan, plan["plan_hash"], revision, path, action="aplicar")
    assert (
        store.inspect(revision)["state"] == "WRITING"
        and store.rows("BI_Itens")["rows"] == []
    )
    assert (
        execute(store, plan, plan["plan_hash"], revision, path, action="abortar")[
            "state"
        ]
        == "ABORTADA"
    )
    assert (
        execute(store, plan, plan["plan_hash"], revision, path, action="abortar")[
            "state"
        ]
        == "ABORTADA"
    )
    assert store.inspect(origin)["state"] == "READY"


def test_expected_base_is_checked_inside_begin_lock(store, tmp_path):
    origin, path, plan = fixture_plan(store, tmp_path)
    original_begin = store.begin

    def race(*args, **kwargs):
        other = original_begin(str(uuid4()), "bi", {})["revision"]
        # Somente a fixture emula outro READY legado sem recuperar os dados.
        with patch("integrations.datastudio.financial_views.assert_operational_items"):
            finish(store, other)
        return original_begin(*args, **kwargs)

    with patch.object(store, "begin", side_effect=race):
        with pytest.raises(StorageError, match="DS_BASE_RECUPERACAO_ALTERADA"):
            execute(
                store, plan, plan["plan_hash"], str(uuid4()), path, action="aplicar"
            )


def test_cli_verifies_and_replays_receipt_private_output(
    store, tmp_path, monkeypatch, capsys
):
    import sys

    from integrations.datastudio.sales_recovery import main

    _, path, plan = fixture_plan(store, tmp_path)
    dsn, source = tmp_path / "dsn", tmp_path / "plan.json"
    dsn.write_text(DSN)
    source.write_text(json.dumps(plan), encoding="utf-8")
    argv = [
        "recovery",
        "--dsn-file",
        str(dsn),
        "--plan",
        str(source),
        "--plan-hash",
        plan["plan_hash"],
        "--new-revision",
        str(uuid4()),
        "--export",
        str(path),
        "--environment",
        "homologacao",
    ]
    for n, action in enumerate(
        ("verificar", "aplicar", "aplicar", "conferir", "reverter")
    ):
        out = tmp_path / f"receipt-{n}.json"
        monkeypatch.setattr(
            sys, "argv", argv + ["--action", action, "--output", str(out)]
        )
        assert main() == 0
        assert out.stat().st_mode & 0o777 == 0o600
    output = capsys.readouterr().out
    assert (
        DSN not in output
        and "cliente_chave" not in output
        and "Nome igual" not in output
    )


def test_tampered_items_duplicate_segment_and_foreign_stage_are_blocked(
    store, tmp_path
):
    from copy import deepcopy

    from ds_backend.contract import digest
    from integrations.datastudio.store import Store

    _, path, plan = fixture_plan(store, tmp_path)
    for field, value in [
        ("receita_item", "9.99"),
        ("cliente_chave", "other"),
        ("data", "2026-11-10"),
    ]:
        altered = deepcopy(plan)
        altered["pedidos"][0]["recuperacao"]["items"][0][field] = value
        altered["plan_hash"] = digest(
            {k: v for k, v in altered.items() if k != "plan_hash"}
        )
        with pytest.raises(StorageError, match="EVIDENCIA_ALTERADA"):
            execute(
                store,
                altered,
                altered["plan_hash"],
                str(uuid4()),
                path,
                action="aplicar",
            )
    with pytest.raises(StorageError, match="DESTINO_OU_REVISAO"):
        execute(
            Store(DSN, "homologacao", "PET"),
            plan,
            plan["plan_hash"],
            str(uuid4()),
            path,
            action="aplicar",
        )
    revision = str(uuid4())
    original = store.batch

    def other_cell(*args, **kwargs):
        result = original(*args, **kwargs)
        with store.connect() as c:
            c.execute(
                'UPDATE farma.nf_stage SET registro=registro||\'{"receita_item":"9.99"}\'::jsonb WHERE execucao=%s',
                (revision,),
            )
        return result

    with patch.object(store, "batch", side_effect=other_cell):
        with pytest.raises(StorageError, match="STAGE_DIVERGENTE"):
            execute(store, plan, plan["plan_hash"], revision, path, action="aplicar")
    assert store.inspect(revision)["state"] == "WRITING"
    assert store.rows("BI_Itens")["rows"] == []


def test_rollback_refuses_later_revision_and_cannot_apply_plan_under_another_id(
    store, tmp_path
):
    _, path, plan = fixture_plan(store, tmp_path)
    revision = str(uuid4())
    execute(store, plan, plan["plan_hash"], revision, path, action="aplicar")
    with pytest.raises(StorageError, match="BASE_RECUPERACAO_ALTERADA"):
        execute(store, plan, plan["plan_hash"], str(uuid4()), path, action="aplicar")
    other = begin(store)
    finish(store, other)
    with pytest.raises(StorageError, match="DS_REVERSAO_EDICAO_POSTERIOR"):
        execute(store, plan, plan["plan_hash"], revision, path, action="reverter")
    assert len(store.rows("BI_Itens")["rows"]) == 1


def test_lost_batch_response_and_seal_response_reuse_persisted_receipts(
    store, tmp_path
):
    _, path, plan = fixture_plan(store, tmp_path)
    revision = str(uuid4())
    original_batch, original_seal = store.batch, store.seal

    def lost_batch(*args, **kwargs):
        original_batch(*args, **kwargs)
        raise ConnectionError("Resposta perdida depois do lote")

    with patch.object(store, "batch", side_effect=lost_batch):
        with pytest.raises(ConnectionError):
            execute(store, plan, plan["plan_hash"], revision, path, action="aplicar")

    def lost_seal(*args, **kwargs):
        original_seal(*args, **kwargs)
        raise ConnectionError("Resposta perdida depois do selo")

    with patch.object(store, "seal", side_effect=lost_seal):
        with pytest.raises(ConnectionError):
            execute(store, plan, plan["plan_hash"], revision, path, action="aplicar")
    receipt = execute(store, plan, plan["plan_hash"], revision, path, action="aplicar")
    assert receipt["changed_rows"] == 1
    with store.connect(readonly=True) as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM controle.nf_lotes WHERE execucao=%s",
                (revision,),
            ).fetchone()["n"]
            == 1
        )
