# Weni CLI, agentes de IA, IA Manager e Flows | Base de conhecimento NexoFlow

> **Referência documental. Atualizado em 09/11/2026.** Não é especificação de funcionalidade já implantada. Não autoriza deploy, criação de agente, alteração de fluxos, disparo de mensagens ou escrita comercial.

Consulte primeiro a [Base Mestre compartilhada](planejamento/DIRETRIZES_E_CONHECIMENTO_NEXOFLOW.md). Este guia continua sendo a referência especializada de agentes e Flows.

## 1. Propósito e aplicações no NexoFlow

Esta base reúne referências oficiais da **Weni / VTEX CX Platform (Weni)** para futuras integrações com **NexoFlow Windows/Local, Analytics, Hub/Cloud, Painel Web e Métricas**. O foco é compreender como agentes personalizados e o IA Manager podem consultar dados oficiais, executar ferramentas autorizadas e eventualmente cooperar com **Flows/Studio** para automações de atendimento (FARMA e PET).

Tratar **IA Manager/Agent Builder** (configuração e coordenação de agentes), **agente passivo**, **agente ativo**, **ferramenta personalizada** e **fluxo de mensagens** como conceitos distintos. Não pressupor que criar/publicar um agente dispare automaticamente um fluxo ou uma mensagem.

## 2. Fontes oficiais e prioridade

**Documentação atual (preferir para CLI, sintaxe e contratos):**

