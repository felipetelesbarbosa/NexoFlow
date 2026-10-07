# Pedidos no NexoFlow 1.0

O **NexoFlow 1.0** usa a FarmaLíder API como fonte de verdade dos dados de pedido. A Weni recebe um snapshot operacional dos campos `pedido_*`; Google Sheets e Looker Studio recebem a estrutura analítica correspondente.

## Arquitetura de coleta

Fluxo principal:

```text
CPF do contato
-> GET /api/Delivery/cliente/cpf/{cpf}
-> valida cliente
-> lê ultimoPedido + itens
-> GET /api/Delivery/pedido/{pedido_id}
-> confirma o mesmo pedido
-> atualiza os campos Weni
-> atualiza Pedidos_FarmaLider / Itens_Pedidos_FarmaLider / BI_Pedidos
```

O retorno do endpoint por CPF já contém `ultimoPedido` e `itens`. Ele é suficiente para construir um snapshot do pedido e funciona como fallback se a segunda consulta falhar temporariamente.

O endpoint por código é preferido como snapshot final porque confirma o mesmo pedido e fornece os metadados operacionais atuais, incluindo `status` e `formaPagamento`.

Os campos atuais da Weni são usados apenas como localizadores de recuperação quando necessário. Se o GET por CPF não puder ser usado, o NexoFlow tenta primeiro `pedido_id`. Se esse campo não existir ou não puder ser validado, `ultimo_pedido` é consultado como **último localizador de ID**, inclusive para recuperar pedidos ocorridos enquanto o NexoFlow esteve fora do ar e outra integração continuou alimentando `ultimo_pedido`.

Mesmo nesse fallback, `ultimo_pedido` não vira fonte de produtos, quantidade, valores, status, data ou forma de pagamento. O ID localizado precisa ser validado por `GET /api/Delivery/pedido/{codigo}`. Se a FarmaLíder API estiver indisponível, o NexoFlow preserva os campos `pedido_*` existentes e não os reconstrói a partir do snapshot legado.

## Contrato dos campos Weni

| Campo | Fonte | Regra |
|---|---|---|
| `pedido_id` | `ultimoPedido.id` ou `capa.id` | identificador oficial do pedido |
| `pedido_produtos` | `itens[].descricao` | nomes em uma lista separada por vírgula |
| `pedido_quantidade_itens` | `itens[].quantidade` | quantidades posicionais separadas por vírgula |
| `pedido_valor_produtos` | `itens[].valor` | valores unitários posicionais separados por vírgula |
| `pedido_valor` | `sum(itens[].total)` | soma dos totais dos itens |
| `pedido_data` | `emissao` | `DD/MM/YY HH:MM:SS` |
| `pedido_status` | `status` | código oficial 0 a 4 |
| `pedido_forma_pagamento` | `formaPagamento` | código Int32 não negativo recebido; de-para documentado de 1 a 5 |

As listas são posicionais. Exemplo:

```text
pedido_produtos: Produto A, Produto B
pedido_quantidade_itens: 2, 1
pedido_valor_produtos: 10, 5.5
```

Isso significa:

```text
Produto A -> quantidade 2 -> valor unitário 10
Produto B -> quantidade 1 -> valor unitário 5.5
```

O NexoFlow mantém cada item também como linha individual em `Itens_Pedidos_FarmaLider`, evitando depender da interpretação da lista para cálculos analíticos.

## Produto

`itens[].descricao` é o nome oficial usado pelo NexoFlow.

`codProduto` não é usado como nome. O código pode continuar armazenado internamente em `produto_codigo` para auditoria e relacionamento técnico, mas o texto apresentado na Weni e no dashboard vem de `descricao`.

## Quantidade e valor

Cada item usa:

```text
descricao
quantidade
valor
total
```

`valor` representa o valor unitário.

`total` representa o total daquele item e é a fonte usada para compor `pedido_valor`.

Portanto:

```text
pedido_valor = soma de todos os itens[].total
```

O frete continua disponível separadamente nos dados técnicos da FarmaLíder e **não é somado ao campo Weni `pedido_valor`**.

No Google Sheets/BI, o NexoFlow mantém três valores distintos:

```text
valor_total_compra      = total dos produtos
farmalider_frete        = frete
valor_total_faturamento = produtos + frete
```

Em `BI_Pedidos`, isso é apresentado como `pedido_valor`, `pedido_frete` e `pedido_faturamento_total`. Em `BI_Vendas` e `BI_Resumo_Diario`, produtos e frete aparecem separados e o faturamento total usa a soma dos dois.

## Data

A emissão da API é interpretada no fuso de negócio **America/Belem**.

Exemplo de origem:

```text
2026-06-05T15:45:27.497
```

Campo Weni:

```text
05/06/26 15:45:27
```

