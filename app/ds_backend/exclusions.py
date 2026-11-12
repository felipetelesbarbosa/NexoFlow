"""Extrai exclusões da cópia exata vinculada à revisão READY, sem alterá-la."""

from __future__ import annotations

import json
from pathlib import Path

from ds_backend.contract import StorageError
from ds_backend.migration import private_json


def extract(review_path, sqlite_path, segment, revision, output):
    from history_exclusions import AUDIT_TABLE
    from history_snapshot import readonly, sha256
    from order_history import financial_record_digest

    review = json.loads(Path(review_path).read_text(encoding="utf-8-sig"))
    from order_history import digest as legacy_digest

    unsigned = dict(review)
    checksum = unsigned.pop("digest", None)
    if checksum != legacy_digest(unsigned) or review.get("segment") != segment:
        raise StorageError("DS_REVISAO_PUBLICADA_ALTERADA")
    source = review.get("evidence", {})
    expected = source.get("sha256")
    if (
        review.get("revision") != revision
        or not isinstance(expected, str)
        or sha256(sqlite_path) != expected
    ):
        raise StorageError("DS_REVISAO_SQLITE_DIVERGENTE")
    rows = []
    with readonly(sqlite_path, segment) as history:
        exists = history.db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (AUDIT_TABLE,)
        ).fetchone()
        if exists:
            for seg, oid, reason, by, at, original_sha, raw in history.db.execute(
                f"SELECT segment,id,reason,authorized_by,applied_at,source_sha256,original_row_json FROM {AUDIT_TABLE} ORDER BY id"
            ):
                if seg != segment:
                    raise StorageError("DS_SEGMENTO_DIVERGENTE")
                original = json.loads(json.loads(raw)[3])
                if original.get("id") != oid or original.get("segment") != segment:
                    raise StorageError("DS_EXCLUSAO_ORIGEM_DIVERGENTE")
                rows.append(
                    dict(
                        segmento=seg,
                        pedido_id=oid,
                        motivo=reason,
                        responsavel=by,
                        aplicado_em_utc=at,
                        fonte_sha256=original_sha,
                        original_sha256=financial_record_digest(original),
                    )
                )
    if sha256(sqlite_path) != expected:
        raise StorageError("DS_SQLITE_ORIGINAL_ALTERADO")
    result = dict(segment=segment, revision=revision, source_sha256=expected, rows=rows)
    private_json(output, result)
    return dict(state="CONFERIDA", exclusions=len(rows))
