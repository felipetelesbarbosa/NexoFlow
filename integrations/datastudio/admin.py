"""Administração local na VPS. Não é endpoint remoto nem aceita senha na CLI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from psycopg import sql

from ds_backend.contract import REGISTRY, StorageError, digest
from integrations.datastudio.read_catalog import READ_REGISTRY
from integrations.datastudio.reader import create_views, view_name
from integrations.datastudio.store import Store, migrate


def grants(conn, segment):
    schema = segment.lower()
    publisher = "nf_ds_" + schema + "_publish"
    reader = "nf_ds_" + schema + "_read"
    for role in (publisher, reader):
        if not conn.execute(
            "SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)
        ).fetchone():
            conn.execute(
                sql.SQL(
                    "CREATE ROLE {} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION"
                ).format(sql.Identifier(role))
            )
    for role in (publisher, reader):
        dangerous = conn.execute(
            "SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls AS unsafe FROM pg_roles WHERE rolname=%s",
            (role,),
        ).fetchone()
        if (
            dangerous["unsafe"]
            or conn.execute(
                "SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member WHERE r.rolname=%s",
                (role,),
            ).fetchone()
        ):
            raise StorageError("DS_CONTA_EXISTENTE_NAO_MINIMA")
    conn.execute(
        sql.SQL("GRANT USAGE ON SCHEMA {},controle TO {},{}").format(
            sql.Identifier(schema), sql.Identifier(publisher), sql.Identifier(reader)
        )
    )
    conn.execute(
        sql.SQL("GRANT CONNECT ON DATABASE {} TO {},{}").format(
            sql.Identifier(conn.info.dbname),
            sql.Identifier(publisher),
            sql.Identifier(reader),
        )
    )
    conn.execute(
        sql.SQL("GRANT SELECT ON controle.nf_contrato TO {},{}").format(
            sql.Identifier(publisher), sql.Identifier(reader)
        )
    )
    # Senhas e LOGIN são provisionados separadamente em sessão privada do administrador.
    for name in (
        "nf_registros",
        "nf_stage",
        "nf_estados",
        "nf_estado_recibos",
        "nf_atuais",
    ):
        conn.execute(
            sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON {}.{} TO {}").format(
                sql.Identifier(schema), sql.Identifier(name), sql.Identifier(publisher)
            )
        )
    for name in (
        "nf_publicacoes",
        "nf_execucoes",
        "nf_lotes",
        "nf_substituicoes",
        "nf_membros",
        "nf_reversoes",
    ):
        conn.execute(
            sql.SQL("GRANT SELECT,INSERT,UPDATE ON controle.{} TO {}").format(
                sql.Identifier(name), sql.Identifier(publisher)
            )
        )
    conn.execute(
        sql.SQL("GRANT DELETE ON controle.nf_membros TO {}").format(
            sql.Identifier(publisher)
        )
    )
    conn.execute(
        sql.SQL("GRANT SELECT ON controle.nf_origens TO {}").format(
            sql.Identifier(publisher)
        )
    )
    conn.execute(
        sql.SQL(
            "GRANT USAGE,SELECT ON SEQUENCE controle.nf_execucoes_versao_seq TO {}"
        ).format(sql.Identifier(publisher))
    )
    # RLS por conta, não por parâmetro alterável da sessão. Tabelas-filhas herdam segmento da execução.
    for name in (
        "nf_publicacoes",
        "nf_execucoes",
        "nf_origens",
        "nf_lotes",
        "nf_substituicoes",
        "nf_membros",
        "nf_reversoes",
    ):
        conn.execute(
            sql.SQL("ALTER TABLE controle.{} ENABLE ROW LEVEL SECURITY").format(
                sql.Identifier(name)
            )
        )
        policy = "ds_" + schema + "_" + name
        if not conn.execute(
            "SELECT 1 FROM pg_policies WHERE schemaname='controle' AND tablename=%s AND policyname=%s",
            (name, policy),
        ).fetchone():
            condition = (
                sql.SQL("segmento={}").format(sql.Literal(segment))
                if name in ("nf_publicacoes", "nf_execucoes", "nf_origens")
                else sql.SQL(
                    "execucao IN(SELECT id FROM controle.nf_execucoes WHERE segmento={})"
                ).format(sql.Literal(segment))
            )
            conn.execute(
                sql.SQL(
                    "CREATE POLICY {} ON controle.{} TO {} USING({}) WITH CHECK({})"
                ).format(
                    sql.Identifier(policy),
                    sql.Identifier(name),
                    sql.Identifier(publisher),
                    condition,
                    condition,
                )
            )
    # O leitor só enxerga visões públicas; Store.info usa esta função restrita na implantação.
    for name, spec in READ_REGISTRY.items():
        if spec["public"]:
            conn.execute(
                sql.SQL("GRANT SELECT ON {}.{} TO {}").format(
                    sql.Identifier(schema),
                    sql.Identifier(view_name(name)),
                    sql.Identifier(reader),
                )
            )
    for name, spec in READ_REGISTRY.items():
        if spec["public"]:
            conn.execute(
                sql.SQL("GRANT SELECT ON {}.{} TO {}").format(
                    sql.Identifier(schema),
                    sql.Identifier(view_name(name)),
                    sql.Identifier(publisher),
                )
            )
    conn.execute(
        sql.SQL("GRANT SELECT ON controle.nf_publicacoes TO {}").format(
            sql.Identifier(reader)
        )
    )
    policy = "ds_" + schema + "_reader"
    if not conn.execute(
        "SELECT 1 FROM pg_policies WHERE schemaname='controle' AND tablename='nf_publicacoes' AND policyname=%s",
        (policy,),
    ).fetchone():
        conn.execute(
            sql.SQL(
                "CREATE POLICY {} ON controle.nf_publicacoes FOR SELECT TO {} USING(segmento={})"
            ).format(
                sql.Identifier(policy), sql.Identifier(reader), sql.Literal(segment)
            )
        )


def run(argv=None):
    p = argparse.ArgumentParser(
        description="Migração aditiva do contrato definitivo Data Studio"
    )
    p.add_argument("--dsn-file", type=Path, required=True)
    p.add_argument("--ambiente", choices=("homologacao", "producao"), required=True)
    p.add_argument("--segmento", choices=("FARMA", "PET"), required=True)
    p.add_argument("--aprovar-origem", type=Path)
    args = p.parse_args(argv)
    dsn = args.dsn_file.read_text(encoding="utf-8-sig").strip()
    migrate(dsn, args.ambiente)
    store = Store(dsn, args.ambiente, args.segmento)
    with store.connect() as conn:
        create_views(conn)
        grants(conn, args.segmento)
        if args.aprovar_origem:
            from psycopg.types.json import Jsonb

            manifest = json.loads(args.aprovar_origem.read_text(encoding="utf-8-sig"))
            if (
                manifest.get("segment") != args.segmento
                or manifest.get("state") != "READY"
                or set(manifest.get("tables", {})) != set(REGISTRY)
            ):
                raise StorageError("DS_ORIGEM_INCOMPLETA")
            conn.execute(
                "INSERT INTO controle.nf_origens VALUES(%s,%s,%s) ON CONFLICT(segmento) DO UPDATE SET hash=excluded.hash,manifest=excluded.manifest",
                (args.segmento, digest(manifest), Jsonb(manifest)),
            )
    print("[OK] Contrato e permissões preparados; nenhum fato comercial importado.")


if __name__ == "__main__":
    run()
