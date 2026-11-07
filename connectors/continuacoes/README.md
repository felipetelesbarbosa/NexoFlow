# Conector de continuações do NexoFlow

Conector privado de leitura das tabelas BI para o Data Studio. Instale `Code.js`, `Tables.js`, `Schemas.js` e `appsscript.json` no Google Apps Script. Não recebe credenciais de APIs do NexoFlow.

A implantação e a substituição inicial das fontes são feitas pelo responsável pelo relatório; o Setup não executa essas etapas. Consulte [configuração, conferência e limites](../../docs/CONTINUACOES.md).

Testes sem Google real: `node --test tests/test_continuation_connector.cjs tests/test_looker_abc_connector.cjs`.

O registro controlado inclui `Historico_Pedidos`, `Historico_Itens`, `BI_LTV_Clientes`, `BI_Cobertura_Historica` e `BI_Historico_Resumo` na implementação da 1.5.21. O leitor resolve papéis e partes futuras pelo manifesto e bloqueia publicação parcial. Para visão anual use resumo ANO; clientes distintos exigem um único recorte ou competência explícita. Detalhe de itens requer período e usa IDs oficiais dos pedidos. Atualize a implantação privada no relatório de teste antes de autorizar as fontes no armazenamento. Consulte o [roteiro FARMA](../../docs/PUBLICADOR%20HISTORICO%20SQLITE%20SHEETS.md).

Regressão completa do leitor: `node --test tests/test_continuation_connector.cjs tests/test_looker_abc_connector.cjs tests/test_history_connector.cjs`.
