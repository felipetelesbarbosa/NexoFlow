"""Atualização restrita do grão de métricas; nunca reescreve fatos/recibos antigos."""

from psycopg import sql

from ds_backend.contract import SCHEMA_HASH, StorageError

PREVIOUS_HASH = "5ea6c5d0abd428a6b00c9d6a8fabe31c051a11dd3c127e17842947f708ac5ac8"
TABLES = ("Metricas_Diarias", "BI_Ads")


def upgrade_empty_metrics(conn, previous):
    if previous != PREVIOUS_HASH:
        raise StorageError("DS_MIGRACAO_CONTRATO_DIVERGENTE")
    # Administração com serviços pausados; trava também barra escritas concorrentes
    # durante a inspeção. Nunca alterar chaves de versões publicadas em silêncio.
    conn.execute(
        "LOCK TABLE controle.nf_execucoes,controle.nf_contrato IN ACCESS EXCLUSIVE MODE"
    )
    for schema in ("farma", "pet"):
        for table in ("nf_registros", "nf_stage", "nf_atuais"):
            conn.execute(
                sql.SQL("LOCK TABLE {}.{} IN ACCESS EXCLUSIVE MODE").format(
                    sql.Identifier(schema), sql.Identifier(table)
                )
            )
    if conn.execute(
        "SELECT 1 FROM controle.nf_execucoes WHERE estado='WRITING' LIMIT 1"
    ).fetchone():
        raise StorageError("DS_MIGRACAO_COM_PUBLICACAO_INCOMPLETA")
    for schema in ("farma", "pet"):
        for table in ("nf_registros", "nf_stage", "nf_atuais"):
            if conn.execute(
                sql.SQL("SELECT 1 FROM {}.{} WHERE tabela=ANY(%s) LIMIT 1").format(
                    sql.Identifier(schema), sql.Identifier(table)
                ),
                (list(TABLES),),
            ).fetchone():
                raise StorageError("DS_MIGRACAO_METRICAS_REQUER_REVISAO")
    conn.execute(
        "UPDATE controle.nf_contrato SET schema_hash=%s WHERE id=1 AND schema_hash=%s",
        (SCHEMA_HASH, previous),
    )
