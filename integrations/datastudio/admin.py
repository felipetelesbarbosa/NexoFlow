"""Administração local na VPS. Não é endpoint remoto nem aceita senha na CLI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from psycopg import sql
from psycopg.rows import scalar_row

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
        if (
            spec["public"]
            and name != "BI_Weni_Conversas_Diarias"
            and not spec.get("optional")
        ):
            conn.execute(
                sql.SQL("GRANT SELECT ON {}.{} TO {}").format(
                    sql.Identifier(schema),
                    sql.Identifier(view_name(name)),
                    sql.Identifier(reader),
                )
            )
    for name, spec in READ_REGISTRY.items():
        if (
            spec["public"]
            and name != "BI_Weni_Conversas_Diarias"
            and not spec.get("optional")
        ):
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
    if segment == "FARMA":
        conn.execute(
            Path(__file__)
            .with_name("grants_conferencia_farma.sql")
            .read_text(encoding="utf-8")
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


def update_farma_report(
    store,
    expected_revision,
    *,
    public_summary=False,
    destinations=False,
    promote_destinations=False,
):
    from integrations.datastudio.financial_views import (
        create_farma_orders_view,
        create_farma_sales_view,
    )

    if store.segment != "FARMA":
        raise StorageError("DS_SEGMENTO_DIVERGENTE")
    if destinations and store.environment != "homologacao" and not promote_destinations:
        raise StorageError("DS_DESTINOS_EXIGE_HOMOLOGACAO")
    with store.connect() as conn:
        # Mesma trava de begin/finish. As duas definições passam a valer juntas.
        active = store.active(conn, lock=True)
        target = store.revision(conn, expected_revision)
        if target["estado"] != "READY" or target["versao"] != active:
            raise StorageError("DS_REVISAO_FORA_DE_ORDEM")
        if conn.execute(
            "SELECT 1 FROM controle.nf_execucoes WHERE segmento='FARMA' AND estado='WRITING'"
        ).fetchone():
            raise StorageError("DS_MIGRACAO_COM_PUBLICACAO_INCOMPLETA")
        if destinations:
            from integrations.datastudio.meta_destinations import install

            install(conn)
        elif public_summary:
            from integrations.datastudio.reader import create_farma_public_summary

            create_farma_public_summary(conn)
        else:
            create_farma_orders_view(conn)
            create_farma_sales_view(conn)
    return active


def run(argv=None):
    p = argparse.ArgumentParser(
        description="Migração aditiva do contrato definitivo Data Studio"
    )
    p.add_argument("--dsn-file", type=Path, required=True)
    p.add_argument("--ambiente", choices=("homologacao", "producao"), required=True)
    p.add_argument("--segmento", choices=("FARMA", "PET"), required=True)
    p.add_argument("--aprovar-origem", type=Path)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--atualizar-visoes-farma", metavar="UUID_READY")
    mode.add_argument("--instalar-destinos-farma", metavar="UUID_READY")
    mode.add_argument("--instalar-publico-farma", metavar="UUID_READY")
    mode.add_argument("--instalar-conversas-projeto", metavar="UUID_PROJETO_WENI")
    p.add_argument("--promover-leitor-destinos-farma", action="store_true")
    p.add_argument("--finalizar-selada")
    p.add_argument("--saida", type=Path)
    p.add_argument("--recibos-esperados", type=int)
    p.add_argument("--registros-esperados", type=int)
    args = p.parse_args(argv)
    if args.promover_leitor_destinos_farma and (
        args.instalar_destinos_farma is None
        or args.ambiente != "producao"
        or args.segmento != "FARMA"
    ):
        p.error("A promoção exige --instalar-destinos-farma no ambiente FARMA de produção.")
    if args.instalar_conversas_projeto is not None:
        if any(
            x is not None
            for x in (
                args.aprovar_origem,
                args.finalizar_selada,
                args.saida,
                args.recibos_esperados,
                args.registros_esperados,
            )
        ):
            p.error("Instale a fonte de conversas isoladamente.")
        from integrations.datastudio.weni_daily import install

        install(
            Store(
                args.dsn_file.read_text(encoding="utf-8-sig").strip(),
                args.ambiente,
                args.segmento,
            ),
            args.instalar_conversas_projeto,
        )
        print("[OK] Projeto vinculado e visão FARMA de conversas instalada.")
        return
    if (
        args.atualizar_visoes_farma is not None
        or args.instalar_publico_farma is not None
        or args.instalar_destinos_farma is not None
    ):
        if any(
            value is not None
            for value in (
                args.finalizar_selada,
                args.aprovar_origem,
                args.saida,
                args.recibos_esperados,
                args.registros_esperados,
            )
        ):
            p.error("A atualização de visões deve ser executada isoladamente.")
        dsn = args.dsn_file.read_text(encoding="utf-8-sig").strip()
        public_summary = args.instalar_publico_farma is not None
        version = update_farma_report(
            Store(dsn, args.ambiente, args.segmento),
            args.instalar_publico_farma
            if public_summary
            else args.instalar_destinos_farma or args.atualizar_visoes_farma,
            public_summary=public_summary,
            destinations=args.instalar_destinos_farma is not None,
            promote_destinations=args.promover_leitor_destinos_farma,
        )
        views = "BI_Publico_Resumo" if public_summary else "BI_Pedidos e BI_Vendas"
        if args.instalar_destinos_farma:
            views = "Destinos e veiculação"
        print(f"[OK] Visões {views} FARMA instaladas na versão READY {version}.")
        return version
    if args.finalizar_selada and (args.saida is None or args.aprovar_origem):
        p.error("Fechamento exige --saida privada e não aceita --aprovar-origem.")
    dsn = args.dsn_file.read_text(encoding="utf-8-sig").strip()
    if args.finalizar_selada:
        from ds_backend.migration import private_json

        store = Store(dsn, args.ambiente, args.segmento)
        status = store.inspect(args.finalizar_selada)
        manifest = status.get("sealed_manifest")
        if manifest is None:
            raise StorageError("DS_REVISAO_NAO_SELADA")
        if any(
            value is not None and value < 0
            for value in (args.recibos_esperados, args.registros_esperados)
        ):
            p.error("Contagens esperadas não podem ser negativas.")
        with store.connect(readonly=True) as conn:
            # A revisão selada não admite novos lotes; conferir o segmento antes
            # das contagens. Não editar ou reconstruir a intenção conservada.
            store.revision(conn, args.finalizar_selada)
            with conn.cursor(row_factory=scalar_row) as counts:
                receipts = counts.execute(
                    "SELECT count(*) FROM controle.nf_lotes WHERE execucao=%s",
                    (args.finalizar_selada,),
                ).fetchall()[0]
                # READY pode ter tombstones adicionados no fechamento. A repetição
                # devolve o recibo conservado sem reinterpretar a contagem pré-commit.
                records = None
                if status["state"] != "READY":
                    records = counts.execute(
                        sql.SQL(
                            "SELECT count(*) FROM {}.nf_stage WHERE execucao=%s"
                        ).format(sql.Identifier(store.schema)),
                        (args.finalizar_selada,),
                    ).fetchall()[0]
        if (
            args.recibos_esperados is not None and receipts != args.recibos_esperados
        ) or (
            records is not None
            and args.registros_esperados is not None
            and records != args.registros_esperados
        ):
            raise StorageError("DS_CONTAGENS_SELADAS_DIVERGENTES")
        result = store.finish(args.finalizar_selada, manifest, complete=True)
        private_json(args.saida, result)
        print("[OK] Fechamento verificado; recibo READY privado gravado.")
        return result
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
    import logging

    import psycopg

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        run()
    except StorageError as error:
        print("[PENDÊNCIA] " + str(error))
        raise SystemExit(3) from None
    except psycopg.Error as error:
        code = (
            "DS_FECHAMENTO_TEMPO_LIMITE"
            if isinstance(error, psycopg.errors.QueryCanceled)
            else "DS_BANCO_INDISPONIVEL"
        )
        print(
            "[PENDÊNCIA] " + code + "; confira a mesma revisão e preserve os recibos."
        )
        raise SystemExit(3) from None
    except OSError:
        print(
            "[PENDÊNCIA] DS_ARQUIVO_PRIVADO_INDISPONIVEL; consulte o estado da mesma revisão antes de repetir."
        )
        raise SystemExit(3) from None
