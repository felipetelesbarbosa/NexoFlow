"""Detalhe acumulado sem descartar o histórico que não estava no BI operacional.

As chaves operacionais reconciliadas têm precedência por venda completa. Itens só
conservados no histórico usam namespace próprio; não se inventa preço unitário.
"""

from typing import LiteralString

from psycopg import sql


def create_farma_sales_view(conn):
    """Resumo diário da mesma venda válida que alimenta itens e Curva ABC."""
    conn.execute("""
        CREATE OR REPLACE VIEW farma.ds_bi_vendas WITH(security_barrier=true) AS
        WITH unidades_por_venda AS (
          SELECT data, venda_chave,
            CASE WHEN count(quantidade)=count(*) THEN sum(quantidade) END AS unidades
          FROM farma.ds_bi_itens GROUP BY data, venda_chave
        ), vendas AS (
          SELECT v.data, count(*)::numeric AS pedidos,
            count(DISTINCT nullif(v.cliente_chave,''))::numeric AS compradores,
            CASE WHEN count(u.unidades)=count(*) THEN sum(u.unidades) END AS unidades,
            CASE WHEN count(v.faturamento_produtos)=count(*) THEN sum(v.faturamento_produtos) END AS produtos,
            CASE WHEN count(v.frete)=count(*) THEN sum(v.frete) END AS frete,
            CASE WHEN count(v.faturamento)=count(*) THEN sum(v.faturamento) END AS total
          FROM farma.ds_bi_clientes_vendas v
          LEFT JOIN unidades_por_venda u USING (data,venda_chave)
          WHERE v.data IS NOT NULL
          GROUP BY v.data
        ), cadastro_dias AS (
          SELECT controle.nf_data(registro->>'data') AS data,
            nullif(registro->>'pedidos','')::numeric AS pedidos,
            registro->>'atualizado_em' AS atualizado_em
          FROM farma.nf_atuais WHERE tabela='BI_Vendas'
        )
        SELECT coalesce(v.data,d.data) AS data,
          coalesce(v.pedidos,0) AS pedidos,
          coalesce(v.pedidos,0) AS pedidos_confirmados_api,
          coalesce(v.compradores,0) AS clientes_compradores,
          CASE WHEN v.data IS NULL THEN 0::numeric ELSE v.unidades END AS unidades_vendidas,
          CASE WHEN v.data IS NULL THEN 0::numeric ELSE v.produtos END AS faturamento_produtos,
          CASE WHEN v.data IS NULL THEN 0::numeric ELSE v.frete END AS faturamento_frete,
          CASE WHEN v.data IS NULL THEN 0::numeric ELSE v.total END AS faturamento_total,
          CASE WHEN v.data IS NULL THEN 0::numeric ELSE v.total END AS faturamento,
          CASE WHEN v.data IS NULL THEN 0::numeric ELSE v.total END AS faturamento_confirmado_api,
          CASE WHEN v.data IS NULL THEN 0::numeric ELSE round(v.total/v.pedidos,2) END AS ticket_medio,
          CASE WHEN v.pedidos>0 THEN 100 ELSE 0 END::numeric AS taxa_confirmacao_pct,
          coalesce(d.atualizado_em,'') AS atualizado_em
        FROM vendas v FULL JOIN cadastro_dias d USING (data)
        WHERE v.data IS NOT NULL OR (d.data IS NOT NULL AND d.pedidos=0)
    """)


