-- psql -X -v revisao=UUID_READY -v inicio=AAAA-MM-DD -v fim=AAAA-MM-DD -f este-arquivo
\set ON_ERROR_STOP on
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout = '45s';
SET LOCAL enable_nestloop = off;
SELECT current_database() = 'nexoflow_datastudio'
       AND current_user = 'nf_metricas_farma_leitor'
       AND :'fim'::date - :'inicio'::date BETWEEN 0 AND 365
       AND EXISTS (SELECT 1 FROM farma.ds_metricas_publicacao
                   WHERE revisao = :'revisao'::uuid) AS conferido \gset
\if :conferido
SELECT p.versao, p.revisao,
       :'inicio'::date AS inicio, :'fim'::date AS fim,
       coalesce(sum(v.pedidos), 0) AS pedidos,
       coalesce(sum(v.faturamento_produtos), 0) AS produtos,
       coalesce(sum(v.faturamento_frete), 0) AS frete,
       coalesce(sum(v.faturamento_total), 0) AS faturamento,
       count(v.data) AS dias_com_registro,
       count(v.data) FILTER (
         WHERE pedidos IS NULL OR faturamento_produtos IS NULL
            OR faturamento_frete IS NULL OR faturamento_total IS NULL
            OR faturamento_produtos + faturamento_frete <> faturamento_total
       ) AS dias_inconsistentes
FROM farma.ds_metricas_publicacao p
LEFT JOIN farma.ds_bi_vendas v ON v.data BETWEEN :'inicio'::date AND :'fim'::date
GROUP BY p.versao, p.revisao;
COMMIT;
\else
DO $$BEGIN RAISE EXCEPTION 'METRICAS_CONFERENCIA_FORA_DO_DESTINO_REVISAO_OU_PERIODO'; END$$;
\endif
