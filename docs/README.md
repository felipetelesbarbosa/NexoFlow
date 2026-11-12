# Documentação do NexoFlow 1.5.35

O **NexoFlow Windows** atende **FarmaLíder e Pets Líder**, com aplicativos operacionais autônomos e dados separados. Confira [segmentos, campos e fluxos](SEGMENTOS%20E%20FLUXOS.md).

Comece pela [instalação](README%20INSTALACAO.md) e pelo [guia de operação](Documentacao%20NexoFlow.md).

[Base Mestre de conhecimento e diretrizes](planejamento/DIRETRIZES_E_CONHECIMENTO_NEXOFLOW.md): arquitetura, contratos, estados, pendências e passagem Codex/Work.

## Uso dos aplicativos

| Assunto | Guia |
| --- | --- |
| Rotina automática durante a madrugada | [NexoFlow Noturno](NOTURNO.md) |
| Contatos, pedidos e grupos na Weni | [NexoFlow Weni](README%20WENI.md) |
| Agentes de IA, Weni CLI, IA Manager e Flows (referência futura) | [Base de conhecimento Weni CLI e agentes](WENI%20CLI%20AGENTES%20E%20FLUXOS.md) |
| Importação de conversas e contatos | [NexoFlow Planilha](README%20DELIVERY.md) |
| Campanhas Farma D+25 e Pets D+30 | [NexoFlow Recompra](README%20RECOMPRA.md) |
| Comandos e diagnóstico | [NexoFlow Terminal](README%20TERMINAL.md) |

## Dados e integrações

- [Ritmo HTTP e retomada da publicação 1.5.30](COTAS%20SHEETS%20HISTORICO%201.5.30.md).

- [Configuração do Google Sheets](GOOGLE%20SETUP.md) e [divisão em três arquivos](planilhas_separadas.md).
- [Continuações automáticas e capacidade do Sheets](CONTINUACOES.md).
- [Criação e retomada de continuações vazias](CORRECAO%20CRIACAO%20CONTINUACOES.md), incluindo a revisão pendente sob 1.5.25.
- [Fontes e indicadores do Data Studio](DATA%20STUDIO.md).
- [Regras de pedidos](PEDIDOS.md), [campos de pedido na Weni](PEDIDOS%20WENI.md) e [API FarmaLíder](FARMALIDER%20API.md).
- [Cadastro por segmento](CADASTRO%20FARMA.md), [localização](geografia.md) e [contatos duplicados](deduplicacao_weni.md).
- [Google Ads](GOOGLE%20ADS.md).

[Relatório técnico da otimização 1.5.12](RELATORIO%20OTIMIZACAO%201.5.12.md) — causas, benchmarks e limites da validação.

## Suporte e desenvolvimento

O código fica em `app/`, as rotinas em `comandos/` e os modelos em `configuracao/`. Instalação, empacotamento e validação ficam em `installer/`, `scripts/` e `tests/`.

[Proxy e rede](README%20PROXY.md) · [Antivírus](ANTIVIRUS%20E%20CONFIANCA.md) · [Ambiente de desenvolvimento](README%20VSCODE.md) · [Testes](../tests/README.md) · [Histórico de mudanças](../CHANGELOG.md) · [Versionamento](VERSIONAMENTO.md)

## Operação atual e planejamento

A [integração Meta nativa](META%20ADS%20NATIVO.md) funciona diretamente no Analytics e no Noturno quando habilitada. O [MCP local](META%20ADS%20MCP%20LOCAL.md) é opcional e não torna Codex um requisito das cargas. [Webhook Weni](WENI%20WEBHOOK.md) e [webhook de pedidos](WEBHOOK%20PEDIDOS%20FUTURO.md) mantêm seus estados e requisitos específicos.

O [catálogo de planejamento](planejamento/README.md) separa o **NexoFlow Hub em homologação e sua evolução planejada**, para VPS, Docker e n8n, da operação Windows distribuída. O plano de [histórico, atribuição e LTV](planejamento/HISTORICO_PEDIDOS_ATRIBUICAO_LTV.md) não representa uma integração implantada.

A fonte do guia de operação é `docs/Documentacao NexoFlow.md`; seu [HTML](Documentacao%20NexoFlow.html) é gerado por `python scripts/build_documentation.py`. Edite o Markdown e regenere o HTML.

- [Diagnóstico somente leitura de pastas e permissões do histórico](DIAGNOSTICO%20ACESSOS%20HISTORICO.md): diferencia as autoridades OAuth/serviço sem substituir a instalação 1.5.27.

- [Analytics e histórico automático 1.5.31](ANALYTICS%20HISTORICO%20AUTOMATICO.md)

- [Otimização de intervalos do histórico — desenvolvimento posterior à 1.5.31](OTIMIZACAO%20INTERVALOS%20HISTORICO.md).