def create_financial_views(conn):
    for schema in ("farma", "pet"):
        # Os identificadores são somente constantes do contrato, nunca parâmetros HTTP.
        def run(statement, schema=schema):
            conn.execute(sql.SQL(statement).format(s=sql.Identifier(schema)))

        # Escolha por venda inteira. Uma projeção operacional com soma menor
        # só pode ser substituída quando TODOS os produtos históricos válidos
        # reconciliam exatamente com o cabeçalho. Divergência acima do cabeçalho
        # continua sendo erro financeiro, não prova de projeção incompleta.
        run("""CREATE OR REPLACE VIEW {s}.ds_bi_itens WITH(security_barrier=true) AS
        WITH cabecalhos AS MATERIALIZED (
          SELECT h.*,substring(encode(sha256(convert_to('venda:FARMALIDER:'||h.pedido_id,'UTF8')),'hex'),1,32) AS venda_chave
          FROM {s}.ds_historico_pedidos h
          WHERE h.vigente='Sim' AND h.estado='valido'
          AND NOT EXISTS(SELECT 1 FROM {s}.ds_exclusoes_publicacao x WHERE x.pedido_id=h.pedido_id)
        ), historicos AS MATERIALIZED (
          SELECT i.*,h.venda_chave,h.cliente_id,h.data
          FROM {s}.ds_historico_itens i JOIN cabecalhos h
            ON h.pedido_id=i.pedido_id AND h.segmento=i.segmento
          WHERE i.vigente='Sim' AND i.estado='valido' AND i.frete='Não'
        ), totais_historicos AS (
          SELECT venda_chave,sum(valor) AS produtos,
            bool_and(coalesce(quantidade>0 AND valor>=0,false)) AS validos
          FROM historicos GROUP BY venda_chave
        ), totais_operacionais AS (
          SELECT venda_chave,sum(receita_item) AS produtos,
            bool_and(coalesce(quantidade>0 AND receita_item>=0,false)) AS validos
          FROM {s}.ds_bi_itens_operacional GROUP BY venda_chave
        ), usar_historico AS MATERIALIZED (
          SELECT h.venda_chave FROM cabecalhos h
          JOIN totais_historicos i USING(venda_chave)
          LEFT JOIN totais_operacionais b USING(venda_chave)
          WHERE i.validos AND i.produtos=h.produtos
          AND (b.venda_chave IS NULL OR (b.validos AND b.produtos<h.produtos))
        )
        SELECT b.* FROM {s}.ds_bi_itens_operacional b
        WHERE NOT EXISTS(SELECT 1 FROM {s}.ds_exclusoes_publicacao x WHERE b.venda_chave=substring(encode(sha256(convert_to('venda:FARMALIDER:'||x.pedido_id,'UTF8')),'hex'),1,32))
        AND NOT EXISTS(SELECT 1 FROM {s}.ds_historico_pedidos h
          WHERE substring(encode(sha256(convert_to('venda:FARMALIDER:'||h.pedido_id,'UTF8')),'hex'),1,32)=b.venda_chave
          AND (h.vigente<>'Sim' OR h.estado<>'valido'))
        AND NOT EXISTS(SELECT 1 FROM usar_historico h WHERE h.venda_chave=b.venda_chave)
        UNION ALL
        SELECT substring(encode(sha256(convert_to('historico_item:'||i.chave,'UTF8')),'hex'),1,32) AS item_chave,
          i.venda_chave,
          substring(encode(sha256(convert_to('farmalider:'||i.cliente_id,'UTF8')),'hex'),1,32) AS cliente_chave,
          i.data,i.sku AS produto_codigo,i.produto AS produto_nome,''::text AS categoria,
          i.quantidade,NULL::numeric AS valor_unitario,i.valor AS receita_item,
          CASE WHEN coalesce(i.sku,'')<>'' THEN 1 ELSE 0 END::numeric AS sku_informado,
          ''::text AS atualizado_em
        FROM historicos i JOIN usar_historico h USING(venda_chave)""")
        # Uma linha por venda oficial. Nomes só são reaproveitados pela identidade
        # oficial; ausência de contato/nome não altera o universo financeiro.
        run("""CREATE OR REPLACE VIEW {s}.ds_bi_clientes_vendas WITH(security_barrier=true) AS
        SELECT b.* FROM {s}.ds_bi_clientes_vendas_operacional b
        WHERE NOT EXISTS(SELECT 1 FROM {s}.ds_exclusoes_publicacao x WHERE b.venda_chave=substring(encode(sha256(convert_to('venda:FARMALIDER:'||x.pedido_id,'UTF8')),'hex'),1,32))
        AND NOT EXISTS(SELECT 1 FROM {s}.ds_historico_pedidos h
          WHERE substring(encode(sha256(convert_to('venda:FARMALIDER:'||h.pedido_id,'UTF8')),'hex'),1,32)=b.venda_chave)
        UNION ALL
        SELECT substring(encode(sha256(convert_to('venda:FARMALIDER:'||h.pedido_id,'UTF8')),'hex'),1,32),
          substring(encode(sha256(convert_to('farmalider:'||h.cliente_id,'UTF8')),'hex'),1,32),
          coalesce((SELECT b.cliente FROM {s}.ds_bi_clientes_vendas_operacional b WHERE b.venda_chave=substring(encode(sha256(convert_to('venda:FARMALIDER:'||h.pedido_id,'UTF8')),'hex'),1,32)),''),
          h.data,1::numeric,h.produtos,h.frete,h.faturamento,''::text
        FROM {s}.ds_historico_pedidos h WHERE h.vigente='Sim' AND h.estado='valido' AND NOT EXISTS(SELECT 1 FROM {s}.ds_exclusoes_publicacao x WHERE x.pedido_id=h.pedido_id) """)
        run("""CREATE OR REPLACE VIEW {s}.ds_bi_clientes WITH(security_barrier=true) AS
        SELECT v.cliente_chave,coalesce(max(nullif(v.cliente,'')),max(nullif(b.cliente,'')),'')::text AS cliente,
          count(DISTINCT v.venda_chave)::numeric AS pedidos_identificados,
          sum(v.faturamento)::numeric AS faturamento_identificado,
          max(v.data) AS ultima_compra_identificada,
          ''::text AS atualizado_em,coalesce(max(b.compra_pendente_validacao),0)::numeric AS compra_pendente_validacao
        FROM {s}.ds_bi_clientes_vendas v LEFT JOIN {s}.ds_bi_clientes_operacional b USING(cliente_chave)
        GROUP BY v.cliente_chave""")
        if schema == "farma":
            create_farma_orders_view(conn)
            create_farma_sales_view(conn)
        else:
            _create_legacy_orders_view(conn, schema)


