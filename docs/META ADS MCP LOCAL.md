# Meta Ads MCP local — especificação NexoFlow

## Escopo inicial

- Aplicativo Meta Developers: **NexoFlow Ads MCP** — ID `29468534812833595`.
- Token de usuário do sistema com escopo `ads_read`; jamais `ads_management`.
- Conta inicialmente autorizada: `898435729140540` (somente leitura).
- Contas adicionais exigem ID real e acesso de visualização pela conta técnica.
- Mesmo nas contas em que o usuário pessoal tem acesso total, o MCP permanece
  exclusivamente de leitura em todas elas.

## Arquitetura

```
Codex local ──STDIO──> connectors/meta_ads_mcp/server.py
                                 │
                                 ▼
                     client.py (somente GET)
                                 │
                                 ▼
                       Meta Marketing API
                                 ▲
              credentials/mcp/meta_ads_credentials.json
```

O GitHub guarda o código e os testes, nunca o processo local ou o token.
O NexoFlow pode importar o mesmo cliente Python em futuras rotinas de Analytics.

## Ferramentas públicas

- `contas_permitidas()` — IDs permitidos pela configuração, sem checar Meta.
- `detalhes_conta(conta_id)` — ID, nome, moeda, status, fuso.
- `campanhas(conta_id, limite=50, paginas=2)`.
- `conjuntos(conta_id, limite=50, paginas=2)`.
- `anuncios(conta_id, limite=50, paginas=2)`.
- `insights(conta_id, data_inicio, data_fim, nivel='campaign', limite=100, paginas=3)`.

Limites: até 100 resultados/página, 10 páginas/chamada e intervalo máximo
entre datas de 92 dias. Saída `parcial=true` indica paginação interrompida.
Não existem ferramentas de modificar, criar, pausar ou excluir ativos.

## Integração futura com NexoFlow Analytics

No repositório inspecionado, `app/analytics.py` define `META_CAMPAIGN_COLUMNS`
com `anuncio_id, anuncio_nome, conjunto_id, conjunto_nome, campanha_id,
campanha_nome, investimento, impressoes, cliques, atualizado_em`.

O projeto também possui `app/ad_attribution.py`, `app/meta_events.py`,
`docs/RASTREAMENTO_META.md`, `BI_Ads`, `Eventos_Anuncios` e `Campanhas_Meta`.

**Não gravar Insights diretamente na tabela sem analisar o grão.** O schema
atual de `Campanhas_Meta` não possui conta de anúncios nem período: somar
custos de diferentes dias/contas sem incluir a data gera dupla contagem ou
sobrescrita. Codex deve propor alteração compatível com migração e testes,
antes de qualquer escrita. Conservar FARMA e PET separados, preservar dados
históricos e rotinas de Recompra.

Conversões Meta (ações/ROAS) são atribuídas pela plataforma de anúncios e
não significam pedidos confirmados na API FarmaLíder; atribuição por CTWA
na Weni exige identidade explícita, sem inferir causalidade somente por ID.

## Exemplos

`insights` de 1º a 31 de outubro de 2026, por campanha:

```text
Use a ferramenta insights de nexoflow-meta-read com:
conta_id: 898435729140540
data_inicio: 2026-10-01
data_fim: 2026-10-31
nivel: campaign
```

## Diagnóstico de erro

- HTTP 400/403: token inválido, sem `ads_read`, conta não atribuída ao usuário
  do sistema ou field não suportado pela versão da API.
- HTTP 429: taxa de consulta excedida; implemente retry com `Retry-After`
  antes de automatizar sincronizações em lote.
- MCP não aparece: confira `codex mcp list`, Python da `.venv` e caminho `server.py`.
- Proibição de conta: confirme lista `allowed_ad_account_ids`, sem desativar
  sua proteção para contornar a autorização.

## Instalação e estado de validação

Execute na instalação local do Windows:

```powershell
cd C:\NexoFlow
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\instalar_meta_ads_mcp.ps1
codex mcp get nexoflow-meta-read
```

