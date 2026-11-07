# NexoFlow | Cronograma mestre: Hub, Central de Operações e Métricas

**Planejamento atualizado em 07/11/2026.** Este documento registra prioridades, responsáveis, dependências e critérios de aceite. **Não autoriza implantação comercial, exposição pública ou exclusão de dados.** Datas de entrega dependem de homologação e recursos reais.

## 1. Produtos, acesso e identidade

| Produto | Objetivo | Público | Endereço proposto (ainda NÃO criado) |
| --- | --- | --- | --- |
| **NexoFlow Windows** | Operação autônoma local: Weni, Analytics, Noturno, Recompra, histórico e relatórios | Operadores autorizados | Não requer URL nem Hub disponível |
| **NexoFlow Hub** | FastAPI, worker Linux, PostgreSQL, n8n e regras compartilhadas | Backend e operações | Interno |
| **Central de Operações** | Web próprio para status, aplicações, integrações, execuções, logs, erros, consumo e administração | Admins/devs autorizados | `painel.nexoflowhub.com.br` |
| **NexoFlow Métricas** | BI web próprio de vendas, clientes, produtos, anúncios e LTV, reproduzindo e ampliando Data Studio | Gestores e convidados | `metricas.nexoflowhub.com.br` |
| **Observabilidade técnica** | Grafana/Prometheus/Loki ou pilha menor dimensionada | Equipe técnica | `monitor.nexoflowhub.com.br` (opcional) |

Os subdomínios são **propostas**. Implantação via Cloudflare Tunnel/HTTPS/Access, RBAC e autorização explícita, sem publicar portas PostgreSQL/Prometheus/Loki. Preservar n8n.nexoflowhub.com.br. Admins podem navegar para Métricas a partir da Central; usuários convidados entram **apenas** em Métricas com suas contas.

## 2. Linha do tempo por etapas e portas de liberação

| Etapa | Estado verificado/planejado | Objetivo | Executor preferencial |
| --- | --- | --- | --- |
| **1. Infraestrutura VPS** | **Concluída com ressalvas** | Docker, PostgreSQL/n8n, Cloudflare, backup Restic/R2, monitoramento e alertas | Work |
| **2. Núcleo Hub Linux** | **Concluída no repositório** | API, worker, filas, locks Hub, histórico/LTV sintético, testes PostgreSQL/CI | Codex |
| **3. Deploy isolado na VPS** | **Concluída com ressalvas** | Hub em contêineres isolados, sete workflows n8n inativos, backups/restauração e testes reais de infraestrutura | Work |
| **3.5. Preparação operacional e desenho dos produtos** | **Próxima, paralela ao início da 4** | Capacidade/retensão, DBeaver, telemetria mínima, inventário BI, modelo de usuários e especificações visuais | Work + Codex |
| **4. Integrações reais SOMENTE LEITURA** | **Planejada** | Atualizar SHA Hub em HML; validar FARMA/PET e progressivamente Weni/Meta/Google; reconciliar dados e cobertura | Codex + Work |
| **5. Observabilidade e Central de Operações web** | **Planejada, arquitetada na 3.5** | Stack técnica, painéis de logs/API/infra e portal próprio inspirado no Iota.hub | Work (infra) + Codex (produto) |
| **6. NexoFlow Métricas web** | **Planejada, inventariada na 3.5** | Dashboard próprio, URL, login individual, permissões por marca e paridade funcional com Data Studio | Codex (produto/BI) + Work (deploy/segurança) |
| **7. Escrita comercial e transição controlada** | **Bloqueada** | Coordenação Windows/Hub, permissões por destino, escrita revisada, rollback e cutover progressivo | Codex + Work, autorização específica |
| **8. Evolução, escala e governança contínua** | **Contínua após homologação** | Performance, retenção, backups, auditoria, custos, usabilidade, novas integrações | Equipe |

**Decisão:** não refazer a Etapa 3. A 3.5 prepara interfaces, governança e infraestrutura leve; não atrasar a homologação read-only da 4 aguardando frontend completo. Não ativar funcionalidades comerciais de escrita na 3.5/4/5/6. Nenhum prazo ou release adicional é declarado como concluído sem provas.