_CUSTOMER_KEY = "substring(encode(sha256(convert_to('farmalider:'||h.cliente_id,'UTF8')),'hex'),1,32)"


def _order_columns(*, resolve_order_id=False):
    # Mesmo contrato do painel. O histórico conserva valores financeiros e
    # identidade; somente o operacional comprovado complementa os demais campos.
    from ds_backend.contract import REGISTRY

    fields = REGISTRY["BI_Pedidos"]["columns"]
    operational: list[sql.Composable] = [
        sql.SQL("b.{}").format(sql.Identifier(f)) for f in fields
    ]
    expressions: dict[str, LiteralString] = {
        "pedido_chave": "'FARMALIDER:'||h.pedido_id",
        "pedido_id": "h.pedido_id",
        "data": "h.data",
        "pedido_valor_produtos": "h.produtos::text",
        "pedido_valor": "h.faturamento",
        "pedido_frete": "h.frete",
        "pedido_faturamento_total": "h.faturamento",
        "cliente_chave": _CUSTOMER_KEY,
        "venda_valida": "CASE WHEN h.estado='valido' THEN 1 ELSE 0 END::numeric",
    }
    historical = [
        sql.SQL(expressions[f]) if f in expressions else column
        for f, column in zip(fields, operational, strict=True)
    ]
    if resolve_order_id:
        operational[fields.index("pedido_id")] = sql.SQL(
            "coalesce(b.id_oficial,b.pedido_id) AS pedido_id"
        )
    return sql.SQL(",").join(operational), sql.SQL(",").join(historical)


def _create_legacy_orders_view(conn, schema):
    _, historical = _order_columns()
    conn.execute(
        sql.SQL("""CREATE OR REPLACE VIEW {s}.ds_bi_pedidos WITH(security_barrier=true) AS
           SELECT b.* FROM {s}.ds_bi_pedidos_operacional b WHERE NOT EXISTS(SELECT 1 FROM {s}.ds_exclusoes_publicacao x WHERE x.pedido_id=b.pedido_id) AND NOT EXISTS(
             SELECT 1 FROM {s}.ds_historico_pedidos h WHERE b.pedido_id=h.pedido_id)
           UNION ALL SELECT {columns}
           FROM {s}.ds_historico_pedidos h LEFT JOIN {s}.ds_bi_pedidos_operacional b
             ON b.pedido_id=h.pedido_id AND b.cliente_chave={customer}
           WHERE h.vigente='Sim' """).format(
            s=sql.Identifier(schema),
            columns=historical,
            customer=sql.SQL(_CUSTOMER_KEY),
        )
    )