O cadastro esperado usa o Python isolado `connectors\meta_ads_mcp\.venv\Scripts\python.exe` e o argumento absoluto `connectors\meta_ads_mcp\server.py`. O token não participa do cadastro e não deve ser passado por `--env`. Preserve servidores Codex já existentes; um registro divergente precisa de diagnóstico antes de qualquer substituição.

A única origem operacional da credencial é `credentials/mcp/meta_ads_credentials.json`. O modelo público `configuracao/meta_ads_credentials.example.json` contém somente placeholder e IDs autorizados. Não colocar token no `.env`, `config.toml`, `secrets_config.py`, workflows, comandos ou logs. Não forçar inclusão da credencial no Git.

O instalador e os testes offline preparam a integração; eles não comprovam que o usuário do sistema tem acesso real à conta. A consulta real e a confirmação do registro no Codex do Windows permanecem pendentes até execução nesse computador. Não usar o nível de acesso pessoal como autorização para escrita: as seis ferramentas continuam somente de leitura, sem administração de anúncios.

O plano de reutilização direta do cliente pelo Analytics, com grão diário, migração compatível, separação dos segmentos e regras dos indicadores, está em [Plano Meta Ads Analytics](PLANO%20META%20ADS%20ANALYTICS.md). Nenhuma etapa de escrita ou mudança de schema foi ativada nesta fase; a versão operacional foi preservada.

## Validação desta integração

Foram executados 19 testes offline do conector com o SDK MCP instalado em ambiente separado, incluindo initialize/tools/list/tools/call por STDIO; 1.575 testes do projeto passaram (68 específicos de ambiente ignorados). Lint e auditoria de consistência passaram. Nenhum token real foi lido e nenhuma consulta à Meta ou escrita de produção foi executada. A instalação PowerShell/Python 3.14 é conferida pelo workflow dedicado e ainda precisa ser executada no computador do usuário. O registro real no Codex desse computador permanece pendente.

Commits preparatórios usam `[skip release]`: verificações continuam ativas, mas o workflow operacional não empacota nem publica essas alterações. A versão permanece 1.5.12.

## Codex CLI durante o Setup

O Codex CLI é necessário para usar este MCP no Codex local. O cliente MetaAdsClient poderá ser reutilizado pelo Analytics sem Codex. O Setup oferece a integração opcional: em Preserve, valida e reaproveita instalações compatíveis; em Clean, reinstala os componentes selecionados, recriando somente o ambiente virtual MCP. A opção interativa Clean vem afirmativa, e Preserve exige seleção; instalações não interativas só executam o extra com `-InstallMetaAdsMcp`.

O instalador detecta capacidades do Codex CLI antes de baixar software. Quando necessário, utiliza o instalador standalone oficial em `https://chatgpt.com/codex/install.ps1`, documentado no [README oficial do Codex](https://github.com/openai/codex/blob/main/README.md). Não exige Node.js para esse método. O processo preserva configurações e autenticação do Codex e os demais servidores MCP. Login e token Meta são configurados manualmente, na sessão do usuário final. Se o Setup estiver sob outra identidade administrativa, a integração fica pendente para execução pelo usuário correto.

Auxiliares para uma instalação local já existente:

```powershell
cd C:\NexoFlow
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\instalar_meta_ads_mcp.ps1 -InstalarCodex
# Reinstalar explicitamente a integração, preservando credenciais existentes do auxiliar:
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\instalar_meta_ads_mcp.ps1 -InstalarCodex -Reinstall
```

Uma falha opcional não desfaz o NexoFlow básico: o resultado é registrado em `logs/meta_ads_mcp_instalacao.json`, sem token. Configuração MCP divergente é preservada e exige conferência; não é sobrescrita automaticamente. Os novos auxiliares estão no código GitHub; o Setup 1.5.12 já publicado não foi substituído. A disponibilização em um novo pacote depende de autorização de release.
