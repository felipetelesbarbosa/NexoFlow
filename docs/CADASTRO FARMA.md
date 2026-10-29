# NexoFlow 1.5.3 — Cadastro por segmento

Weni, Analytics, Recompra e Planilha compartilham o cliente da API FarmaLíder. O perfil selecionado determina a listagem **`clientes/FARMA`** ou **`clientes/PET`**, sempre em produção, com a mesma seleção de conexão direta/proxy.

## Consultas e identidade

A listagem pode conter `cliente`, `ultimoPedido` e `itens`, ou somente cadastro. Snapshots completos são conferidos por proprietário, emissão, itens, valores e segmento, e reutilizados durante a execução. Dados incompletos ou ausência na lista usam consulta individual por CPF e, quando necessário, por ID do pedido. No retorno individual, o segmento precisa ser comprovado.

CPF válido dispensa comparação de nome e telefone. Zeros à esquerda só são repostos quando tornam os verificadores válidos. CPF inválido consultável exige primeiro nome ou telefone local correspondente ao contato Weni, sem ambiguidade. Ausência, zero e formato malformado ficam pendentes; não autorizam inventar CPF ou titularidade.

A base de uma marca não fornece identidade ou pedido à outra. Respostas divergentes de um mesmo ID e múltiplos candidatos compatíveis não são resolvidos pela primeira ocorrência.

## Preencher cadastros

Em contatos existentes, valores cadastrados são preservados e lacunas podem receber gênero, idade e localização com evidência na revisão. O endereço deve corresponder de forma única ao último pedido do mesmo cliente, inclusive quando for secundário. CEP isolado não comprova o endereço completo. Dados incompletos ou conflitantes ficam pendentes.

A rotina Weni também propõe criar clientes ausentes com CPF válido, identidade única e pedido validado no segmento. Confere CPF/telefone para evitar duplicação, preenche os campos disponíveis e revalida a fonte antes da criação. CPF inválido sem vínculo independente e conflitos ficam pendentes. A criação não presume consentimento nem adiciona grupos.

Farma usa `ultima_compra`; Pets usa `compra_recente` e não exige maioridade. O recorte de produtos humanos é exclusivo da Farma. Veja [segmentos, campos e fluxos](SEGMENTOS%20E%20FLUXOS.md).

## Histórico e desempenho

A resposta da listagem completa pode aguardar até **600 segundos** por tentativa; consultas individuais mantêm **90 segundos**. O índice é reutilizado na execução. A descoberta global de Weni/Analytics consulta a base do segmento mesmo em incrementais; o modo incremental continua útil para o processamento de mensagens e mudanças.

Pedidos completos observados são guardados privadamente e entregues pelo Analytics ao Sheets por ID. Mudanças de pedido mais recente não apagam os anteriores já observados. O histórico comercial fica nas planilhas; a Weni conserva o snapshot mais recente. Compras intermediárias nunca observadas dependem de um endpoint de pedidos por período, ainda não usado pelo NexoFlow.

O Analytics mantém a reconsulta de status dos pedidos já registrados somente até 20 dias. Leituras da simulação não dispensam a conferência exigida pela aplicação. Revise os relatórios e preserve o histórico local ao atualizar.
