# F. Inventário Data Studio → NexoFlow Métricas
Inspeção autenticada em 07/11/2026. Os relatórios atuais foram consultados e preservados. Nenhuma fórmula, fonte, logo ou layout foi editado.

## Cobertura e grau da prova
As dez páginas FARMA e as nove páginas PET foram percorridas. O inventário visual cobre cards, títulos, colunas, controles e paginação expostos na interface. Propriedades e fórmulas foram abertas em componentes selecionados; isso não equivale a auditoria completa de todos os bindings/joins.

**Nenhuma página é declarada integralmente homologada em todos os critérios de paridade.** A coluna de validação da matriz distingue visual observado, configuração inspecionada, fórmula aberta e regra ainda pendente. Gráficos Vega em iframes foram identificados visualmente, mas o código interno e todos os valores não foram extraídos. Os rankings continham dados pessoais, que não foram copiados para os artefatos.

A fonte é o nome mostrado na UI, não garantia de lineage até a planilha. Campos financeiros oficiais e cobertura devem ser confrontados na Etapa 4. O processamento privado Windows não foi consultado.

| Página | FARMA atual | PET atual | Destino planejado |
| --- | --- | --- | --- |
| Resumo | Percorrida | Percorrida | Igual estrutura, por marca |
| Vendas | Percorrida | Percorrida | Igual estrutura |
| Meus clientes | Percorrida | Percorrida | Igual estrutura + recorrência/LTV |
| Pedidos por cliente | Percorrida | Percorrida | Mesmo detalhe autorizado |
| Produtos mais vendidos | Percorrida | Percorrida | Mesmos rankings + participação Top 5 |
| Curva ABC | Percorrida | Percorrida | Mesmo cálculo validado por período |
| Anúncios | Cards/tabela de associação parcial | Placeholder e receita média por cliente | Reestruturar ambas com fontes e KPIs comprovados |
| Pedidos dos anúncios | Percorrida | Ausente na navegação atual | Criar equivalência PET, por orientação do responsável |
| Base de clientes | Percorrida | Percorrida | Mesma estrutura, sem confundir contato e pessoa |
| Atualização dos dados | Percorrida | Percorrida | Fonte, frescor, cobertura e falhas separados |

## Fórmulas efetivamente abertas
- FARMA Resumo: campo faturamento, agregação Soma.
- PET Resumo e FARMA Vendas: CASE WHEN SUM(pedidos)>0 THEN SUM(faturamento)/SUM(pedidos) ELSE NULL END.
- PET Meus clientes: CASE WHEN COUNT_DISTINCT(cliente_chave)>0 THEN SUM(faturamento)/COUNT_DISTINCT(cliente_chave) ELSE NULL END.
- FARMA Anúncios: compradores = COUNT_DISTINCT(cliente_chave); receita associada = SUM(pedido_faturamento_total).
- FARMA Anúncios: CASE WHEN COUNT_DISTINCT(contact_uuid)>0 THEN COUNT_DISTINCT(cliente_chave)/COUNT_DISTINCT(contact_uuid) ELSE NULL END.
- FARMA Produtos: COUNT_DISTINCT(CASE WHEN sku_informado=1 THEN produto_codigo ELSE NULL END).
- FARMA e PET Base: COUNT_DISTINCT(contato_chave).
- ABC classe A: campo upstream produtos_classe_a com Soma; a classificação upstream não foi inspecionada.

Não transferir uma fórmula observada em um relatório automaticamente para o outro sem verificar sua origem. A matriz registra os escopos.

## Achados funcionais
Resumo/Vendas usam período; as páginas Base e Atualização mostram snapshot/estado e não apresentaram filtro de período equivalente. No Métricas, diferenciar data de compra, data de aquisição, data do snapshot e data da coleta.

Pedidos por cliente: combinação “NexoFlow - Pedidos e produtos por cliente”, colunas Cliente/Data/Produto e métricas Qtd./Valor, ordenação data decrescente, 100 linhas por página, cruzamento de filtros habilitado e drill-down desligado. Joins foram conferidos na retomada abaixo; a unicidade upstream e a reconciliação para evitar multiplicação ainda estão pendentes.

Curva ABC possui cards por classe, participação de receita, resumo por período com Top 5, tabela de produtos e pares comprados juntos. Produtos mais vendidos não contém o card Top 5 como KPI isolado na visualização observada; contém participação acumulada no ranking. Top 10 dermocosméticos não foi observado na página atual e será extensão condicionada à classificação confiável.

FARMA Anúncios declara período de chegada pelo primeiro anúncio e usa “receita associada”. A taxa atual é contato→compra, não conversa→venda. Pedidos dos anúncios informa último pedido identificado por contato e valor incluindo frete. Essas limitações precisam estar visíveis até haver histórico/atribuição completa.

