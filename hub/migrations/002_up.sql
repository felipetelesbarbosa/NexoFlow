ALTER TABLE hub.tarefas ADD COLUMN tipo text NOT NULL DEFAULT 'avaliacao' CHECK(tipo IN ('avaliacao','historico'));
ALTER TABLE hub.tarefas ADD COLUMN parametros jsonb;
CREATE TABLE hub.historico_janelas (
 segmento text NOT NULL CHECK(segmento IN ('FARMA','PET')), chave text NOT NULL,
 inicio text NOT NULL, fim text NOT NULL, limite bigint NOT NULL CHECK(limite>0),
 proxima_pagina integer NOT NULL DEFAULT 1, total bigint, paginas integer,
 estado text NOT NULL DEFAULT 'incompleta', motivo text NOT NULL DEFAULT '', atualizada_em timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(segmento,chave)
);
CREATE TABLE hub.historico_recebidos (
 segmento text NOT NULL, janela text NOT NULL, pedido_id text NOT NULL, pagina integer NOT NULL,
 PRIMARY KEY(segmento,janela,pedido_id), FOREIGN KEY(segmento,janela) REFERENCES hub.historico_janelas(segmento,chave)
);
CREATE TABLE hub.historico_pedidos (
 segmento text NOT NULL CHECK(segmento IN ('FARMA','PET')), pedido_id text NOT NULL,
 cliente_id text NOT NULL, registro jsonb NOT NULL,
 observado_em timestamptz NOT NULL DEFAULT now(), atualizado_em timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(segmento,pedido_id)
);
CREATE TABLE hub.historico_pendencias (
 segmento text NOT NULL, pedido_id text NOT NULL, motivo text NOT NULL,
 PRIMARY KEY(segmento,pedido_id)
);
CREATE TABLE hub.historico_revisoes (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 segmento text NOT NULL, pedido_id text NOT NULL, anterior text NOT NULL, atual text NOT NULL,
 modo text NOT NULL, tarefa_id uuid NOT NULL, criada_em timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(segmento,tarefa_id) REFERENCES hub.tarefas(segmento,id)
);
CREATE TABLE hub.historico_ltv (
 segmento text NOT NULL, cliente_id text NOT NULL, valor_centavos bigint NOT NULL,
 compras integer NOT NULL, primeira text NOT NULL, ultima text NOT NULL,
 cobertura text NOT NULL DEFAULT 'LTV_OBSERVADO', PRIMARY KEY(segmento,cliente_id)
);
INSERT INTO hub.migracoes(versao) VALUES(2);
