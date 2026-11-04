# Integração Meta Ads MCP local — conferência técnica

**Contexto:** este documento registra a fase preparatória que manteve a versão 1.5.12. A entrega 1.5.13 foi autorizada em 04/11/2026 e aguarda os checks do mesmo commit antes da publicação, preservando o release anterior. Para a operação nativa, consulte o [relatório atual](RELATORIO%20META%20ADS%20NATIVO.md).

## Alterações

Conector opcional em `connectors/meta_ads_mcp`, com cliente reutilizável sem dependência do servidor MCP ou do Codex no futuro Analytics. Transporte STDIO, seis ferramentas de leitura, GET com host/caminhos fixos, allowlist de contas, verificação de ads_read e bloqueio de ads_management. Credenciais somente em `credentials/mcp/meta_ads_credentials.json`, ignoradas pelo Git; token fora de URL, cadastro Codex, exemplos e mensagens de erro.

Setup opcional instala/valida Codex CLI pelo instalador standalone oficial. Preserve reaproveita instalações compatíveis; Clean reinstala os componentes selecionados. O ambiente MCP usa Python 3.14 isolado e se reconstrói com recuperação quando incompatível. Instalação opcional falha de forma explícita e registra pendência sem desfazer o NexoFlow básico. Configurações e autenticação do Codex e outros servidores MCP são preservados. Versão NexoFlow permanece 1.5.12; commits desta integração usam [skip release].

## Testes executados

- 19 testes offline do conector com SDK MCP real, incluindo initialize, tools/list e tools/call em subprocesso STDIO; HTTP sintético cobre autorização, allowlist, paginação, limites, dados vazios/malformados, 400/401/403/429 e timeout.
- 17 testes do validador/instaladores: PowerShell real com download e comandos externos simulados, detecção compatível repetida sem reinstalar, Clean, recuperação, registro existente/divergente e Python incompatível.
- 1.592 testes do projeto: passaram, com 68 dependentes de ambiente ignorados localmente.
- Ruff, consistência, verificação de dependências e auditoria de segredos: sem problemas encontrados nas verificações executadas. Dependências opcionais foram instaladas em ambiente separado.
- Workflow dedicado valida o conector em Linux e Windows/Python 3.14 e os validadores PowerShell em Windows. Os checks do commit final devem ser conferidos no GitHub; nenhum teste usa token de produção.

## Pendências e limites

O computador Windows do usuário, seu Codex e o token privado não estão acessíveis neste ambiente. Login Codex, token ads_read, escopo efetivo, acesso à conta e consulta real Meta ainda precisam de validação local. Nenhuma campanha foi alterada e nenhuma gravação em Google Sheets/Data Studio foi realizada. O instalador oficial do Codex não foi executado para instalar software real durante os testes. O novo fluxo de Setup está no código GitHub; o Setup 1.5.12 publicado anteriormente não foi substituído. Distribuir novo pacote exige autorização de release e validação do pacote instalado.

## Plano Analytics / Data Studio

Ver [PLANO META ADS ANALYTICS](PLANO%20META%20ADS%20ANALYTICS.md). Primeiro validar somente leitura e mapear conta/campanha/anúncio explicitamente para FARMA/PET. Depois simular fatos por conta + anúncio + dia, com moeda, fuso e janela de atribuição. O método insights atual agrega o período; dados diários exigem adaptar a consulta explicitamente. Não escrever esse agregado diretamente em Campanhas_Meta: o schema legado não contém conta/período.

Propor migração compatível, validar em cópia e obter autorização antes de novas abas/colunas ou escrita. Integrar ao dashboard informado preservando as abas Anúncios e Pedidos dos Anúncios e filtros por data. Custos e métricas atribuídas Meta ficam separados de pedidos/receita confirmados pela FarmaLíder. Repetições devem atualizar a mesma chave, sem duplicar custos ou vendas; CPA/CAC/ROAS ficam indisponíveis quando falta cobertura ou definição comparável. Ativação no Analytics/Noturno é etapa posterior, sem mudanças nas rotinas atuais.
