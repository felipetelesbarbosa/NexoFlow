"""Recuperação administrativa dirigida; revisão nova, nunca reabrir READY origem."""

from __future__ import annotations

import argparse
import json
import os
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid5

from psycopg import sql

from ds_backend.contract import SCHEMA_HASH, StorageError, digest, normalize, record_key
from ds_backend.migration import private_json
from integrations.datastudio.sales_diagnostic import diagnose, file_hash
from integrations.datastudio.store import Store, identifier


def checked_plan(plan, expected_hash, store, revision):
    body = {k: v for k, v in plan.items() if k != "plan_hash"}
    if digest(body) != expected_hash or plan.get("plan_hash") != expected_hash:
        raise StorageError("DS_RECUPERACAO_HASH_DIVERGENTE")
    if (
        store.segment != "FARMA"
        or plan.get("segment") != store.segment
        or plan.get("target") != store.target
        or plan.get("protocol") != "ds_diagnostico_vendas_1"
        or identifier(revision) == plan.get("revision")
    ):
        raise StorageError("DS_RECUPERACAO_DESTINO_OU_REVISAO_INVALIDA")
    recovery = plan.get("recuperacao", {})
    if (
        plan.get("dry_run") is not True
        or plan.get("escrita_real") is not False
        or plan.get("export_unchanged") is not True
        or not plan.get("export_sha256")
        or recovery.get("referencia_confere") is not True
        or recovery.get("todos_candidatos_conciliados") is not True
    ):
        raise StorageError("DS_RECUPERACAO_PLANO_NAO_CONCILIADO")
    rows = []
    for case in plan["pedidos"]:
        proposal = case["recuperacao"]
        if (
            case["cabecalho_historico"]
            or case["itens_projetados"] != 0
            or proposal["action"] != "CANDIDATO_REPROJETAR_PEDIDO_COMPLETO"
            or proposal["atualizados"]
            or proposal["mantidos"]
            or proposal["remocoes_autorizadas"]
            or proposal["inseridos"] != len(proposal["items"])
        ):
            raise StorageError("DS_RECUPERACAO_ESCOPO_INVALIDO")
        rows.extend(proposal["items"])
    if not rows or len({r["item_chave"] for r in rows}) != len(rows):
        raise StorageError("DS_RECUPERACAO_CHAVES_INVALIDAS")
    rows.sort(key=lambda r: r["item_chave"])
    batches = []
    for start in range(0, len(rows), 200):
        chunk = normalize("BI_Itens", rows[start : start + 200], store.segment)
        bid = str(uuid5(UUID(revision), f"{expected_hash}:BI_Itens:{start}"))
        signature = digest(
            dict(revision=revision, table="BI_Itens", rows=chunk, remove=[])
        )
        batches.append((bid, chunk, signature))
    manifest = dict(
        schema_hash=SCHEMA_HASH,
        complete_sources=True,
        batches={bid: signature for bid, _, signature in batches},
    )
    evidence = dict(
        recovery_protocol="ds_recuperacao_itens_1",
        plan_hash=expected_hash,
        origin_revision=plan["revision"],
        origin_version=plan["version"],
        source_hash=plan["source_hash"],
        export_sha256=plan["export_sha256"],
    )
    return batches, manifest, evidence