Nas tabelas analíticas, o NexoFlow também mantém `data` e `hora` separadas para filtros, séries e agrupamentos do Looker Studio.

## Status

De-para oficial:

| Código | API | Apresentação |
|---:|---|---|
| -1 | `PendentePagamento` | Pendente pagamento |
| 0 | `EmProcessamento` | Em processamento |
| 1 | `EmTransito` | Em trânsito |
| 2 | `Concluido` | Concluído |
| 3 | `Cancelado` | Cancelado |

A Weni recebe o **código** em `pedido_status`. O Analytics deriva `pedido_status_nome` para apresentação no Google Sheets/Looker Studio.

Estados 0, 1, 2 e 4 confirmados pela API contam como pedido feito. O estado 3 fica fora das métricas de venda.

## Forma de pagamento

De-para oficial:

| Código | Apresentação |
|---:|---|
| 1 | Dinheiro |
| 2 | Débito |
| 3 | Crédito |
| 4 | Ticket |
| 5 | Pix por Link de Pagamento |
| 6 | PIX no POS |
| 0 | CANCELADO |

A Weni recebe o código em `pedido_forma_pagamento`. O Analytics deriva `pedido_forma_pagamento_nome`. Códigos Int32 não negativos sem de-para, como 0 e 6, são preservados e exibidos no Google Sheets/BI como `Não identificado (código X)`. Essa descrição não atribui uma forma de pagamento ao código. Pagamento ausente ou inválido mantém a descrição vazia.

No NexoFlow Weni, cada código sem de-para gera um registro `INFO` por execução, com totais por código no resumo. Isso não impede a atualização dos demais campos válidos.

## Exemplo real do contrato

Para um pedido com dois itens:

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

No dashboard, os códigos podem ser apresentados como:

```text
Status: Cancelado
Forma de pagamento: Débito
```

sem alterar os códigos armazenados na Weni.

## Google Sheets

### Pedidos_FarmaLider

Uma linha por pedido oficial. Mantém identificação, emissão, status, forma de pagamento, total dos itens, vínculo do cliente, origem e dados técnicos de confirmação.

### Itens_Pedidos_FarmaLider

Uma linha por item, com:

- pedido;
- descrição do produto;
- código técnico do produto, quando disponível;
- quantidade;
- valor unitário;
- valor total do item;
- data e hora.

### Metricas_Vendas

Agregação diária para pedidos válidos, compradores, unidades e faturamento.

### BI_Pedidos

Tabela pronta para o Looker Studio, uma linha por pedido, contendo:

- pedido_id;
- data e hora amigáveis;
- cliente e CPF;
- produtos;
- quantidades;
- valores unitários;
- valor dos produtos;
- frete;
- faturamento total do pedido, com produtos + frete;
- código e nome do status;
- código e nome da forma de pagamento;
- canal;
- primeiro e último anúncio;
- horário da atualização.

Use `BI_Pedidos` para páginas como **Compradores do dia**, **Pedidos do dia** e detalhamento de vendas.

## Atualização Weni

A escrita continua seguindo o fluxo seguro:

```text
GET FarmaLíder
-> plano de alterações
-> dry-run
-> auditoria
-> confirmação humana
-> POST dos campos Weni
```

Nenhum campo de pedido é gravado fora da allowlist.

A preparação e a auditoria do plano terminam antes das gravações. O resumo de contatos com pedido validado pela API também conta os que já estavam atualizados. Esse total não representa pedidos únicos nem contatos alterados; as alterações são contabilizadas separadamente.

Os oito campos do contrato de pedido são obrigatórios na Weni: `pedido_id`, `pedido_data`, `pedido_status`, `pedido_produtos`, `pedido_quantidade_itens`, `pedido_valor_produtos`, `pedido_valor` e `pedido_forma_pagamento`. Se qualquer um estiver ausente, o preflight bloqueia o NexoFlow Weni antes do apply, evitando snapshot parcial.

## Rechecagem

Pedidos em 0, 1 ou 4 continuam sendo rechecados nas execuções seguintes até chegar a:

- 2, Concluído; ou
- 3, Cancelado.

O status -1, Pendente pagamento, permanece em rechecagem e não entra como venda até haver pagamento e mudança de status.

A mudança de status atualiza o snapshot sem trocar o `pedido_id` por outro pedido arbitrariamente.

## Segurança

O NexoFlow valida:

- CPF;
- vínculo do cliente;
- ID do pedido;
- `codCliente`;
- `codPedido` de cada item;
- emissão;
- status conhecido;
- descrição de produto;
- quantidades e valores numéricos.

Respostas inconsistentes não alimentam métricas como venda confirmada.

Leia também [FarmaLíder API](FARMALIDER%20API.md), [NexoFlow Weni](../README%20WENI.md) e [Looker Studio](LOOKER%20STUDIO.md).

<!-- NexoFlow 1.0 -->
