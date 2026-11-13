"""Revisões isoladas, recibos duráveis e leitura da última versão confirmada."""

from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ds_backend.contract import (
    DATABASES,
    REGISTRY,
    SCHEMA_HASH,
    StorageError,
    digest,
    identifier,
    normalize,
    record_key,
    table_contract,
    target,
)

# A ancestralidade evita ressuscitar uma revisão revertida ao publicar a seguinte.
LINEAGE = """WITH RECURSIVE linhagem(versao) AS (
 SELECT %s::bigint UNION ALL
 SELECT e.base FROM controle.nf_execucoes e JOIN linhagem l ON e.versao=l.versao
 WHERE l.versao>0), visiveis AS (
 SELECT DISTINCT ON (chave) chave,registro FROM {schema}.nf_registros
 WHERE tabela=%s AND versao IN(SELECT versao FROM linhagem)
 ORDER BY chave,versao DESC)
"""


def migrate(dsn, environment):
    if environment not in DATABASES:
        raise StorageError("DS_AMBIENTE_INVALIDO")
    with psycopg.connect(dsn) as conn:
        if (
            conn.execute("SELECT current_database()").fetchone()[0]
            != DATABASES[environment]
        ):
            raise StorageError("DS_BANCO_DIVERGENTE")
        conn.execute(
            Path(__file__).with_name("002_backend.sql").read_text(encoding="utf-8-sig")
        )
        previous = conn.execute(
            "SELECT schema_hash FROM controle.nf_contrato WHERE id=1"
        ).fetchone()
        if previous and previous[0] != SCHEMA_HASH:
            from integrations.datastudio.metric_contract_upgrade import (
                upgrade_empty_metrics,
            )

            upgrade_empty_metrics(conn, previous[0])
        conn.execute(
            "INSERT INTO controle.nf_contrato VALUES(1,%s) ON CONFLICT DO NOTHING",
            (SCHEMA_HASH,),
        )


