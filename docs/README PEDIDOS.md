# NexoFlow 1.5.8 — Pedidos

As regras compartilhadas de pedidos atendem **FarmaLíder e Pets Líder**, com organizações e planilhas separadas. Farma usa `ultima_compra`; Pets usa `compra_recente`. A referência dos eventos é `pedido_data`: D+25 na Farma e D+30 no Pets. Veja [segmentos e fluxos](SEGMENTOS%20E%20FLUXOS.md).

A FarmaLíder API é a fonte de verdade dos pedidos do NexoFlow 1.5.8.

Fluxo atual:

```text
CPF -> GET cliente/cpf/{cpf} -> ultimoPedido + itens
    -> GET pedido/{pedido_id}
    -> campos pedido_* na Weni
    -> Google Sheets / BI_Pedidos / Data Studio
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

O status efetivo usa o enum atual: -2 Em aberto, -1 Pendente de pagamento, 0 Em processamento, 4 Pronto para rota, 1 Em trânsito, 2 Concluído e 3 Cancelado. Pedidos validados pela API com status efetivo -2, -1, 0, 4, 1 ou 2, sem cancelamento, contam como venda e atualizam `ultima_compra` (Farma) ou `compra_recente` (Pets). Os estados -2, -1, 0, 1 e 4 permanecem em rechecagem até Concluído ou Cancelado.

| Código de pagamento | Descrição |
|---:|---|
| 0 | Cancelado |
| 1 | Dinheiro |
| 2 | Débito |
| 3 | Crédito |
| 4 | Ticket |
| 5 | Pix por Link de Pagamento |
| 6 | Pix no POS |

Pagamento 0 ou `_` grava o texto literal `Cancelado` em `pedido_forma_pagamento` e força o status efetivo 3 na Weni/BI. `Pedidos_FarmaLider` preserva status e pagamento brutos da API. Os normalizadores aceitam códigos e nomes oficiais dos enums; códigos de pagamento Int32 válidos sem de-para a partir de 7 aparecem como `Não identificado (código X)`.

Depois de atualizar ou reinstalar, gere um novo dry-run completo com `comandos/atualizar_weni_carga_completa.bat`, revise o relatório e confirme o apply para revalidar os snapshots com essa política. Em seguida, execute `comandos/executar_carga_completa.bat` para recalcular o Analytics/BI. Não reutilize um snapshot de revisão gerado pela política anterior.

A documentação completa está em [Pedidos no NexoFlow 1.5.8](PEDIDOS.md) e [FarmaLíder API](FARMALIDER%20API.md).

<!-- NexoFlow 1.5.8 -->
