DROP VIEW hub.central_tarefas;
CREATE VIEW hub.central_tarefas WITH (security_barrier=true) AS
    SELECT t.segmento, t.id, t.estado, t.criada_em AS criado_em, t.atualizada_em AS atualizado_em,
        t.tipo, CASE WHEN t.tipo = 'noturno' THEN
            ARRAY(SELECT c.etapa FROM hub.checkpoints c
                  WHERE c.segmento = t.segmento AND c.tarefa_id = t.id ORDER BY c.etapa)
        END AS etapas_concluidas
    FROM hub.tarefas t WHERE t.segmento = current_setting('nexoflow.segmento', true);
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='hub_central_leitor') THEN
        GRANT SELECT ON hub.central_tarefas TO hub_central_leitor;
    END IF;
END $$;
DELETE FROM hub.migracoes WHERE versao=7;
