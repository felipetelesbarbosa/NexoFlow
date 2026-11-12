-- Executar apenas no piloto, após conferir schema e backup. Não altera fatos/view.
DO $$ BEGIN
 IF current_database() <> 'nexoflow_datastudio_piloto' THEN
  RAISE EXCEPTION 'BI_PG_BANCO_DIVERGENTE';
 END IF;
 IF to_regclass('farma.bi_itens') IS NULL THEN
  RAISE EXCEPTION 'BI_PG_DESTINO_AUSENTE';
 END IF;
END $$;
CREATE SCHEMA IF NOT EXISTS nexoflow_publicacao;
CREATE TABLE IF NOT EXISTS nexoflow_publicacao.sessions (
 id uuid PRIMARY KEY, revision bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
 publisher text NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS nexoflow_publicacao.watermark (
 singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton), revision bigint NOT NULL
);
INSERT INTO nexoflow_publicacao.watermark VALUES(true,0) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS nexoflow_publicacao.batches (
 id uuid PRIMARY KEY, session_id uuid NOT NULL REFERENCES nexoflow_publicacao.sessions(id),
 digest text NOT NULL, receipt jsonb NOT NULL, reverted boolean NOT NULL DEFAULT false,
 committed_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS nexoflow_publicacao.changes (
 batch_id uuid NOT NULL REFERENCES nexoflow_publicacao.batches(id), item_chave text NOT NULL,
 previous jsonb, applied jsonb, PRIMARY KEY(batch_id,item_chave)
);
-- Auditoria privada: não incluir estes dados nos logs/artefatos públicos.
CREATE TABLE IF NOT EXISTS nexoflow_publicacao.sale_batches (
 session_id uuid NOT NULL REFERENCES nexoflow_publicacao.sessions(id),
 venda_chave text NOT NULL, batch_id uuid NOT NULL REFERENCES nexoflow_publicacao.batches(id),
 PRIMARY KEY(session_id,venda_chave)
);

-- Índice aditivo; não altera chaves, fatos ou a visão do Metabase.
CREATE INDEX IF NOT EXISTS nf_bi_itens_venda ON farma.bi_itens(venda_chave);
CREATE TABLE IF NOT EXISTS nexoflow_publicacao.plans (
 session_id uuid PRIMARY KEY REFERENCES nexoflow_publicacao.sessions(id),
 digest text NOT NULL, manifest jsonb NOT NULL, complete boolean NOT NULL,
 state text NOT NULL CHECK(state IN ('WRITING','READY','PARCIAL','REVERTIDO'))
);
CREATE OR REPLACE VIEW nexoflow_publicacao.estado_leitura AS
SELECT coalesce((SELECT p.state FROM nexoflow_publicacao.plans p
 JOIN nexoflow_publicacao.sessions s ON s.id=p.session_id ORDER BY s.revision DESC LIMIT 1),'LEGADO') AS state,
 coalesce((SELECT max(s.revision) FROM nexoflow_publicacao.plans p JOIN nexoflow_publicacao.sessions s ON s.id=p.session_id),0) AS revision;
CREATE INDEX IF NOT EXISTS nf_bi_itens_data ON farma.bi_itens(data);
