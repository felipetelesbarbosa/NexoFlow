CREATE TABLE hub.sinal_worker (
    unico boolean PRIMARY KEY CHECK (unico),
    ciclo_em timestamptz NOT NULL
);

CREATE INDEX tarefas_ultima_conclusao ON hub.tarefas
    (segmento, atualizada_em DESC) WHERE estado = 'concluida';

CREATE VIEW hub.central_operacao WITH (security_barrier=true) AS
    SELECT escopo.segmento,
           worker.ciclo_em AS worker_ultimo_ciclo_em,
           CASE
               WHEN worker.ciclo_em IS NULL THEN 'sem_sinal'
               WHEN worker.ciclo_em < now() - interval '30 seconds' THEN 'sinal_atrasado'
               ELSE 'ativo'
           END AS worker_estado,
           fila.prontas AS fila_prontas,
           fila.em_espera AS fila_em_espera,
           fila.expiradas AS fila_leases_expirados,
           EXTRACT(epoch FROM now() - fila.pronta_desde)::bigint AS fila_espera_segundos,
           (SELECT t.atualizada_em FROM hub.tarefas t
            WHERE t.segmento = escopo.segmento AND t.estado = 'concluida'
            ORDER BY t.atualizada_em DESC LIMIT 1) AS ultima_conclusao_em
    FROM (VALUES ('FARMA'), ('PET')) AS escopo(segmento)
    LEFT JOIN hub.sinal_worker worker ON worker.unico
    CROSS JOIN LATERAL (
        SELECT count(*) FILTER (WHERE estado IN ('pendente','aguardando') AND disponivel_em <= now()) AS prontas,
               count(*) FILTER (WHERE estado IN ('pendente','aguardando') AND disponivel_em > now()) AS em_espera,
               count(*) FILTER (WHERE estado = 'executando' AND lease_ate <= now()) AS expiradas,
               min(disponivel_em) FILTER (WHERE estado IN ('pendente','aguardando') AND disponivel_em <= now()) AS pronta_desde
        FROM hub.tarefas
        WHERE segmento = escopo.segmento AND estado IN ('pendente','aguardando','executando')
    ) AS fila
    WHERE escopo.segmento = current_setting('nexoflow.segmento', true);

INSERT INTO hub.migracoes(versao) VALUES (4);