### Estado do código

O Windows **1.5.18** está publicado conforme o repositório, mas o Hub da VPS foi homologado originalmente no SHA `23f2806`. Antes de atualizar o Hub, conferir o SHA exato da tag, diff, migrations, backup, rollback e regressões; atualizar HML de modo controlado e **sem deploy comercial automático**. O Windows continua autônomo, sem dependência do Hub.

## 3. Etapa 3.5 | O que iniciar AGORA

### 3.5.1 Capacidade, armazenamento e retenção

- Medir uso por CPU, RAM, disco, rede, banco, índices, volumes Docker, imagens, n8n e logs. A apresentação inicial da Hostinger foi 6 GB / 200 GB; medir novamente e acompanhar tendência.
- Confirmar rotação dos logs `json-file` 10 MB × 3 por contêiner e identificar logs fora do Docker.
- Auditar **retenção de execuções n8n** (sucesso, falha, em andamento e dados de debug), incluindo limites de gravação e impacto em PostgreSQL.
- Planejar retenção diferenciada de métricas, logs operacionais, eventos, auditoria e fatos comerciais. **Nunca tratar pedidos, LTV, checkpoints e reconciliação como cache descartável.**
- Executar inventário de imagens antigas, builds temporários, staging, respostas JSON, arquivos de ensaio e arquivos órfãos. Permitir somente limpezas seletivas, com confirmação de ausência de dependência, rollback e backup; não usar `docker volume prune` ou `down -v`.
- Manter alertas existentes e alertas progressivos por disco (incluindo o existente em 85%), memória, serviços, banco e backups.
- Restic/R2: política de retenção já testada em **dry-run**; nenhuma exclusão real de snapshots sem autorização separada.

**Aceite:** inventário fonte-a-fonte, políticas documentadas, simulação/ensaios e ausência de exclusões destrutivas não aprovadas.

### 3.5.2 DBeaver Community no PC (opcional para devs)

- **Sim, recomendar DBeaver Community nos computadores Windows de quem realmente precisa de consultas SQL.** Não instalar DBeaver na VPS e não obrigar usuários gestores/convidados a instalar.
- Work prepara túnel SSH/encaminhamento privado adequado às redes Docker e usuário PostgreSQL dedicado **somente leitura**, grants mínimos e preferencialmente views saneadas, sem abrir 5432 para internet.
- Separar credenciais do Hub e do n8n; não usar usuários migradores/admin em ferramentas interativas; registrar como conceder, testar e revogar acessos.
- Entregar guia de configuração local e consultas seguras. Usuários NexoFlow Métricas **não** recebem acesso ao banco.
- **pgAdmin na VPS fica fora do escopo inicial**; avaliar somente se houver necessidade específica de administração PostgreSQL web, não como substituto da Central.

### 3.5.3 Contrato de telemetria e segurança

- Instrumentar métricas seguras de API e tarefas: timestamp, segmento FARMA/PET, aplicação, operação, método HTTP, status, duração/p50/p95, retries, timeouts, filas, checkpoint, sucesso/erro, ID de correlação opaco, versionamento e cobertura dos dados.
- Distinguir **HTTP 200** de **pedido validado**, tarefa concluída e receita reconhecida. Identificar proxy/TLS/429/5xx independentemente, com contagens e percentuais calculados sobre denominadores explícitos.
- Logs e detalhes de erros **sempre sanitizados**: proibir Authorization/Bearer, token em query, CPF, nome, endereço, telefone, payload/response integral, segredo, DSN e URL autenticada. A captura do Iota.hub com bearer visível **não é referência de segurança**.
- Definir modelo de autenticação/usuários/RBAC de Central e Métricas antes de expor UI: senha armazenada com hash forte, recuperação segura, rate limit, trilha de auditoria, proteção de sessões/CSRF, MFA administrativo e revogação; Cloudflare Access adicional para páginas técnicas.

**Aceite:** contratos versionados, fixtures de telemetria, testes de vazamento de segredos/PII, proteção por segmento e infraestrutura mínima compatível com KVM 4.

### 3.5.4 Inventário real dos dois Data Studio (especificação do Métricas)

