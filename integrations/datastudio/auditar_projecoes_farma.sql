-- psql -X -v revisao=UUID_READY -v inicio=AAAA-MM-DD -v fim=AAAA-MM-DD -f este-arquivo
-- A conta de leitura precisa das mesmas visões FARMA usadas pelo relatório.
\set ON_ERROR_STOP on
-- Por padrão imprime a comparação de todos os dias. Passar -v somente_diferencas=true
-- seleciona dias divergentes e TOTAL sem alterar as guardas nem o universo.
\if :{?somente_diferencas}
\else
    \set somente_diferencas false
\endif
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout = '50s';
SET LOCAL enable_nestloop = off;
SET LOCAL nexoflow.auditoria_revisao = :'revisao';

DO $$
BEGIN
    IF current_database() NOT IN ('nexoflow_datastudio','nexoflow_datastudio_homologacao')
       OR NOT EXISTS (
           SELECT 1 FROM controle.nf_publicacoes
           WHERE segmento = 'FARMA' AND versao > 0
             AND execucao = current_setting('nexoflow.auditoria_revisao')::uuid
       ) THEN
        RAISE EXCEPTION 'DS_AUDITORIA_REVISAO_ATIVA_DIVERGENTE';
    END IF;
END $$;
SELECT :'inicio'::date <= :'fim'::date AS datas_ok \gset
\if :datas_ok
\else
    DO $$BEGIN RAISE EXCEPTION 'DS_PERIODO_INVALIDO'; END$$;
\endif
SELECT segmento, execucao, versao, transaction_timestamp() AS conferido_em,
       :'inicio'::date AS inicio, :'fim'::date AS fim
FROM controle.nf_publicacoes WHERE segmento = 'FARMA';

-- Cada fonte dispõe do mesmo limite de tempo do leitor. O cliente psql só
-- conserva agregados diários. A revisão e o snapshot são comuns às consultas.
WITH grupos AS (
    SELECT coalesce(data::text,'TOTAL') AS recorte,
           count(*) FILTER (WHERE pedidos IS NULL OR faturamento_produtos IS NULL
               OR faturamento_frete IS NULL OR faturamento_total IS NULL OR unidades_vendidas IS NULL) AS campos_ausentes,
           coalesce(sum(pedidos),0) AS pedidos,
           coalesce(sum(round(faturamento_produtos*100)),0) AS produtos,
           coalesce(sum(round(faturamento_frete*100)),0) AS frete,
           coalesce(sum(round(faturamento_total*100)),0) AS total,
           coalesce(sum(unidades_vendidas),0) AS unidades
    FROM farma.ds_bi_vendas WHERE data BETWEEN :'inicio' AND :'fim'
    GROUP BY GROUPING SETS ((data),())
)
SELECT jsonb_object_agg(recorte,to_jsonb(g)-'recorte') AS resumo FROM grupos g \gset

WITH grupos AS (
    SELECT coalesce(data::text,'TOTAL') AS recorte,
           count(*) FILTER (WHERE faturamento_produtos IS NULL OR frete IS NULL OR faturamento IS NULL) AS campos_ausentes,
           count(*) AS pedidos,
           count(*) - count(DISTINCT nullif(btrim(venda_chave),'')) AS chaves_invalidas,
           coalesce(sum(round(faturamento_produtos*100)),0) AS produtos,
           coalesce(sum(round(frete*100)),0) AS frete,
           coalesce(sum(round(faturamento*100)),0) AS total
    FROM farma.ds_bi_clientes_vendas WHERE data BETWEEN :'inicio' AND :'fim'
    GROUP BY GROUPING SETS ((data),())
)
SELECT jsonb_object_agg(recorte,to_jsonb(g)-'recorte') AS vendas FROM grupos g \gset

