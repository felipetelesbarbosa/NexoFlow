# Pedidos — NexoFlow 1.0

O NexoFlow usa primeiro `ultimo_pedido`. Quando ele está preenchido e possui ID válido, o JSON da Weni fornece ID, data, produtos, quantidades, valores unitários e total, e dele são alimentados os dados principais do pedido. A API consulta somente esse mesmo ID para confirmar o status e completa `pedido_status`, totalizando seis campos `pedido_*`. O fallback `CPF → ultimoPedido → pedido` só ocorre quando `ultimo_pedido` estiver ausente, vazio ou `null`. Estados 0, 1, 2 e 4 confirmados pela API contam como pedido feito e podem atualizar `ultima_compra`; somente status 3 — Cancelado fica fora.

A documentação principal está em [Pedidos no NexoFlow 1.0](docs/PEDIDOS.md). Ela descreve as entradas, a confirmação de titular e identificador, produtos em JSON, valores e frete, datas em America/Belem e os limites do histórico disponível.

Consulte também o [contrato da API FarmaLíder](docs/FARMALIDER%20API.md).
