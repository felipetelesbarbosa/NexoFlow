"""ABC por período: agrega no PostgreSQL, sem transportar fatos ao Apps Script.

O núcleo legado AbcCore.js é a referência de paridade. Valores são somados em
centavos; classes empatadas usam a participação ANTERIOR ao grupo empatado.
"""

import json
from decimal import Decimal

from psycopg import sql
from psycopg.types.json import set_json_loads

from ds_backend.contract import StorageError

COMMON = "periodo_inicio periodo_fim periodo_rotulo".split()
FIELDS = {
    "abc": COMMON
    + "produto_chave produto_codigo produto_nome categoria unidades receita_produtos pedidos ranking_receita ranking_unidades participacao_receita participacao_acumulada participacao_receita_pct participacao_acumulada_pct classe_abc abc_disponivel atualizado_em".split(),
    "resumo": COMMON
    + "produtos_classe_a produtos_classe_b produtos_classe_c receita_classe_a receita_classe_b receita_classe_c participacao_top5_receita skus_distintos faturamento_produtos participacao_top5_receita_pct abc_disponivel atualizado_em".split(),
    "juntos": COMMON
    + "produto_a_codigo produto_a_nome produto_b_codigo produto_b_nome pedidos_juntos atualizado_em".split(),
}

# As duas visões já aplicam exclusões, vigência, cancelamentos e escolha de
# itens por venda inteira. A projeção é lida uma vez por consulta/snapshot.
BASE = """WITH itens AS MATERIALIZED (
 SELECT DISTINCT item_chave,venda_chave,data,produto_codigo,produto_nome,categoria,
 quantidade,receita_item FROM {s}.ds_bi_itens WHERE data BETWEEN %s AND %s
), pedidos AS MATERIALIZED (
 SELECT DISTINCT venda_chave,data,faturamento_produtos
 FROM {s}.ds_bi_clientes_vendas WHERE data BETWEEN %s AND %s
), i AS MATERIALIZED (
 SELECT *,coalesce(nullif(btrim(produto_codigo),''),'sem_sku:'||item_chave) AS produto,
 coalesce(btrim(produto_codigo),'') AS sku,coalesce(btrim(produto_nome),'') AS nome,
 round(receita_item*100) AS centavos FROM itens
), por_venda AS MATERIALIZED (
 SELECT venda_chave,sum(centavos) AS centavos,count(*) AS n,
 count(DISTINCT nullif(sku,'')) AS skus FROM i GROUP BY venda_chave
), validacao AS MATERIALIZED (
 SELECT NOT (
 EXISTS(SELECT 1 FROM itens WHERE nullif(btrim(item_chave),'') IS NULL
   OR nullif(btrim(venda_chave),'') IS NULL OR quantidade IS NULL OR quantidade<=0
   OR quantidade::text IN ('NaN','Infinity','-Infinity')
   OR receita_item IS NULL OR receita_item<0 OR receita_item::text IN ('NaN','Infinity','-Infinity'))
 OR EXISTS(SELECT 1 FROM itens GROUP BY btrim(item_chave) HAVING count(*)>1)
 OR EXISTS(SELECT 1 FROM pedidos WHERE nullif(btrim(venda_chave),'') IS NULL
   OR faturamento_produtos IS NULL OR faturamento_produtos<0
   OR faturamento_produtos::text IN ('NaN','Infinity','-Infinity'))
 OR EXISTS(SELECT 1 FROM pedidos GROUP BY btrim(venda_chave) HAVING count(*)>1)
 OR EXISTS(SELECT 1 FROM i LEFT JOIN pedidos p USING(venda_chave)
   WHERE p.venda_chave IS NULL OR i.data<>p.data)
 OR EXISTS(SELECT 1 FROM pedidos p LEFT JOIN por_venda v USING(venda_chave)
   WHERE v.n IS NULL OR abs(round(p.faturamento_produtos*100)-v.centavos)>1)
 ) AS ok,EXISTS(SELECT 1 FROM por_venda WHERE skus>500) AS pares_excessivos,
 (SELECT coalesce(sum(centavos),0)>9007199254740991 FROM i) AS precisao_excedida
), produtos AS MATERIALIZED (
 SELECT produto,min(sku) AS sku,sum(quantidade) AS unidades,sum(centavos) AS centavos,
 count(DISTINCT venda_chave) AS pedidos FROM i GROUP BY produto
), nomes AS MATERIALIZED (
 SELECT DISTINCT ON(produto) produto,nome,coalesce(categoria,'') AS categoria
 FROM i ORDER BY produto,data DESC,nome COLLATE "C" DESC,item_chave COLLATE "C" DESC
)
"""


