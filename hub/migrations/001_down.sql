-- Somente schema vazio em banco temporário de homologação, protegido pelo CLI.
DROP TABLE hub.cobertura;
DROP TABLE hub.auditoria;
DROP TABLE hub.checkpoints;
DROP TABLE hub.tentativas;
DROP TABLE hub.coordenacao;
DROP TABLE hub.tarefas;
DROP TABLE hub.migracoes;
DROP SCHEMA hub;
