-- Executar como administrador do banco dedicado. Exclusivo do publicador FARMA.
DO $$
BEGIN
  IF current_database() NOT IN ('nexoflow_datastudio', 'nexoflow_datastudio_homologacao') THEN
    RAISE EXCEPTION 'DS_BANCO_DIVERGENTE';
  END IF;
END $$;

GRANT SELECT (pedido_id) ON farma.ds_exclusoes_publicacao TO nf_ds_farma_publish;
GRANT SELECT (venda_chave, item_chave, receita_item, quantidade, data, cliente_chave)
  ON farma.ds_bi_itens_operacional TO nf_ds_farma_publish;
GRANT SELECT (venda_chave, faturamento_produtos, data, cliente_chave)
  ON farma.ds_bi_clientes_vendas_operacional TO nf_ds_farma_publish;

-- Staging privado para um documento de Recompra maior que um corpo HTTP.
CREATE TABLE IF NOT EXISTS farma.nf_estado_partes (
  upload uuid NOT NULL, posicao integer NOT NULL, dados text NOT NULL,
  criado timestamptz NOT NULL DEFAULT clock_timestamp(), PRIMARY KEY (upload,posicao)
);
REVOKE ALL ON farma.nf_estado_partes FROM PUBLIC;
GRANT SELECT, INSERT, DELETE ON farma.nf_estado_partes TO nf_ds_farma_publish;
