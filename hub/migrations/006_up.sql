ALTER TABLE hub.tarefas DROP CONSTRAINT tarefas_tipo_check;
ALTER TABLE hub.tarefas ADD CONSTRAINT tarefas_tipo_check
    CHECK (tipo IN ('avaliacao', 'historico') OR (tipo = 'noturno' AND segmento = 'FARMA'));

CREATE OR REPLACE VIEW hub.central_tarefas WITH (security_barrier=true) AS
    SELECT t.segmento, t.id, t.estado, t.criada_em AS criado_em, t.atualizada_em AS atualizado_em,
        t.tipo, CASE WHEN t.tipo = 'noturno' THEN
            ARRAY(SELECT c.etapa FROM hub.checkpoints c
                  WHERE c.segmento = t.segmento AND c.tarefa_id = t.id ORDER BY c.etapa)
        END AS etapas_concluidas
    FROM hub.tarefas t WHERE t.segmento = current_setting('nexoflow.segmento', true);

INSERT INTO hub.migracoes(versao) VALUES (6);