- [VTEX Developers | Weni by VTEX CLI: introdução e instalação](https://developers.vtex.com/docs/guides/using-the-weni-by-vtex-cli)
- [VTEX Developers | Referência de comandos Weni CLI](https://developers.vtex.com/docs/guides/weni-by-vtex-cli-command-reference)
- [VTEX Developers | Working with Weni agents](https://developers.vtex.com/docs/guides/working-with-weni-by-vtex-agents)
- [VTEX Developers | Testes de ferramentas com Weni Run](https://developers.vtex.com/docs/guides/using-weni-run-to-execute-tool-tests)
- [Comunicado oficial de migração da documentação CLI para VTEX Developers (2025)](https://developers.vtex.com/updates/release-notes/2025-11-21-wenibyvtex-cli-in-devportal).

**Documentação complementar da Weni CLI (verificar atualidade antes de implementar):**

- [Weni CLI | Portal original](https://weni-ai.github.io/weni-cli/)
- [Weni CLI | Agentes e YAML](https://weni-ai.github.io/weni-cli/user-guide/agents/)
- [Weni CLI | Agentes passivos](https://weni-ai.github.io/weni-cli/core-concepts/passive-agents/)
- [Weni CLI | Agentes ativos](https://weni-ai.github.io/weni-cli/core-concepts/active-agents/)
- [Weni CLI | Ferramentas Python](https://weni-ai.github.io/weni-cli/core-concepts/tools/)
- [Weni CLI | Testes de agentes ativos](https://weni-ai.github.io/weni-cli/run/active-agent-run/)
- [Weni CLI | Referência de comandos e logs](https://weni-ai.github.io/weni-cli/utils/commands-glossary/)
- [Repositório oficial da Weni CLI](https://github.com/weni-ai/weni-cli).

**Fluxos, disparadores e integrações de mensagens:**

- [Weni Flows | API Explorer v2](https://flows.weni.ai/api/v2/explorer/) — contratos de fluxos, campos, contatos, grupos, execuções e inicialização.
- [Organização Weni no GitHub](https://github.com/weni-ai) e [repositório Weni Flows](https://github.com/weni-ai/flows) — referência de módulos e código, não substitui a API contratada.
- [Weni Agent Builder](https://agentbuilder.weni.ai/) — interface do produto, requer contexto/autorização para validar comportamento do IA Manager.

**Nota sobre atualização:** a Weni informou a migração da documentação de CLI para o VTEX Developers Portal. Em divergências de comandos, conferir documentação do portal, versão instalada com `weni --version` e comportamento efetivo autorizado. O site Weni CLI original e materiais antigos da comunidade servem como referência complementar, não como contrato imutável.

## 3. Modelo conceitual para futuras integrações

| Camada | Papel documentado / hipótese de integração | Cuidados |
| --- | --- | --- |
| **IA Manager / Agent Builder** | Configurar/acompanhar agentes e comportamentos no produto; investigar especificamente a orquestração entre agentes antes de afirmar detalhes internos. | Não inferir APIs ou gatilhos apenas da interface. |
| **Agente passivo** | Reage a entrada do usuário, contexto e instruções; pode chamar tools. | Guardrails, parâmetros, autorização e tratamento de erros. |
| **Agente ativo** | Usa pré-processamento e regras/condições para selecionar ações; definição YAML distinta. | Testar pipeline, elegibilidade, templates e risco de ações duplicadas. |
| **Tool** | Classe Python que herda de `Tool` e implementa `execute(context)`; pode consultar APIs e executar lógica própria. | Segredos via Context, validação de parâmetros, timeout, idempotência, observabilidade. |
| **Weni Flows/Studio** | Executa fluxos e gatilhos de mensagens; a API Flows contém operações próprias de inicialização. | Não confundir publicar agente com começar fluxo; restringir POST e campanhas a ambientes autorizados. |
| **NexoFlow** | Fonte técnica potencial de dados verificados para consulta, regras e integração; mantém autonomia e separação FARMA/PET. | Nenhuma função nova de disparo está autorizada por esta documentação. |

### 3.1 Comandos CLI para estudo, não execução nesta tarefa

```bash
weni --version
weni login
weni project list
weni project current
weni project use <project_uuid>
weni run agent_definition.yaml <agent_key> <tool_key> -v
weni logs --agent <agent_key> --tool <tool_key>
# MUTANTE: cria/atualiza agentes e tools; exigir ambiente e autorização próprios:
weni project push agent_definition.yaml
```

Definições de agentes usam YAML com `name`, `description`, `instructions`, `guardrails`, `tools`, `source.path`, `source.entrypoint`, parâmetros e opcionalmente `path_test`. Ferramentas personalizadas usam SDK Python, `Context` e objetos de resposta. Agentes ativos têm configuração de `rules`, `start_condition` e `pre_processing`, com teste próprio documentado na Weni CLI. Verificar sempre diferenças entre documentação legada e a versão instalada.

**Limite:** a CLI pode publicar/configurar agentes. **Não assumir** que seu comando `project push` inicia campanhas ou o Flows do atendimento.

### 3.2 Como um fluxo pode começar (documentação da API Weni Flows)

O [API Explorer v2 da Weni Flows](https://flows.weni.ai/api/v2/explorer/) documenta, entre outros:

- `GET /api/v2/flows.json` — listar fluxos autorizados.
- `GET /api/v2/flow_starts.json` — consultar inicializações.
- `POST /api/v2/flow_starts.json` — **iniciar contatos em um fluxo**, com UUID do fluxo e destinatários (`contacts`, `urns` ou `groups`, conforme contrato), opção de `restart_participants` e `extra`.
- `GET /api/v2/fields.json` e rotas de consultas de contatos — validar campos e identidades.
- `GET /api/v2/definitions.json` — exportação de definições, segundo permissões.

Essa documentação confirma a existência de uma operação de início de fluxo. **Não confirma** que todo tipo de agente personalizado tem permissão para chamá-la automaticamente ou que qualquer gatilho de IA Manager tenha equivalência direta com um `flow_start`. Esse vínculo exige teste no tenant/projeto e aprovação da regra comercial.

Não confundir um `POST /flow_starts` para contatos identificados com broadcast em massa, início por palavra-chave, resposta de atendimento ou execução de ferramenta CLI. São vias distintas, com controles de permissão, elegibilidade e mensagens.

## 4. Casos futuros de uso a investigar (não implantados por esta nota)

- **Atendimento de pedidos:** agente consulta via tool de leitura um pedido confirmado e pode orientar o cliente, sem inventar pagamento/entrega.
- **Abertura ou encaminhamento:** agente identifica intenção, seleciona fluxo oficial previamente aprovado e registra correlação, evitando múltiplos disparos.
- **Recompra FARMA/PET:** eventuais ações só após validar elegibilidade, consentimento LGPD, regras de opt-out, restrições de campanha, status oficial e proteção contra duplicações. Não substituir o contrato atual de Recompra.
- **Atualização operacional:** fluxo ou agente consulta status da integração sem permitir que o modelo altere pedidos, pagamentos ou clientes sem autorização explícita.
- **Observabilidade:** eventos de tool/agente/fluxo podem alimentar indicadores agregados na Central de Operações, evitando payloads pessoais e segredos.

## 5. Contrato de segurança para qualquer implementação futura

1. **Primeiro documentar o fluxo real:** agente → tool → endpoint Weni/NexoFlow → validação → eventual `flow_start` → confirmação. Identificar onde cada decisão ocorre.
2. **Leitura antes de escrita:** APIs de consulta e testes sintéticos não concedem autorização para `POST` em produção.
3. **Isolar segmentos/organizações:** chaves, UUIDs de fluxo, contatos, campanhas, tokens, regras e estados FARMA/PET separados.
4. **Consentimento e canal:** confirmar opt-in/opt-out, política WhatsApp/template, janela de atendimento, finalidade e base legal aplicável antes de disparos.
5. **Identidade robusta:** conferir UUID/URN do contato e vínculo com o pedido; não usar só nome/CPF informado em texto pelo agente.
6. **Idempotência e concorrência:** chave por evento/fluxo/contato/segmento, locks, rechecagem de estados, deduplicação e limite de taxa.
7. **Erros recuperáveis:** timeouts, 429, 4xx/5xx, retries com backoff e limites; uma resposta perdida não autoriza repetição cega de envio.
8. **Observabilidade segura:** logs com timestamp, tipo de agente, tool, flow UUID, resultado, duração e correlação opaca. Omitir tokens, PII, mensagens integrais e headers de autenticação.
9. **Teste e aceitação:** validar comportamento do IA Manager em ambiente autorizado, ferramentas em testes, fluxo de ponta a ponta, casos de falha, exceções e retorno ao humano.
10. **Controle operacional:** habilitação explícita, dry-run, auditoria, rollback quando tecnicamente aplicável e possibilidade de desativação imediata.

## 6. Como investigar problemas de agentes e fluxos

- **Agente não chama tool:** conferir YAML, nome/entrypoint, descrição, parâmetros `required`, guardrails, disponibilidade, versões e testes `weni run`.
- **Tool falha:** validar parâmetros, `context.credentials`, status HTTP da API alvo, timeout, logs e tratamento de exceções; mascarar dados sensíveis.
- **IA Manager não encaminha:** conferir no produto quem seleciona agente, ferramenta, fluxo e estado conversacional. Registrar evidência, não deduzir implementação interna.
- **Fluxo não inicia:** confirmar UUID do flow, contato/URN, permissões do token, requisitos de elegibilidade, status no `flow_starts` e respostas da API.
- **Fluxo dispara duas vezes:** investigar retries, eventos duplicados, reinício de participantes, concorrência e chave idempotente.
- **Atendimento humano:** distinguir transferência para Live Desk/Chats, seleção de fluxo e resposta textual do agente; requer desenho e homologação próprios.

## 7. Documentação NexoFlow relacionada

- [NexoFlow Weni: integração existente, campos e política de escrita](README%20WENI.md)
- [Segmentos e fluxos](SEGMENTOS%20E%20FLUXOS.md)
- [Webhook de anúncios/conversas Weni](WENI%20WEBHOOK.md)
- [Recompra e políticas operacionais](README%20RECOMPRA.md)
- [Planejamento NexoFlow Hub e Métricas](planejamento/README.md).

**Estado em 09/11/2026:** este documento **não comprova** que o IA Manager esteja integrado via CLI ao NexoFlow, nem que o NexoFlow dispare `flow_starts` por agente. É referência de pesquisa para futuras correções e desenvolvimentos. Para cada trabalho, confirmar versão, permissão, endpoints e ambiente reais antes de alterar algo.
