-- Aditiva e isolada. Não executa CREATE DATABASE nem altera o piloto/Hub/n8n.
DO $$ BEGIN
 IF current_database() NOT IN ('nexoflow_datastudio','nexoflow_datastudio_homologacao') THEN
  RAISE EXCEPTION 'DS_BANCO_DIVERGENTE';
 END IF;
 EXECUTE format('REVOKE CONNECT,TEMPORARY ON DATABASE %I FROM PUBLIC',current_database());
END $$;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
CREATE SCHEMA IF NOT EXISTS controle;
CREATE SCHEMA IF NOT EXISTS farma;
CREATE SCHEMA IF NOT EXISTS pet;
CREATE TABLE IF NOT EXISTS controle.nf_execucoes(
 id uuid PRIMARY KEY, segmento text NOT NULL CHECK(segmento IN ('FARMA','PET')),
 versao bigint GENERATED ALWAYS AS IDENTITY UNIQUE, base bigint NOT NULL,
 estado text NOT NULL CHECK(estado IN ('WRITING','READY','ABORTADA')),
 finalidade text NOT NULL, evidencia jsonb NOT NULL DEFAULT '{}',
 criado timestamptz NOT NULL DEFAULT clock_timestamp(),
 heartbeat timestamptz NOT NULL DEFAULT clock_timestamp(),
 confirmado timestamptz, manifest jsonb, recibo jsonb
);
CREATE TABLE IF NOT EXISTS controle.nf_publicacoes(
 segmento text PRIMARY KEY, versao bigint NOT NULL DEFAULT 0, execucao uuid
);
INSERT INTO controle.nf_publicacoes(segmento) VALUES('FARMA'),('PET') ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS controle.nf_lotes(
 id uuid PRIMARY KEY, execucao uuid NOT NULL REFERENCES controle.nf_execucoes(id),
 hash text NOT NULL, recibo jsonb NOT NULL, criado timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS controle.nf_substituicoes(
 execucao uuid NOT NULL REFERENCES controle.nf_execucoes(id), tabela text NOT NULL,
 PRIMARY KEY(execucao,tabela)
);
CREATE TABLE IF NOT EXISTS controle.nf_origens(
 segmento text PRIMARY KEY, hash text NOT NULL, manifest jsonb NOT NULL
);
DO $$ DECLARE s text; BEGIN FOREACH s IN ARRAY ARRAY['farma','pet'] LOOP
 EXECUTE format('CREATE TABLE IF NOT EXISTS %I.nf_registros(
  tabela text NOT NULL,chave text NOT NULL,versao bigint NOT NULL,
  registro jsonb,PRIMARY KEY(tabela,chave,versao))',s);
 EXECUTE format('CREATE INDEX IF NOT EXISTS nf_registros_visiveis ON %I.nf_registros(tabela,versao,chave)',s);
 EXECUTE format('CREATE TABLE IF NOT EXISTS %I.nf_stage(
  execucao uuid NOT NULL,tabela text NOT NULL,chave text NOT NULL,registro jsonb,
  PRIMARY KEY(execucao,tabela,chave))',s);
 EXECUTE format('CREATE TABLE IF NOT EXISTS %I.nf_estados(
  nome text PRIMARY KEY,versao bigint NOT NULL,hash text NOT NULL,documento jsonb NOT NULL,
  atualizado timestamptz NOT NULL DEFAULT clock_timestamp())',s);
 EXECUTE format('CREATE TABLE IF NOT EXISTS %I.nf_estado_recibos(
  id uuid PRIMARY KEY,hash text NOT NULL,recibo jsonb NOT NULL)',s);
END LOOP; END $$;
CREATE TABLE IF NOT EXISTS controle.nf_membros(
 execucao uuid NOT NULL REFERENCES controle.nf_execucoes(id),tabela text NOT NULL,chave text NOT NULL,
 PRIMARY KEY(execucao,tabela,chave)
);
CREATE UNIQUE INDEX IF NOT EXISTS nf_um_gravador ON controle.nf_execucoes(segmento) WHERE estado='WRITING';
ALTER TABLE controle.nf_substituicoes ADD COLUMN IF NOT EXISTS esperado jsonb;
CREATE TABLE IF NOT EXISTS controle.nf_contrato(id integer PRIMARY KEY CHECK(id=1),schema_hash text NOT NULL);
ALTER TABLE controle.nf_execucoes ADD COLUMN IF NOT EXISTS intencao jsonb;
CREATE TABLE IF NOT EXISTS controle.nf_reversoes(execucao uuid PRIMARY KEY REFERENCES controle.nf_execucoes(id),recibo jsonb NOT NULL);
CREATE OR REPLACE FUNCTION controle.nf_data(value text) RETURNS date
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$
 SELECT CASE WHEN value='' THEN NULL ELSE
 make_date(substring(value,1,4)::integer,substring(value,6,2)::integer,substring(value,9,2)::integer) END
$$;
DO $$ DECLARE s text; BEGIN FOREACH s IN ARRAY ARRAY['farma','pet'] LOOP
 EXECUTE format('CREATE TABLE IF NOT EXISTS %I.nf_atuais(tabela text NOT NULL,chave text NOT NULL,registro jsonb NOT NULL,PRIMARY KEY(tabela,chave))',s);
END LOOP; END $$;
