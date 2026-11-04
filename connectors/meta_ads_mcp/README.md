# NexoFlow Meta Ads MCP local

Servidor local STDIO com seis ferramentas de consulta: `contas_permitidas`, `detalhes_conta`, `campanhas`, `conjuntos`, `anuncios` e `insights`. O GitHub contém o código, não hospeda esse processo. Não há ferramentas para editar campanhas, conjuntos, anúncios ou orçamentos.

Instalação Windows e regras de credenciais: [Meta Ads MCP local](../../docs/META%20ADS%20MCP%20LOCAL.md).

Evolução proposta, ainda sem gravações ou alteração de schema: [Plano para Analytics](../../docs/PLANO%20META%20ADS%20ANALYTICS.md).

O Analytics poderá reutilizar `MetaAdsClient` sem depender de MCP/Codex. Somente a existência desse cliente não habilita cargas no Google Sheets ou no Noturno. A credencial operacional permanece exclusivamente em `credentials/mcp/meta_ads_credentials.json`, fora do Git e dos pacotes públicos.
