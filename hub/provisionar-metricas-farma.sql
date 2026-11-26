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
ALTER ROLE nf_metricas_farma_leitor IN DATABASE nexoflow_datastudio
    SET default_transaction_read_only = on;
COMMIT;
