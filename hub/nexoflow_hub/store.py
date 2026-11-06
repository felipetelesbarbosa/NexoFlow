"""Fila PostgreSQL com lease, fencing e commits atômicos por etapa."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .config import Settings
from .contracts import SCENARIOS


class Conflict(Exception):
    pass


class LostLease(Exception):
    pass


class Store:
    def __init__(self, settings: Settings):
        self.settings = settings

    def connect(self) -> psycopg.Connection[dict[str, Any]]:
        connection = cast(
            psycopg.Connection[dict[str, Any]],
            psycopg.connect(
                self.settings.dsn,
                connect_timeout=5,
                options="-c statement_timeout=5000 -c lock_timeout=3000",
            ),
        )
        connection.row_factory = dict_row
        return connection

    def migrate(self, *, down=False):
        with self.connect() as db:
            db.execute("SELECT pg_advisory_xact_lock(812631)")
            found = db.execute("SELECT to_regclass('hub.migracoes') AS t").fetchone()
            assert found is not None
            exists = found["t"]
            if down:
                if not exists:
                    return
                # A reversão de schema nunca descarta tarefas nem cobertura.
                count = db.execute(
                    "SELECT (SELECT count(*) FROM hub.tarefas)+(SELECT count(*) FROM hub.cobertura) AS n"
                ).fetchone()
                assert count is not None
                if count["n"]:
                    raise Conflict("ROLLBACK_COM_DADOS_BLOQUEADO")
            elif exists:
                versions = db.execute(
                    "SELECT versao FROM hub.migracoes ORDER BY versao"
                ).fetchall()
                if versions != [{"versao": 1}]:
                    raise Conflict("SCHEMA_INCOMPATIVEL")
                return
            path = (
                Path(__file__).resolve().parents[1]
                / "migrations"
                / ("001_down.sql" if down else "001_up.sql")
            )
            db.execute(path.read_bytes())

    def ready(self):
        with self.connect() as db:
            return db.execute("SELECT versao FROM hub.migracoes").fetchall() == [
                {"versao": 1}
            ]

    def create(self, segment, origin, key, scenario):
        if scenario not in SCENARIOS:
            raise ValueError("CENARIO_NAO_HABILITADO")
        digest = hashlib.sha256(
            json.dumps({"cenario": scenario}, sort_keys=True).encode()
        ).hexdigest()
        with self.connect() as db:
            row = db.execute(
                """INSERT INTO hub.tarefas(id,segmento,origem,chave,pedido_hash,cenario,estado)
                VALUES (%s,%s,%s,%s,%s,%s,'pendente') ON CONFLICT(segmento,origem,chave) DO NOTHING RETURNING *""",
                (uuid4(), segment, origin, key, digest, scenario),
            ).fetchone()
            if row is None:
                row = db.execute(
                    "SELECT * FROM hub.tarefas WHERE segmento=%s AND origem=%s AND chave=%s",
                    (segment, origin, key),
                ).fetchone()
                if row is None:
                    raise Conflict("TAREFA_AUSENTE")
                if row["pedido_hash"] != digest:
                    raise Conflict("IDEMPOTENCIA_CONFLITANTE")
            else:
                self.audit(db, row, "CRIADA")
            return row

    @staticmethod
    def audit(db, task, event):
        db.execute(
            "INSERT INTO hub.auditoria(segmento,tarefa_id,evento) VALUES(%s,%s,%s)",
            (task["segmento"], task["id"], event),
        )

    def get(self, segment, uid):
        with self.connect() as db:
            return db.execute(
                "SELECT * FROM hub.tarefas WHERE segmento=%s AND id=%s", (segment, uid)
            ).fetchone()

    def list(self, segment):
        with self.connect() as db:
            return db.execute(
                "SELECT * FROM hub.tarefas WHERE segmento=%s ORDER BY criada_em DESC LIMIT 100",
                (segment,),
            ).fetchall()

    def claim(self):
        with self.connect() as db:
            # Só uma eleição por segmento por transação; diferentes segmentos
            # continuam livres. SKIP LOCKED evita head-of-line entre workers.
            for segment in ("FARMA", "PET"):
                elected = db.execute(
                    "SELECT pg_try_advisory_xact_lock(%s) AS ok",
                    (812632 if segment == "FARMA" else 812633,),
                ).fetchone()
                assert elected is not None
                if not elected["ok"]:
                    continue
                guard = db.execute(
                    "SELECT lease_ate>clock_timestamp() AS ativo FROM hub.coordenacao WHERE segmento=%s FOR UPDATE",
                    (segment,),
                ).fetchone()
                if guard and guard["ativo"]:
                    continue
                task = db.execute(
                    """SELECT * FROM hub.tarefas WHERE segmento=%s AND
                    ((estado IN ('pendente','aguardando') AND disponivel_em<=clock_timestamp()) OR
                    (estado='executando' AND lease_ate<=clock_timestamp()))
                    ORDER BY criada_em FOR UPDATE SKIP LOCKED LIMIT 1""",
                    (segment,),
                ).fetchone()
                if not task:
                    continue
                if task["estado"] == "executando":
                    db.execute(
                        "UPDATE hub.tentativas SET estado='interrompida',terminada_em=clock_timestamp() WHERE tarefa_id=%s AND segmento=%s AND numero=%s",
                        (task["id"], segment, task["tentativa"]),
                    )
                if task["tentativa"] >= self.settings.max_attempts:
                    db.execute(
                        "UPDATE hub.tarefas SET estado='falhou',erro='TENTATIVAS_ESGOTADAS',dono=NULL,lease_ate=NULL WHERE id=%s",
                        (task["id"],),
                    )
                    self.audit(db, task, "TENTATIVAS_ESGOTADAS")
                    continue
                token = uuid4()
                task = db.execute(
                    """UPDATE hub.tarefas SET estado='executando',dono=%s,
                    lease_ate=clock_timestamp()+%s*interval '1 second',tentativa=tentativa+1,
                    atualizada_em=clock_timestamp(),erro=NULL WHERE id=%s RETURNING *""",
                    (token, self.settings.lease_seconds, task["id"]),
                ).fetchone()
                if task is None:
                    raise Conflict("TAREFA_AUSENTE")
                db.execute(
                    """INSERT INTO hub.coordenacao(segmento,tarefa_id,dono,lease_ate) VALUES(%s,%s,%s,%s)
                    ON CONFLICT(segmento) DO UPDATE SET tarefa_id=EXCLUDED.tarefa_id,dono=EXCLUDED.dono,lease_ate=EXCLUDED.lease_ate""",
                    (segment, task["id"], token, task["lease_ate"]),
                )
                db.execute(
                    "INSERT INTO hub.tentativas(segmento,tarefa_id,numero,dono,estado) VALUES(%s,%s,%s,%s,'executando')",
                    (segment, task["id"], task["tentativa"], token),
                )
                self.audit(db, task, "INICIADA")
                return task
        return None

    def fenced(self, db, task):
        guard = db.execute(
            "SELECT 1 FROM hub.coordenacao WHERE segmento=%s AND tarefa_id=%s AND dono=%s AND lease_ate>clock_timestamp() FOR UPDATE",
            (task["segmento"], task["id"], task["dono"]),
        ).fetchone()
        if not guard:
            raise LostLease("LEASE_PERDIDO")
        row = db.execute(
            """SELECT * FROM hub.tarefas WHERE id=%s AND segmento=%s AND dono=%s
            AND estado='executando' AND lease_ate>clock_timestamp() FOR UPDATE""",
            (task["id"], task["segmento"], task["dono"]),
        ).fetchone()
        if not row:
            raise LostLease("LEASE_PERDIDO")
        return row

    def checkpoints(self, task):
        with self.connect() as db:
            return {
                r["etapa"]: r["resultado"]
                for r in db.execute(
                    "SELECT etapa,resultado FROM hub.checkpoints WHERE segmento=%s AND tarefa_id=%s ORDER BY etapa",
                    (task["segmento"], task["id"]),
                )
            }

    def checkpoint(self, task, step, result):
        with self.connect() as db:
            self.fenced(db, task)
            prior = db.execute(
                "SELECT resultado FROM hub.checkpoints WHERE segmento=%s AND tarefa_id=%s AND etapa=%s",
                (task["segmento"], task["id"], step),
            ).fetchone()
            if prior and prior["resultado"] != result:
                raise Conflict("CHECKPOINT_CONFLITANTE")
            if not prior:
                db.execute(
                    "INSERT INTO hub.checkpoints(segmento,tarefa_id,etapa,resultado) VALUES(%s,%s,%s,%s)",
                    (task["segmento"], task["id"], step, Jsonb(result)),
                )
                self.audit(db, task, "ETAPA_CONFIRMADA")
            db.execute(
                "UPDATE hub.tarefas SET lease_ate=clock_timestamp()+%s*interval '1 second',atualizada_em=clock_timestamp() WHERE id=%s",
                (self.settings.lease_seconds, task["id"]),
            )
            db.execute(
                "UPDATE hub.coordenacao SET lease_ate=clock_timestamp()+%s*interval '1 second' WHERE segmento=%s AND dono=%s",
                (self.settings.lease_seconds, task["segmento"], task["dono"]),
            )

    def finish(self, task, state, *, result=None, error=None):
        if state not in {
            "concluida",
            "parcial",
            "aguardando",
            "falhou",
            "revisao_necessaria",
        }:
            raise ValueError("ESTADO_INVALIDO")
        allowed_errors = {
            None,
            "REDE_SIMULADA",
            "AUTENTICACAO_SIMULADA",
            "RESPOSTA_INCERTA",
            "FALHA_INTERNA",
            "TENTATIVAS_ESGOTADAS",
        }
        if error not in allowed_errors:
            raise ValueError("ERRO_NAO_SANITIZADO")
        with self.connect() as db:
            self.fenced(db, task)
            delay = min(60, 2 ** task["tentativa"])
            if (
                state == "aguardando"
                and task["tentativa"] >= self.settings.max_attempts
            ):
                state, error = "falhou", "TENTATIVAS_ESGOTADAS"
            db.execute(
                """UPDATE hub.tarefas SET estado=%s,resultado=%s,erro=%s,dono=NULL,lease_ate=NULL,
                atualizada_em=clock_timestamp(),disponivel_em=clock_timestamp()+%s*interval '1 second'
                WHERE id=%s AND segmento=%s""",
                (state, Jsonb(result), error, delay, task["id"], task["segmento"]),
            )
            db.execute(
                "UPDATE hub.tentativas SET estado=%s,terminada_em=clock_timestamp() WHERE tarefa_id=%s AND segmento=%s AND numero=%s",
                (state, task["id"], task["segmento"], task["tentativa"]),
            )
            db.execute(
                "DELETE FROM hub.coordenacao WHERE segmento=%s AND dono=%s",
                (task["segmento"], task["dono"]),
            )
            self.audit(db, task, state.upper())
