# Backend definitivo Data Studio — entrega 1.5.37

Estado: código e distribuição publicados; implantação e conciliação comercial pendentes. Referência de partida: `5b21d4799115a490447c483d5a40788cd59eb100`. O SHA entregue deve ser obtido do commit desta entrega e dos checks GitHub; não confundir com o SHA do piloto. Sem carga comercial, acesso ao C: do operador, implantação VPS ou troca de relatório neste trabalho.

## Implementado

- `app/ds_backend/`: contrato fechado, catálogo de tabelas, cliente autenticado, adaptador do armazenamento existente, cache e estados remotos, corte de migração, auditoria financeira e preservação de exclusões. `app/run_datastudio.py` e Terminal expõem preparo, simulação, lote limitado, retomada, conferência, selagem e reversão.
- Rotinas Windows selecionam explicitamente Sheets ou PostgreSQL; mantém-se Sheets como padrão e não há fallback. Validadores comerciais e construção de BI existentes são reaproveitados. PostgreSQL pode funcionar sem credenciais Google; a exportação inicial é a exceção explícita que lê Sheets.
- `integrations/datastudio/`: migração 002 aditiva, APIs de publicação/leitura separadas, staging, recibos, revisão visível atômica, projeção ativa indexada, arquivo de versões, estados CAS, papéis e RLS por segmento. PostgreSQL sem porta publicada; Compose anexa serviços à rede conferida pelo Work.
- `connectors/datastudio_api/`: novo projeto leitor, catálogo autorizado e tipos preservados, filtros e agregações SQL, distintos no período, limites explícitos e falha sem totais parciais. Segredos de leitura separados dos de publicação.
- Configuração por perfil, atualização AST com backup privado e Preserve sem sobrescrever credenciais. Modelo JSON sem valores inventados. Não foi alterado o arquivo efetivo do operador.
- Manifesto/hash completo da exportação é aprovado pelo administrador antes do primeiro READY. Uma base local parcial não substitui o histórico acumulado. Exclusões vêm da revisão e evidência exatas, em leitura, sem apagar a base bruta.

Os dez módulos assinados do publicador Sheets permanecem byte a byte. O contrato piloto, a visão Metabase e o banco piloto não são reapontados. Hub, Métricas e n8n ficam fora do destino.

## Validação

Testes usam serviços simulados, SQLite sintético e PostgreSQL 18.6 descartável sem portas publicadas. Cobrem tipos, centavos, segmentação, idempotência, resposta perdida, concorrência, versão antiga, substituição incompleta, rollback e não ressurreição de revisão revertida. A CLI real é exercitada em preparo → simular → aplicar um lote → retomar → conferir → repetir sem duplicação → reverter. A leitura compara pedidos/itens/LTV e preserva cancelamentos. Datas indexadas são verificadas por plano de execução e linhas examinadas, sem aprovação por tempo arbitrário.

A exportação lê uma grade simulada de 500 mil linhas em blocos e recusa mudança de origem durante o corte. O conector tem testes Node. O teste Docker executa os dois serviços autenticados e valida as contas mínimas e ausência de portas. A matriz Windows/Setup e a conferência dos pacotes são exigidas antes da publicação; seus resultados são registrados na execução GitHub do SHA final.

## Evidência comercial recebida e limites

O Work informou que a 001 já aplicada contém apenas revogações de PUBLIC e criação dos três schemas. Ela não deve ser repetida; 002 usa criação idempotente no banco correto. A revisão histórica READY informada tem 267.722 pedidos e 552.261 itens; o SQLite atual tem cobertura menor. Esses números são referências datadas, não resultados desta implementação.

A diferença aritmética entre 552.826 linhas simuladas anteriormente e 552.261 históricas é 565. A causa não foi comprovada aqui: requer exportar e comparar chaves/versões nos cortes reais. Não alterar valores, descartar pendências ou remover `LIMITES_DA_API_NAO_HOMOLOGADOS` para fechar totais.