def decimal_json(value):
    return json.loads(value, parse_float=Decimal)


def aggregates(conn, schema, start, end, mode, limit):
    """Uma instrução, resultado limitado por produtos/pares, nunca por itens."""
    if mode == "juntos":
        query = (
            BASE
            + """, skus AS MATERIALIZED (
          SELECT DISTINCT venda_chave,sku FROM i,validacao
          WHERE sku<>'' AND ok AND NOT pares_excessivos
        ), pares AS (
          SELECT a.sku AS a,b.sku AS b,count(*) AS pedidos
          FROM skus a JOIN skus b ON a.venda_chave=b.venda_chave AND a.sku COLLATE "C"<b.sku COLLATE "C"
          GROUP BY a.sku,b.sku
        ), saida AS (
          SELECT p.*,na.nome AS nome_a,nb.nome AS nome_b FROM pares p
          JOIN nomes na ON na.produto=p.a JOIN nomes nb ON nb.produto=p.b LIMIT %s
        ) SELECT v.ok,v.pares_excessivos,v.precisao_excedida,to_jsonb(o) AS registro
          FROM validacao v LEFT JOIN saida o ON true"""
        )
    elif mode == "resumo":
        # O resumo tem UMA linha mesmo com mais de 50 mil produtos distintos.
        # Classes usam receita anterior ao grupo empatado, como no AbcCore.
        query = (
            BASE
            + """, total AS (
          SELECT coalesce(sum(centavos),0) AS valor,
            coalesce(bool_and(sku<>''),false) AND coalesce(sum(centavos),0)>0 AS disponivel
          FROM produtos
        ), ranking AS (
          SELECT p.*,row_number() OVER(ORDER BY centavos DESC,produto COLLATE "C") AS pos,
          sum(centavos) OVER(ORDER BY centavos DESC RANGE UNBOUNDED PRECEDING)
            - sum(centavos) OVER(PARTITION BY centavos) AS antes
          FROM produtos p
        ), classes AS (
          SELECT p.*,CASE WHEN disponivel THEN
            CASE WHEN antes*100<valor*80 THEN 'A'
                 WHEN antes*100<valor*95 THEN 'B' ELSE 'C' END END AS classe
          FROM ranking p CROSS JOIN total
        ), somas AS (
          SELECT count(*) FILTER(WHERE sku<>'') AS skus_distintos,
            coalesce(sum(centavos) FILTER(WHERE pos<=5),0) AS top,
            count(*) FILTER(WHERE classe='A') AS ca,
            count(*) FILTER(WHERE classe='B') AS cb,
            count(*) FILTER(WHERE classe='C') AS cc,
            coalesce(sum(centavos) FILTER(WHERE classe='A'),0) AS va,
            coalesce(sum(centavos) FILTER(WHERE classe='B'),0) AS vb,
            coalesce(sum(centavos) FILTER(WHERE classe='C'),0) AS vc
          FROM classes
        ), saida AS (
          SELECT skus_distintos,valor/100 AS faturamento_produtos,
            top/nullif(valor,0) AS participacao_top5_receita,
            top/nullif(valor,0)*100 AS participacao_top5_receita_pct,
            disponivel::int AS abc_disponivel,
            CASE WHEN disponivel THEN ca END AS produtos_classe_a,
            CASE WHEN disponivel THEN cb END AS produtos_classe_b,
            CASE WHEN disponivel THEN cc END AS produtos_classe_c,
            CASE WHEN disponivel THEN va/valor END AS receita_classe_a,
            CASE WHEN disponivel THEN vb/valor END AS receita_classe_b,
            CASE WHEN disponivel THEN vc/valor END AS receita_classe_c
          FROM somas CROSS JOIN total LIMIT %s
        ) SELECT v.ok,v.pares_excessivos,v.precisao_excedida,to_jsonb(o) AS registro
          FROM validacao v CROSS JOIN saida o"""
        )
    else:
        query = (
            BASE
            + """, saida AS (
          SELECT p.*,n.nome,n.categoria FROM produtos p JOIN nomes n USING(produto)
          CROSS JOIN validacao v WHERE v.ok LIMIT %s
        ) SELECT v.ok,v.pares_excessivos,v.precisao_excedida,to_jsonb(o) AS registro
          FROM validacao v LEFT JOIN saida o ON true"""
        )
    # JSON numeric decoding must preserve precision (psycopg defaults to float).
    set_json_loads(decimal_json, conn)
    rows = conn.execute(
        sql.SQL(query).format(s=sql.Identifier(schema)),
        (start, end, start, end, limit + 1),
    ).fetchall()
    if not rows or not rows[0]["ok"]:
        raise StorageError("DS_ABC_BASE_INCOMPLETA")
    if rows[0]["precisao_excedida"]:
        raise StorageError("DS_ABC_PRECISAO_EXCEDIDA")
    if rows[0]["pares_excessivos"]:
        raise StorageError("DS_ABC_PEDIDO_EXCEDE_LIMITE_PARES")
    result = [r["registro"] for r in rows if r["registro"] is not None]
    if len(result) > limit:
        raise StorageError("DS_CONSULTA_EXCEDE_LIMITE_USE_RESUMO_OU_PERIODO")
    return result


