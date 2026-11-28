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
        ) END AS motivos,
        CASE WHEN t.tipo = 'noturno' THEN
            CASE WHEN t.cenario IN ('leitura_real_amostral','planejamento_real') THEN
                jsonb_build_object(
                    'modo', t.cenario,
                    'primeira_etapa_pendente', CASE
                        WHEN t.resultado->>'primeira_etapa_pendente' IN (
                            'atualizacao_weni','analytics','publicacao','recompra','analytics_final'
                        ) THEN t.resultado->>'primeira_etapa_pendente' ELSE NULL END,
                    'planejamento_motivo', CASE
                        WHEN t.resultado->'planejamento'->>'motivo' IN (
                            'ESTADO_PRIVADO_AUSENTE','RESERVAS_NAO_CONFIRMADAS',
                            'CONTEXTO_INCOMPLETO','LIMITE_AMOSTRA_EXCEDIDO',
                            'ESCOPO_FARMA_HML_OBRIGATORIO','LEITURA_NAO_CONFIRMADA',
                            'CREDENCIAL_NAO_PROVISIONADA','SAIDA_PRIVADA_NAO_CONFIGURADA'
                        ) THEN t.resultado->'planejamento'->>'motivo' ELSE NULL END,
                    'planos', (SELECT jsonb_agg(jsonb_build_object(
                        'etapa', p.nome,
                        'estado', CASE WHEN t.resultado->'etapas'->p.nome->>'estado' IN (
                           'planejado','parcial','pendente','nao_executada'
                        ) THEN t.resultado->'etapas'->p.nome->>'estado' ELSE 'nao_executada' END
                    ) ORDER BY p.ord) FROM (VALUES
                       ('atualizacao_weni',1),('analytics',2),('publicacao',3),
                       ('recompra',4),('analytics_final',5)) p(nome,ord)),
                    'fontes', (SELECT jsonb_agg(jsonb_build_object(
                        'nome', f.nome,
                        'estado', CASE
                            WHEN t.resultado->'fontes'->f.nome->>'estado' IN (
                                'amostra_validada','validada','parcial','pendente','nao_executada'
                            ) THEN t.resultado->'fontes'->f.nome->>'estado' ELSE 'pendente' END,
                        'cobertura_integral', COALESCE(
                            t.resultado->'fontes'->f.nome->'cobertura_integral' = 'true'::jsonb, false
                        ),
                        'origem', CASE
                            WHEN t.resultado->'fontes'->f.nome->'sintetico' = 'false'::jsonb
                            THEN 'real' ELSE 'nao_confirmada' END,
                        'motivo', CASE
                            WHEN t.resultado->'fontes'->f.nome->>'motivo' IN (
                              'CREDENCIAL_NAO_PROVISIONADA','SAIDA_PRIVADA_NAO_CONFIGURADA',
                              'ESCOPO_FARMA_HML_OBRIGATORIO','LEITURA_NAO_CONFIRMADA',
                              'CREDENCIAL_INVALIDA','CONTEXTO_INCOMPLETO','LIMITE_AMOSTRA_EXCEDIDO',
                              'ESTADO_PRIVADO_AUSENTE','RESERVAS_NAO_CONFIRMADAS'
                            ) THEN t.resultado->'fontes'->f.nome->>'motivo' ELSE NULL END
                    ) ORDER BY f.ord) FROM (VALUES ('weni',1),('farmalider',2),('meta',3)) f(nome,ord))
                )
            ELSE jsonb_build_object('modo','sintetico') END
        END AS evidencia
    FROM hub.tarefas t WHERE t.segmento = current_setting('nexoflow.segmento', true);
DELETE FROM hub.migracoes WHERE versao=9;
