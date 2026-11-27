DROP VIEW hub.central_tarefas;
CREATE OR REPLACE VIEW hub.central_tarefas WITH (security_barrier=true) AS
    SELECT t.segmento, t.id, t.estado, t.criada_em AS criado_em, t.atualizada_em AS atualizado_em,
        t.tipo, CASE WHEN t.tipo = 'noturno' THEN
            ARRAY(SELECT c.etapa FROM hub.checkpoints c
                  WHERE c.segmento = t.segmento AND c.tarefa_id = t.id ORDER BY c.etapa)
        END AS etapas_concluidas,
        CASE WHEN t.tipo = 'noturno' THEN ARRAY(
            SELECT DISTINCT code FROM (
                SELECT p->>'motivo' AS code FROM jsonb_array_elements(
                    CASE WHEN jsonb_typeof(t.resultado->'pendencias')='array'
                         THEN t.resultado->'pendencias' ELSE '[]'::jsonb END) p
                UNION SELECT t.erro
            ) codes WHERE code IN ('RESERVA_FARMA','COBERTURA_PARCIAL','RESPOSTA_INCERTA',
                                   'FONTE_ESSENCIAL_INCOMPLETA') ORDER BY code
        ) END AS motivos
    FROM hub.tarefas t WHERE t.segmento = current_setting('nexoflow.segmento', true);
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='hub_central_leitor') THEN
        GRANT SELECT ON hub.central_tarefas TO hub_central_leitor;
    END IF;
END $$;
DELETE FROM hub.migracoes WHERE versao=8;
