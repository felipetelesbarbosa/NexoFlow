"""Convites e concessões da Central, separados das credenciais e dos dados comerciais."""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path
from time import time
from uuid import uuid4

from fastapi import HTTPException

INVITE_TTL = 7 * 24 * 60 * 60


@contextmanager
def registry(path: Path):
    try:
        with closing(sqlite3.connect(path, timeout=3)) as db, db:
            db.row_factory = sqlite3.Row
            db.execute(
                """CREATE TABLE IF NOT EXISTS central_members (
                       subject TEXT PRIMARY KEY, email TEXT, scopes TEXT NOT NULL,
                       revoked INTEGER NOT NULL DEFAULT 0
                   )"""
            )
            db.execute(
                """CREATE TABLE IF NOT EXISTS central_invites (
                       id TEXT PRIMARY KEY, digest TEXT NOT NULL UNIQUE,
                       email TEXT NOT NULL, scopes TEXT NOT NULL, expires_at INTEGER NOT NULL,
                       status TEXT NOT NULL DEFAULT 'pendente'
                   )"""
            )
            db.execute(
                """CREATE TABLE IF NOT EXISTS central_access_audit (
                       actor TEXT NOT NULL, action TEXT NOT NULL, reference TEXT NOT NULL,
                       registered_at INTEGER NOT NULL
                   )"""
            )
            yield db
    except sqlite3.Error:
        raise HTTPException(503, "GESTAO_DE_ACESSO_INDISPONIVEL") from None


def member(path: Path, subject: str):
    with registry(path) as db:
        return db.execute(
            "SELECT scopes, revoked FROM central_members WHERE subject = ?", (subject,)
        ).fetchone()


def overview(path: Path, legacy: dict[str, list[str]], admin: str):
    with registry(path) as db:
        managed = {
            row["subject"]: row
            for row in db.execute(
                "SELECT subject, email, scopes, revoked FROM central_members"
            )
        }
        users = [
            {
                "id": subject,
                "email": managed[subject]["email"] if subject in managed else None,
                "segmentos": json.loads(managed[subject]["scopes"])
                if subject in managed
                else legacy[subject],
                "super_admin": subject == admin,
            }
            for subject in sorted(legacy.keys() | managed.keys())
            if subject not in managed or not managed[subject]["revoked"]
        ]
        invites = [
            {**dict(row), "segmentos": json.loads(row["segmentos"])}
            for row in db.execute(
                """SELECT id, email, scopes AS segmentos, expires_at AS expira_em,
                          CASE WHEN status = 'pendente' AND expires_at <= ? THEN 'expirado'
                               ELSE status END AS estado
                   FROM central_invites ORDER BY rowid DESC LIMIT 100""",
                (int(time()),),
            )
        ]
    return {"usuarios": users, "convites": invites}


def audit(db, actor: str, action: str, reference: str, now: int) -> None:
    db.execute(
        "INSERT INTO central_access_audit VALUES (?, ?, ?, ?)",
        (actor, action, reference, now),
    )


def invite(path: Path, actor: str, email: str, scopes: list[str]):
    now = int(time())
    token = secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode("ascii")).hexdigest()
    invite_id = str(uuid4())
    with registry(path) as db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute(
            "SELECT 1 FROM central_members WHERE email = ? AND revoked = 0", (email,)
        ).fetchone():
            raise HTTPException(409, "EMAIL_JA_TEM_ACESSO")
        if db.execute(
            """SELECT 1 FROM central_invites
               WHERE email = ? AND status = 'pendente' AND expires_at > ?""",
            (email, now),
        ).fetchone():
            raise HTTPException(409, "CONVITE_JA_PENDENTE")
        db.execute(
            "INSERT INTO central_invites (id,digest,email,scopes,expires_at) VALUES (?,?,?,?,?)",
            (invite_id, digest, email, json.dumps(scopes), now + INVITE_TTL),
        )
        audit(db, actor, "convite_criado", invite_id, now)
    return {"id": invite_id, "codigo": token, "expira_em": now + INVITE_TTL}


def accept(path: Path, subject: str, email: str, token: str, has_legacy_access: bool):
    now = int(time())
    digest = hashlib.sha256(token.encode("ascii")).hexdigest()
    with registry(path) as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            """SELECT id, scopes FROM central_invites
               WHERE digest = ? AND email = ? AND status = 'pendente' AND expires_at > ?""",
            (digest, email.casefold(), now),
        ).fetchone()
        if row is None:
            raise HTTPException(403, "CONVITE_INVALIDO_OU_INDISPONIVEL")
        existing = db.execute(
            "SELECT revoked FROM central_members WHERE subject = ?", (subject,)
        ).fetchone()
        if (existing is None and has_legacy_access) or (
            existing and not existing["revoked"]
        ):
            raise HTTPException(409, "OPERADOR_JA_TEM_ACESSO")
        db.execute(
            """INSERT INTO central_members (subject,email,scopes) VALUES (?,?,?)
               ON CONFLICT(subject) DO UPDATE
               SET email = excluded.email, scopes = excluded.scopes, revoked = 0""",
            (subject, email.casefold(), row["scopes"]),
        )
        db.execute(
            "UPDATE central_invites SET status = 'aceito' WHERE id = ?", (row["id"],)
        )
        audit(db, subject, "convite_aceito", row["id"], now)


def cancel(path: Path, actor: str, invite_id: str):
    now = int(time())
    with registry(path) as db:
        count = db.execute(
            """UPDATE central_invites SET status = 'cancelado'
               WHERE id = ? AND status = 'pendente' AND expires_at > ?""",
            (invite_id, now),
        ).rowcount
        if not count:
            raise HTTPException(404, "CONVITE_PENDENTE_NAO_ENCONTRADO")
        audit(db, actor, "convite_cancelado", invite_id, now)


def revoke(path: Path, actor: str, subject: str, has_legacy_access: bool):
    if subject == actor:
        raise HTTPException(409, "SUPER_ADMIN_NAO_PODE_REMOVER_O_PROPRIO_ACESSO")
    with registry(path) as db:
        db.execute("BEGIN IMMEDIATE")
        count = db.execute(
            "UPDATE central_members SET revoked = 1 WHERE subject = ? AND revoked = 0",
            (subject,),
        ).rowcount
        if not count:
            if not has_legacy_access:
                raise HTTPException(404, "OPERADOR_NAO_ENCONTRADO")
            count = db.execute(
                "INSERT INTO central_members (subject,scopes,revoked) VALUES (?, '[]', 1) "
                "ON CONFLICT(subject) DO NOTHING",
                (subject,),
            ).rowcount
        if count:
            audit(db, actor, "acesso_revogado", subject, int(time()))
