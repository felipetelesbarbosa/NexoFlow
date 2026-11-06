CREATE SCHEMA IF NOT EXISTS hub;
CREATE TABLE hub.migracoes (versao integer PRIMARY KEY, aplicada_em timestamptz NOT NULL DEFAULT now());
CREATE TABLE hub.tarefas (
 id uuid PRIMARY KEY, segmento text NOT NULL CHECK (segmento IN ('FARMA','PET')),
 origem text NOT NULL CHECK (origem IN ('manual','n8n','teste')),
 chave text NOT NULL, pedido_hash text NOT NULL, cenario text NOT NULL,
 estado text NOT NULL CHECK (estado IN ('pendente','executando','aguardando','concluida','parcial','falhou','revisao_necessaria')),
 criada_em timestamptz NOT NULL DEFAULT now(), atualizada_em timestamptz NOT NULL DEFAULT now(),
 disponivel_em timestamptz NOT NULL DEFAULT now(), lease_ate timestamptz,
 dono uuid, tentativa integer NOT NULL DEFAULT 0, erro text, resultado jsonb,
 UNIQUE(segmento,origem,chave), UNIQUE(segmento,id)
);
CREATE INDEX fila_hub ON hub.tarefas(estado,disponivel_em,criada_em);
CREATE TABLE hub.coordenacao (
 segmento text PRIMARY KEY CHECK(segmento IN ('FARMA','PET')),
 tarefa_id uuid NOT NULL, dono uuid NOT NULL, lease_ate timestamptz NOT NULL,
 FOREIGN KEY(segmento,tarefa_id) REFERENCES hub.tarefas(segmento,id)
);
CREATE TABLE hub.tentativas (
 segmento text NOT NULL, tarefa_id uuid NOT NULL, numero integer NOT NULL, dono uuid NOT NULL,
 estado text NOT NULL, iniciada_em timestamptz NOT NULL DEFAULT now(), terminada_em timestamptz,
 PRIMARY KEY(segmento,tarefa_id,numero), FOREIGN KEY(segmento,tarefa_id) REFERENCES hub.tarefas(segmento,id)
);
CREATE TABLE hub.checkpoints (
 segmento text NOT NULL, tarefa_id uuid NOT NULL, etapa integer NOT NULL,
 resultado jsonb NOT NULL, confirmada_em timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(segmento,tarefa_id,etapa), FOREIGN KEY(segmento,tarefa_id) REFERENCES hub.tarefas(segmento,id)
);
CREATE TABLE hub.auditoria (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, segmento text NOT NULL, tarefa_id uuid NOT NULL,
 evento text NOT NULL, criada_em timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(segmento,tarefa_id) REFERENCES hub.tarefas(segmento,id)
);
-- Nenhuma rota/página de histórico é suposta; esta tabela só poderá receber
-- cobertura comprovada quando o contrato de fonte estiver disponível.
CREATE TABLE hub.cobertura (
 segmento text NOT NULL CHECK(segmento IN ('FARMA','PET')), fonte text NOT NULL,
 contrato text NOT NULL, inicio timestamptz NOT NULL, fim timestamptz NOT NULL,
 estado text NOT NULL CHECK(estado IN ('incompleta','comprovada')),
 PRIMARY KEY(segmento,fonte,contrato,inicio,fim), CHECK(fim>=inicio)
);
INSERT INTO hub.migracoes(versao) VALUES (1);
