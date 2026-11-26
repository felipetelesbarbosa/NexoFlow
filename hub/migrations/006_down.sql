DROP VIEW hub.central_tarefas;
CREATE VIEW hub.central_tarefas WITH (security_barrier=true) AS
    SELECT segmento, id, estado, criada_em AS criado_em, atualizada_em AS atualizado_em
    FROM hub.tarefas WHERE segmento = current_setting('nexoflow.segmento', true);

ALTER TABLE hub.tarefas DROP CONSTRAINT tarefas_tipo_check;
ALTER TABLE hub.tarefas ADD CONSTRAINT tarefas_tipo_check
    CHECK (tipo IN ('avaliacao', 'historico'));
DELETE FROM hub.migracoes WHERE versao = 6;
