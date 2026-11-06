# Planejamento — NexoFlow Hub

Esta pasta reúne propostas do **NexoFlow Hub**, projeto paralelo futuro para VPS, Docker e n8n. Seu conteúdo descreve hipóteses, contratos pendentes e critérios de homologação; não constitui uma implantação.

| Produto | Situação e escopo |
| --- | --- |
| **NexoFlow Windows** | Aplicativos operacionais autônomos: Weni, Analytics, Planilha, Recompra, Terminal e Noturno. Python, credenciais e agendamentos locais; integração Meta nativa e MCP opcional. |
| **NexoFlow Hub** | Projeto futuro. VPS, Docker, n8n, persistência e eventual coordenação precisam de especificação, implementação isolada e homologação próprias. |

O Setup Windows não instala serviços do Hub nem exige que uma VPS esteja disponível. Os schemas, IDs dos arquivos Sheets, históricos, guardas e regras comerciais do Windows são preservados. Uma integração futura não pode introduzir dependência ou escrita concorrente sem contrato e validação específicos.

- [Histórico de pedidos, atribuição e LTV](HISTORICO_PEDIDOS_ATRIBUICAO_LTV.md): arquitetura conceitual, API histórica ainda sem contrato completo e workflows n8n não implantados.
- [Documentação operacional Windows](../README.md): instalação, rotinas atuais e integrações já disponíveis.
