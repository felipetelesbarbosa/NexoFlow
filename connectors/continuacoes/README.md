# Conector de continuações do NexoFlow

Conector privado de leitura das tabelas BI para o Data Studio. Instale `Code.js`, `Tables.js`, `Schemas.js` e `appsscript.json` no Google Apps Script. Não recebe credenciais de APIs do NexoFlow.

A implantação e a substituição inicial das fontes são feitas pelo responsável pelo relatório; o Setup não executa essas etapas. Consulte [configuração, conferência e limites](../../docs/CONTINUACOES.md).

Testes sem Google real: `node --test tests/test_continuation_connector.cjs tests/test_looker_abc_connector.cjs`.
