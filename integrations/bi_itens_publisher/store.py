"""Transações PostgreSQL exclusivas do piloto; sem SQL dinâmico de destino."""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from bi_postgres_contract import (
    BUSINESS_COLUMNS,
    COLUMNS,
    PROTOCOL,
    TARGET,
    PublicationError,
    digest,
    uid,
    validate_payload,
)

COLS = ",".join(COLUMNS)
COMPARE = (
    "ROW("
    + ",".join("t." + c for c in BUSINESS_COLUMNS)
    + ") IS DISTINCT FROM ROW("
    + ",".join("s." + c for c in BUSINESS_COLUMNS)
    + ")"
)


class Store:
    def __init__(
        self,
        dsn: str,
        publisher: str = "windows-farma",
        *,
        require_dedicated_role=False,
    ):
        self.dsn, self.publisher = dsn, publisher
        self.require_dedicated_role = require_dedicated_role

    def connect(self):
        # Limites locais da transação; nunca alterar timeouts globais do servidor.
        return psycopg.connect(
            self.dsn,
            row_factory=dict_row,
            connect_timeout=10,
            options="-c statement_timeout=60000 -c lock_timeout=10000",
        )

    def check(self, conn):
        if (
            conn.execute("SELECT current_database() AS name").fetchone()["name"]
            != "nexoflow_datastudio_piloto"
        ):
            raise PublicationError("BI_PG_BANCO_DIVERGENTE")
        if self.require_dedicated_role:
            role = conn.execute(
                "SELECT rolname,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=current_user"
            ).fetchone()
            if role["rolname"] != "nf_bi_itens_publisher" or any(
                role[k]
                for k in (
                    "rolsuper",
                    "rolcreatedb",
                    "rolcreaterole",
                    "rolreplication",
                    "rolbypassrls",
                )
            ):
                raise PublicationError("BI_PG_PRIVILEGIOS_EXCESSIVOS")
        columns = conn.execute(
            "SELECT column_name,data_type FROM information_schema.columns WHERE table_schema='farma' AND table_name='bi_itens' ORDER BY ordinal_position"
        ).fetchall()
        types = {r["column_name"]: r["data_type"] for r in columns}
        if (
            set(types) != set(COLUMNS)
            or any(
                types[c] not in {"text", "character varying"}
                for c in (
                    "item_chave",
                    "venda_chave",
                    "cliente_chave",
                    "produto_codigo",
                    "produto_nome",
                    "categoria",
                )
            )
            or any(
                types[c] != "numeric"
                for c in ("quantidade", "valor_unitario", "receita_item")
            )
            or types["data"] != "date"
            or types["sku_informado"] not in {"integer", "smallint", "bigint"}
            or types["atualizado_em"] not in {"text", "timestamp with time zone"}
        ):
            raise PublicationError("BI_PG_SCHEMA_DIVERGENTE")
        unsafe = conn.execute(
            "SELECT 1 FROM pg_class WHERE oid='farma.bi_itens'::regclass AND (relrowsecurity OR relforcerowsecurity OR relkind<>'r')"
        ).fetchone()
        triggers = conn.execute(
            "SELECT 1 FROM pg_trigger WHERE tgrelid='farma.bi_itens'::regclass AND NOT tgisinternal AND tgenabled<>'D' LIMIT 1"
        ).fetchone()
        references = conn.execute(
            "SELECT 1 FROM pg_constraint WHERE contype='f' AND (conrelid='farma.bi_itens'::regclass OR confrelid='farma.bi_itens'::regclass) LIMIT 1"
        ).fetchone()
        if unsafe or triggers or references:
            raise PublicationError("BI_PG_ESTRUTURA_EXIGE_REVISAO")
        primary = conn.execute(
            "SELECT a.attname FROM pg_index i JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=ANY(i.indkey) WHERE i.indrelid='farma.bi_itens'::regclass AND i.indisprimary ORDER BY a.attnum"
        ).fetchall()
        if [r["attname"] for r in primary] != ["item_chave"]:
            raise PublicationError("BI_PG_CHAVE_PRIMARIA_DIVERGENTE")

    def session(self, identifier):
        identifier = uid(identifier)
        with self.connect() as conn:
            self.check(conn)
            conn.execute(
                "INSERT INTO nexoflow_publicacao.sessions(id,publisher) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                (identifier, self.publisher),
            )
            row = conn.execute(
                "SELECT id,revision,publisher FROM nexoflow_publicacao.sessions WHERE id=%s",
                (identifier,),
            ).fetchone()
            if row["publisher"] != self.publisher:
                raise PublicationError("BI_PG_PROPRIETARIO_DIVERGENTE")
            return {
                "session_id": str(row["id"]),
                "revision": row["revision"],
                "target": TARGET,
                "protocol": PROTOCOL,
            }

    def plan(self, session_id, manifest, complete):
        session_id = uid(session_id)
        if (
            type(complete) is not bool
            or not isinstance(manifest, list)
            or not manifest
            or len(manifest) > 5000
        ):
            raise PublicationError("BI_PG_PLANO_INVALIDO")
        checked = []
        for entry in manifest:
            if (
                not isinstance(entry, dict)
                or set(entry) != {"batch_id", "digest"}
                or not isinstance(entry["digest"], str)
                or not re.fullmatch("[0-9a-f]{64}", entry["digest"])
            ):
                raise PublicationError("BI_PG_PLANO_INVALIDO")
            checked.append(
                {"batch_id": uid(entry["batch_id"]), "digest": entry["digest"]}
            )
        if len({e["batch_id"] for e in checked}) != len(checked):
            raise PublicationError("BI_PG_PLANO_DUPLICADO")
        checked.sort(key=lambda e: e["batch_id"])
        fingerprint = digest({"manifest": checked, "complete": complete})
        with self.connect() as conn:
            self.check(conn)
            conn.execute("SELECT pg_advisory_xact_lock(734263518)")
            session = conn.execute(
                "SELECT revision,publisher FROM nexoflow_publicacao.sessions WHERE id=%s",
                (session_id,),
            ).fetchone()
            if not session or session["publisher"] != self.publisher:
                raise PublicationError("BI_PG_SESSAO_INVALIDA")
            old = conn.execute(
                "SELECT digest,state FROM nexoflow_publicacao.plans WHERE session_id=%s",
                (session_id,),
            ).fetchone()
            if old:
                if old["state"] == "REVERTIDO":
                    raise PublicationError("BI_PG_PLANO_REVERTIDO")
                if old["digest"] != fingerprint:
                    raise PublicationError("BI_PG_PLANO_DIVERGENTE")
                return {
                    "session_id": session_id,
                    "state": old["state"],
                    "digest": fingerprint,
                }
            watermark = conn.execute(
                "SELECT revision FROM nexoflow_publicacao.watermark WHERE singleton"
            ).fetchone()["revision"]
            if session["revision"] < watermark:
                raise PublicationError("BI_PG_LOTE_ANTIGO")
            if conn.execute(
                "SELECT 1 FROM nexoflow_publicacao.plans WHERE state='WRITING' LIMIT 1"
            ).fetchone():
                raise PublicationError("BI_PG_PUBLICACAO_PENDENTE")
            conn.execute(
                "INSERT INTO nexoflow_publicacao.plans VALUES(%s,%s,%s,%s,'WRITING')",
                (session_id, fingerprint, Jsonb(checked), complete),
            )
            return {"session_id": session_id, "state": "WRITING", "digest": fingerprint}

    def plan_status(self, identifier):
        identifier = uid(identifier)
        with self.connect() as conn:
            self.check(conn)
            row = conn.execute(
                """SELECT s.revision,coalesce(p.state,'RESERVADA') AS state,w.revision AS watermark
              FROM nexoflow_publicacao.sessions s LEFT JOIN nexoflow_publicacao.plans p ON p.session_id=s.id
              CROSS JOIN nexoflow_publicacao.watermark w WHERE s.id=%s AND s.publisher=%s""",
                (identifier, self.publisher),
            ).fetchone()
            if not row:
                raise PublicationError("BI_PG_SESSAO_INVALIDA")
            return {
                "protocol": PROTOCOL,
                "target": TARGET,
                "session_id": identifier,
                **row,
            }

    def receipt(self, identifier):
        with self.connect() as conn:
            self.check(conn)
            row = conn.execute(
                "SELECT b.receipt,b.reverted FROM nexoflow_publicacao.batches b JOIN nexoflow_publicacao.sessions s ON s.id=b.session_id WHERE b.id=%s AND s.publisher=%s",
                (uid(identifier), self.publisher),
            ).fetchone()
            if row is None:
                return None
            if row["reverted"]:
                raise PublicationError("BI_PG_LOTE_REVERTIDO")
            return row["receipt"]

    def apply(self, raw, *, simulate=False):
        payload = validate_payload(raw)
        fingerprint = digest(payload)
        with self.connect() as conn:
            self.check(conn)
            # Um único escritor lógico; inclui sessão/tombstones e lotes vazios.
            conn.execute("SELECT pg_advisory_xact_lock(734263518)")
            revision = 0
            if not simulate:
                old = conn.execute(
                    "SELECT digest,receipt,reverted FROM nexoflow_publicacao.batches WHERE id=%s",
                    (payload["batch_id"],),
                ).fetchone()
                if old:
                    if old["digest"] != fingerprint or old["reverted"]:
                        raise PublicationError("BI_PG_LOTE_DIVERGENTE_OU_REVERTIDO")
                    return old["receipt"]
                plan = conn.execute(
                    "SELECT manifest,complete,state FROM nexoflow_publicacao.plans WHERE session_id=%s",
                    (payload["session_id"],),
                ).fetchone()
                if (
                    not plan
                    or plan["state"] == "REVERTIDO"
                    or plan["complete"] != payload["complete"]
                    or {"batch_id": payload["batch_id"], "digest": fingerprint}
                    not in plan["manifest"]
                ):
                    raise PublicationError("BI_PG_LOTE_FORA_PLANO")
                session = conn.execute(
                    "SELECT revision,publisher FROM nexoflow_publicacao.sessions WHERE id=%s",
                    (payload["session_id"],),
                ).fetchone()
                if not session or session["publisher"] != self.publisher:
                    raise PublicationError("BI_PG_SESSAO_INVALIDA")
                revision = session["revision"]
                watermark = conn.execute(
                    "SELECT revision FROM nexoflow_publicacao.watermark WHERE singleton FOR UPDATE"
                ).fetchone()["revision"]
                if revision < watermark:
                    raise PublicationError("BI_PG_LOTE_ANTIGO")
            conn.execute(
                "CREATE TEMP TABLE nf_itens_stage (LIKE farma.bi_itens) ON COMMIT DROP"
            )
            with conn.cursor().copy(f"COPY nf_itens_stage ({COLS}) FROM STDIN") as copy:
                for row in payload["rows"]:
                    copy.write_row([row[c] for c in COLUMNS])
            expected = {r["item_chave"]: r for r in payload["rows"]}
            for staged in conn.execute(
                "SELECT item_chave,quantidade,valor_unitario,receita_item FROM nf_itens_stage"
            ):
                if any(
                    staged[c] != Decimal(expected[staged["item_chave"]][c])
                    for c in ("quantidade", "valor_unitario", "receita_item")
                ):
                    raise PublicationError("BI_PG_PRECISAO_DIVERGENTE")
            collision = conn.execute(
                "SELECT 1 FROM nf_itens_stage s JOIN farma.bi_itens t USING(item_chave) WHERE t.venda_chave<>s.venda_chave LIMIT 1"
            ).fetchone()
            if collision:
                raise PublicationError("BI_PG_ITEM_TROCOU_DE_PEDIDO")
            counts = conn.execute(f"""SELECT count(*) FILTER(WHERE t.item_chave IS NULL)::int AS inseridos,
             count(*) FILTER(WHERE t.item_chave IS NOT NULL AND {COMPARE})::int AS atualizados,
             count(*) FILTER(WHERE t.item_chave IS NOT NULL AND NOT ({COMPARE}))::int AS mantidos
             FROM nf_itens_stage s LEFT JOIN farma.bi_itens t USING(item_chave)""").fetchone()
            removed = conn.execute(
                "SELECT count(*)::int AS n FROM farma.bi_itens t WHERE t.venda_chave=ANY(%s) AND NOT EXISTS(SELECT 1 FROM nf_itens_stage s WHERE s.item_chave=t.item_chave)",
                (payload["sales"],),
            ).fetchone()["n"]
            receipt = {
                "protocol": PROTOCOL,
                "target": TARGET,
                "batch_id": payload["batch_id"],
                "session_id": payload["session_id"],
                "revision": revision,
                "digest": fingerprint,
                "confirmed": not simulate,
                "state": "SIMULADO" if simulate else "CONFIRMADO",
                "complete": payload["complete"],
                **counts,
                "removidos": removed if payload["complete"] else 0,
                "remocoes_bloqueadas": removed if not payload["complete"] else 0,
            }
            if simulate:
                # TEMP e COPY também são revertidos: nenhum registro durável foi escrito.
                conn.rollback()
                return receipt
            conn.execute(
                "INSERT INTO nexoflow_publicacao.batches(id,session_id,digest,receipt) VALUES(%s,%s,%s,%s)",
                (
                    payload["batch_id"],
                    payload["session_id"],
                    fingerprint,
                    Jsonb(receipt),
                ),
            )
            overlap = conn.execute(
                "SELECT 1 FROM nexoflow_publicacao.sale_batches WHERE session_id=%s AND venda_chave=ANY(%s) LIMIT 1",
                (payload["session_id"], payload["sales"]),
            ).fetchone()
            if overlap:
                raise PublicationError("BI_PG_ESCOPO_REUTILIZADO")
            for sale in payload["sales"]:
                conn.execute(
                    "INSERT INTO nexoflow_publicacao.sale_batches VALUES(%s,%s,%s)",
                    (payload["session_id"], sale, payload["batch_id"]),
                )
            conn.execute(
                f"""INSERT INTO nexoflow_publicacao.changes(batch_id,item_chave,previous,applied)
              SELECT %s,coalesce(s.item_chave,t.item_chave),CASE WHEN t.item_chave IS NULL THEN NULL ELSE to_jsonb(t) END,
              CASE WHEN s.item_chave IS NULL THEN NULL ELSE to_jsonb(s) END
              FROM nf_itens_stage s FULL JOIN
              (SELECT * FROM farma.bi_itens WHERE venda_chave=ANY(%s)
               OR item_chave IN(SELECT item_chave FROM nf_itens_stage)) t USING(item_chave)
              WHERE (s.item_chave IS NOT NULL AND (t.item_chave IS NULL OR {COMPARE}))
              OR (s.item_chave IS NULL AND %s AND t.venda_chave=ANY(%s))""",
                (
                    payload["batch_id"],
                    payload["sales"],
                    payload["complete"],
                    payload["sales"],
                ),
            )
            assignments = ",".join(
                c + "=EXCLUDED." + c for c in COLUMNS if c != "item_chave"
            )
            compare_upsert = COMPARE.replace("s.", "EXCLUDED.")
            conn.execute(
                f"INSERT INTO farma.bi_itens AS t ({COLS}) SELECT {COLS} FROM nf_itens_stage ON CONFLICT(item_chave) DO UPDATE SET {assignments} WHERE {compare_upsert}"
            )
            if payload["complete"]:
                conn.execute(
                    "DELETE FROM farma.bi_itens t WHERE t.venda_chave=ANY(%s) AND NOT EXISTS(SELECT 1 FROM nf_itens_stage s WHERE s.item_chave=t.item_chave)",
                    (payload["sales"],),
                )
            mismatch = conn.execute(
                """SELECT 1 FROM nexoflow_publicacao.changes c LEFT JOIN farma.bi_itens t USING(item_chave)
                WHERE c.batch_id=%s AND c.applied IS DISTINCT FROM CASE WHEN t.item_chave IS NULL THEN NULL ELSE to_jsonb(t) END LIMIT 1""",
                (payload["batch_id"],),
            ).fetchone()
            if mismatch:
                raise PublicationError("BI_PG_CONFERENCIA_POS_GRAVACAO")
            conn.execute(
                "UPDATE nexoflow_publicacao.watermark SET revision=%s WHERE singleton",
                (revision,),
            )
            total = conn.execute(
                "SELECT count(*)::int AS n FROM nexoflow_publicacao.batches WHERE session_id=%s AND NOT reverted",
                (payload["session_id"],),
            ).fetchone()["n"]
            if total == len(plan["manifest"]):
                conn.execute(
                    "UPDATE nexoflow_publicacao.plans SET state=%s WHERE session_id=%s",
                    (
                        "READY" if payload["complete"] else "PARCIAL",
                        payload["session_id"],
                    ),
                )
            # O contexto psycopg só entrega o resultado ao chamador após COMMIT.
            return receipt

    def close_plan(self, identifier):
        """Encerra apenas plano sem lotes aplicados ou com todos revertidos."""
        identifier = uid(identifier)
        with self.connect() as conn:
            self.check(conn)
            conn.execute("SELECT pg_advisory_xact_lock(734263518)")
            if conn.execute(
                "SELECT 1 FROM nexoflow_publicacao.batches WHERE session_id=%s AND NOT reverted LIMIT 1",
                (identifier,),
            ).fetchone():
                raise PublicationError("BI_PG_PLANO_TEM_LOTES_APLICADOS")
            if not conn.execute(
                "SELECT 1 FROM nexoflow_publicacao.plans WHERE session_id=%s",
                (identifier,),
            ).fetchone():
                raise PublicationError("BI_PG_PLANO_AUSENTE")
            conn.execute(
                "UPDATE nexoflow_publicacao.plans SET state='REVERTIDO' WHERE session_id=%s",
                (identifier,),
            )
            revision = conn.execute(
                "INSERT INTO nexoflow_publicacao.sessions(id,publisher) VALUES(gen_random_uuid(),'encerramento-local') RETURNING revision"
            ).fetchone()["revision"]
            conn.execute(
                "UPDATE nexoflow_publicacao.watermark SET revision=%s WHERE singleton",
                (revision,),
            )
            return {"state": "REVERTIDO", "fatos_alterados": 0}

    def rollback(self, identifier):
        """Somente ferramenta administrativa local; não é rota da API Windows."""
        identifier = uid(identifier)
        with self.connect() as conn:
            self.check(conn)
            conn.execute("SELECT pg_advisory_xact_lock(734263518)")
            batch = conn.execute(
                "SELECT reverted,session_id FROM nexoflow_publicacao.batches WHERE id=%s FOR UPDATE",
                (identifier,),
            ).fetchone()
            if not batch:
                raise PublicationError("BI_PG_LOTE_AUSENTE")
            if batch["reverted"]:
                return {"state": "REVERTIDO", "alteracoes": 0}
            conflict = conn.execute(
                """SELECT 1 FROM nexoflow_publicacao.changes c LEFT JOIN farma.bi_itens t USING(item_chave)
               WHERE c.batch_id=%s AND c.applied IS DISTINCT FROM CASE WHEN t.item_chave IS NULL THEN NULL ELSE to_jsonb(t) END LIMIT 1""",
                (identifier,),
            ).fetchone()
            if conflict:
                raise PublicationError("BI_PG_EDICAO_POSTERIOR")
            conn.execute(
                "DELETE FROM farma.bi_itens t USING nexoflow_publicacao.changes c WHERE c.batch_id=%s AND t.item_chave=c.item_chave",
                (identifier,),
            )
            conn.execute(
                f"""INSERT INTO farma.bi_itens ({COLS}) SELECT {",".join("r." + c for c in COLUMNS)}
              FROM nexoflow_publicacao.changes c CROSS JOIN LATERAL jsonb_populate_record(NULL::farma.bi_itens,c.previous) r
              WHERE c.batch_id=%s AND c.previous IS NOT NULL""",
                (identifier,),
            )
            conn.execute(
                "UPDATE nexoflow_publicacao.batches SET reverted=true WHERE id=%s",
                (identifier,),
            )
            conn.execute(
                "UPDATE nexoflow_publicacao.plans SET state='REVERTIDO' WHERE session_id=%s",
                (batch["session_id"],),
            )
            # Fence também avança para impedir reaplicação por uma sessão antiga.
            row = conn.execute(
                "INSERT INTO nexoflow_publicacao.sessions(id,publisher) VALUES(gen_random_uuid(),'rollback-local') RETURNING revision"
            ).fetchone()
            conn.execute(
                "UPDATE nexoflow_publicacao.watermark SET revision=%s WHERE singleton",
                (row["revision"],),
            )
            return {"state": "REVERTIDO"}


def migrate(dsn):
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        Store(dsn).check(conn)
        for name in ("migration.sql", "migration_002_read_view.sql"):
            conn.execute(Path(__file__).with_name(name).read_text(encoding="utf-8"))
