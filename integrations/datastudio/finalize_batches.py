"""Projeção em blocos na mesma transação; nenhum commit/READY intermediário."""

import logging

from ds_backend.contract import StorageError

FINALIZE_ROWS = 5000


def write_stage(conn, schema, revision, version):
    if schema not in ("farma", "pet"):
        raise StorageError("DS_SEGMENTO_DIVERGENTE")
    after = ("", "")
    total = 0
    blocks = 0
    while True:
        keys = conn.execute(
            f"SELECT tabela,chave FROM {schema}.nf_stage WHERE execucao=%s AND (tabela,chave)>(%s,%s) ORDER BY tabela,chave LIMIT %s",
            (revision, *after, FINALIZE_ROWS),
        ).fetchall()
        if not keys:
            logging.info(
                "[FECHAMENTO] Projeção conferível concluída: registros=%s; blocos=%s; transação ainda não confirmada.",
                total,
                blocks,
            )
            return total
        end = (keys[-1]["tabela"], keys[-1]["chave"])
        bounds = (revision, *after, *end)
        where = "execucao=%s AND (tabela,chave)>(%s,%s) AND (tabela,chave)<=(%s,%s)"
        total += conn.execute(
            f"INSERT INTO {schema}.nf_registros(tabela,chave,versao,registro) SELECT tabela,chave,%s,registro FROM {schema}.nf_stage WHERE "
            + where,
            (version, *bounds),
        ).rowcount
        conn.execute(
            f"INSERT INTO {schema}.nf_atuais(tabela,chave,registro) SELECT tabela,chave,registro FROM {schema}.nf_stage WHERE "
            + where
            + f" AND registro IS NOT NULL ON CONFLICT(tabela,chave) DO UPDATE SET registro=excluded.registro WHERE {schema}.nf_atuais.registro IS DISTINCT FROM excluded.registro",
            bounds,
        )
        conn.execute(
            f"DELETE FROM {schema}.nf_atuais a USING {schema}.nf_stage s WHERE "
            + where.replace("execucao", "s.execucao").replace(
                "(tabela,chave)", "(s.tabela,s.chave)"
            )
            + " AND s.registro IS NULL AND a.tabela=s.tabela AND a.chave=s.chave",
            bounds,
        )
        blocks += 1
        if blocks == 1 or blocks % 10 == 0:
            logging.info(
                "[FECHAMENTO] Registros processados=%s; blocos=%s; aguardando validações e commit.",
                total,
                blocks,
            )
        after = end
