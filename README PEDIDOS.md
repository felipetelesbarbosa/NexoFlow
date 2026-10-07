# NexoFlow 1.0 — Pedidos

A FarmaLíder API é a fonte de verdade dos pedidos do NexoFlow 1.0.

Fluxo atual:

```text
CPF -> GET cliente/cpf/{cpf} -> ultimoPedido + itens
    -> GET pedido/{pedido_id}
    -> campos pedido_* na Weni
    -> Google Sheets / BI_Pedidos / Looker Studio
```

O nome do produto vem de `itens[].descricao`. `codProduto` é apenas código técnico.

Campos Weni:

```text
pedido_id
pedido_data
pedido_status
pedido_forma_pagamento
pedido_produtos
pedido_quantidade_itens
pedido_valor_produtos
pedido_valor
```

Produtos, quantidades e valores unitários são separados por vírgula e mantêm a mesma ordem posicional. `pedido_valor` é a soma de `itens[].total`. A data é gravada como `DD/MM/YY HH:MM:SS`.

A documentação completa está em [Pedidos no NexoFlow 1.0](docs/PEDIDOS.md) e [FarmaLíder API](docs/FARMALIDER%20API.md).

<!-- NexoFlow 1.0 -->
