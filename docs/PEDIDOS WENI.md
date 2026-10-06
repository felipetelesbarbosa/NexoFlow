# Pedidos da Weni — NexoFlow 1.0

O JSON `ultimo_pedido` é a fonte prioritária. Quando estiver preenchido e válido, ele fornece diretamente o identificador, data/hora, nomes dos produtos, quantidades, valores unitários e valor total; o NexoFlow usa essas informações para preencher `pedido_id`, `pedido_data`, `pedido_produtos`, `pedido_quantidade_itens` e `pedido_valor`. Depois de consultar o mesmo pedido pela API, também preenche `pedido_status` com o rótulo oficial do estado atual. A rotina Weni mantém esses campos autorizados, e o Analytics os preserva na `Base_Contatos`.

O contrato completo, incluindo confirmação pela FarmaLíder, produtos e cancelamentos, está em [Pedidos no NexoFlow 1.0](PEDIDOS.md).

O campo `ultimo_pedido` pode chegar como objeto, texto JSON ou wrapper da Weni. O parser reconhece os identificadores `pedido_id`, `pedidoId`, `codigo` e `codPedido` quando disponíveis. Quando há ID válido, os dados desse JSON permanecem prioritários e a FarmaLíder API é consultada somente em `/pedido/{codigo}` para confirmar o status do mesmo pedido. A busca `cliente/cpf/{cpf} → ultimoPedido.id` só ocorre quando `ultimo_pedido` estiver ausente, vazio ou `null`. Com identificador oficial, a chave do pedido é `FARMALIDER:<pedido_id>`; sem ele, a rotina mantém uma chave sintética estável para o registro recebido.

Produtos permanecem estruturados em JSON, preservando nomes, códigos quando existirem, quantidades e valores. Estados 0, 1, 2 e 4 confirmados pela API contam como pedido feito; status 3 é cancelado e fica fora dos indicadores e de `ultima_compra`. Erros de parse são registrados, e informação ausente não é completada por suposição.
<!-- NexoFlow 1.0 -->
