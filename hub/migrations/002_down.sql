DO $$ BEGIN
 IF EXISTS (SELECT 1 FROM hub.historico_pedidos) OR EXISTS (SELECT 1 FROM hub.historico_janelas)
    OR EXISTS (SELECT 1 FROM hub.tarefas WHERE tipo='historico') THEN
  RAISE EXCEPTION 'ROLLBACK_HISTORICO_COM_DADOS_BLOQUEADO';
 END IF;
END $$;
DROP TABLE hub.historico_ltv,hub.historico_revisoes,hub.historico_pendencias,hub.historico_pedidos,hub.historico_recebidos,hub.historico_janelas;
ALTER TABLE hub.tarefas DROP COLUMN parametros, DROP COLUMN tipo;
DELETE FROM hub.migracoes WHERE versao=2;
