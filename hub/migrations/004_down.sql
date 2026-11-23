DROP VIEW hub.central_operacao;
DROP INDEX hub.tarefas_ultima_conclusao;
DROP TABLE hub.sinal_worker;
DELETE FROM hub.migracoes WHERE versao=4;