PET Anúncios permanece com “Aguardando dados” para CAC/ROAS/Payback/conversão e um card de receita média por cliente. Não é prova de métricas de mídia nem de falta de vendas. A orientação posterior do responsável exige as mesmas páginas que FARMA, ajustes em Anúncios e KPIs adicionais.

Atualização: o horário exibido como atualização da página foi diferente do último processamento registrado na fonte. O Métricas deve mostrar ambos com semântica clara, além da cobertura dos pedidos.

## Interações e lacunas
Paginação e ordenação foram identificadas; configuração de crossfilter/drill foi conferida nas tabelas de pedidos e status. Menus de busca por cliente/produto, classe ABC, cidade/canal/faixa etária e pedido foram observados. Não foi feita busca por dados pessoais ou exportação de clientes.

Ainda precisam de ensaio: todos os filtros cruzados em cada componente, todos os drill-downs, exportação por perfil, comportamento de todos os cartões em período vazio, comparações históricas, joins e fórmulas comunitárias/Apps Script. Fontes/campos a confirmar estão marcados por linha; não preencher com inferência.

As cores PET azul #20AFE9 e laranja #F69F11 e a logo foram observadas. Identidade de cada marca deve ser preservada; não substituir os Data Studio durante a construção do produto.

## Novos KPIs obrigatórios
LTV observado, recorrência, frequência, clientes novos, conversas, taxa conversa→venda, investimento, CAC, ROAS e Payback entram no projeto mesmo quando ausentes no Data Studio. As definições/guardas estão na matriz e na arquitetura. Não prometer completude histórica nem atribuição causal a partir de HTTP 200, clique ou associação temporal.

A matriz CSV é a fonte detalhada de paridade, com página/elemento, fonte, fórmula, filtros, equivalente, melhoria, dependência, aceite e estado.


## Inspeção complementar na retomada de 07/11/2026

Esta seção reduz lacunas específicas do inventário inicial. A inspeção foi somente leitura de configurações, sem salvar alterações nas fontes ou no relatório.

### Resumo: bindings e fórmulas confirmados

Nos dois relatórios, os quatro cards usam a fonte BI_Clientes_Vendas da própria marca e dimensão de período data. Foram abertos os bindings: faturamento com Soma; pedidos com Soma; compradores com COUNT_DISTINCT(cliente_chave); ticket com CASE WHEN SUM(pedidos)>0 THEN SUM(faturamento)/SUM(pedidos) ELSE NULL END. As comparações estavam desligadas nos cards inspecionados.

### Combinações efetivamente inspecionadas

FARMA e PET, Pedidos por cliente: BI_Clientes_Vendas à esquerda, BI_Itens à direita; LEFT JOIN por data=data e venda_chave=venda_chave. A esquerda inclui venda_chave, data, cliente e cliente_chave; a direita inclui data, venda_chave e produto_nome, com quantidade e receita_item como métricas. O período automático está na tabela esquerda; a tabela direita não apresenta dimensão de período selecionada. A configuração não prova unicidade nem integridade upstream. No Métricas, preservar item_chave e SKU para não fundir produtos homônimos, e nunca somar o total do cabeçalho após um join de itens.

FARMA, Anúncios: Base_Contatos da Operação à esquerda e BI_Pedidos do Dashboard à direita. LEFT JOIN pela chave calculada Pedido após anúncio = pedido_id da direita. Fórmula aberta: CASE WHEN pedido_data>=primeiro_anuncio_data THEN pedido_id ELSE NULL END. Período da esquerda: primeiro_anuncio_data; direita sem dimensão de período selecionada. Filtros mostrados na combinação e conferidos no gerenciador: origem primeiro_anuncio_origem corresponde a ^Meta Ads$; venda_valida>0. São sete gráficos ligados à combinação. Essa configuração não estabelece causalidade, deduplicação por comprador/pedido ou cobertura de todos os pedidos. PET não tem essa combinação na lista atual.

### Ensaios funcionais adicionais

Em modo Leitura, com filtro temporário 15/11/2026 a 15/11/2026, Resumo FARMA e PET: faturamento, pedidos e ticket exibem Não há dados; compradores distintos exibem 0; rankings de produtos e clientes exibem Não há dados. Vendas FARMA e PET: cards financeiros, pedidos, unidades e tabela diária exibem Não há dados. Os gráficos Vega continuam em iframe; sua série interna não foi extraída. Não foi inferido comportamento interno a partir do iframe vazio.

No PET, a paginação do ranking de produtos foi executada de 1–10 para 11–20 de 68 linhas. Esses ensaios verificam os componentes indicados, não todos os filtros de todas as páginas. A navegação entre páginas usa controles de período independentes; um filtro de data em Resumo não alterou automaticamente o controle de Vendas. Requisito para o Métricas: filtro global consistente, escopo visível e reset previsível.

A matriz CSV conserva 106 linhas. As observações complementares substituem as pendências de binding/join nos pontos acima; permanecem pendentes a unicidade/reconciliação upstream, todas as regras comunitárias e os demais ensaios de interação/exportação por perfil.
