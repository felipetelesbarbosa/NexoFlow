"""Confere a ds133 por anúncio usando a READY e um recorte idêntico da cópia."""

import argparse
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from psycopg import Error

from ds_backend.contract import StorageError
from integrations.datastudio.store import Store

SOURCE = """
WITH base AS (
  SELECT b.*, d.registro->>'campanha_id' AS campanha_id,
       d.registro->>'campanha_nome' AS campanha,
       d.registro->>'anuncio_status' AS anuncio_status
  FROM farma.ds_bi_meta_resultados b
  LEFT JOIN farma.nf_atuais d
    ON d.tabela='Meta_Ads_Diario' AND d.registro->>'chave'=b.chave
  WHERE b.data BETWEEN %s AND %s
)
SELECT anuncio_id,conta_id,segmento,classificacao,moeda,fuso,politica_atribuicao,
   array_agg(DISTINCT campanha_id) FILTER (WHERE nullif(campanha_id,'') IS NOT NULL) AS campanhas,
   array_agg(DISTINCT campanha) FILTER (WHERE nullif(campanha,'') IS NOT NULL) AS nomes_campanha,
   array_agg(DISTINCT anuncio_status) FILTER (WHERE nullif(anuncio_status,'') IS NOT NULL) AS estados,
   count(*) AS linhas,count(DISTINCT data) AS dias,min(data) AS inicio,max(data) AS fim,
   100*sum(investimento_atribuivel) AS investimento_centavos,
   100*sum(investimento_original) AS investimento_original_centavos,
   sum(conversas_iniciadas_meta) AS conversas_meta,
   sum(conversas) AS conversas_weni,
   sum(eventos_ctwa) AS eventos_ctwa,
   count(*) FILTER (WHERE investimento_atribuivel IS NULL) AS linhas_sem_investimento,
   count(*) FILTER (WHERE conversas_iniciadas_meta IS NULL) AS linhas_sem_conversas_meta
FROM base
GROUP BY anuncio_id,conta_id,segmento,classificacao,moeda,fuso,politica_atribuicao
ORDER BY anuncio_id,conta_id,classificacao,moeda,fuso,politica_atribuicao
"""


def whole(value):
    if value is None:
        return None
    if not value.is_finite() or value != int(value):
        raise StorageError("DS_ANUNCIOS_PRECISAO")
    return int(value)


def compare(rows, copy):
    fields = {"anuncio_id", "investimento_centavos", "conversas_meta"}
    observed = {}
    if not isinstance(copy, list):
        raise StorageError("DS_ANUNCIOS_COPIA_INVALIDA")
    for row in copy:
        if (
            not isinstance(row, dict)
            or row.keys() != fields
            or not isinstance(row["anuncio_id"], str)
            or not row["anuncio_id"].strip()
            or row["anuncio_id"] in observed
            or any(
                row[f] is not None and type(row[f]) is not int
                for f in ("investimento_centavos", "conversas_meta")
            )
        ):
            raise StorageError("DS_ANUNCIOS_COPIA_INVALIDA")
        observed[row["anuncio_id"]] = row
    expected = {}
    for row in rows:
        if (row["segmento"], row["classificacao"], row["moeda"]) != (
            "FARMA",
            "FARMA",
            "BRL",
        ):
            continue
        ad = row["anuncio_id"]
        if not ad or ad in expected or row["linhas"] > row["dias"]:
            # Dois grãos oficiais com mesmo ID podem descrever o mesmo gasto.
            raise StorageError("DS_ANUNCIOS_GRAO_AMBIGUO")
        expected[ad] = row
    result = []
    for ad in sorted(expected.keys() | observed.keys()):
        pg, looker = expected.get(ad), observed.get(ad)
        present = "AMBOS" if pg and looker else "SO_POSTGRESQL" if pg else "SO_COPIA"
        detail = {"anuncio_id": ad, "presenca": present}
        for field, missing in (
            ("investimento_centavos", "linhas_sem_investimento"),
            ("conversas_meta", "linhas_sem_conversas_meta"),
        ):
            left = pg[field] if pg else 0
            right = looker[field] if looker else 0
            detail[field + "_delta_pg_menos_copia"] = (
                None
                if left is None or right is None or (pg and pg[missing])
                else left - right
            )
        result.append(detail)
    return result


def audit(store, revision, start, end, copy=None):
    if store.segment != "FARMA":
        raise StorageError("DS_SEGMENTO_DIVERGENTE")
    if start > end:
        raise StorageError("DS_PERIODO_INVALIDO")
    with store.connect(readonly=True) as conn:
        active = store.active(conn)
        expected = store.revision(conn, revision)
        if expected["estado"] != "READY" or expected["versao"] != active:
            raise StorageError("DS_REVISAO_FORA_DE_ORDEM")
        rows = conn.execute(SOURCE, (start, end)).fetchall()
    for row in rows:
        for name, value in row.items():
            if isinstance(value, Decimal):
                row[name] = whole(value)
    return dict(
        versao=active,
        revisao=revision,
        inicio=start,
        fim=end,
        linhas_por_anuncio=rows,
        conciliacao=None if copy is None else compare(rows, copy),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn-file", type=Path, required=True)
    parser.add_argument(
        "--ambiente", choices=("producao", "homologacao"), required=True
    )
    parser.add_argument("--revisao", required=True)
    parser.add_argument("--inicio", type=date.fromisoformat, required=True)
    parser.add_argument("--fim", type=date.fromisoformat, required=True)
    parser.add_argument("--copia", type=Path)
    args = parser.parse_args()
    try:
        dsn = args.dsn_file.read_text(encoding="utf-8-sig").strip()
        copy = (
            json.loads(args.copia.read_text(encoding="utf-8-sig"))
            if args.copia
            else None
        )
        if args.copia and copy is None:
            raise StorageError("DS_ANUNCIOS_COPIA_INVALIDA")
        result = audit(
            Store(dsn, args.ambiente, "FARMA"),
            args.revisao,
            args.inicio,
            args.fim,
            copy,
        )
    except StorageError as exc:
        parser.exit(3, str(exc) + "\n")
    except (OSError, ValueError):
        parser.exit(3, "DS_ANUNCIOS_ARQUIVO_INVALIDO\n")
    except Error:
        parser.exit(3, "DS_ANUNCIOS_LEITURA_INDISPONIVEL\n")
    print(json.dumps(result, ensure_ascii=False, default=date.isoformat))


if __name__ == "__main__":
    main()
