# Documentação do NexoFlow 1.0

Comece pela [instalação](README%20INSTALACAO.md) e pelo [guia de operação](Documentacao%20NexoFlow.md).

## Uso dos aplicativos

| Assunto | Guia |
| --- | --- |
| Rotina automática durante a madrugada | [NexoFlow Noturno](NOTURNO.md) |
| Contatos, pedidos e grupos na Weni | [NexoFlow Weni](README%20WENI.md) |
| Importação de conversas e contatos | [NexoFlow Planilha](README%20DELIVERY.md) |
| Campanha D+25 | [NexoFlow Recompra](README%20RECOMPRA.md) |
| Comandos e diagnóstico | [NexoFlow Terminal](README%20TERMINAL.md) |

## Dados e integrações

- [Configuração do Google Sheets](GOOGLE%20SETUP.md) e [divisão em três arquivos](planilhas_separadas.md).
- [Fontes e indicadores do Looker Studio](LOOKER%20STUDIO.md).
- [Regras de pedidos](PEDIDOS.md), [campos de pedido na Weni](PEDIDOS%20WENI.md) e [API FarmaLíder](FARMALIDER%20API.md).
- [Cadastro FARMA](CADASTRO%20FARMA.md), [localização](geografia.md) e [contatos duplicados](deduplicacao_weni.md).
- [Google Ads](GOOGLE%20ADS.md).

## Suporte e desenvolvimento

O código fica em `app/`, as rotinas em `comandos/` e os modelos em `configuracao/`. Instalação, empacotamento e validação ficam em `installer/`, `scripts/` e `tests/`.

[Proxy e rede](README%20PROXY.md) · [Antivírus](ANTIVIRUS%20E%20CONFIANCA.md) · [Ambiente de desenvolvimento](README%20VSCODE.md) · [Testes](../tests/README.md) · [Histórico de mudanças](../CHANGELOG.md)

Os guias de [webhook Weni](WENI%20WEBHOOK.md), [webhook de pedidos](WEBHOOK%20PEDIDOS%20FUTURO.md) e [Meta Ads](META%20FUTURO.md) descrevem recursos opcionais ou futuros.

A fonte do guia de operação é `docs/Documentacao NexoFlow.md`; seu [HTML](Documentacao%20NexoFlow.html) é gerado por `python scripts/build_documentation.py`. Edite o Markdown e regenere o HTML.
