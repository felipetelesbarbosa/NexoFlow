# Planejamento | NexoFlow

Esta pasta reúne o planejamento do **NexoFlow Hub**, da **Central de Operações** e do **NexoFlow Métricas**. O roadmap diferencia entregas já homologadas de funcionalidades planejadas e **não autoriza produção, publicação de serviços ou exclusões destrutivas**.

## Cronograma oficial

**[Cronograma mestre: Hub, Central de Operações e NexoFlow Métricas](CRONOGRAMA_MESTRE_HUB_METRICAS.md)**

O documento consolida:
- Etapas 1–3 já realizadas, com ressalvas.
- **Etapa 3.5 (próxima):** capacidade e retenção, telemetria, acesso técnico PostgreSQL, DBeaver Community no PC, identidade e inventário dos dashboards atuais.
- **Etapa 4:** integrações comerciais homologadas **somente para leitura**.
- **Etapa 5:** observabilidade e Central de Operações própria, inspirada nas referências visuais Iota.hub.
- **Etapa 6:** **NexoFlow Métricas** com URL/login próprios, permissões por marca e paridade com os dois dashboards Data Studio existentes.
- **Etapa 7:** eventual ativação de escrita comercial, somente após coordenação segura Windows/Hub e autorização própria.
- **Etapa 8:** evolução, escala e governança.

## Produtos e situação

| Produto | Situação |
| --- | --- |
| **Windows** | Operacional e autônomo; release 1.5.18 disponível, sujeito a homologações comerciais próprias. |
| **Hub Linux** | Núcleo desenvolvido; implantado em **homologação isolada na VPS** na Etapa 3, originalmente SHA 23f2806. Testes n8n/PostgreSQL, backups e restauração aprovados com ressalvas. Nenhuma integração comercial ativada. |
| **Central de Operações** | Planejada, com preparação de telemetria e segurança na 3.5. |
| **NexoFlow Métricas** | Planejado, com inventário/paridade Data Studio e arquitetura de permissões iniciados na 3.5. |

A implantação na VPS registrada pelo relatório do Work não deve ser confundida com a implantação comercial: `HUB_AMBIENTE=homologacao`, `HUB_ESCRITA_REAL=false` e workflows não comerciais inativos. O SHA atual do Windows não deve ser aplicado automaticamente na VPS.

## Referências de BI atuais

- [NexoFlow Analytics - FarmaLíder (Data Studio)](https://datastudio.google.com/reporting/e60ba3bc-fe88-417d-8a39-d8512debf175/page/oeZAG)
- [NexoFlow Analytics - Pets Líder (Data Studio)](https://datastudio.google.com/reporting/35c02ed5-901b-4134-a735-5ac9a9290306/page/oeZAG)

Ambos são **baseline obrigatório** do NexoFlow Métricas. Inventariar páginas, fórmulas, filtros, controles e interações antes de desenvolver paridade; manter os relatórios atuais funcionando até aceitação formal.

## Planejamento especializado

- [Histórico de pedidos, atribuição e LTV](HISTORICO_PEDIDOS_ATRIBUICAO_LTV.md): contratos e propostas comerciais, confrontar com documentação operacional atual.
- [Guia operacional Windows](../HISTORICO%20PEDIDOS.md).
- [Núcleo e guia Hub](../../hub/README.md).
- [Weni CLI, IA Manager, agentes ativos/passivos e integração futura com Flows](../WENI%20CLI%20AGENTES%20E%20FLUXOS.md) — referências e critérios de validação, **sem ativação de agentes ou disparos comerciais**.

O Windows deve continuar autônomo, sem dependência de n8n/VPS, e os dois segmentos devem manter separação de estado, credenciais, dados e permissões. Todos os segredos permanecem fora do Git.
