# Pedidos - NexoFlow

Documentação atual de pedidos do **NexoFlow**.

## Fonte atual

O projeto lê o campo de contato Weni:

```text
ultimo_pedido
```

Os antigos campos separados `pedido_data`, `pedido_produtos`, `pedido_valor` e
`pedido_quantidade_itens` pertencem às versões iniciais do projeto e não são a
estrutura atual do parser.

## Exemplo de `ultimo_pedido`

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

O parser também aceita `ultimo_pedido` quando a Weni entrega um wrapper contendo
o JSON como texto.

## Identificador oficial do pedido

Quando existir, o projeto reconhece estas chaves:

```text
pedido_id
pedidoId
codigo
codPedido
```

Com identificador oficial, a chave canônica pode ser construída como:

```text
FARMALIDER:<pedido_id>
```

Sem identificador, o projeto gera uma chave sintética estável a partir dos dados
disponíveis para evitar duplicação indevida.

## Confirmação pela FarmaLíder

Se houver `pedido_id`, o projeto consulta:

```text
GET /api/Delivery/pedido/{codigo}?token=...
```

Quando a API confirma o pedido, os dados oficiais podem enriquecer a linha,
incluindo:

- `farmalider_public_id`;
- emissão;
- status;
- filial;
- cliente interno;
- forma de pagamento;
- cupom;
- frete;
- cancelamento;
- entrega;
- valor calculado pelos itens da API;
- quantidade de itens da API;
- data/hora da confirmação.

A origem do pedido passa a indicar Weni + FarmaLíder quando o enriquecimento é
bem-sucedido.

## Sem `pedido_id`

A API atual usada pelo projeto não possui uma rota para localizar todos os
pedidos do cliente apenas pelo CPF.

Por isso, sem `pedido_id`:

- o pedido pode ser salvo com os dados do `ultimo_pedido`;
- o CPF continua útil para validar/vincular o cliente;
- o pedido não é considerado confirmado pela API apenas por causa do CPF.

## Abas

### `Pedidos_FarmaLider`

Uma linha por `pedido_chave`.

Inclui identificação do contato, CPF, snapshots de anúncio, valores do pedido,
status de validação e campos de confirmação da FarmaLíder.

### `Itens_Pedidos_FarmaLider`

Uma linha por item do pedido, com:

- pedido;
- contato;
- produto;
- quantidade;
- valor unitário;
- valor total;
- data/hora.

### `Metricas_Vendas`

Agregação diária com:

- pedidos;
- pedidos confirmados pela API;
- clientes compradores;
- unidades vendidas;
- faturamento;
- faturamento confirmado pela API.

No incremental, se nenhum pedido/item mudou, o projeto não recalcula
`Metricas_Vendas` desnecessariamente.

## Relação com anúncios

A linha do pedido recebe snapshots dos campos de primeiro e último anúncio do
contato quando esses dados estão disponíveis.

Esses campos permitem analisar compras de clientes impactados por anúncios, mas
não devem ser apresentados automaticamente como causalidade de venda gerada pelo
anúncio.

## Limitação histórica

`ultimo_pedido` representa o estado que está salvo no contato no momento da
leitura. Se um pedido antigo for substituído na Weni antes de o sincronizador
capturá-lo, esse pedido não pode ser reconstruído apenas pela leitura atual dos
campos.

Existe uma estrutura de webhook preparada para evolução futura, mas ela não é
necessária para a operação normal.

Leia também `docs/PEDIDOS WENI.md` e `docs/FARMALIDER API.md`.
