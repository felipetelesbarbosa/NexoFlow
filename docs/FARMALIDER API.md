# FarmaLíder API - contrato usado pelo projeto

Documentação atual do uso da API pelo **NexoFlow**.

## Autenticação

A integração atual usa token pela QueryString:

```text
?token=...
```

Não envia `Authorization: Bearer`.

## URLs

Com proxy corporativo:

```text
https://api.farmalider.net.br/farmalider
```

Sem proxy:

```text
https://api.farmalider.net.br:3200/farmalider
```

## Cliente por CPF

```text
GET /api/Delivery/cliente/cpf/{cpf}?token=...
```

O CPF normalizado é a ponte de identidade entre Weni e FarmaLíder. O `contact_uuid` continua sendo a chave principal do contato na Weni.

O retorno atual possui três blocos relevantes:

```text
cliente
ultimoPedido
itens
```

O NexoFlow valida `cliente.cpf` e `cliente.id`, usa `ultimoPedido.id` como o pedido oficial mais recente e já consegue montar um snapshot completo usando os `itens` retornados pelo mesmo GET.

Dados consumidos:

```text
ultimoPedido.id
ultimoPedido.emissao
ultimoPedido.status
ultimoPedido.formaPagamento
ultimoPedido.codCliente
ultimoPedido.frete

itens[].codPedido
itens[].codProduto
itens[].descricao
itens[].quantidade
itens[].valor
itens[].total
```

`itens[].descricao` é o nome do produto. `codProduto` permanece somente como código técnico e não é usado como descrição/nome.

## Pedido por código

```text
GET /api/Delivery/pedido/{codigo}?token=...
```

Depois de obter `ultimoPedido.id` pela consulta de CPF, o NexoFlow consulta o mesmo pedido por código. Este endpoint é o snapshot final preferencial.

O retorno é normalizado no mesmo formato do endpoint por CPF:

```text
capa -> dados do pedido
itens -> produtos do pedido
```

Se o GET por pedido falhar temporariamente e o GET por CPF trouxe `ultimoPedido + itens` válidos, o NexoFlow pode usar esse primeiro retorno como fallback completo.

## Mapeamento para Weni

| Campo Weni | Campo API |
|---|---|
| `pedido_id` | `capa.id` / `ultimoPedido.id` |
| `pedido_produtos` | `itens[].descricao` |
| `pedido_quantidade_itens` | `itens[].quantidade` |
| `pedido_valor_produtos` | `itens[].valor` |
| `pedido_valor` | soma de `itens[].total` |
| `pedido_data` | `emissao` |
| `pedido_status` | `status` |
| `pedido_forma_pagamento` | `formaPagamento` |

Produtos, quantidades e valores unitários são serializados como listas separadas por vírgula, preservando a mesma ordem posicional.

`pedido_valor` representa a soma dos totais dos itens. O frete continua separado nos dados técnicos e não é somado ao campo Weni.

## Status do pedido

De-para da documentação oficial da integração:

| Código | Identificador oficial | Rótulo |
|---:|---|---|
| 0 | `EmProcessamento` | Em processamento |
| 1 | `EmTransito` | Em trânsito |
| 2 | `Concluido` | Concluído |
| 3 | `Cancelado` | Cancelado |
| 4 | `ProntoParaRota` | Pronto para rota |

A Weni armazena o código em `pedido_status`. O Analytics deriva o nome amigável.

Para indicadores, 0, 1, 2 e 4 contam como pedido feito quando a resposta foi validada. O código 3 não entra nas métricas de venda.

## Forma de pagamento

De-para da documentação oficial da integração:

| Código | Forma |
|---:|---|
| 1 | Dinheiro |
| 2 | Débito |
| 3 | Crédito |
| 4 | Ticket |
| 5 | Online/link/Pix |

A Weni armazena o código em `pedido_forma_pagamento`. O Analytics mantém também `farmalider_forma_pagamento_nome` e disponibiliza a descrição amigável na camada BI.

## Data

Timestamps sem offset retornados pela API são interpretados em **America/Belem**.

Exemplo:

```text
API:  2026-06-05T15:45:27.497
Weni: 05/06/26 15:45:27
```

Internamente, o NexoFlow preserva data/hora canônica para agregações e filtros.

## Limitação de histórico

O endpoint por CPF retorna o **último pedido** disponível e seus itens. Isso não equivale a uma listagem histórica paginada de todos os pedidos do cliente.

Consequência:

```text
CPF -> último pedido atual
pedido_id -> confirmação/enriquecimento do mesmo pedido
```

O NexoFlow não inventa pedidos anteriores que não estejam disponíveis nas fontes consultadas.


## Concorrência e proteção

A integração usa concorrência controlada:

- até 4 workers;
- lotes de até 500 CPFs;
- paralelismo somente a partir do limiar configurado;
- delay global mínimo de 10 ms entre inícios;
- sessão HTTP por thread;
- retry;
- cooldown e throttle após 429;
- circuit breaker;
- telemetria de latência;
- aviso de requisição lenta acima do limite configurado.

Os valores operacionais ficam em `config.py`.

## Melhoria futura: histórico de pedidos por CPF

A API usada permite localizar cliente por CPF, obter sua referência de último pedido quando disponível e consultar pedido por código, mas não lista o histórico de pedidos de um cliente. Como evolução recomendada da FarmaLíder API, criar uma rota de consulta por CPF, preferencialmente paginada e com filtros de período/status, por exemplo:

```text
GET /api/Delivery/pedidos/cpf/{cpf}
```

Filtros desejáveis: `inicio`, `fim`, `status`, `pagina` e `tamanhoPagina`. Essa rota é uma proposta de evolução, não uma integração atualmente implementada.
<!-- NexoFlow 1.0 -->