**Fontes obrigatórias de paridade funcional:**
- **NexoFlow Analytics - FarmaLíder:** https://datastudio.google.com/reporting/e60ba3bc-fe88-417d-8a39-d8512debf175/page/oeZAG
- **NexoFlow Analytics - Pets Líder:** https://datastudio.google.com/reporting/35c02ed5-901b-4134-a735-5ac9a9290306/page/oeZAG

**Navegação observada em 07/11/2026, no navegador autenticado, não auditoria completa das páginas:**

| Página funcional | FarmaLíder | Pets Líder |
| --- | :---: | :---: |
| Resumo | Sim | Sim |
| Vendas | Sim | Sim |
| Meus clientes | Sim | Sim |
| Pedidos por cliente | Sim | Sim |
| Produtos mais vendidos | Sim | Sim |
| Curva ABC | Sim | Sim |
| Anúncios | Sim | Sim |
| Pedidos dos anúncios | Sim | **Ainda não observada** |
| Base de clientes | Sim | Sim |
| Atualização dos dados | Sim | Sim |

**Resumo observado em ambos:** filtros por período, cartões de faturamento, pedidos, compradores e ticket médio, gráfico `Faturamento por dia`, tabelas `Produtos de destaque` e `Clientes de destaque`, paginação e última atualização. Não assumir que as demais páginas foram integralmente inspecionadas.

Antes da Etapa 6, Work/Codex deverá **percorrer cada página de ambos os relatórios** e produzir uma **matriz de paridade verificável** com:
1. Nome da página, objetivo, cards, campos, métricas, dimensões, fórmulas e fonte de dados.
2. Filtros por data, segmento, cidade, bairro, cliente, produto, anúncio, ordenação, busca, paginação e aplicação entre gráficos.
3. Comportamentos reais: seleção cruzada, drill-down, navegação, reset de filtros, exportação, atualização e controles de acesso.
4. Tratamento dos períodos anteriores, dados ausentes, cobertura histórica e diferença entre LTV total e vendas no período.
5. Identidade visual de cada marca, logos corretos e cores; PET usa azul `#20AFE9` e laranja `#F69F11` como referência, **sem verde herdado de FARMA**.
6. Critérios de aceite, prova por screenshot/consulta e classificação `replicado`, `melhorado`, `pendente de fonte` ou `descontinuado com justificativa aprovada`.

**Não reduzir o escopo ao painel de Resumo**, nem substituir os relatórios atuais antes de aferição completa.

## 4. Etapa 4 | APIs reais em modo de leitura

- Homologar SHA atualizado na VPS e compatibilidade com schema/migrations, n8n e backups, preservando volumes e credenciais HML.
- Prioridade FARMA e PET pelo `GET /api/Delivery/pedidos/{segmento}`, com data civil final serializada corretamente, paginação e limite oficial 1–500, deduplicação por ID oficial, status, frete e reconciliação de pendências. COMEÇAR com pequenos períodos e orçamento limitado.
- Depois Weni leitura, Meta Ads nativo somente leitura, Google Ads leitura somente com acesso oficial e atribuição causal comprovada. Não presumir custos nem vendas por anúncio somente por clique/conversa.
- Contratos por fonte, latência, erro, fallback, checkpoint, cobertura, reprocessamento e validação contra dados Windows/Data Studio. Confirmar identidades e escopo de segmento.
- Escrita Weni/Sheets, publicação BI, webhooks públicos e importação anual automática continuam **bloqueados** até aceite e autorização próprios.

**Aceite:** leituras GET limitadas e auditadas, comparativos FARMA/PET, idempotência, proteção de PII, cobertura reportada com limites reais, sem efeitos externos.

## 5. Etapa 5 | Observabilidade e Central de Operações

**Referência de UI:** sete screenshots fornecidas da Iota.hub. Inspirar-se em princípios de usabilidade, **não copiar marca, layout proprietário pixel a pixel ou código**. Visual dark clean/grafite, navegação simples, azul de destaque, cards compactos, gráficos, filtros, tabela de erros e drawer lateral sanitizado. Prever tema claro e responsividade.