def execute(
    store,
    plan,
    expected_hash,
    revision,
    export,
    *,
    action="verificar",
    max_batches=None,
    abc_start=None,
    abc_end=None,
):
    revision = identifier(revision)
    batches, manifest, evidence = checked_plan(plan, expected_hash, store, revision)
    if action not in ("verificar", "aplicar", "conferir", "reverter", "abortar") or (
        max_batches is not None and (type(max_batches) is not int or max_batches < 1)
    ):
        raise StorageError("DS_RECUPERACAO_ACAO_INVALIDA")
    with store.connect(readonly=True) as conn:
        origin = store.revision(conn, plan["revision"])
        if (
            origin["estado"] != "READY"
            or origin["versao"] != plan["version"]
            or origin["evidencia"].get("source_hash") != plan["source_hash"]
        ):
            raise StorageError("DS_RECUPERACAO_ORIGEM_DIVERGENTE")
        existing = conn.execute(
            "SELECT 1 FROM controle.nf_execucoes WHERE id=%s", (revision,)
        ).fetchone()
        status = store.revision(conn, revision) if existing else None
        if status and (
            status["evidencia"] != evidence
            or status["finalidade"] != "bi"
            or status["segmento"] != store.segment
            or status["base"] != plan["version"]
        ):
            raise StorageError("DS_RECUPERACAO_REVISAO_REUTILIZADA")
        active = store.active(conn)
        reverted = conn.execute(
            "SELECT recibo FROM controle.nf_reversoes WHERE execucao=%s", (revision,)
        ).fetchone()
    if action == "reverter":
        if not status:
            raise StorageError("DS_REVISAO_AUSENTE")
        return store.rollback(revision, status["versao"])
    if action == "abortar":
        if not status or active != plan["version"]:
            raise StorageError("DS_RECUPERACAO_ESTADO_INVALIDO")
        return store.abort(revision)
    if reverted or (status and status["estado"] == "ABORTADA"):
        raise StorageError("DS_RECUPERACAO_ENCERRADA")
    if action == "conferir":
        if not status or status["estado"] != "READY" or active != status["versao"]:
            raise StorageError("DS_RECUPERACAO_NAO_CONFIRMADA")
        from datetime import date

        from integrations.datastudio.abc_reader import aggregates, calculate

        start, end = abc_start or plan["start"], abc_end or plan["end"]
        try:
            if date.fromisoformat(start) > date.fromisoformat(end):
                raise ValueError
        except (ValueError, TypeError):
            raise StorageError("DS_PERIODO_INVALIDO") from None
        with store.connect(readonly=True) as conn:
            if store.active(conn) != status["versao"]:
                raise StorageError("DS_RECUPERACAO_EDICAO_POSTERIOR")
            conn.execute("SET LOCAL enable_nestloop=off")
            summary = calculate(
                aggregates(conn, store.schema, start, end, "resumo", 50000),
                start,
                end,
                "resumo",
            )
            daily = conn.execute(
                sql.SQL("""SELECT data,count(*) AS itens,
              count(DISTINCT venda_chave) AS pedidos,sum(quantidade) AS unidades,
              sum(round(receita_item*100)) AS produtos_centavos
              FROM {s}.ds_bi_itens WHERE data BETWEEN %s AND %s GROUP BY data ORDER BY data""").format(
                    s=sql.Identifier(store.schema)
                ),
                (start, end),
            ).fetchall()
        return dict(
            state="CONFERIDA",
            revision=revision,
            version=status["versao"],
            start=start,
            end=end,
            abc=[
                {k: str(v) if isinstance(v, Decimal) else v for k, v in r.items()}
                for r in summary
            ],
            daily=[
                dict(
                    data=str(r["data"]),
                    itens=r["itens"],
                    pedidos=r["pedidos"],
                    unidades=str(r["unidades"]),
                    produtos_centavos=int(r["produtos_centavos"]),
                )
                for r in daily
            ],
        )
    if status and status["estado"] == "READY":
        if active != status["versao"]:
            raise StorageError("DS_RECUPERACAO_EDICAO_POSTERIOR")
        # Resposta perdida após commit: só reler recibo, sem recoleta nem lote novo.
        return store.finish(revision, manifest, complete=True)
    if active != plan["version"]:
        raise StorageError("DS_BASE_RECUPERACAO_ALTERADA")
    if file_hash(export) != plan["export_sha256"]:
        raise StorageError("DS_RECUPERACAO_CORTE_DIVERGENTE")
    expected = dict(
        segment=store.segment,
        revision=plan["revision"],
        version=plan["version"],
        days={
            d: {k: v[k] for k in ("orders", "operational_items", "product_cents")}
            for d, v in plan["recuperacao"]["por_dia"].items()
        },
    )
    fresh = diagnose(
        store,
        plan["revision"],
        plan["version"],
        plan["start"],
        plan["end"],
        export=export,
        expected=expected,
    )
    if fresh["plan_hash"] != expected_hash:
        raise StorageError("DS_RECUPERACAO_EVIDENCIA_ALTERADA")
    if action == "verificar":
        return dict(
            state="VERIFICADA",
            plan_hash=expected_hash,
            orders=len(plan["pedidos"]),
            items=sum(len(rows) for _, rows, _ in batches),
            written=False,
        )
    store.begin(revision, "bi", evidence, expected_base=plan["version"])
    sent = 0
    for bid, rows, signature in batches:
        receipt = store.receipt(bid)
        if receipt is None:
            if max_batches is not None and sent >= max_batches:
                return dict(
                    state="PAUSADA", revision=revision, manifest_hash=digest(manifest)
                )
            receipt = store.batch(revision, bid, "BI_Itens", rows)
            sent += 1
        if (
            receipt["hash"] != signature
            or receipt["revision"] != revision
            or receipt["state"] != "CONFIRMADO"
            or receipt["inserted"] != len(rows)
            or receipt["updated"]
            or receipt["unchanged"]
            or receipt["removed"]
        ):
            raise StorageError("DS_RECUPERACAO_RECIBO_DIVERGENTE")
    # Recusar lotes, tabelas, remoções ou células acrescentados fora deste plano.
    with store.connect() as conn:
        store.writable(conn, revision, allow_sealed=True)
        receipts = conn.execute(
            "SELECT id,hash FROM controle.nf_lotes WHERE execucao=%s", (revision,)
        ).fetchall()
        actual = conn.execute(
            sql.SQL(
                "SELECT tabela,chave,registro FROM {s}.nf_stage WHERE execucao=%s"
            ).format(s=sql.Identifier(store.schema)),
            (revision,),
        ).fetchall()
        proposed = {
            record_key("BI_Itens", r): r for _, rows, _ in batches for r in rows
        }
        if (
            {str(r["id"]): r["hash"] for r in receipts} != manifest["batches"]
            or len(actual) != len(proposed)
            or any(
                r["tabela"] != "BI_Itens" or proposed.get(r["chave"]) != r["registro"]
                for r in actual
            )
        ):
            raise StorageError("DS_RECUPERACAO_STAGE_DIVERGENTE")
    store.seal(revision, manifest)
    return store.finish(revision, manifest, complete=True)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn-file", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--plan-hash", required=True)
    parser.add_argument("--new-revision", required=True)
    parser.add_argument("--export", type=Path, required=True)
    parser.add_argument(
        "--environment", choices=("homologacao", "producao"), required=True
    )
    parser.add_argument(
        "--action",
        choices=("verificar", "aplicar", "conferir", "reverter", "abortar"),
        default="verificar",
    )
    parser.add_argument("--max-batches", type=int)
    parser.add_argument("--abc-start")
    parser.add_argument("--abc-end")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise StorageError("DS_SAIDA_JA_EXISTE")
    plan = json.loads(args.plan.read_text(encoding="utf-8-sig"))
    store = Store(args.dsn_file.read_text().strip(), args.environment, "FARMA")
    result = execute(
        store,
        plan,
        args.plan_hash,
        args.new_revision,
        args.export,
        action=args.action,
        max_batches=args.max_batches,
        abc_start=args.abc_start,
        abc_end=args.abc_end,
    )
    private_json(args.output, result)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except StorageError as exc:
        print(str(exc))
        raise SystemExit(2) from None
    except Exception:
        print("DS_RECUPERACAO_FALHOU; preservar revisão e conferir diagnóstico privado")
        raise SystemExit(2) from None