Não foi identificada fonte manual independente pelo Work. Isso não prova ausência de células manuais. As 37 conexões reais, campos e três mesclagens precisam ser mapeados antes da troca; zero usos diretos não permite remover fonte. `BI_Meta_Resultados` integra o catálogo. Custo ausente não vira zero/CAC/ROAS inventado.

## Próxima execução

Seguir [guia e comandos](MIGRACAO%20WINDOWS%20POSTGRESQL%20DATA%20STUDIO.md), [mapa de tabelas](ESTRUTURA%20POSTGRESQL%20DATA%20STUDIO.md) e [roteiro Work](PROMPT%20WORK%20POSTGRESQL%20DEFINITIVO.md). Só ativar o backend após corte completo READY, conferência financeira e importação dos estados atuais. A carga curta real, capacidade do volume, fontes oficiais e migração comercial continuam pendentes do Work/operador. A fonte antiga fica disponível para reversão, mas não é atualizada automaticamente depois do corte PostgreSQL.

Validação local em 12/11/2026: 27 testes do contrato definitivo aprovados com PostgreSQL 18.6 e imagens Docker reais, incluindo as duas APIs autenticadas sem portas publicadas. A projeção ativa usa índices; o teste verifica o plano e a quantidade de linhas examinadas. Os testes de CLI medem persistência/recibos, não apenas ausência de exceções. Falhas iniciais de execução por disco temporário cheio foram repetidas após remover somente builds intermediários desta tarefa.

Suíte Linux final desta implementação: **1.943 aprovados, 144 ignorados e 1.475 subtestes aprovados**. Os ignorados correspondem a plataformas/integrações que exigem seus próprios ambientes; não são comprovação de Windows. PostgreSQL/Docker definitivo: **27 aprovados**. CI/CodeQL, matriz Windows, Setup e pacotes ainda exigem conferência no SHA enviado; não declarar publicação antes disso.

Revisão final de concorrência: a paginação da API publicadora também usa REPEATABLE READ. O teste força um commit de outra revisão entre a seleção da versão e das linhas e exige que ambas permaneçam no mesmo snapshot. A API leitora já utilizava esse isolamento.

A matriz Windows detectou um erro na fixture do backup de configuração: `write_text` gerava CRLF e a asserção comparava com uma string LF. O backup estava correto. A fixture agora grava CRLF explicitamente e compara os bytes originais, exercitando a preservação também em Linux. Nenhuma guarda foi removida; exige nova validação do SHA corrigido antes do build/publicação.

## Evidência final da distribuição

Publicada em **12/11/2026, 19:18:38 (America/Fortaleza)**, SHA `2683717431b1c4313efaaaef35cfaaf20236958a`. [Release](https://github.com/felipetelesbarbosa/NexoFlow/releases/tag/v1.5.37), [CI e pacotes](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/43314024652), [CodeQL](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/43314024795), [Meta](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/43314026009) e [publicação reutilizando os artefatos](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/43318519275). Downloads públicos conferidos: hashes, CRC, 571 entradas do manifesto, 123 módulos e versões dos executáveis. Sem implantação ou migração comercial.

SHA-256 Setup: `53f2410e9f8c0a3aeb48196d23c35f5d8f2c81fd5ec0b570222d245060f227fd`.

SHA-256 projeto completo: `81feee7ff472d286d4837307657bcd9646fa5f51b364e4cb03ab5920f04a0480`.

Os mesmos bytes aprovados na preparação foram baixados da release pública e conferidos novamente. O commit documental posterior não altera a tag ou seus pacotes.


## Complemento — inventário real do relatório

O [roteiro posterior](ROTEIRO%20INVENTARIO%20FARMA%20POSTGRESQL.md) confronta 37 aliases, cinco mesclagens (duas sem gráficos), 75 componentes, oito controles, 14 filtros e três substituições de IDs. Identifica 28 aliases com tabela leitora disponível e nove sem substituição direta, evitando declarar o corte completo. Corrige no leitor a inclusão de resumo não vigente e o filtro parcial de competências, protege compradores distintos e configura BRL no conector. São mudanças de servidor/conector, sem alteração da distribuição 1.5.37, do contrato de publicação ou do hash do catálogo. Evidência de Google vem do Work; testes do Codex são sintéticos.
