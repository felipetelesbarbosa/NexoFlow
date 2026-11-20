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
