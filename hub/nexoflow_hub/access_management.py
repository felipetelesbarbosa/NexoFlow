"""Convites e concessões da Central, separados das credenciais e dos dados comerciais."""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path
from time import time
from typing import Literal
from uuid import uuid4

from fastapi import HTTPException

INVITE_TTL = 7 * 24 * 60 * 60
Role = Literal["convidado", "admin"]


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
            # Aditivo: o volume existente, os convites e as revogações não
            # precisam ser regravados. Nenhum papel pode criar um Super Admin.
            db.execute(
                """CREATE TABLE IF NOT EXISTS central_roles (
                       subject TEXT PRIMARY KEY,
                       role TEXT NOT NULL CHECK(role IN ('convidado', 'admin'))
                   )"""
            )
            db.execute(
                """CREATE TABLE IF NOT EXISTS central_invite_roles (
                       invite_id TEXT PRIMARY KEY,
                       role TEXT NOT NULL CHECK(role IN ('convidado', 'admin'))
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


def assigned_role(path: Path, subject: str):
    with registry(path) as db:
        row = db.execute(
            "SELECT role FROM central_roles WHERE subject = ?", (subject,)
        ).fetchone()
        return row["role"] if row is not None else None


def overview(
    path: Path, legacy: dict[str, list[str]], admin: str,
    legacy_admins: set[str] | None = None,
):
    with registry(path) as db:
        managed = {
            row["subject"]: row
            for row in db.execute(
                "SELECT subject, email, scopes, revoked FROM central_members"
            )
        }
        roles = {
            row["subject"]: row["role"]
            for row in db.execute("SELECT subject, role FROM central_roles")
        }
        users = [
            {
                "id": subject,
                "email": managed[subject]["email"] if subject in managed else None,
                "segmentos": json.loads(managed[subject]["scopes"])
                if subject in managed
                else legacy[subject],
                "super_admin": subject == admin,
                "papel": "super_admin" if subject == admin else roles.get(
                    subject, "admin" if subject in (legacy_admins or set()) else "convidado"
                ),
            }
            for subject in sorted(legacy.keys() | managed.keys())
            if subject not in managed or not managed[subject]["revoked"]
        ]
        invites = [
            {**dict(row), "segmentos": json.loads(row["segmentos"])}
            for row in db.execute(
                """SELECT central_invites.id, email, scopes AS segmentos, expires_at AS expira_em,
                          COALESCE(central_invite_roles.role, 'convidado') AS papel,
                          CASE WHEN status = 'pendente' AND expires_at <= ? THEN 'expirado'
                               ELSE status END AS estado
                   FROM central_invites
                   LEFT JOIN central_invite_roles ON central_invite_roles.invite_id = central_invites.id
                   ORDER BY central_invites.rowid DESC LIMIT 100""",
                (int(time()),),
            )
        ]
    return {"usuarios": users, "convites": invites}


def audit(db, actor: str, action: str, reference: str, now: int) -> None:
    db.execute(
        "INSERT INTO central_access_audit VALUES (?, ?, ?, ?)",
        (actor, action, reference, now),
    )


def invite(path: Path, actor: str, email: str, scopes: list[str], role: Role = "convidado"):
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
        db.execute(
            "INSERT INTO central_invite_roles VALUES (?,?)", (invite_id, role)
        )
        audit(db, actor, "convite_criado", invite_id, now)
    return {"id": invite_id, "codigo": token, "expira_em": now + INVITE_TTL}


def accept(path: Path, subject: str, email: str, token: str, has_legacy_access: bool):
    now = int(time())
    digest = hashlib.sha256(token.encode("ascii")).hexdigest()
    with registry(path) as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            """SELECT central_invites.id, scopes,
                      COALESCE(central_invite_roles.role, 'convidado') AS role
               FROM central_invites
               LEFT JOIN central_invite_roles ON central_invite_roles.invite_id = central_invites.id
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
        db.execute(
            """INSERT INTO central_roles (subject,role) VALUES (?,?)
               ON CONFLICT(subject) DO UPDATE SET role = excluded.role""",
            (subject, row["role"]),
        )
        audit(db, subject, "convite_aceito", row["id"], now)


def set_role(path: Path, actor: str, subject: str, role: Role, has_legacy_access: bool):
    if subject == actor:
        raise HTTPException(409, "PAPEL_SUPER_ADMIN_IMUTAVEL")
    with registry(path) as db:
        db.execute("BEGIN IMMEDIATE")
        current = db.execute(
            "SELECT revoked FROM central_members WHERE subject = ?", (subject,)
        ).fetchone()
        if (current is not None and current["revoked"]) or (
            current is None and not has_legacy_access
        ):
            raise HTTPException(404, "OPERADOR_NAO_ENCONTRADO")
        db.execute(
            """INSERT INTO central_roles (subject,role) VALUES (?,?)
               ON CONFLICT(subject) DO UPDATE SET role = excluded.role""",
            (subject, role),
        )
        audit(db, actor, "papel_" + role, subject, int(time()))


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
