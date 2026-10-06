# Pedidos — NexoFlow 1.0

O NexoFlow usa primeiro `ultimo_pedido`. Quando ele está preenchido e possui ID válido, os dados do pedido vêm da Weni e a API consulta somente esse mesmo ID para confirmar o status. O fallback `CPF → ultimoPedido → pedido` só ocorre quando `ultimo_pedido` estiver ausente, vazio ou `null`. Todos os estados permanecem registrados; somente status 2 confirmado pela API entra em vendas e pode atualizar `ultima_compra`.

A documentação principal está em [Pedidos no NexoFlow 1.0](docs/PEDIDOS.md). Ela descreve as entradas, a confirmação de titular e identificador, produtos em JSON, valores e frete, datas em America/Belem e os limites do histórico disponível.

Consulte também o [contrato da API FarmaLíder](docs/FARMALIDER%20API.md).