**Infra observável, dimensionada por medição real:**
- Grafana para visualização técnica; Prometheus/exporters para métricas e Loki/agente para logs, **ou alternativa mais leve** se custo de RAM/CPU/disco do KVM 4 justificar.
- Retenção explícita e limite de recursos; não expor Prometheus/Loki na internet. Manter alertas externos independentes do Grafana.
- Medir n8n, API, worker, PostgreSQL, backups, Docker, redes, throughput de chamadas por provedor, latência, status HTTP, tentativas, falhas, duração, filas, checkpoints, custo/uso quando houver fonte legítima.

**Central de Operações própria:**
- Dashboard principal de saúde, success/error rates, últimas execuções e recursos.
- Aplicações/Integrações: FARMA/PET, Weni, Meta, Google Ads, Sheets, n8n e fontes futuras, separadas por ambiente.
- Execuções e filas: histórico/Analytics/Noturno/Recompra, jobs, retries, checkpoints, auditorias e estados.
- Logs/Erros: busca e detalhe sanitizado de request/response, endpoint sem tokens, método, status, tempo, código classificado, correlation ID; **nunca mostrar cabeçalhos secretos**.
- Dados/Capacidade: metadados e contagens agregadas de tabelas, tamanhos e crescimento, **sem console SQL administrativo exposto**.
- Usuários/Permissões: admin, desenvolvedor, leitor técnico com políticas do backend. Login próprio + proteção adicional Cloudflare Access.
- Inicialmente **somente consulta**; comandos de executar/reprocessar/aplicar integrações exigem etapa de autorização posterior.

**Aceite:** visibilidade fim-a-fim em ensaios reais controlados, acesso individual, autorização backend, logs saneados e uso de recursos sustentado no KVM 4.

## 6. Etapa 6 | NexoFlow Métricas web: paridade Data Studio e melhorias

O **NexoFlow Métricas** não é Grafana, n8n nem a Central técnica. É um produto BI próprio com endereço separado e acesso direto para gestores/convidados, inclusive quem **não é admin**.

### Requisitos de acesso

- Administrador cria usuários individuais com login/senha e pode habilitar, revogar, bloquear, redefinir e auditar acessos. Não compartilhar credencial única.
- Perfis `administrador`, `gestor`, `visualizador` e papéis técnicos distintos. Um visualizador pode ter acesso exclusivamente a `FARMA` ou `PET`, apenas aos relatórios/métricas autorizados.
- Autorização real por organização/segmento/relatório implementada **no servidor e nas consultas**, não apenas ocultação de componentes visuais.
- Links com filtros não podem elevar permissões ou contornar autenticação. Sem acesso a credenciais das APIs, SQL, n8n ou logs brutos.
- Separar autenticação/sessão de Métricas do Hub administrativo. Um link próprio aparece no menu do Hub para quem tiver permissão.

### Paridade obrigatória e refinamentos

- Reproduzir **todas as páginas existentes de FARMA e PET** conforme matriz 3.5.4, com as mesmas definições de métricas. Preencher lacunas equivalentes apenas quando houver fonte confiável; avaliar `Pedidos dos anúncios` para PET.
- Filtros de período equivalentes aos atuais, inclusive datas livres, comparação com período anterior **somente quando válida**, reset, filtros cruzados, detalhamento, ordenação, busca, paginação, seleção e exportação autorizada.
- Resumo: receita, pedidos, compradores, ticket, evolução, rankings e última sincronização.
- Vendas: receita/produtos/frete, pedidos válidos/cancelados, evolução e compradores por período.
- Clientes: comprador oficial distinto, recorrência, frequência, LTV **observado acumulado** independente do filtro mensal, primeira/última compra e cobertura `completa/incompleta/não comprovada`.
- Pedidos por cliente: agrupamento correto por identidade oficial confirmada, sem confundir pessoas com contatos Weni; detalhe de pedidos/itens conforme permissão.
- Produtos: ranking por receita/unidades, Top 5 participação, Top 10 dermocosméticos FARMA quando existir classificação, Curva ABC própria (80/15/5), filtro uniforme.
- Público/Base: contatos, compradores, sem compra, porcentagem, localidade e geografia normalizada; CPF/PII minimizados conforme perfil.
- Anúncios: Meta/Google custos, conversas, taxa conversa→venda, compradores, conversões, CAC/ROAS/payback apenas com atribuição e denominadores comprovados; sem inferir compra por clique ou simples contato.
- Pedidos dos anúncios: evidências temporais, anúncio elegível anterior ao pedido, comprador (quando autorizado), itens e valor, vínculos relacionados versus **atribuídos**, filtro por período.
- Atualização: fontes, frescor, atrasos, cobertura, falhas e dados ainda pendentes.
- Visual: identidade própria NexoFlow, clean/dark responsivo, FARMA/PET com marca e cores coerentes, sem reproduzir layout genérico do Data Studio ou expor dados sensíveis em cards.

