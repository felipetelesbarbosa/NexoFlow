-- Somente administrador no piloto, após confirmar a visão real e criar login exclusivo.
-- Login nf_bi_itens_reader: NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS.
DO $$ BEGIN
 IF current_database()<>'nexoflow_datastudio_piloto' THEN RAISE EXCEPTION 'BI_PG_BANCO_DIVERGENTE'; END IF;
 IF to_regclass('farma.produtos_itens_datastudio') IS NULL THEN RAISE EXCEPTION 'BI_PG_VISAO_API_AUSENTE'; END IF;
 IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='nf_bi_itens_reader'
 AND (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls))
 THEN RAISE EXCEPTION 'BI_PG_LEITOR_PRIVILEGIOS'; END IF;
END $$;
GRANT CONNECT ON DATABASE nexoflow_datastudio_piloto TO nf_bi_itens_reader;
GRANT USAGE ON SCHEMA farma,nexoflow_publicacao TO nf_bi_itens_reader;
GRANT SELECT ON farma.produtos_itens_datastudio,nexoflow_publicacao.estado_leitura TO nf_bi_itens_reader;
-- Não conceder SELECT na tabela-base ou nos journals; não conceder DML, DDL ou TEMP.

-- farma.produtos_itens e todos os privilégios atuais do Metabase permanecem intocados.
