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

Pedidos por cliente: combinação “NexoFlow - Pedidos e produtos por cliente”, colunas Cliente/Data/Produto e métricas Qtd./Valor, ordenação data decrescente, 100 linhas por página, cruzamento de filtros habilitado e drill-down desligado. Joins da combinação ainda precisam de conferência para evitar multiplicação.

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