### Arquitetura de dados

- PostgreSQL Hub armazena fatos validados e agregações/views específicas de consulta. Dashboard usa API BI dedicada e consultas autorizadas, preferencialmente views materializadas/incrementais, sem leituras pesadas em tabelas brutas a cada visualização.
- Paridade exige **mesmo período, mesma política monetária, mesma fonte, mesmo estágio de cobertura e mesma identidade**. Divergências são rastreadas e não mascaradas.
- Política de refresco, cache, consultas indexadas, métricas de uso, logs saneados, testes de isolamento por segmento e controle de exportações.
- Preservar os dois relatórios Data Studio atuais como referência e fallback até validação formal página a página; nenhuma substituição ou desligamento antecipado.

**Aceite:** matriz de paridade preenchida para cada relatório, testes automatizados e amostras reais autorizadas, paridade financeira documentada, login por marca, sem vazamento entre perfis, desempenho/capacidade satisfatórios, rollback para relatórios existentes.

## 7. Etapa 7 | Escrita comercial e coordenação

Escrita real do Hub continua desabilitada até autorização por destino/segmento. PostgreSQL Hub e locks Win32 **não coordenam os dois ambientes**. Definir proprietário único para cada escritor, fencing/lock compartilhado ou corte operacional, confirmação posterior, resposta incerta, deduplicação e rollback. Separar leitura de escrita; ativação de Weni, Sheets ou outros consumidores é gradativa. Comprovar observabilidade e backup antes de cada liberação.

## 8. Responsabilidades, prioridades e regras de aceite transversais

| Executor | Foco |
| --- | --- |
| **Codex** | Contratos Python, segurança/telemetria no código, DB migrations, endpoints de consulta, frontend web, métricas e testes de regressão Windows/Hub |
| **Work** | Auditoria VPS, Docker, PostgreSQL read-only/túnel, rede, grafana/coletores quando aprovados, Cloudflare, deployment/backup/monitoramento, ensaios e relatórios |
| **Responsável pelo projeto** | Aprovar exposições públicas, perfis/usuários reais, escrita comercial, exclusões destrutivas, credenciais e transição de dashboards |

A autonomia para mudanças **reversíveis e isoladas em homologação** é ampla. Exigir autorização específica antes de: excluir snapshots/volumes/dados, publicar dashboards com dados comerciais ou criar novos subdomínios públicos, ativar escrita comercial, rodar cargas de grande volume, rotacionar credenciais compartilhadas ou reiniciar VPS. Não atualizar `main` automaticamente na VPS; registrar SHA e testes de cada implantação.

### Próximos entregáveis práticos

1. **Work 3.5:** inventário e retenção; verificar execuções n8n; acesso PostgreSQL read-only via túnel e manual DBeaver; contrato mínimo de métricas; projeto de autorização; monitoramento de custo/capacidade. Sem mexer em serviços comerciais.
2. **Codex 3.5/4:** instrumentação mínima e contrato de métricas/erros, API de consulta e validação de regressões Windows 1.5.18 ↔ Hub, sem portal completo ainda.
3. **Work + Codex 4:** homologação real em leitura, por fonte e segmento, com desempenho, recorte de datas, idempotência e comparação das contas atuais.
4. **Work + Codex 5/6:** dashboards/portal e Métricas com paridade e autorização; só então considerar substituição do Data Studio.

Este documento prevalece como **roadmap**, não como prova de que funcionalidades planejadas estejam ativadas.
