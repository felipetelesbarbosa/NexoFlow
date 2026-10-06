# Pedidos da Weni — NexoFlow 1.0

Os dados podem vir do JSON `ultimo_pedido` ou de `pedido_id`, `pedido_data`, `pedido_produtos`, `pedido_quantidade_itens` e `pedido_valor`. A rotina Weni mantém os campos autorizados, e o Analytics preserva os campos separados na `Base_Contatos` e deriva o JSON quando necessário.

O contrato completo, incluindo confirmação pela FarmaLíder, produtos e cancelamentos, está em [Pedidos no NexoFlow 1.0](PEDIDOS.md).

O campo `ultimo_pedido` pode chegar como objeto, texto JSON ou wrapper da Weni. O parser reconhece os identificadores `pedido_id`, `pedidoId`, `codigo` e `codPedido` quando disponíveis. Com identificador oficial, a chave do pedido é `FARMALIDER:<pedido_id>`; sem ele, a rotina mantém uma chave sintética estável para o registro recebido.

Produtos devem continuar estruturados em JSON, preservando códigos, quantidades e valores. Erros de parse são registrados, e informação ausente não é completada por suposição.
