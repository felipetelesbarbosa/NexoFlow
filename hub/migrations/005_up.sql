CREATE TABLE hub.api_requisicoes (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    segmento text NOT NULL CHECK (segmento IN ('FARMA', 'PET')),
    api text NOT NULL CHECK (api IN ('hub', 'weni')),
    ocorrido_em timestamptz NOT NULL DEFAULT clock_timestamp(),
    metodo text NOT NULL CHECK (metodo IN ('GET', 'POST')),
    endpoint text NOT NULL CHECK (length(endpoint) <= 100),
    http integer NOT NULL CHECK (http BETWEEN 200 AND 599),
    duracao_ms integer NOT NULL CHECK (duracao_ms >= 0),
    corpo jsonb,
    erro text CHECK (length(erro) <= 64)
);
CREATE INDEX api_requisicoes_segmento_hora ON hub.api_requisicoes (segmento, ocorrido_em DESC);
CREATE INDEX api_requisicoes_pagina ON hub.api_requisicoes (segmento, api, id DESC);
CREATE INDEX api_requisicoes_retencao ON hub.api_requisicoes (ocorrido_em);

CREATE VIEW hub.central_api_requisicoes WITH (security_barrier=true) AS
    SELECT id, segmento, api, ocorrido_em, metodo, endpoint, http, duracao_ms, corpo, erro
    FROM hub.api_requisicoes WHERE segmento = current_setting('nexoflow.segmento', true);

INSERT INTO hub.migracoes(versao) VALUES (5);
