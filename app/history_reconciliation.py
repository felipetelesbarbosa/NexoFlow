"""Compatibilidade oficial, restrita ao plano 1.5.25 antes do primeiro lote."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from dedup_io import save_private
from history_snapshot import readonly, sha256
from order_history import HistoryError, digest
from order_history_sheets import SCHEMAS, iter_tables

PROTOCOL = "historico_compatibilidade_pre_lote_v1"
# Release v1.5.25, commit 12af79daa7df1385203974f582bc716114589b1e.
LEGACY_SIGNATURE = "fe36f917fd1a164b7bad9722d0f69d44d32391015d8d6d7c2d31c78b8a01d785"
LEGACY_SIGNATURES = {
    LEGACY_SIGNATURE,
    # Os mesmos seis blobs oficiais com checkout Windows CRLF.
    "5145fe31d04c2a6bc1dcfb1eef2f7154c36d5dbcb053a6f5c0c8d5d42956aca5",
}
RECEIPT_KEY = "code_reconciliation"


def _bindings(review, current):
    return dict(
        format=PROTOCOL,
        revision=review["revision"],
        review_digest=review["digest"],
        from_signature=review["publisher_signature"],
        to_signature=current,
        journal_signature=review["journal_signature"],
        metadata_signature=review["metadata_signature"],
        input_digest=review["input_digest"],
        source_digest=review["source_digest"],
        evidence_digest=digest(review["evidence"]),
        snapshot_sha256=review["evidence"]["sha256"],
        batch_hashes_digest=digest(review["batch_hashes"]),
        capacity_digest=digest(review["capacity"]),
    )


def compatible(db, review, current):
    from history_publication import get, rows_hash

    try:
        receipt = get(db, RECEIPT_KEY)
        if (
            not isinstance(receipt, dict)
            or review["publisher_signature"] not in LEGACY_SIGNATURES
        ):
            return False
        original = dict(receipt)
        checksum = original.pop("digest", None)
        return (
            checksum == digest(original)
            and all(
                receipt.get(key) == value
                for key, value in _bindings(review, current).items()
            )
            and receipt.get("baseline_digest") == rows_hash(db, "baseline")
            and receipt.get("pending_batches") == review["batches"]
        )
    except (KeyError, TypeError, ValueError):
        return False


def _zero_batches(db, review):
    from history_publication import get, journal_signature

    if (
        get(db, "finished")
        or get(db, "finished") not in (None, False)
        or type(get(db, "started")) is not bool
        or get(db, "manifest_pending") is not None
        or db.execute(
            "SELECT 1 FROM batches WHERE state IS NULL OR state!='pending' LIMIT 1"
        ).fetchone()
        or db.execute("SELECT count(*) FROM batches").fetchone()[0] != review["batches"]
        or get(db, "review") != review
        or journal_signature(db) != review["journal_signature"]
        or list(Path(review["journal"]).parent.glob("lote_*.json"))
    ):
        raise HistoryError("RECONCILIACAO_EXIGE_ZERO_LOTES_E_NENHUMA_INCERTEZA")
    hashes = [
        digest([t, p, body])
        for t, p, body in db.execute("SELECT t,p,body FROM batches ORDER BY n")
    ]
    if hashes != review["batch_hashes"]:
        raise HistoryError("PLANO_DE_LOTE_ALTERADO")


def _transform(db, review, segment):
    from history_conference import receipts, summarize
    from history_exclusions import exclusion_audit
    from history_publication import add_retirements, pack, rows_hash

    evidence = review["evidence"]
    path = Path(evidence["path"])
    if path.stat().st_size != evidence["bytes"] or sha256(path) != evidence["sha256"]:
        raise HistoryError("COPIA_SQLITE_ALTERADA_APOS_REVISAO")
    with readonly(path, segment) as history, closing(sqlite3.connect("")) as fresh:
        conference = summarize(
            history.records(), segment, context={"snapshot_sha256": evidence["sha256"]}
        )
        stable_conference = dict(conference)
        stable_conference.pop("conferido_em", None)
        original_conference = dict(evidence.get("conference") or {})
        original_conference.pop("conferido_em", None)
        counts = {
            table: history.db.execute(
                f"SELECT count(*) FROM {table} WHERE segment=?", (segment,)
            ).fetchone()[0]
            for table in (
                "history_orders",
                "history_windows",
                "history_issues",
                "history_revisions",
            )
        }
        counts.update(
            product_item_lines=conference["recortes"][-1]["itens_linhas_observadas"],
            valid_buyers=conference["recortes"][-1]["clientes_com_compra_valida"],
        )
        if (
            stable_conference != original_conference
            or counts != evidence.get("local_counts")
            or receipts(history) != evidence.get("receipts")
            or exclusion_audit(history.db, segment)
            != evidence.get("publication_exclusions")
            or history.db.execute("PRAGMA user_version").fetchone()[0]
            != evidence.get("schema_user_version")
        ):
            raise HistoryError("EVIDENCIA_DA_FONTE_DIVERGENTE")
        fresh.executescript(
            "CREATE TABLE incoming(t TEXT,k TEXT,v TEXT,PRIMARY KEY(t,k)); CREATE TABLE baseline(t TEXT,k TEXT,v TEXT,PRIMARY KEY(t,k));"
        )
        for title, row in iter_tables(history):
            fresh.execute(
                "INSERT INTO incoming VALUES(?,?,?)",
                (title, row["chave"], pack(title, row, segment)),
            )
        if rows_hash(fresh, "incoming") != review["input_digest"]:
            raise HistoryError("TRANSFORMACAO_ALTERADA_RECONCILIACAO_BLOQUEADA")
        fresh.executemany(
            "INSERT INTO baseline VALUES(?,?,?)",
            db.execute("SELECT t,k,v FROM baseline"),
        )
        add_retirements(fresh, segment, evidence)
        if rows_hash(fresh, "incoming") != review["source_digest"]:
            raise HistoryError("PROJECAO_ALTERADA_RECONCILIACAO_BLOQUEADA")
    if sha256(path) != evidence["sha256"]:
        raise HistoryError("COPIA_SQLITE_ALTERADA_APOS_REVISAO")


def _baseline(engine, db, parts):
    from history_publication import pack

    with closing(sqlite3.connect("")) as observed:
        observed.execute(
            "CREATE TABLE seen(t TEXT,p INTEGER,r INTEGER,PRIMARY KEY(t,p,r))"
        )
        for part in parts:
            title = part["title"]
            headers = SCHEMAS[title]
            for position, cells in engine.remote.scan(part, headers):
                if not any(v not in ("", None) for v in cells):
                    continue
                if len(cells) > len(headers):
                    raise HistoryError("BASELINE_REMOTA_ALTERADA")
                raw = pack(
                    title,
                    dict(
                        zip(
                            headers,
                            cells + [""] * (len(headers) - len(cells)),
                            strict=True,
                        )
                    ),
                    engine.segment,
                )
                old = db.execute(
                    "SELECT v FROM baseline WHERE t=? AND p=? AND r=?",
                    (title, part["number"], position),
                ).fetchone()
                if old != (raw,):
                    raise HistoryError("BASELINE_REMOTA_ALTERADA")
                observed.execute(
                    "INSERT INTO seen VALUES(?,?,?)", (title, part["number"], position)
                )
        for title, part, position in db.execute("SELECT t,p,r FROM baseline"):
            if not observed.execute(
                "SELECT 1 FROM seen WHERE t=? AND p=? AND r=?", (title, part, position)
            ).fetchone():
                raise HistoryError("BASELINE_REMOTA_ALTERADA")


def reconcile(engine, review):
    from copy import deepcopy

    from history_publication import get, publisher_signature, rows_hash

    current = publisher_signature()
    with closing(engine._open_local(review)) as db:
        if compatible(db, review, current):
            receipt = get(db, RECEIPT_KEY)
        else:
            if db.execute("SELECT 1 FROM meta WHERE k=?", (RECEIPT_KEY,)).fetchone():
                raise HistoryError("COMPROVANTE_DE_COMPATIBILIDADE_INVALIDO")
            if review.get("publisher_signature") not in LEGACY_SIGNATURES:
                raise HistoryError("PUBLICADOR_LEGADO_NAO_SUPORTADO_PARA_RECONCILIACAO")
            db.execute("BEGIN IMMEDIATE")
            if db.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise HistoryError("JOURNAL_INTEGRIDADE_INVALIDA")
            _zero_batches(db, review)
            if (
                rows_hash(db, "incoming") != review["source_digest"]
                or digest(get(db, "metadata")) != review["metadata_signature"]
            ):
                raise HistoryError("PLANO_LOCAL_ALTERADO")
            metadata = get(db, "metadata")
            if get(db, "parts") != metadata["parts"]:
                raise HistoryError("RECONCILIACAO_NAO_ACEITA_PARTES_JA_ATIVADAS")
            _transform(db, review, engine.segment)
            engine.remote.acquire()
            manifest = engine.remote.manifest()
            if (
                manifest != get(db, "manifest")
                or engine.remote.context() != review["context"]
            ):
                raise HistoryError("MANIFESTO_OU_DESTINOS_ALTERADOS")
            verifier = getattr(engine.remote, "verify_reconciliation", None)
            if verifier is None:
                raise HistoryError("TRANSPORTE_NAO_COMPROVA_RECONCILIACAO")
            proofs = verifier(
                review["capacity"], deepcopy(metadata), review["revision"]
            )
            _baseline(engine, db, metadata["parts"])
            engine.remote.acquire()
            if (
                engine.remote.manifest() != manifest
                or engine.remote.context() != review["context"]
            ):
                raise HistoryError("MANIFESTO_MUDOU_DURANTE_RECONCILIACAO")
            _zero_batches(db, review)
            if sha256(review["evidence"]["path"]) != review["evidence"]["sha256"]:
                raise HistoryError("COPIA_SQLITE_ALTERADA_APOS_REVISAO")
            receipt = dict(
                **_bindings(review, current),
                validated_at=datetime.now(UTC).isoformat(),
                baseline_digest=rows_hash(db, "baseline"),
                pending_batches=review["batches"],
                manifest_at_reconciliation=manifest,
                remote_proofs=proofs,
            )
            receipt["digest"] = digest(receipt)
            db.execute(
                "INSERT OR REPLACE INTO meta VALUES(?,?)",
                (RECEIPT_KEY, json.dumps(receipt, ensure_ascii=False)),
            )
            db.commit()
    # A transação no journal é autoritativa; nova tentativa recupera esta cópia
    # legível se o processo parar depois do commit e antes de exportar.
    save_private(
        Path(review["journal"]).parent / "compatibilidade_codigo_v1.json", receipt
    )
    return receipt
