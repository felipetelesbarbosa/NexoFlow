-- Após migrate, executar como administrador SOMENTE no piloto.
-- Criar antes um login exclusivo nf_bi_itens_publisher via canal privado,
-- sem superuser/createdb/createrole/replication/bypassrls. Não usar owner/postgres.
DO $$ BEGIN
 IF current_database()<>'nexoflow_datastudio_piloto' THEN
  RAISE EXCEPTION 'BI_PG_BANCO_DIVERGENTE';
 END IF;
 IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='nf_bi_itens_publisher'
 AND (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls)) THEN
  RAISE EXCEPTION 'BI_PG_PRIVILEGIOS_EXCESSIVOS';
 END IF;
END $$;
GRANT CONNECT,TEMPORARY ON DATABASE nexoflow_datastudio_piloto TO nf_bi_itens_publisher;
GRANT USAGE ON SCHEMA farma,nexoflow_publicacao TO nf_bi_itens_publisher;
GRANT SELECT,INSERT,UPDATE,DELETE ON farma.bi_itens TO nf_bi_itens_publisher;
GRANT SELECT,INSERT ON nexoflow_publicacao.sessions,nexoflow_publicacao.batches,
 nexoflow_publicacao.changes,nexoflow_publicacao.sale_batches TO nf_bi_itens_publisher;
GRANT SELECT,UPDATE ON nexoflow_publicacao.watermark TO nf_bi_itens_publisher;
GRANT USAGE ON SEQUENCE nexoflow_publicacao.sessions_revision_seq TO nf_bi_itens_publisher;
-- Sem CREATE no schema, sem DDL, sem privilégios em outros bancos/tabelas.
-- A visão farma.produtos_itens e o usuário somente leitura do Metabase não mudam.
GRANT SELECT,INSERT,UPDATE ON nexoflow_publicacao.plans TO nf_bi_itens_publisher;