def create_farma_orders_view(conn):
    """Reaplica apenas a definição de leitura FARMA, mantendo a revisão ativa."""
    operational, historical = _order_columns(resolve_order_id=True)
    conn.execute(
        sql.SQL("""CREATE OR REPLACE VIEW farma.ds_bi_pedidos WITH(security_barrier=true) AS
        WITH origens AS NOT MATERIALIZED (
          SELECT b.pedido_chave,nullif(b.pedido_id,'') AS id_campo,
            CASE WHEN b.pedido_chave LIKE 'FARMALIDER:%' THEN
              nullif(substr(b.pedido_chave,length('FARMALIDER:')+1),'') END AS id_chave
          FROM farma.ds_bi_pedidos_operacional b
        ), identidades_permitidas AS MATERIALIZED (
          -- Separar a exclusão da validação: o otimizador não pode invocar a
          -- asserção de cardinalidade para aliases já excluídos do relatório.
          SELECT o.* FROM origens o
          WHERE NOT EXISTS (SELECT 1 FROM farma.ds_exclusoes_publicacao x WHERE x.pedido_id=o.id_campo)
            AND NOT EXISTS (SELECT 1 FROM farma.ds_exclusoes_publicacao x WHERE x.pedido_id=o.id_chave)
        ), operacional AS NOT MATERIALIZED (
          SELECT b.*,CASE
            WHEN o.id_chave IS NULL OR o.id_campo IS NULL OR o.id_chave=o.id_campo
              THEN coalesce(o.id_campo,o.id_chave)
            -- Duas identidades oficiais conflitantes interrompem a consulta.
            ELSE (SELECT id FROM unnest(ARRAY[o.id_campo,o.id_chave]) AS id)
          END AS id_oficial
          FROM identidades_permitidas o JOIN farma.ds_bi_pedidos_operacional b USING(pedido_chave)
        ), sem_historico AS MATERIALIZED (
          SELECT b.* FROM operacional b
          WHERE NOT EXISTS (SELECT 1 FROM farma.ds_historico_pedidos h WHERE h.pedido_id=b.id_oficial)
        ), candidatas AS (
          SELECT CASE
            WHEN count(*)=1 THEN ARRAY[min(pedido_chave)]
            WHEN bool_or(pedido_chave='FARMALIDER:'||id_oficial)
              AND count(DISTINCT ROW(cliente_chave,data,venda_valida,pedido_valor,
                                      pedido_frete,pedido_faturamento_total))=1
              THEN ARRAY['FARMALIDER:'||id_oficial]
            ELSE array_agg(pedido_chave)
          END AS chaves
          FROM sem_historico
          GROUP BY id_oficial, CASE WHEN id_oficial IS NULL THEN pedido_chave END
        ), metadados AS (
          SELECT id_oficial,cliente_chave,CASE WHEN count(*)=1 THEN min(pedido_chave)
            ELSE max(pedido_chave) FILTER (WHERE pedido_chave='FARMALIDER:'||id_oficial)
          END AS chave
          FROM operacional WHERE id_oficial IS NOT NULL AND nullif(cliente_chave,'') IS NOT NULL
          GROUP BY id_oficial,cliente_chave
        )
        -- A subconsulta escalar exige exatamente uma candidata por venda.
        -- Uma colisão operacional ambígua interrompe inclusive COUNT/SUM.
        SELECT {operational} FROM sem_historico b JOIN candidatas c
          ON b.pedido_chave=(SELECT chave FROM unnest(c.chaves) AS chave)
        UNION ALL
        SELECT {historical} FROM farma.ds_historico_pedidos h
        LEFT JOIN metadados m ON m.id_oficial=h.pedido_id AND m.cliente_chave={customer}
          AND nullif(h.cliente_id,'') IS NOT NULL
        LEFT JOIN operacional b ON b.pedido_chave=m.chave
        WHERE h.vigente='Sim'
          AND NOT EXISTS (SELECT 1 FROM farma.ds_exclusoes_publicacao x WHERE x.pedido_id=h.pedido_id)
        """).format(
            operational=operational,
            historical=historical,
            customer=sql.SQL(_CUSTOMER_KEY),
        )
    )


