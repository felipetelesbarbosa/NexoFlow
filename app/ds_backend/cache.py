"""SQLite de trabalho reconstruído do servidor, sem ler o arquivo comercial local.

Triggers temporários capturam só linhas alteradas. A confirmação do lote remoto
precede o commit local. Nenhum payload SQLite é enviado à API de leitura.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

from ds_backend.contract import StorageError, record_key

SCHEMAS = json.loads(
    Path(__file__).with_name("cache_schema.json").read_text(encoding="utf-8-sig")
)
_TEMP = None
_STORE = None


def connect(store):
    global _TEMP, _STORE
    if _STORE is not store:
        if _TEMP is not None:
            _TEMP.cleanup()
        _TEMP = tempfile.TemporaryDirectory(prefix="nexoflow-pg-cache-")
        _STORE = store
        path = Path(_TEMP.name) / "observacoes.sqlite"
        with sqlite3.connect(path) as db:
            for name, spec in SCHEMAS.items():
                db.execute(spec["sql"])
                columns = ",".join('"' + c + '"' for c in spec["columns"])
                marks = ",".join("?" for _ in spec["columns"])
                for row in store.records("Cache_" + name):
                    db.execute(
                        'INSERT INTO "'
                        + name
                        + '"('
                        + columns
                        + ") VALUES("
                        + marks
                        + ")",
                        [
                            None if c in ("total", "pages") and row[c] == "" else row[c]
                            for c in spec["columns"]
                        ],
                    )
        path.chmod(0o600)
    if _TEMP is None:
        raise StorageError("DS_CACHE_INDISPONIVEL")
    db = sqlite3.connect(
        Path(_TEMP.name) / "observacoes.sqlite", factory=RemoteConnection, timeout=30
    )
    db.remote = store
    db.execute("CREATE TEMP TABLE nf_changes(t TEXT,k TEXT,v TEXT,PRIMARY KEY(t,k))")
    for name, spec in SCHEMAS.items():
        columns = spec["columns"]
        keys = spec["keys"]

        def encoded(prefix, fields):
            return (
                "json_object("
                + ",".join("'" + c + "'," + prefix + '."' + c + '"' for c in fields)
                + ")"
            )

        new = encoded("NEW", columns)
        newkey = encoded("NEW", keys)
        oldkey = encoded("OLD", keys)
        for event, code in [
            (
                "INSERT",
                f"INSERT OR REPLACE INTO nf_changes VALUES('{name}',{newkey},{new});",
            ),
            (
                "DELETE",
                f"INSERT OR REPLACE INTO nf_changes VALUES('{name}',{oldkey},NULL);",
            ),
            (
                "UPDATE",
                f"INSERT OR REPLACE INTO nf_changes VALUES('{name}',{oldkey},NULL);INSERT OR REPLACE INTO nf_changes VALUES('{name}',{newkey},{new});",
            ),
        ]:
            db.execute(
                f'CREATE TEMP TRIGGER nf_{name}_{event} AFTER {event} ON main."{name}" BEGIN {code} END'
            )
    return db


class RemoteConnection(sqlite3.Connection):
    remote = None

    def commit(self):
        if self.remote is None:
            return super().commit()
        for name in SCHEMAS:
            changes = self.execute(
                "SELECT k,v FROM nf_changes WHERE t=? ORDER BY k", (name,)
            ).fetchall()
            if not changes:
                continue
            records = []
            remove = []
            for key, value in changes:
                if value is None:
                    remove.append(record_key("Cache_" + name, json.loads(key)))
                else:
                    records.append(json.loads(value))
            self.remote._send("Cache_" + name, records, remove)
            self.remote._cache.pop("Cache_" + name, None)
        self.execute("DELETE FROM nf_changes")
        super().commit()

    def executescript(self, script):
        self.commit()
        return super().executescript(script)

    def __exit__(self, kind, value, traceback):
        if kind is None:
            try:
                self.commit()
            except BaseException:
                self.rollback()
                raise
        else:
            self.rollback()
        return False
