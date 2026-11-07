"""Cópia SQLite consistente com WAL; evidência original aberta só para leitura."""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from order_history import HistoryError
from order_history_store import HistoryStore


def sha256(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


@contextmanager
def readonly(path, segment):
    with closing(
        sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    ) as db:
        db.execute("PRAGMA query_only=ON")
        if db.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise HistoryError("SQLITE_INTEGRIDADE_INVALIDA")
        names = {
            r[0]
            for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if "profile" not in names:
            raise HistoryError("PERFIL_SQLITE_NAO_COMPROVADO")
        profiles = db.execute("SELECT segment FROM profile").fetchall()
        if profiles != [(segment,)]:
            raise HistoryError("SQLITE_DE_OUTRO_SEGMENTO")
        required = {
            "history_orders": {"segment", "id", "owner", "record"},
            "history_windows": {"key", "segment", "start", "end", "status"},
            "history_seen": {"window_key", "id"},
            "history_issues": {"segment", "id", "reason"},
            "history_revisions": {"segment", "id"},
        }
        for table, columns in required.items():
            present = {r[1] for r in db.execute(f"PRAGMA table_info({table})")}
            if not columns <= present:
                raise HistoryError("SQLITE_SCHEMA_HISTORICO_INCOMPATIVEL")
        for table in (
            "history_orders",
            "history_windows",
            "history_issues",
            "history_revisions",
        ):
            if db.execute(
                f"SELECT count(*) FROM {table} WHERE segment!=? OR segment IS NULL",
                (segment,),
            ).fetchone()[0]:
                raise HistoryError("SQLITE_COM_SEGMENTOS_MISTURADOS")
        store = object.__new__(HistoryStore)
        store.db, store.segment, store.active_run = db, segment, None
        yield store


def snapshot(source, directory, segment) -> dict[str, Any]:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = directory / (uuid4().hex + ".sqlite")
    with readonly(source, segment) as original:
        with closing(sqlite3.connect(target)) as copy:
            original.db.backup(copy, pages=2048)
    target.chmod(0o600)
    with readonly(target, segment):
        pass
    return dict(
        path=str(target.resolve()), sha256=sha256(target), bytes=target.stat().st_size
    )