def assert_financial(conn, schema):
    from ds_backend.contract import StorageError

    assert_operational_items(conn, schema)

    # Agregar cada grão antes do relacionamento: não multiplicar o cabeçalho
    # pelo número de itens nem somar LTV por mês/contato.
    mismatch = conn.execute(
        sql.SQL("""WITH itens AS(
      SELECT venda_chave,sum(receita_item) AS produtos FROM {s}.ds_bi_itens GROUP BY venda_chave)
      SELECT 1 FROM {s}.ds_historico_pedidos h LEFT JOIN itens i
       ON i.venda_chave=substring(encode(sha256(convert_to('venda:FARMALIDER:'||h.pedido_id,'UTF8')),'hex'),1,32)
      WHERE h.estado='valido' AND h.vigente='Sim' AND h.produtos IS DISTINCT FROM i.produtos LIMIT 1""").format(
            s=sql.Identifier(schema)
        )
    ).fetchone()
    if mismatch:
        raise StorageError("DS_CONFERENCIA_ITENS_PEDIDO_DIVERGENTE")
    mismatch = conn.execute(
        sql.SQL("""WITH pedidos AS(
      SELECT cliente_id,sum(faturamento) AS ltv FROM {s}.ds_historico_pedidos WHERE estado='valido' AND vigente='Sim' GROUP BY cliente_id),
      clientes AS(SELECT cliente_id,ltv_observado FROM {s}.ds_bi_ltv_clientes WHERE vigente='Sim')
      SELECT 1 FROM pedidos p FULL JOIN clientes c USING(cliente_id) WHERE p.ltv IS DISTINCT FROM c.ltv_observado LIMIT 1""").format(
            s=sql.Identifier(schema)
        )
    ).fetchone()
    if mismatch:
        raise StorageError("DS_CONFERENCIA_LTV_DIVERGENTE")


def assert_operational_items(conn, schema):
    """Guarda transacional de novos READY; históricos têm validação própria."""
    from ds_backend.contract import StorageError

    mismatch = conn.execute(
        sql.SQL("""WITH omitidas AS MATERIALIZED (
      SELECT substring(encode(sha256(convert_to('venda:FARMALIDER:'||pedido_id,'UTF8')),'hex'),1,32) AS venda_chave
      FROM {s}.ds_historico_pedidos UNION
      SELECT substring(encode(sha256(convert_to('venda:FARMALIDER:'||pedido_id,'UTF8')),'hex'),1,32)
      FROM {s}.ds_exclusoes_publicacao
    ), itens AS MATERIALIZED (
      SELECT venda_chave,count(*) AS n,count(DISTINCT item_chave) AS chaves,
      sum(round(receita_item*100)) AS centavos,
      bool_and(coalesce(quantidade>0 AND receita_item>=0 AND
        quantidade::text NOT IN ('NaN','Infinity','-Infinity') AND
        receita_item::text NOT IN ('NaN','Infinity','-Infinity') AND
        nullif(item_chave,'') IS NOT NULL,false)) AS validos,
      min(data) AS inicio,max(data) AS fim,min(cliente_chave) AS cliente_min,max(cliente_chave) AS cliente_max
      FROM {s}.ds_bi_itens_operacional GROUP BY venda_chave
    ) SELECT 1 FROM {s}.ds_bi_clientes_vendas_operacional v
    LEFT JOIN omitidas h USING(venda_chave) LEFT JOIN itens i USING(venda_chave)
    WHERE h.venda_chave IS NULL AND (nullif(v.venda_chave,'') IS NULL OR v.data IS NULL
      OR v.faturamento_produtos IS NULL OR v.faturamento_produtos<0
      OR v.faturamento_produtos::text IN ('NaN','Infinity','-Infinity')
      OR i.n IS NULL OR NOT i.validos OR i.n<>i.chaves
      OR round(v.faturamento_produtos*100) IS DISTINCT FROM i.centavos
      OR v.data IS DISTINCT FROM i.inicio OR v.data IS DISTINCT FROM i.fim
      OR v.cliente_chave IS DISTINCT FROM i.cliente_min OR v.cliente_chave IS DISTINCT FROM i.cliente_max)
    LIMIT 1""").format(s=sql.Identifier(schema))
    ).fetchone()
    if mismatch:
        raise StorageError("DS_BI_ITENS_DEFASADOS")
