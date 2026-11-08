"""Exceções autorizadas numa cópia de publicação; fonte bruta preservada."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

from dedup_io import save_private
from history_conference import summarize
from history_snapshot import readonly, sha256, snapshot
from order_history import HistoryError, identity

AUDIT_TABLE = "history_publication_exclusions"


def require(condition, message):
    if not condition:
        raise HistoryError(message)


def unaffected_digest(db, segment, ids):
    result = hashlib.sha256()
    placeholders = ",".join("?" for _ in ids)
    for name, ddl in db.execute(
        "SELECT name,sql FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ):
        if name == AUDIT_TABLE:
            continue
        result.update(json.dumps([name, ddl], ensure_ascii=False).encode())
        quoted = '"' + name.replace('"', '""') + '"'
        if name == "history_orders":
            sql = f"SELECT rowid,* FROM {quoted} WHERE NOT (segment=? AND id IN ({placeholders})) ORDER BY rowid"
            rows = db.execute(sql, (segment, *ids))
        else:
            rows = db.execute(f"SELECT rowid,* FROM {quoted} ORDER BY rowid")
        for row in rows:
            encoded = json.dumps(list(row), ensure_ascii=False).encode()
            result.update(len(encoded).to_bytes(8, "big"))
            result.update(encoded)
    return result.hexdigest()


def exclusion_audit(db, segment):
    if not db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (AUDIT_TABLE,)
    ).fetchone():
        return []
    require(
        not db.execute(
            f"SELECT 1 FROM {AUDIT_TABLE} WHERE segment!=? OR segment IS NULL",
            (segment,),
        ).fetchone(),
        "EXCLUSAO_DE_OUTRO_SEGMENTO",
    )
    fields = (
        "segmento",
        "pedido_id",
        "motivo",
        "responsavel",
        "aplicado_em_utc",
        "fonte_sha256",
        "valor_original_centavos",
    )
    entries = []
    for row in db.execute(
        f"SELECT segment,id,reason,authorized_by,applied_at,source_sha256,revenue_cents,original_row_json FROM {AUDIT_TABLE} ORDER BY id"
    ):
        entry: dict[str, Any] = dict(zip(fields, row[:7], strict=True))
        original = json.loads(json.loads(row[7])[3])
        require(
            original["segment"] == segment and original["id"] == entry["pedido_id"],
            "AUDITORIA_EXCLUSAO_DIVERGENTE",
        )
        entry["pedido_original"] = dict(
            segmento=segment,
            pedido_id=original["id"],
            cliente_id=original["owner"],
            data=original["date"],
            estado=original["state"],
            produtos=str(Decimal(original["products_cents"]) / 100),
            frete=str(Decimal(original["freight_cents"]) / 100),
            faturamento=str(Decimal(original["revenue_cents"]) / 100),
        )
        entries.append(entry)
    return entries


def aggregate_exclusions(entries):
    """Resumo sem IDs ou texto livre; detalhes ficam no comprovante privado."""
    return {
        "quantidade": len(entries),
        "faturamento_original_centavos": sum(
            entry["valor_original_centavos"] for entry in entries
        ),
    }


def derive(
    source,
    expected_hash,
    output_root,
    segment,
    ids,
    reason,
    authorized_by,
    summary_path=None,
):
    """Só remove history_orders na cópia; guarda a linha original na auditoria.

    Recebimentos, revisões, pendências e janelas continuam descrevendo a coleta
    bruta. O resumo financeiro e todas as tabelas são recalculados pelo publicador.
    Não configura uma exceção global na API, Weni ou Analytics legado.
    """
    ids = tuple(ids)
    require(segment in {"FARMA", "PET"}, "SEGMENTO_INVALIDO")
    require(
        bool(ids) and len(ids) == len(set(ids)) and all(identity(i) == i for i in ids),
        "IDS_EXCLUSAO_INVALIDOS_OU_DUPLICADOS",
    )
    require(
        isinstance(reason, str)
        and bool(reason.strip())
        and isinstance(authorized_by, str)
        and bool(authorized_by.strip()),
        "MOTIVO_E_RESPONSAVEL_OBRIGATORIOS",
    )
    source = Path(source).resolve()
    require(source.is_file(), "BACKUP_NAO_ENCONTRADO")
    wal = source.with_name(source.name + "-wal")
    require(
        not wal.exists() or wal.stat().st_size == 0,
        "USE_BACKUP_CONSISTENTE_SEM_WAL_EXTERNO",
    )
    require(sha256(source) == expected_hash.lower(), "HASH_BACKUP_DIVERGENTE")
    if summary_path:
        summary_path = Path(summary_path).resolve()
        require(not summary_path.exists(), "RESUMO_EXIGE_CAMINHO_INEDITO")
    print("[1/4] Conferindo fonte e pedidos autorizados...", flush=True)
    with readonly(source, segment) as history:
        require(
            not history.db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (AUDIT_TABLE,),
            ).fetchone(),
            "FONTE_JA_TEM_EXCLUSOES_USE_BACKUP_BRUTO",
        )
        before = summarize(history.records(), segment)
        originals = []
        for oid in ids:
            row = history.db.execute(
                "SELECT segment,id,owner,record,first_seen,updated FROM history_orders WHERE segment=? AND id=?",
                (segment, oid),
            ).fetchone()
            require(row is not None, "PEDIDO_EXCLUSAO_AUSENTE")
            record = json.loads(row[3])
            require(record["state"] == "valido", "EXCLUSAO_EXIGE_COMPRA_VALIDA")
            require(
                not history.db.execute(
                    "SELECT 1 FROM history_issues WHERE segment=? AND id=?",
                    (segment, oid),
                ).fetchone(),
                "EXCLUSAO_COM_PENDENCIA_REQUER_CONFERENCIA",
            )
            originals.append(row)
        unchanged = unaffected_digest(history.db, segment, ids)
    directory = Path(output_root).resolve() / uuid4().hex
    directory.mkdir(parents=True, mode=0o700)
    print("[2/4] Criando cópia e registrando as exclusões...", flush=True)
    evidence = snapshot(source, directory, segment)
    target = Path(evidence["path"])
    at = datetime.now(UTC).isoformat()
    with closing(sqlite3.connect(target)) as db:
        with db:
            db.execute(f"""CREATE TABLE {AUDIT_TABLE} (
                segment TEXT NOT NULL,id TEXT NOT NULL,reason TEXT NOT NULL,
                authorized_by TEXT NOT NULL,applied_at TEXT NOT NULL,
                source_sha256 TEXT NOT NULL,revenue_cents INTEGER NOT NULL,
                original_row_json TEXT NOT NULL,PRIMARY KEY(segment,id))""")
            for row in originals:
                record = json.loads(row[3])
                db.execute(
                    f"INSERT INTO {AUDIT_TABLE} VALUES(?,?,?,?,?,?,?,?)",
                    (
                        segment,
                        row[1],
                        reason,
                        authorized_by,
                        at,
                        expected_hash.lower(),
                        record["revenue_cents"],
                        json.dumps(list(row), ensure_ascii=False),
                    ),
                )
                count = db.execute(
                    "DELETE FROM history_orders WHERE segment=? AND id=?",
                    (segment, row[1]),
                ).rowcount
                require(count == 1, "EXCLUSAO_NAO_CORRESPONDE_A_UM_PEDIDO")
    print("[3/4] Reconferindo integridade, demais dados e totais...", flush=True)
    with readonly(target, segment) as history:
        require(
            unaffected_digest(history.db, segment, ids) == unchanged,
            "DADOS_FORA_DAS_EXCLUSOES_ALTERADOS",
        )
        after = summarize(history.records(), segment)
        a, b = before["recortes"][-1], after["recortes"][-1]
        require(
            a["pedidos"] - b["pedidos"] == len(ids)
            and a["validos"] - b["validos"] == len(ids),
            "CONTAGEM_EXCLUSOES_DIVERGENTE",
        )
        for field, source_field in (
            ("produtos_centavos", "products_cents"),
            ("frete_centavos", "freight_cents"),
            ("faturamento_centavos", "revenue_cents"),
        ):
            removed = sum(json.loads(row[3])[source_field] for row in originals)
            require(a[field] - b[field] == removed, "VALOR_EXCLUSOES_DIVERGENTE")
        for field in ("cancelados", "pendentes", "outros"):
            require(a[field] == b[field], "ESTADOS_FORA_DAS_EXCLUSOES_ALTERADOS")
        audit = exclusion_audit(history.db, segment)
        require(len(audit) == len(ids), "AUDITORIA_EXCLUSOES_INCOMPLETA")
    require(
        sha256(source) == expected_hash.lower(),
        "BACKUP_ORIGINAL_ALTERADO_DURANTE_OPERACAO",
    )
    evidence.update(sha256=sha256(target), bytes=target.stat().st_size)
    after["contexto"] = dict(
        snapshot_sha256=evidence["sha256"], fonte_sha256=expected_hash.lower()
    )
    after["exclusoes_publicacao"] = aggregate_exclusions(audit)
    proof = dict(
        formato="historico_exclusoes_v1",
        segmento=segment,
        fonte=dict(path=str(source), sha256=expected_hash.lower()),
        copia_publicacao=evidence,
        exclusoes=audit,
        antes=before["recortes"][-1],
        depois=after["recortes"][-1],
        demais_dados_sha256=unchanged,
        escopo="Somente esta cópia de publicação; fonte, API e banco operacional preservados",
        recebimentos="Janelas, recibos e revisões preservam a coleta bruta antes das exclusões.",
    )
    proof_path = directory / "comprovante-exclusoes.json"
    summary_path = summary_path or directory / "resumo-apos-exclusoes.json"
    save_private(proof_path, proof)
    save_private(summary_path, after)
    print("[4/4] Cópia concluída. Nenhum fato publicado.", flush=True)
    result = dict(
        banco_publicacao=str(target),
        sha256=evidence["sha256"],
        bytes=evidence["bytes"],
        comprovante=str(proof_path),
        resumo=str(summary_path),
        total=after["recortes"][-1],
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def exclude(args):
    from config import LOG_DIR
    from recompra_lock import state_lock
    from runtime_profile import segment

    require(
        args.banco is not None and bool(args.sha256_banco),
        "EXCLUSAO_EXIGE_BANCO_E_SHA256",
    )
    with state_lock(LOG_DIR / "historico_pedidos_state.json"):
        derive(
            args.banco,
            args.sha256_banco,
            LOG_DIR / "privado" / "exclusoes-publicacao",
            segment(),
            args.excluir_pedidos,
            args.motivo_exclusao,
            args.responsavel_exclusao,
            args.resumo_mensal,
        )
    return 0
