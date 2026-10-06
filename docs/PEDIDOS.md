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

O campo `ultimo_pedido` preenchido é a fonte prioritária. Os campos separados não podem substituí-lo por outro pedido nem ocultar conteúdo inválido. Um snapshot previamente confirmado ou cancelado pela API pode ser preservado, incluindo valores, itens e estado, somente quando pertence ao mesmo ID oficial positivo, passa pelas validações do snapshot e tem data igual ou mais recente. O JSON original continua preservado em `Pedidos_FarmaLider.ultimo_pedido_raw`; isso evita que um JSON antigo apague um cancelamento já registrado do mesmo pedido.

O JSON produzido para `pedido_produtos` é um envelope com a lista `produtos`, identificação e data do pedido, valores, quantidades, origem, estados de validação/confirmação, `farmalider_frete`, `farmalider_status_pedido` e `farmalider_cancelamento`. Ele não é uma descrição de produtos em texto livre. Os códigos recebidos são preservados; um nome ausente permanece ausente. O código do produto não deve ser apresentado como se fosse seu nome.

## Resolução e confirmação

**Caminho 1:** leia primeiro `ultimo_pedido` na Weni. Quando preenchido, use seus dados e não consulte a API para resolver esse pedido. Com ID, data, produtos, quantidades e valores válidos, o NexoFlow Weni alimenta os cinco campos `pedido_id`, `pedido_data`, `pedido_produtos`, `pedido_quantidade_itens` e `pedido_valor`, inclusive quando a API está configurada. Uma confirmação oficial já registrada no snapshot válido do mesmo pedido pode ser preservada; o conteúdo bruto não recebe confirmação API por suposição.

Conteúdo preenchido inválido ou incompleto não autoriza buscar outro pedido pelo CPF. Registre a pendência e preserve os campos existentes, sem inventar identificação, data, frete ou status. O parser espera objeto JSON ou texto contendo JSON estruturado; uma descrição livre de produtos sem os dados obrigatórios permanece pendente.

**Caminho 2:** somente quando `ultimo_pedido` estiver ausente, vazio ou `null`, e houver CPF válido e acesso à API, consulte:

```text
CPF → GET cliente/cpf/{cpf} → resposta.ultimoPedido.id → GET pedido/{codigo}
```

São aceitos valor nulo, espaços e texto `null`, inclusive no formato encapsulado `{"value": ...}` da Weni. Um objeto ou lista inválidos continuam sendo conteúdo preenchido, não ausência de informação. Campos `pedido_*` antigos não determinam o pedido desse caminho: a referência vem de `ultimoPedido.id`. Um snapshot válido do mesmo ID pode manter a comparação de valores; snapshots de outro ID são descartados da resolução atual. A API fornece os dados para alimentar os mesmos cinco campos da Weni antes da carga do Analytics.

Na resposta oficial, `cliente` identifica o titular e `ultimoPedido` é outro objeto da resposta. O retorno legado com os campos do cliente diretamente no objeto também é aceito para validar o vínculo.

No caminho 2, o NexoFlow valida o CPF retornado, a identidade do cliente, o identificador solicitado e o titular do pedido. Um retorno divergente não confirma uma compra para o contato. O enriquecimento de cadastro do Analytics também pode consultar CPF independentemente; essa consulta não autoriza substituir um pedido preenchido na Weni pela referência `ultimoPedido`.

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

No novo retorno da API, confirmado pelo responsável pelo projeto, `itens[].codProduto` contém o nome do produto em texto. Esse valor alimenta `produto_nome` e `pedido_produtos.produtos[].nome`; `produto_codigo` fica vazio quando não foi fornecido. Para compatibilidade com o retorno anterior, inteiros e strings formadas somente por dígitos em `codProduto` continuam sendo códigos. Os campos explícitos `nome` e `descricao` também são aceitos como texto e têm prioridade quando preenchidos. O nome atual informado pela API prevalece sobre descrições antigas da Weni. Produtos com o mesmo nome continuam em linhas distintas conforme os itens do pedido.

Os nomes da Weni só complementam itens da API quando há associação inequívoca por código ou por quantidade e valores compatíveis. Falta de nome, total ou valor unitário não autoriza inventar informação.

## Cancelamentos e métricas

O cancelamento permanece registrado junto do pedido e acompanha sua representação estruturada. Registrar um pedido cancelado não significa confirmar uma venda.

### Status oficial do pedido

De-para da documentação fornecida pelo usuário, **Integração API Líder.pdf**, seção **Status do Pedido**:

| Código | Identificador da API | Rótulo em português |
|---|---|---|
| 0 | `EmProcessamento` | Em processamento |
| 1 | `EmTransito` | Em trânsito |
| 2 | `Concluido` | Concluído |
| 3 | `Cancelado` | Cancelado |
| 4 | `ProntoParaRota` | Pronto para rota |

`farmalider_status_pedido` preserva o código original e `farmalider_status_pedido_nome` apresenta o rótulo oficial quando conhecido. Se o código estiver ausente ou for desconhecido, o nome fica vazio. O dashboard pode mostrar “Status não conhecido” como aviso derivado dessa ausência, sem gravá-lo como um estado oficial. O código **3** identifica um pedido cancelado mesmo que a data de cancelamento esteja ausente. Códigos desconhecidos não permitem inferir cancelamento ou conclusão.

### Critério dos indicadores de vendas

Faturamento, pedidos, unidades vendidas e compradores incluem somente os pedidos identificados pelo NexoFlow em **Concluído (código 2)**, não cancelados e com os demais critérios de validação satisfeitos. A regra se aplica também às métricas de vendas usadas em Resumo, Conversão e Ads.

| Estado do pedido | Captura e auditoria | Indicadores de vendas |
|---|---|---|
| 0, 1 ou 4 | Preservados; podem atualizar os cinco campos `pedido_*` quando os dados são válidos. | Fora dos indicadores enquanto não concluídos. |
| 2 | Preservado. | Elegível quando validado e não cancelado. |
| 3 | Cancelamento preservado. | Fora dos indicadores. |
| Ausente ou desconhecido | Informação disponível preservada, sem inferir conclusão. | Fora dos indicadores. |

**Concluído é um estado operacional/logístico:** por si só, não comprova pagamento ou liquidação financeira. Os indicadores cobrem os pedidos identificados pelo NexoFlow; não representam automaticamente todas as vendas da FarmaLíder nem comprovam uma venda originada por um anúncio.

- Pedidos cancelados não compõem faturamento, unidades vendidas, compradores ou métricas de pedidos válidos.
- `ultima_compra` somente avança para um pedido concluído, não cancelado e confirmado pela API FarmaLíder.
- Um cancelamento explícito mantém o pedido fora das métricas mesmo que outro campo indique código 2.
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