WITH grupos AS (
    SELECT coalesce(data::text,'TOTAL') AS recorte,
           count(*) FILTER (WHERE quantidade IS NULL OR receita_item IS NULL OR nullif(btrim(venda_chave),'') IS NULL) AS campos_ausentes,
           count(*) AS itens, count(DISTINCT nullif(btrim(venda_chave),'')) AS pedidos,
           count(*) - count(DISTINCT nullif(btrim(item_chave),'')) AS chaves_invalidas,
           count(DISTINCT nullif(btrim(produto_codigo),'')) AS skus,
           coalesce(sum(quantidade),0) AS unidades,
           coalesce(sum(round(receita_item*100)),0) AS produtos
    FROM farma.ds_bi_itens WHERE data BETWEEN :'inicio' AND :'fim'
    GROUP BY GROUPING SETS ((data),())
)
SELECT jsonb_object_agg(recorte,to_jsonb(g)-'recorte') AS itens FROM grupos g \gset

-- pedido_valor_produtos é texto de exibição no legado. Frete e total do
-- cabeçalho são numéricos; só vendas válidas entram na receita. Chaves em
-- duplicidade também são contadas nas linhas de pedidos fora da receita.
WITH grupos AS (
    SELECT coalesce(data::text,'TOTAL') AS recorte,
           count(*) FILTER (WHERE venda_valida IS NULL OR
               (venda_valida=1 AND (pedido_frete IS NULL OR pedido_faturamento_total IS NULL))) AS campos_ausentes,
           count(*) FILTER (WHERE venda_valida=1) AS pedidos,
           count(nullif(btrim(pedido_id),'')) -
               count(DISTINCT nullif(btrim(pedido_id),'')) AS linhas_duplicadas,
           count(*) FILTER (WHERE venda_valida=1 AND nullif(btrim(pedido_id),'') IS NULL) AS validos_sem_id,
           coalesce(sum(round(pedido_frete*100)) FILTER (WHERE venda_valida=1),0) AS frete,
           coalesce(sum(round(pedido_faturamento_total*100)) FILTER (WHERE venda_valida=1),0) AS total
    FROM farma.ds_bi_pedidos WHERE data BETWEEN :'inicio' AND :'fim'
    GROUP BY GROUPING SETS ((data),())
)
SELECT jsonb_object_agg(recorte,to_jsonb(g)-'recorte') AS pedidos FROM grupos g \gset

-- Uma linha em TOTAL calcula distintos em todo o intervalo; ausência de dia
-- nas quatro fontes representa período vazio, incluindo zero pedidos válidos.
WITH fontes AS (
    SELECT :'resumo'::jsonb AS r, :'vendas'::jsonb AS v,
           :'itens'::jsonb AS i, :'pedidos'::jsonb AS p
), dias AS (
    SELECT recorte, r->recorte AS r, v->recorte AS v, i->recorte AS i, p->recorte AS p
    FROM fontes, jsonb_object_keys(r||v||i||p) AS recorte
), diferencas AS (
    SELECT recorte, r AS resumo, v AS vendas, i AS itens, p AS pedidos,
           coalesce((r->>'produtos')::numeric,0) - coalesce((i->>'produtos')::numeric,0) AS resumo_menos_itens_centavos,
           coalesce((r->>'produtos')::numeric,0) - coalesce((v->>'produtos')::numeric,0) AS resumo_menos_vendas_centavos,
           coalesce((r->>'unidades')::numeric,0) - coalesce((i->>'unidades')::numeric,0) AS delta_unidades,
           coalesce((r->>'pedidos')::numeric,0) = coalesce((v->>'pedidos')::numeric,0)
               AND coalesce((r->>'pedidos')::numeric,0) = coalesce((i->>'pedidos')::numeric,0)
               AND coalesce((r->>'pedidos')::numeric,0) = coalesce((p->>'pedidos')::numeric,0) AS contagens_ok,
           coalesce((r->>'frete')::numeric,0) = coalesce((v->>'frete')::numeric,0)
               AND coalesce((r->>'frete')::numeric,0) = coalesce((p->>'frete')::numeric,0) AS frete_ok,
           coalesce((r->>'total')::numeric,0) = coalesce((v->>'total')::numeric,0)
               AND coalesce((r->>'total')::numeric,0) = coalesce((p->>'total')::numeric,0)
               AND coalesce((r->>'total')::numeric,0) = coalesce((r->>'produtos')::numeric,0) + coalesce((r->>'frete')::numeric,0) AS total_ok,
           coalesce((p->>'validos_sem_id')::bigint,0) + coalesce((p->>'linhas_duplicadas')::bigint,0)
               + coalesce((v->>'chaves_invalidas')::bigint,0) + coalesce((i->>'chaves_invalidas')::bigint,0) = 0 AS chaves_ok,
           coalesce((r->>'campos_ausentes')::bigint,0) + coalesce((v->>'campos_ausentes')::bigint,0)
               + coalesce((i->>'campos_ausentes')::bigint,0) + coalesce((p->>'campos_ausentes')::bigint,0) = 0 AS campos_ok
    FROM dias
), relatorio AS (
    SELECT *, resumo_menos_itens_centavos=0 AND resumo_menos_vendas_centavos=0
        AND delta_unidades=0 AND contagens_ok AND frete_ok AND total_ok AND chaves_ok AND campos_ok AS confere
    FROM diferencas
)
SELECT jsonb_agg(to_jsonb(r) ORDER BY recorte) AS dias, bool_and(confere) AS financeiro_ok
FROM relatorio r \gset