class Store:
    def __init__(self, dsn, environment, segment, *, require_dedicated_role=False):
        self.require_dedicated_role = require_dedicated_role
        self.dsn, self.environment, self.segment = dsn, environment, segment
        self.target = target(environment, segment)
        self.schema = segment.lower()  # whitelist acima, nunca identificador do cliente

    @contextmanager
    def connect(self, *, readonly=False):
        with psycopg.connect(
            self.dsn, row_factory=dict_row, connect_timeout=10
        ) as conn:
            if readonly:
                conn.execute(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                )
            conn.execute("SET LOCAL statement_timeout='50s'")
            conn.execute("SET LOCAL lock_timeout='5s'")
            if (
                conn.execute("SELECT current_database() AS db").fetchone()["db"]
                != DATABASES[self.environment]
            ):
                raise StorageError("DS_BANCO_DIVERGENTE")
            expected = conn.execute(
                "SELECT schema_hash FROM controle.nf_contrato WHERE id=1"
            ).fetchone()
            if not expected or expected["schema_hash"] != SCHEMA_HASH:
                raise StorageError("DS_SCHEMA_BANCO_DIVERGENTE")
            if self.require_dedicated_role:
                role = (
                    "nf_ds_"
                    + self.schema
                    + ("_read" if self.__class__.__name__ == "Reader" else "_publish")
                )
                if (
                    conn.execute("SELECT current_user AS role").fetchone()["role"]
                    != role
                ):
                    raise StorageError("DS_CONTA_DIVERGENTE")
            yield conn

    def info(self):
        with self.connect() as conn:
            active = self.active(conn)
            pending = conn.execute(
                "SELECT id,finalidade FROM controle.nf_execucoes WHERE segmento=%s AND estado='WRITING'",
                (self.segment,),
            ).fetchall()
        return dict(
            protocol="nexoflow_datastudio_1",
            target=self.target,
            segment=self.segment,
            environment=self.environment,
            schema_hash=SCHEMA_HASH,
            version=active,
            server_version=Path(__file__)
            .resolve()
            .parents[2]
            .joinpath("VERSION")
            .read_text(encoding="utf-8-sig")
            .strip(),
            source_sha=os.environ.get("NEXOFLOW_SOURCE_SHA", "checkout-local"),
            pending=[dict(id=str(r["id"]), purpose=r["finalidade"]) for r in pending],
        )

    def active(self, conn, *, lock=False):
        return conn.execute(
            "SELECT versao FROM controle.nf_publicacoes WHERE segmento=%s"
            + (" FOR UPDATE" if lock else ""),
            (self.segment,),
        ).fetchone()["versao"]

    def revision(self, conn, revision, *, lock=False):
        row = conn.execute(
            "SELECT * FROM controle.nf_execucoes WHERE id=%s AND segmento=%s"
            + (" FOR UPDATE" if lock else ""),
            (identifier(revision), self.segment),
        ).fetchone()
        if not row:
            raise StorageError("DS_REVISAO_AUSENTE")
        return row

    def writable(self, conn, revision, *, allow_sealed=False):
        row = self.revision(conn, revision, lock=True)
        if row["estado"] != "WRITING" or self.active(conn) != row["base"]:
            raise StorageError("DS_REVISAO_FORA_DE_ORDEM")
        if row["intencao"] is not None and not allow_sealed:
            raise StorageError("DS_REVISAO_SELADA_IMUTAVEL")
        conn.execute(
            "UPDATE controle.nf_execucoes SET heartbeat=clock_timestamp() WHERE id=%s",
            (row["id"],),
        )
        return row

    def begin(self, revision, purpose, evidence):
        revision = identifier(revision)
        if purpose == "teste" and self.environment != "homologacao":
            raise StorageError("DS_TESTE_EM_PRODUCAO")
        if purpose not in (
            "analytics",
            "historico",
            "meta",
            "delivery",
            "bi",
            "migracao",
            "teste",
            "weni",
            "recompra",
        ) or not isinstance(evidence, dict):
            raise StorageError("DS_ESCOPO_INVALIDO")
        with self.connect() as conn:
            base = self.active(conn, lock=True)
            if not base and purpose not in ("migracao", "teste"):
                raise StorageError("DS_CORTE_INICIAL_NAO_CONFIRMADO")
            old = conn.execute(
                "SELECT * FROM controle.nf_execucoes WHERE id=%s", (revision,)
            ).fetchone()
            if old:
                if (
                    old["segmento"] != self.segment
                    or old["finalidade"] != purpose
                    or old["evidencia"] != evidence
                ):
                    raise StorageError("DS_REVISAO_REUTILIZADA")
                return self.status(conn, revision)
            if conn.execute(
                "SELECT 1 FROM controle.nf_execucoes WHERE segmento=%s AND estado='WRITING'",
                (self.segment,),
            ).fetchone():
                raise StorageError("DS_REVISAO_PENDENTE_RETOMAR")
            conn.execute(
                "INSERT INTO controle.nf_execucoes(id,segmento,base,estado,finalidade,evidencia) VALUES(%s,%s,%s,'WRITING',%s,%s)",
                (revision, self.segment, base, purpose, Jsonb(evidence)),
            )
            return self.status(conn, revision)

    def effective(self, conn, name, version):
        if version == self.active(conn):
            # Mesma interface de parâmetros; versão é comprovada na transação.
            return f"SELECT chave,registro FROM {self.schema}.nf_atuais WHERE %s::bigint>=0 AND tabela=%s"
        return (
            LINEAGE.format(schema=self.schema)
            + " SELECT chave,registro FROM visiveis WHERE registro IS NOT NULL"
        )

    def rows(self, name, *, revision=None, after="", limit=1000):
        table_contract(name)
        if (
            not isinstance(limit, int)
            or not 1 <= limit <= 1000
            or not isinstance(after, str)
        ):
            raise StorageError("DS_LIMITE_LEITURA")
        with self.connect(readonly=True) as conn:
            version = self.active(conn)
            if revision:
                rev = self.revision(conn, revision)
                version = rev["base"] if rev["estado"] == "WRITING" else rev["versao"]
                if rev["estado"] == "ABORTADA":
                    raise StorageError("DS_REVISAO_ABORTADA")
            query = self.effective(conn, name, version)
            params = [version, name]
            if revision and rev["estado"] == "WRITING":
                query = (
                    f"WITH visiveis AS(SELECT chave,registro FROM {self.schema}.nf_atuais WHERE %s::bigint>=0 AND tabela=%s)"
                    + f""", uniao AS(
                  SELECT chave,registro,0 AS prioridade FROM visiveis
                  UNION ALL SELECT chave,registro,1 FROM {self.schema}.nf_stage WHERE execucao=%s AND tabela=%s),
                  final AS(SELECT DISTINCT ON(chave) chave,registro FROM uniao ORDER BY chave,prioridade DESC)
                  SELECT chave,registro FROM final WHERE registro IS NOT NULL"""
                )
                params.extend([identifier(revision), name])
            result = conn.execute(
                query + " AND chave>%s ORDER BY chave LIMIT %s",
                (*params, after, limit + 1),
            ).fetchall()
            page = result[:limit]
            return dict(
                version=version,
                rows=[r["registro"] for r in page],
                next=page[-1]["chave"] if len(result) > limit else None,
            )

    def receipt(self, batch):
        with self.connect() as conn:
            row = conn.execute(
                "SELECT l.recibo FROM controle.nf_lotes l JOIN controle.nf_execucoes e ON e.id=l.execucao WHERE l.id=%s AND e.segmento=%s",
                (identifier(batch), self.segment),
            ).fetchone()
            return row["recibo"] if row else None

    def batch(self, revision, batch_id, name, rows, *, remove=None, simulate=False):
        revision, batch_id = identifier(revision), identifier(batch_id)
        rows = normalize(name, rows, self.segment)
        remove = remove or []
        if (
            not isinstance(remove, list)
            or len(remove) > 1000
            or any(not isinstance(x, str) or len(x) != 64 for x in remove)
        ):
            raise StorageError("DS_REMOCAO_INVALIDA")
        # Exclusões são explícitas; nunca se deduz ausência de uma extração parcial.
        if remove and table_contract(name)["full_history"]:
            raise StorageError("DS_HISTORICO_EXIGE_REVISAO_EXCLUSAO")
        keys = [record_key(name, r) for r in rows]
        if len(set(keys)) != len(keys) or set(keys) & set(remove):
            raise StorageError("DS_CHAVE_DUPLICADA")
        signature = digest(
            dict(revision=revision, table=name, rows=rows, remove=remove)
        )
        with self.connect() as conn:
            old = conn.execute(
                "SELECT l.* FROM controle.nf_lotes l JOIN controle.nf_execucoes e ON e.id=l.execucao WHERE l.id=%s AND e.segmento=%s",
                (batch_id, self.segment),
            ).fetchone()
            if old:
                if old["hash"] != signature or str(old["execucao"]) != revision:
                    raise StorageError("DS_LOTE_REUTILIZADO")
                return old["recibo"]
            rev = self.writable(conn, revision)
            # Outra chamada pode ter confirmado o mesmo lote enquanto este
            # pedido aguardava a trava da execução. Repetir só a leitura.
            raced = conn.execute(
                "SELECT hash,recibo,execucao FROM controle.nf_lotes WHERE id=%s",
                (batch_id,),
            ).fetchone()
            if raced:
                if raced["hash"] != signature or str(raced["execucao"]) != revision:
                    raise StorageError("DS_LOTE_REUTILIZADO")
                return raced["recibo"]
            counts = dict(inserted=0, updated=0, unchanged=0, removed=0)
            effective = self.effective(conn, name, rev["base"])
            current = {
                r["chave"]: r["registro"]
                for r in conn.execute(
                    "SELECT * FROM (" + effective + ") q WHERE chave=ANY(%s)",
                    (rev["base"], name, keys + remove),
                ).fetchall()
            }
            current.update(
                {
                    r["chave"]: r["registro"]
                    for r in conn.execute(
                        f"SELECT chave,registro FROM {self.schema}.nf_stage WHERE execucao=%s AND tabela=%s AND chave=ANY(%s)",
                        (revision, name, keys + remove),
                    ).fetchall()
                }
            )
            for key, record in [
                *zip(keys, rows, strict=True),
                *((k, None) for k in remove),
            ]:
                previous = current.get(key)
                kind = (
                    "unchanged"
                    if previous == record
                    else "removed"
                    if record is None
                    else "inserted"
                    if previous is None
                    else "updated"
                )
                counts[kind] += 1
                if not simulate and record is not None:
                    conn.execute(
                        "INSERT INTO controle.nf_membros VALUES(%s,%s,%s) ON CONFLICT DO NOTHING",
                        (revision, name, key),
                    )
                if not simulate and kind != "unchanged":
                    conn.execute(
                        f"INSERT INTO {self.schema}.nf_stage(execucao,tabela,chave,registro) VALUES(%s,%s,%s,%s) ON CONFLICT(execucao,tabela,chave) DO UPDATE SET registro=excluded.registro",
                        (
                            revision,
                            name,
                            key,
                            Jsonb(record) if record is not None else None,
                        ),
                    )
            receipt = dict(
                id=batch_id,
                revision=revision,
                hash=signature,
                state="SIMULADO" if simulate else "CONFIRMADO",
                **counts,
            )
            if simulate:
                conn.rollback()
            if not simulate:
                conn.execute(
                    "INSERT INTO controle.nf_lotes(id,execucao,hash,recibo) VALUES(%s,%s,%s,%s)",
                    (batch_id, revision, signature, Jsonb(receipt)),
                )
            return receipt

    def replace(self, revision, name, expected):
        if (
            not isinstance(expected, dict)
            or set(expected) != {"count", "sha256"}
            or not isinstance(expected["count"], int)
            or expected["count"] < 0
        ):
            raise StorageError("DS_SUBSTITUICAO_SEM_PLANO")
        spec = table_contract(name)
        if spec["full_history"] or name in (
            "Base_Contatos",
            "Pedidos_FarmaLider",
            "Itens_Pedidos_FarmaLider",
        ):
            raise StorageError("DS_BASE_ACUMULADA_NAO_SUBSTITUIVEL")
        with self.connect() as conn:
            self.writable(conn, revision)
            previous = conn.execute(
                "SELECT esperado FROM controle.nf_substituicoes WHERE execucao=%s AND tabela=%s",
                (identifier(revision), name),
            ).fetchone()
            if previous and previous["esperado"] != expected:
                conn.execute(
                    f"DELETE FROM {self.schema}.nf_stage WHERE execucao=%s AND tabela=%s",
                    (identifier(revision), name),
                )
                conn.execute(
                    "DELETE FROM controle.nf_membros WHERE execucao=%s AND tabela=%s",
                    (identifier(revision), name),
                )
            conn.execute(
                "INSERT INTO controle.nf_substituicoes(execucao,tabela,esperado) VALUES(%s,%s,%s) ON CONFLICT(execucao,tabela) DO UPDATE SET esperado=excluded.esperado",
                (identifier(revision), name, Jsonb(expected)),
            )

        return dict(state="CONFIRMADO")

    def status(self, conn, revision):
        row = self.revision(conn, revision)
        return dict(
            revision=str(row["id"]),
            version=row["versao"],
            base=row["base"],
            state=row["estado"],
            receipt=row["recibo"],
            sealed_manifest=row["intencao"],
        )

    def inspect(self, revision):
        with self.connect() as conn:
            return self.status(conn, revision)

    def finish(self, revision, manifest, *, complete):
        if complete is not True or not isinstance(manifest, dict):
            raise StorageError("DS_EXTRACAO_INCOMPLETA")
        revision = identifier(revision)
        signature = digest(manifest)
        with self.connect() as conn:
            self.active(conn, lock=True)
            row = self.revision(conn, revision, lock=True)
            if row["estado"] == "READY":
                if row["manifest"] != manifest:
                    raise StorageError("DS_FECHAMENTO_DIVERGENTE")
                return row["recibo"]
            # Ordem de locks sempre publicação -> execução para evitar deadlocks com begin.
            self.active(conn, lock=True)
            row = self.writable(conn, revision, allow_sealed=True)
            if row["intencao"] is not None and row["intencao"] != manifest:
                raise StorageError("DS_PLANO_SELADO_DIVERGENTE")
            # Um manifest confirma TODOS os recibos, inclusive lotes mantidos.
            receipts = conn.execute(
                "SELECT id,hash FROM controle.nf_lotes WHERE execucao=%s ORDER BY id",
                (revision,),
            ).fetchall()
            expected = {str(r["id"]): r["hash"] for r in receipts}
            if (
                set(manifest) != {"schema_hash", "batches", "complete_sources"}
                or manifest["schema_hash"] != SCHEMA_HASH
                or manifest["batches"] != expected
            ):
                raise StorageError("DS_MANIFESTO_DIVERGENTE")
            if manifest["complete_sources"] is not True:
                raise StorageError("DS_FONTES_INCOMPLETAS")
            if row["base"] == 0 and row["finalidade"] != "teste":
                approved = conn.execute(
                    "SELECT hash,manifest FROM controle.nf_origens WHERE segmento=%s",
                    (self.segment,),
                ).fetchone()
                if (
                    not approved
                    or row["evidencia"].get("source_hash") != approved["hash"]
                ):
                    raise StorageError("DS_CORTE_INICIAL_NAO_APROVADO")
                initial_manifest = approved["manifest"]
                if (
                    self.environment == "producao"
                    and initial_manifest.get("evidence", {}).get("scope")
                    != "CORTE_COMPLETO"
                ):
                    raise StorageError("DS_PILOTO_EM_PRODUCAO")
            else:
                initial_manifest = None
            replacements = conn.execute(
                "SELECT tabela,esperado FROM controle.nf_substituicoes WHERE execucao=%s",
                (revision,),
            ).fetchall()
            for item in replacements:
                name = item["tabela"]
                members = [
                    r["chave"]
                    for r in conn.execute(
                        "SELECT chave FROM controle.nf_membros WHERE execucao=%s AND tabela=%s ORDER BY chave",
                        (revision, name),
                    )
                ]
                if item["esperado"] != dict(count=len(members), sha256=digest(members)):
                    raise StorageError("DS_SUBSTITUICAO_INCOMPLETA")
                conn.execute(
                    f"""INSERT INTO {self.schema}.nf_stage(execucao,tabela,chave,registro)
                  SELECT %s,%s,q.chave,NULL FROM ("""
                    + self.effective(conn, name, row["base"])
                    + """)q
                  WHERE NOT EXISTS(SELECT 1 FROM controle.nf_membros s WHERE s.execucao=%s AND s.tabela=%s AND s.chave=q.chave)
                  ON CONFLICT DO NOTHING""",
                    (revision, name, row["base"], name, revision, name),
                )
            count = conn.execute(
                f"""INSERT INTO {self.schema}.nf_registros(tabela,chave,versao,registro)
              SELECT tabela,chave,%s,registro FROM {self.schema}.nf_stage WHERE execucao=%s""",
                (row["versao"], revision),
            ).rowcount
            conn.execute(
                f"INSERT INTO {self.schema}.nf_atuais(tabela,chave,registro) SELECT tabela,chave,registro FROM {self.schema}.nf_stage WHERE execucao=%s AND registro IS NOT NULL ON CONFLICT(tabela,chave) DO UPDATE SET registro=excluded.registro",
                (revision,),
            )
            conn.execute(
                f"DELETE FROM {self.schema}.nf_atuais a USING {self.schema}.nf_stage s WHERE s.execucao=%s AND s.registro IS NULL AND a.tabela=s.tabela AND a.chave=s.chave",
                (revision,),
            )
            if initial_manifest is not None:
                actual = self.fingerprints(conn, row["versao"])
                if initial_manifest["tables"] != actual:
                    raise StorageError("DS_CORTE_INICIAL_DIVERGENTE")
            receipt = dict(
                state="READY",
                revision=revision,
                version=row["versao"],
                manifest_hash=signature,
                changed_rows=count,
                source_sha=os.environ.get("NEXOFLOW_SOURCE_SHA", "checkout-local"),
            )
            conn.execute(
                "UPDATE controle.nf_execucoes SET estado='READY',confirmado=clock_timestamp(),manifest=%s,recibo=%s WHERE id=%s",
                (Jsonb(manifest), Jsonb(receipt), revision),
            )
            conn.execute(
                "UPDATE controle.nf_publicacoes SET versao=%s,execucao=%s WHERE segmento=%s",
                (row["versao"], revision, self.segment),
            )
            from integrations.datastudio.financial_views import assert_financial

            assert_financial(conn, self.schema)
            return receipt

    def rollback(self, revision, expected_version):
        with self.connect() as conn:
            active = self.active(conn, lock=True)
            row = self.revision(conn, revision, lock=True)
            old = conn.execute(
                "SELECT recibo FROM controle.nf_reversoes WHERE execucao=%s",
                (identifier(revision),),
            ).fetchone()
            if old:
                return old["recibo"]
            if (
                row["estado"] != "READY"
                or active != row["versao"]
                or active != expected_version
            ):
                raise StorageError("DS_REVERSAO_EDICAO_POSTERIOR")
            if conn.execute(
                "SELECT 1 FROM controle.nf_execucoes WHERE segmento=%s AND estado='WRITING'",
                (self.segment,),
            ).fetchone():
                raise StorageError("DS_REVISAO_PENDENTE_RETOMAR")
            conn.execute(f"DELETE FROM {self.schema}.nf_atuais")
            for name in REGISTRY:
                conn.execute(
                    f"INSERT INTO {self.schema}.nf_atuais(tabela,chave,registro) SELECT %s,q.chave,q.registro FROM ("
                    + LINEAGE.format(schema=self.schema)
                    + " SELECT chave,registro FROM visiveis WHERE registro IS NOT NULL)q",
                    (name, row["base"], name),
                )
            conn.execute(
                "UPDATE controle.nf_publicacoes SET versao=%s,execucao=(SELECT id FROM controle.nf_execucoes WHERE versao=%s) WHERE segmento=%s",
                (row["base"], row["base"], self.segment),
            )
            receipt = dict(state="REVERTIDA", version=row["base"])
            conn.execute(
                "INSERT INTO controle.nf_reversoes VALUES(%s,%s)",
                (identifier(revision), Jsonb(receipt)),
            )
            return receipt

    def abort(self, revision):
        with self.connect() as conn:
            if self.revision(conn, revision)["estado"] == "ABORTADA":
                return dict(state="ABORTADA", facts_preserved=True)
            self.writable(conn, revision, allow_sealed=True)
            conn.execute(
                "UPDATE controle.nf_execucoes SET estado='ABORTADA' WHERE id=%s",
                (identifier(revision),),
            )
            return dict(state="ABORTADA", facts_preserved=True)

    def fingerprints(self, conn, version):
        result = {}
        for name in REGISTRY:
            hashed = hashlib.sha256()
            count = 0
            with conn.cursor(name="ds_" + __import__("uuid").uuid4().hex) as cursor:
                cursor.execute(
                    self.effective(conn, name, version) + " ORDER BY chave",
                    (version, name),
                )
                for row in cursor:
                    hashed.update(
                        json.dumps(
                            row["registro"],
                            sort_keys=True,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ).encode()
                        + b"\n"
                    )
                    count += 1
            result[name] = dict(count=count, sha256=hashed.hexdigest())
        return result

    def state_get(self, name):
        self.state_name(name)
        with self.connect() as conn:
            row = conn.execute(
                f"SELECT versao,hash,documento FROM {self.schema}.nf_estados WHERE nome=%s",
                (name,),
            ).fetchone()
            return (
                dict(version=row["versao"], hash=row["hash"], document=row["documento"])
                if row
                else dict(version=0, hash=digest(None), document=None)
            )

    @staticmethod
    def state_name(name):
        if name not in (
            "weni_update",
            "recompra",
            "historico_cursor",
            "carga_fracionada",
            "cache_observacoes",
        ):
            raise StorageError("DS_ESTADO_NAO_AUTORIZADO")

    def state_put(self, name, expected_version, document, receipt_id):
        self.state_name(name)
        receipt_id = identifier(receipt_id)
        if (
            not isinstance(expected_version, int)
            or expected_version < 0
            or not isinstance(document, dict)
        ):
            raise StorageError("DS_ESTADO_INVALIDO")
        checksum = digest(dict(name=name, base=expected_version, document=document))
        with self.connect() as conn:
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                (self.segment + ":state:" + name,),
            )
            previous = conn.execute(
                f"SELECT hash,recibo FROM {self.schema}.nf_estado_recibos WHERE id=%s",
                (receipt_id,),
            ).fetchone()
            if previous:
                if previous["hash"] != checksum:
                    raise StorageError("DS_RECIBO_REUTILIZADO")
                return previous["recibo"]
            current = conn.execute(
                f"SELECT versao FROM {self.schema}.nf_estados WHERE nome=%s FOR UPDATE",
                (name,),
            ).fetchone()
            if (current["versao"] if current else 0) != expected_version:
                raise StorageError("DS_ESTADO_EDICAO_CONCORRENTE")
            receipt = dict(
                id=receipt_id,
                state="CONFIRMADO",
                version=expected_version + 1,
                hash=digest(document),
            )
            conn.execute(
                f"INSERT INTO {self.schema}.nf_estados(nome,versao,hash,documento) VALUES(%s,%s,%s,%s) ON CONFLICT(nome) DO UPDATE SET versao=excluded.versao,hash=excluded.hash,documento=excluded.documento,atualizado=clock_timestamp()",
                (name, receipt["version"], receipt["hash"], Jsonb(document)),
            )
            conn.execute(
                f"INSERT INTO {self.schema}.nf_estado_recibos VALUES(%s,%s,%s)",
                (receipt_id, checksum, Jsonb(receipt)),
            )
            return receipt

    def seal(self, revision, manifest):
        if (
            not isinstance(manifest, dict)
            or manifest.get("schema_hash") != SCHEMA_HASH
            or manifest.get("complete_sources") is not True
        ):
            raise StorageError("DS_PLANO_INCOMPLETO")
        with self.connect() as conn:
            row = self.writable(conn, revision, allow_sealed=True)
            if row["intencao"] is not None and row["intencao"] != manifest:
                raise StorageError("DS_PLANO_SELADO_DIVERGENTE")
            receipts = conn.execute(
                "SELECT id,hash FROM controle.nf_lotes WHERE execucao=%s",
                (identifier(revision),),
            ).fetchall()
            if manifest.get("batches") != {str(r["id"]): r["hash"] for r in receipts}:
                raise StorageError("DS_MANIFESTO_DIVERGENTE")
            conn.execute(
                "UPDATE controle.nf_execucoes SET intencao=%s WHERE id=%s",
                (Jsonb(manifest), identifier(revision)),
            )
            return dict(
                state="SELADA",
                revision=identifier(revision),
                manifest_hash=digest(manifest),
            )

    def capacity(self):
        with self.connect() as conn:
            size = conn.execute(
                "SELECT pg_database_size(current_database()) AS bytes"
            ).fetchone()["bytes"]
            stages = conn.execute(
                f"SELECT count(*) AS n FROM {self.schema}.nf_stage"
            ).fetchone()["n"]
            return dict(
                database_bytes=size,
                staged_rows=stages,
                filesystem_free_bytes=None,
                note="Espaço livre deve ser conferido no volume PostgreSQL pelo Work; a API não inspeciona outros bancos nem o filesystem da VPS.",
            )

    def audit(self):
        with self.connect(readonly=True) as conn:
            version = self.active(conn)
            if not version:
                raise StorageError("DS_SEM_PUBLICACAO_CONFIRMADA")
            rows = conn.execute(f"""WITH itens AS(
              SELECT pedido_id,segmento,count(*) AS linhas,sum(quantidade) AS unidades
              FROM {self.schema}.ds_historico_itens WHERE vigente='Sim' AND estado='valido' AND frete='Não' GROUP BY pedido_id,segmento),
              fatos AS(SELECT h.*,coalesce(i.linhas,0) AS linhas,coalesce(i.unidades,0) AS unidades
                FROM {self.schema}.ds_historico_pedidos h LEFT JOIN itens i USING(pedido_id,segmento) WHERE h.vigente='Sim'),
              recortes AS(SELECT CASE WHEN data IS NULL THEN 'SEM_EMISSAO' ELSE to_char(data,'YYYY-MM') END AS recorte,* FROM fatos
                UNION ALL SELECT 'TOTAL',* FROM fatos)
              SELECT recorte,count(*) AS pedidos,count(*) FILTER(WHERE estado='valido') AS validos,
                count(*) FILTER(WHERE estado='cancelado') AS cancelados,count(*) FILTER(WHERE estado='pendente') AS pendentes,
                count(*) FILTER(WHERE estado NOT IN('valido','cancelado','pendente')) AS outros,
                count(DISTINCT cliente_id) FILTER(WHERE estado='valido') AS compradores,
                coalesce(sum(linhas) FILTER(WHERE estado='valido'),0) AS itens,
                coalesce(sum(unidades) FILTER(WHERE estado='valido'),0) AS unidades,
                coalesce(sum(produtos*100) FILTER(WHERE estado='valido'),0) AS produtos_centavos,
                coalesce(sum(frete*100) FILTER(WHERE estado='valido'),0) AS frete_centavos,
                coalesce(sum(faturamento*100) FILTER(WHERE estado='valido'),0) AS faturamento_centavos
              FROM recortes GROUP BY recorte ORDER BY recorte""").fetchall()
            # Não divulgar CPF, contatos, cliques ou IDs comerciais na conferência.
            return dict(
                version=version,
                segment=self.segment,
                coverage="LIMITES_DA_API_NAO_HOMOLOGADOS",
                periods=[
                    {
                        k: str(v) if isinstance(v, __import__("decimal").Decimal) else v
                        for k, v in r.items()
                    }
                    for r in rows
                ],
                semantics="itens=linhas de produto; frete técnico excluído; compradores distintos diretamente por recorte",
            )
