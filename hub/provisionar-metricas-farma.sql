-- Executar no banco comercial nexoflow_datastudio pelo proprietário das visões.
-- Criar antes o papel dedicado nf_metricas_farma_leitor com LOGIN, NOINHERIT,
-- NOSUPERUSER, NOCREATEDB, NOCREATEROLE, NOREPLICATION, NOBYPASSRLS e limite de
-- duas conexões. Definir a senha em canal privado, fora deste arquivo.
\set ON_ERROR_STOP on
BEGIN;
DO $$
BEGIN
    IF current_database() <> 'nexoflow_datastudio' THEN
        RAISE EXCEPTION 'METRICAS_BANCO_INCORRETO';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_roles
        WHERE rolname = 'nf_metricas_farma_leitor' AND rolcanlogin AND NOT rolsuper
          AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication
          AND NOT rolbypassrls AND NOT rolinherit AND rolconnlimit BETWEEN 1 AND 2
    ) OR EXISTS (
        SELECT 1 FROM pg_auth_members
        WHERE member = 'nf_metricas_farma_leitor'::regrole
    ) THEN
        RAISE EXCEPTION 'METRICAS_PAPEL_LEITOR_INVALIDO';
    END IF;
END $$;

CREATE OR REPLACE VIEW farma.ds_metricas_publicacao WITH (security_barrier = true) AS
SELECT p.execucao AS revisao, p.versao
FROM controle.nf_publicacoes p
JOIN controle.nf_execucoes e
  ON e.id = p.execucao AND e.versao = p.versao AND e.segmento = p.segmento
WHERE p.segmento = 'FARMA' AND p.versao > 0 AND e.estado = 'READY';

GRANT CONNECT ON DATABASE nexoflow_datastudio TO nf_metricas_farma_leitor;
GRANT USAGE ON SCHEMA farma TO nf_metricas_farma_leitor;
GRANT SELECT ON farma.ds_metricas_publicacao TO nf_metricas_farma_leitor;
GRANT SELECT (data, pedidos, faturamento_produtos, faturamento_frete, faturamento_total)
    ON farma.ds_bi_vendas TO nf_metricas_farma_leitor;
GRANT SELECT (data, produto_codigo, produto_nome, quantidade, receita_item)
    ON farma.ds_bi_itens TO nf_metricas_farma_leitor;
DO $$
BEGIN
    IF to_regprocedure('farma.ds_veiculacao_meta_v4(date,date,boolean)') IS NOT NULL
       AND to_regprocedure('farma.ds_atribuicao_periodo_v1(date,date,boolean)') IS NOT NULL THEN
        GRANT EXECUTE ON FUNCTION farma.ds_veiculacao_meta_v4(date,date,boolean),
            farma.ds_atribuicao_periodo_v1(date,date,boolean) TO nf_metricas_farma_leitor;
    END IF;
END $$;
CREATE OR REPLACE FUNCTION farma.ds_metricas_pedidos_anuncios(
    inicio date, fim date, tipo text, identificador text
)
RETURNS TABLE(anuncio text, campanha text, presente boolean, completa boolean,
    conversa date, emissao date, vinculo text, receita numeric)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $sql$
    WITH midia AS MATERIALIZED (
        SELECT registro AS fato FROM farma.nf_atuais
        WHERE tabela = 'Meta_Ads_Diario'
          AND registro->>'segmento' = 'FARMA' AND registro->>'classificacao' = 'FARMA'
          AND 0 <= fim - inicio AND fim - inicio < 366
          AND identificador ~ '^[0-9]{1,25}$'
    ), alvos AS (
        SELECT fato->>'conta_id' AS conta, fato->>'anuncio_id' AS ad,
               fato->>'moeda' AS moeda, fato->>'fuso' AS fuso,
               fato->>'politica_atribuicao' AS politica,
               max(nullif(fato->>'campanha_nome', '')) AS nome
        FROM midia
        WHERE CASE tipo WHEN 'campanha' THEN fato->>'campanha_id'
                        WHEN 'grupo' THEN fato->>'conjunto_id'
                        WHEN 'anuncio' THEN fato->>'anuncio_id' END = identificador
          AND fato->>'data' BETWEEN to_char(inicio, 'YYYY-MM-DD') AND to_char(fim, 'YYYY-MM-DD')
          AND nullif(fato->>'anuncio_id', '') IS NOT NULL
        GROUP BY 1, 2, 3, 4, 5
    ), pacotes AS (
        SELECT a.ad, a.nome, a.conta, a.moeda, a.fuso, a.politica, e.evidencia
        FROM alvos a LEFT JOIN LATERAL (
            SELECT k.evidencia
            FROM midia m CROSS JOIN LATERAL (
                SELECT nullif(m.fato->>'payload_api_json', '')::jsonb->'nf_pedidos_periodo_v1' AS evidencia
            ) k
            WHERE (m.fato->>'conta_id', m.fato->>'anuncio_id', m.fato->>'moeda',
                   m.fato->>'fuso', m.fato->>'politica_atribuicao')
                  = (a.conta, a.ad, a.moeda, a.fuso, a.politica)
              AND k.evidencia IS NOT NULL
            ORDER BY k.evidencia->>'coletado_em' DESC NULLS LAST, m.fato->>'data' DESC, m.fato->>'chave'
            LIMIT 1
        ) e ON true
    )
    SELECT a.ad, a.nome, a.evidencia IS NOT NULL,
        coalesce(a.evidencia->>'cobertura' = 'conferida'
            AND (a.evidencia->>'inicio')::date <= inicio AND (a.evidencia->>'fim')::date >= fim, false),
        (p.item->>'abertura')::date, (p.item->>'emissao')::date, p.item->>'vinculo',
        (p.item->>'receita')::numeric
    FROM pacotes a LEFT JOIN LATERAL (
        SELECT item FROM jsonb_array_elements(a.evidencia->'pedidos') AS pedido(item)
        WHERE (item->>'abertura')::date BETWEEN inicio AND fim
          AND (item->>'emissao')::date BETWEEN inicio AND fim
          AND item->>'vinculo' IN ('direto', 'posterior', 'sem_vinculo_conversa')
    ) p ON true
    ORDER BY p.item->>'emissao' DESC NULLS LAST, a.ad, a.conta, a.moeda, a.fuso, a.politica,
             p.item->>'abertura', p.item->>'vinculo', p.item->>'receita'
    LIMIT 101
$sql$;
REVOKE ALL ON FUNCTION farma.ds_metricas_pedidos_anuncios(date,date,text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION farma.ds_metricas_pedidos_anuncios(date,date,text,text)
    TO nf_metricas_farma_leitor;
ALTER ROLE nf_metricas_farma_leitor IN DATABASE nexoflow_datastudio
    SET default_transaction_read_only = on;
COMMIT;