-- Cada linha é um agregado. Para conferir só 09–12/11, executar novamente
-- com o mesmo UUID e esse intervalo: o TOTAL traz os quatro dias combinados.
SELECT d->>'recorte' AS recorte, d->'resumo' AS bi_vendas, d->'vendas' AS bi_clientes_vendas,
       d->'itens' AS bi_itens, d->'pedidos' AS bi_pedidos,
       d->'resumo_menos_itens_centavos' AS resumo_menos_itens_centavos, d->'confere' AS confere
FROM jsonb_array_elements(:'dias'::jsonb) AS d
WHERE NOT :'somente_diferencas'::boolean OR d->>'recorte'='TOTAL' OR NOT (d->>'confere')::boolean;

-- LTV acumulado por cliente oficial. Exclui clientes sem compra válida
-- no universo histórico. Nenhum filtro de período é aplicado ao LTV.
WITH h AS (
    SELECT cliente_id, count(*) AS pedidos, count(faturamento)=count(*) AS completo, sum(round(faturamento*100)) AS ltv
    FROM farma.ds_historico_pedidos WHERE segmento='FARMA' AND vigente='Sim' AND estado='valido'
    GROUP BY cliente_id
), l AS (
    SELECT cliente_id, count(*) AS n, count(*)=count(ltv_observado) AND count(*)=count(pedidos) AS completo,
           sum(pedidos) AS pedidos, sum(round(ltv_observado*100)) AS ltv
    FROM farma.ds_bi_ltv_clientes WHERE segmento='FARMA' AND vigente='Sim'
    GROUP BY cliente_id
)
SELECT count(h.cliente_id) AS clientes, coalesce(sum(h.pedidos),0) AS pedidos,
       coalesce(sum(h.ltv),0) AS ltv_centavos,
       count(*) FILTER (WHERE h.completo IS NOT TRUE OR l.completo IS NOT TRUE OR l.n IS DISTINCT FROM 1 OR h.pedidos IS DISTINCT FROM l.pedidos
                        OR h.ltv IS DISTINCT FROM l.ltv) AS clientes_divergentes
FROM h FULL JOIN l USING (cliente_id) \gset ltv_
\echo LTV histórico: clientes=:ltv_clientes pedidos=:ltv_pedidos centavos=:ltv_ltv_centavos clientes_divergentes=:ltv_clientes_divergentes
SELECT :'ltv_clientes_divergentes'::bigint = 0 AS ltv_ok \gset
\if :ltv_ok
\else
    DO $$BEGIN RAISE EXCEPTION 'DS_AUDITORIA_LTV_DIVERGENTE'; END$$;
\endif
\if :financeiro_ok
\else
    DO $$BEGIN RAISE EXCEPTION 'DS_AUDITORIA_PROJECOES_DIVERGENTES'; END$$;
\endif
COMMIT;
