-- Homologação: um evento identifica uma ocorrência do fluxo FARMA.
CREATE TABLE hub.eventos_weni (
    segmento text NOT NULL CHECK (segmento = 'FARMA'),
    evento_id uuid NOT NULL,
    tipo text NOT NULL CHECK (tipo = 'atendimento_transferido'),
    ocorrido_em timestamptz NOT NULL,
    recebido_em timestamptz NOT NULL DEFAULT clock_timestamp(),
    recibo uuid NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    PRIMARY KEY (segmento, evento_id)
);

CREATE INDEX eventos_weni_central ON hub.eventos_weni
    (segmento, recebido_em DESC, ocorrido_em DESC, tipo);
CREATE INDEX tarefas_central ON hub.tarefas (segmento, criada_em DESC, id DESC);

CREATE VIEW hub.central_tarefas WITH (security_barrier=true) AS
    SELECT segmento, id, estado, criada_em AS criado_em, atualizada_em AS atualizado_em
    FROM hub.tarefas WHERE segmento = current_setting('nexoflow.segmento', true);

CREATE VIEW hub.central_eventos WITH (security_barrier=true) AS
    SELECT segmento, tipo, ocorrido_em, recebido_em
    FROM hub.eventos_weni WHERE segmento = current_setting('nexoflow.segmento', true);

INSERT INTO hub.migracoes(versao) VALUES (3);
