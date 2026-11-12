"""Detalhe acumulado sem descartar o histórico que não estava no BI operacional.

As chaves operacionais existentes têm precedência por venda completa. Itens só
conservados no histórico usam namespace próprio; não se inventa preço unitário.
"""

from psycopg import sql


def create_financial_views(conn):
    for schema in ("farma", "pet"):
        # Os identificadores são somente constantes do contrato, nunca parâmetros HTTP.
        def run(statement, schema=schema):
            conn.execute(sql.SQL(statement).format(s=sql.Identifier(schema)))

        run("""CREATE OR REPLACE VIEW {s}.ds_bi_itens WITH(security_barrier=true) AS
        SELECT b.* FROM {s}.ds_bi_itens_operacional b
        WHERE NOT EXISTS(SELECT 1 FROM {s}.ds_exclusoes_publicacao x WHERE b.venda_chave=substring(encode(sha256(convert_to('venda:FARMALIDER:'||x.pedido_id,'UTF8')),'hex'),1,32))
        AND NOT EXISTS(SELECT 1 FROM {s}.ds_historico_pedidos h
          WHERE substring(encode(sha256(convert_to('venda:FARMALIDER:'||h.pedido_id,'UTF8')),'hex'),1,32)=b.venda_chave
          AND (h.vigente<>'Sim' OR h.estado<>'valido'))
        UNION ALL
        SELECT substring(encode(sha256(convert_to('historico_item:'||i.chave,'UTF8')),'hex'),1,32) AS item_chave,
        substring(encode(sha256(convert_to('venda:FARMALIDER:'||h.pedido_id,'UTF8')),'hex'),1,32) AS venda_chave,
        substring(encode(sha256(convert_to('farmalider:'||h.cliente_id,'UTF8')),'hex'),1,32) AS cliente_chave,
        h.data, i.sku AS produto_codigo,i.produto AS produto_nome,''::text AS categoria,
        i.quantidade,NULL::numeric AS valor_unitario,i.valor AS receita_item,
        CASE WHEN coalesce(i.sku,'')<>'' THEN 1 ELSE 0 END::numeric AS sku_informado,
        ''::text AS atualizado_em
        FROM {s}.ds_historico_itens i JOIN {s}.ds_historico_pedidos h ON h.pedido_id=i.pedido_id AND h.segmento=i.segmento
        WHERE h.vigente='Sim' AND h.estado='valido' AND NOT EXISTS(SELECT 1 FROM {s}.ds_exclusoes_publicacao x WHERE x.pedido_id=h.pedido_id) AND i.vigente='Sim' AND i.estado='valido' AND i.frete='Não'
        AND NOT EXISTS(SELECT 1 FROM {s}.ds_bi_itens_operacional b WHERE b.venda_chave=substring(encode(sha256(convert_to('venda:FARMALIDER:'||h.pedido_id,'UTF8')),'hex'),1,32))""")
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
        # Mesmo ID de campo do painel; os campos que o histórico publicado não
        # conserva ficam nulos/vazios. Não inventar hora, pagamento ou anúncio.
        from ds_backend.contract import REGISTRY

        spec = REGISTRY["BI_Pedidos"]
        customer = "substring(encode(sha256(convert_to('farmalider:'||h.cliente_id,'UTF8')),'hex'),1,32)"
        expressions = {
            "pedido_chave": "'FARMALIDER:'||h.pedido_id",
            "pedido_id": "h.pedido_id",
            "data": "h.data",
            "pedido_valor_produtos": "h.produtos::text",
            "pedido_valor": "h.faturamento",
            "pedido_frete": "h.frete",
            "pedido_faturamento_total": "h.faturamento",
            "cliente_chave": customer,
            "venda_valida": "CASE WHEN h.estado='valido' THEN 1 ELSE 0 END::numeric",
        }
        for field in spec["columns"]:
            if field not in expressions:
                expressions[field] = 'b."' + field + '"'
        # Labels/atribuição existentes são reutilizados apenas com o mesmo cliente oficial.
        connection = sql.SQL("""CREATE OR REPLACE VIEW {s}.ds_bi_pedidos WITH(security_barrier=true) AS
           SELECT b.* FROM {s}.ds_bi_pedidos_operacional b WHERE NOT EXISTS(SELECT 1 FROM {s}.ds_exclusoes_publicacao x WHERE x.pedido_id=b.pedido_id) AND NOT EXISTS(
             SELECT 1 FROM {s}.ds_historico_pedidos h WHERE b.pedido_id=h.pedido_id)
           UNION ALL SELECT {columns}
           FROM {s}.ds_historico_pedidos h LEFT JOIN {s}.ds_bi_pedidos_operacional b
             ON b.pedido_id=h.pedido_id AND b.cliente_chave={customer}
           WHERE h.vigente='Sim' """).format(
            s=sql.Identifier(schema),
            columns=sql.SQL(",").join(sql.SQL(expressions[f]) for f in spec["columns"]),
            customer=sql.SQL(customer),
        )
        conn.execute(connection)


def assert_financial(conn, schema):
    from ds_backend.contract import StorageError

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
