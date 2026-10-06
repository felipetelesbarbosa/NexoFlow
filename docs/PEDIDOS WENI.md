# Pedidos da Weni - formato atual

A operação atual usa o campo `ultimo_pedido` do contato Weni.

## Exemplo

```json
{
  "data_hora": "2026-09-30T16:07:00Z",
  "valor_total_compra": 110.80,
  "produtos": [
    {
      "nome": "Dipirona Gotas 20ml",
      "quantidade": 2,
      "valor_unitario": 8.50,
      "valor_total": 17.00
    }
  ]
}
```

O campo pode chegar como objeto ou como texto JSON dentro da estrutura retornada
pela Weni.

## Identificador oficial

Se disponível, o parser reconhece:

- `pedido_id`
- `pedidoId`
- `codigo`
- `codPedido`

Com identificador, o sincronizador consulta a FarmaLíder para confirmar e
enriquecer o pedido.

Sem identificador, o pedido continua podendo ser persistido com os dados da
Weni, mas não recebe confirmação oficial da API FarmaLíder.

## Validação

O projeto não deve inventar informação ausente. Erros de parse ficam registrados
para diagnóstico e não devem ser silenciosamente corrigidos com suposições.

## Abas

- `Pedidos_FarmaLider`
- `Itens_Pedidos_FarmaLider`
- `Metricas_Vendas`

Leia `README PEDIDOS.md` para a visão completa.