def js_order(value):
    """Comparação lexical do núcleo V8 (unidades UTF-16)."""
    return value.encode("utf-16-be")


def calculate(records, start, end, mode):
    common = dict(
        periodo_inicio=start,
        periodo_fim=end,
        periodo_rotulo="/".join(reversed(start.split("-")))
        + " a "
        + "/".join(reversed(end.split("-"))),
        atualizado_em="",
    )
    if mode == "resumo":
        return [dict(common, **records[0])]
    if mode == "juntos":
        # A ordem do par e o desempate conservam a comparação do JSON no JS.
        for r in records:
            if js_order(r["a"]) > js_order(r["b"]):
                r["a"], r["b"] = r["b"], r["a"]
                r["nome_a"], r["nome_b"] = r["nome_b"], r["nome_a"]
        records.sort(
            key=lambda r: (
                -r["pedidos"],
                js_order(
                    json.dumps(
                        [r["a"], r["b"]], ensure_ascii=False, separators=(",", ":")
                    )
                ),
            )
        )
        return [
            dict(
                common,
                produto_a_codigo=r["a"],
                produto_b_codigo=r["b"],
                produto_a_nome=r["nome_a"],
                produto_b_nome=r["nome_b"],
                pedidos_juntos=r["pedidos"],
            )
            for r in records
        ]
    ranked = sorted(records, key=lambda r: (-r["centavos"], js_order(r["produto"])))
    total = sum((r["centavos"] for r in ranked), Decimal(0))
    if total > 2**53 - 1:
        raise StorageError("DS_ABC_PRECISAO_EXCEDIDA")
    available = total > 0 and all(r["sku"] for r in ranked)
    unit_ranks = {}
    previous = None
    rank = 0
    for index, r in enumerate(
        sorted(ranked, key=lambda r: (-r["unidades"], js_order(r["produto"]))), 1
    ):
        if r["unidades"] != previous:
            rank = index
        unit_ranks[r["produto"]] = rank
        previous = r["unidades"]
    cumulative, previous, rank, klass = Decimal(0), None, 0, ""
    output = []
    for index, r in enumerate(ranked, 1):
        cents = Decimal(r["centavos"])
        if cents != previous:
            rank = index
            klass = (
                (
                    "A"
                    if cumulative * 100 < total * 80
                    else "B"
                    if cumulative * 100 < total * 95
                    else "C"
                )
                if available
                else ""
            )
        cumulative += cents
        previous = cents
        output.append(
            dict(
                common,
                produto_chave=r["produto"],
                produto_codigo=r["sku"],
                produto_nome=r["nome"],
                categoria=r["categoria"],
                unidades=r["unidades"],
                receita_produtos=cents / 100,
                pedidos=r["pedidos"],
                ranking_receita=rank,
                ranking_unidades=unit_ranks[r["produto"]],
                participacao_receita=cents / total if total else None,
                participacao_acumulada=cumulative / total if total else None,
                participacao_receita_pct=cents / total * 100 if total else None,
                participacao_acumulada_pct=cumulative / total * 100 if total else None,
                classe_abc=klass,
                abc_disponivel=int(available),
            )
        )
    return output
