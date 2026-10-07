# NexoFlow 1.0 — Pedidos na Weni

Os campos de pedido da Weni são o snapshot operacional do último pedido obtido pela FarmaLíder API. Eles não são mais a fonte prioritária da resolução quando a API está disponível.

## Fluxo

```text
CPF
-> GET cliente/cpf/{cpf}
-> ultimoPedido + itens
-> GET pedido/{pedido_id}
-> plano auditado
-> campos pedido_* na Weni
```

## Campos

| Campo | Conteúdo |
|---|---|
| `pedido_id` | ID oficial do pedido |
| `pedido_produtos` | `descricao` dos itens, separados por vírgula |
| `pedido_quantidade_itens` | quantidades posicionais, separadas por vírgula |
| `pedido_valor_produtos` | valores unitários posicionais, separados por vírgula |
| `pedido_valor` | soma de `itens[].total` |
| `pedido_data` | `DD/MM/YY HH:MM:SS` |
| `pedido_status` | código 0 a 4 |
| `pedido_forma_pagamento` | código Int32 não negativo recebido; de-para documentado de 1 a 5 |

Pagamentos válidos sem de-para, como 0 e 6, mantêm seu código na Weni e recebem a descrição `Não identificado (código X)` no Google Sheets/BI. Pagamento ausente ou inválido mantém a descrição vazia.

Exemplo:

```text
pedido_id: 340793
pedido_produtos: PROLOPA BD 100+25MG C/30CAP, TP PRAMIPEXOL PRATI 1MG C/30 CPR (G)
pedido_quantidade_itens: 1, 1
pedido_valor_produtos: 53.9, 58.9
pedido_valor: 112.8
pedido_data: 05/06/26 15:45:27
pedido_status: 3
pedido_forma_pagamento: 2
```

`ultimo_pedido` continua aceito apenas para compatibilidade/fallback offline. O NexoFlow Weni não depende dele para escolher o pedido quando a FarmaLíder API está disponível.

A escrita continua protegida por dry-run, auditoria, confirmação e verificação de conflito por contato.

Os logs de preparação e auditoria precedem as gravações. O total de contatos com pedido validado pela API inclui os que não precisam de alteração. Cada código de pagamento sem de-para aparece em `INFO` uma vez por execução, com totais por código no resumo, sem bloquear a atualização.

Veja [PEDIDOS.md](PEDIDOS.md) para regras completas.

<!-- NexoFlow 1.0 -->
