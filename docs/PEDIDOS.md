# Pedidos no NexoFlow 1.0

O NexoFlow Weni e o Analytics compartilham a resolução de pedidos. O Weni mantém os campos autorizados do contato; o Analytics preserva os dados na planilha e alimenta `Pedidos_FarmaLider`, `Itens_Pedidos_FarmaLider`, `Metricas_Vendas` e a camada BI.

## Duas formas de entrada

O pedido pode chegar em `ultimo_pedido`, como objeto ou texto JSON, ou nos campos separados da Weni:

| Campo | Significado |
|---|---|
| `pedido_id` | Identificador do pedido, preservado como texto. |
| `pedido_data` | Data e hora do pedido. |
| `pedido_produtos` | JSON estruturado com produtos e os metadados disponíveis do pedido. |
| `pedido_quantidade_itens` | Quantidade total de unidades informada pelo pedido. |
| `pedido_valor` | Valor total do pedido. |

O Analytics mantém esses campos na `Base_Contatos` e pode derivar `ultimo_pedido` a partir deles. A derivação não cria um pedido histórico nem modifica o campo original na Weni.

Um `ultimo_pedido` válido tem preferência sobre campos separados sem confirmação. Um envelope confirmado pela API, ou identificado como cancelado pela API, pode substituir o snapshot usado na análise quando tem data igual ou mais recente. O JSON original continua preservado em `Pedidos_FarmaLider.ultimo_pedido_raw`; isso evita que um JSON antigo prevaleça sobre um cancelamento mais recente.

O JSON produzido para `pedido_produtos` é um envelope com a lista `produtos`, identificação e data do pedido, valores, quantidades, origem, estados de validação/confirmação, `farmalider_frete`, `farmalider_status_pedido` e `farmalider_cancelamento`. Ele não é uma descrição de produtos em texto livre. Os códigos recebidos são preservados; um nome ausente permanece ausente. O código do produto não deve ser apresentado como se fosse seu nome.

## Resolução e confirmação

O caminho inicial é ler o pedido disponível em `ultimo_pedido` ou derivá-lo dos campos `pedido_*`. Quando há identificador oficial, o pedido específico pode ser confirmado e enriquecido pela FarmaLíder.

Quando esse caminho não fornece um pedido utilizável com identificador oficial, e há CPF válido e acesso à API, o fallback é:

```text
CPF → GET cliente/cpf/{cpf} → resposta.ultimoPedido.id → GET pedido/{codigo}
```

Na resposta oficial, `cliente` identifica o titular e `ultimoPedido` é outro objeto da resposta. O retorno legado com os campos do cliente diretamente no objeto também é aceito para validar o vínculo.

O NexoFlow valida o CPF retornado, a identidade do cliente, o identificador solicitado e o titular do pedido. Um retorno divergente não confirma uma compra para o contato. Informação somente da Weni conserva sua origem e não recebe confirmação oficial por suposição.

`ultimoPedido` é uma referência ao último pedido disponível do cliente, não uma lista de todo o histórico. Um pedido antigo que nunca foi capturado não é reconstruído apenas pela leitura atual do contato.

Quando vários contatos retornam o mesmo pedido oficial, o Analytics mantém um único snapshot por identificador. A atribuição de anúncio desse pedido fica ausente quando a associação com um contato é ambígua. A lista de itens é reconciliada nas próximas cargas: posições removidas pela API deixam de compor os indicadores.

## Valores, frete e produtos

O registro distingue o total do pedido, a soma dos itens e o frete. `valor_origem` registra a origem do valor:

- `TOTAL_GERAL_API`: total explícito válido da API, que tem prioridade.
- `SOMA_ITENS_MAIS_FRETE_API`: soma dos itens com frete explícito válido.
- `SOMA_ITENS_API`: soma dos itens, sem frete disponível; valor parcial.
- `WENI`: valor recebido da Weni, sem transformar sua origem em confirmação oficial.

Quando só há a soma dos itens, sem total geral ou frete explícito, o estado é `ATENCAO_TOTAL_PARCIAL`. O pedido continua registrado para auditoria, mas não atualiza os cinco campos `pedido_*` na Weni nem alimenta as métricas de vendas.

Uma divergência entre o valor da Weni e o total resolvido pela API fica registrada em `valor_total_weni` e `diferenca_total_weni_api`, com `ATENÇÃO_TOTAL_DIVERGENTE`. O total da API prevalece; não se escolhe o maior valor entre as fontes.

Não se deve somar o frete novamente a um total que já o inclui, nem apresentar a soma dos itens como total oficial sem identificar essa derivação. O JSON preserva os metadados de origem do valor.

Nas tabelas de itens, cada linha representa um item do pedido. `produto_codigo` e `produto_nome` são campos distintos; o nome pode ficar vazio. O total do pedido não deve ser repetido nas somas dos itens. `quantidade_produtos` e quantidade de unidades não são o mesmo indicador.

Os nomes da Weni só complementam itens da API quando há associação inequívoca por código ou por quantidade e valores compatíveis. Falta de nome, total ou valor unitário não autoriza inventar informação.

## Cancelamentos e métricas

O cancelamento permanece registrado junto do pedido e acompanha sua representação estruturada. Registrar um pedido cancelado não significa confirmar uma venda.

- Pedidos cancelados não compõem faturamento, unidades vendidas, compradores ou métricas de pedidos válidos.
- `ultima_compra` somente avança para uma compra não cancelada confirmada pela API FarmaLíder.
- Dados válidos não são apagados apenas porque uma fonte deixou de informar um campo.
- Divergências de identificador ou titular são registradas para diagnóstico e não devem alimentar indicadores como pedidos confirmados.

Para períodos com vários dias, faturamento, pedidos válidos e unidades podem ser somados. Compradores únicos do período exigem deduplicação: somar compradores únicos diários pode contar a mesma pessoa novamente. O ticket médio do período é faturamento dividido por pedidos compatíveis, quando o denominador for positivo.

## Datas e períodos

O fuso de negócio é **America/Belem**, com **UTC−3 / GMT−3**. Timestamps com offset são convertidos para esse fuso antes de determinar a data do pedido. Datas e horas sem offset provenientes da operação local são interpretadas nesse fuso.

Por exemplo, `2026-10-06T03:00:00Z` corresponde a `2026-10-06T00:00:00-03:00`. Horário de captura/sincronização não deve substituir a emissão do pedido.

Essa regra não cria retroativamente dias ou pedidos ausentes na planilha. Relatórios devem indicar a cobertura disponível e diferenciar hoje, ainda parcial, de períodos completos.

## Operação

Execute o NexoFlow Weni antes do Analytics. As gravações da Weni continuam passando por dry-run, auditoria, revisão e aplicação do snapshot. O Analytics lê os campos disponíveis e mantém as estruturas analíticas; não substitui essa revisão.

Confira os estados de validação e confirmação antes de interpretar uma linha como venda. Testes locais não comprovam acesso a uma API real nem o carregamento de todo o histórico. Credenciais não fazem parte dos exemplos, da documentação ou dos arquivos versionados.

Leia também o [contrato da API FarmaLíder](FARMALIDER%20API.md) e o [procedimento do NexoFlow Weni](../README%20WENI.md).
