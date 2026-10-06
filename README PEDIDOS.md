# Pedidos — NexoFlow 1.0

O NexoFlow aceita pedidos em `ultimo_pedido` ou nos campos separados `pedido_*`. Quando esses dados não fornecem um pedido utilizável com identificador oficial, a rotina pode consultar o último pedido disponível pelo CPF confirmado. Cancelamentos são preservados sem tratá-los como vendas.

A documentação principal está em [Pedidos no NexoFlow 1.0](docs/PEDIDOS.md). Ela descreve as entradas, a confirmação de titular e identificador, produtos em JSON, valores e frete, datas em America/Belem e os limites do histórico disponível.

Consulte também o [contrato da API FarmaLíder](docs/FARMALIDER%20API.md).
