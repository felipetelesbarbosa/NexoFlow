# Data Studio — dados do NexoFlow

Nome atualizado conforme o [anúncio oficial do Google de 10/04/2026](https://cloud.google.com/blog/products/data-analytics/looker-studio-is-data-studio).

O **NexoFlow Analytics** prepara as tabelas no **Google Sheets**. O **Data Studio** lê essas fontes para apresentar os indicadores; executar o NexoFlow não cria gráficos nem configura o relatório automaticamente.

Cada segmento usa seu próprio Dashboard. Para reproduzir o painel Farma no Pets, duplique o relatório e substitua todas as fontes por abas `BI_*` equivalentes no Dashboard Pets. O NexoFlow não duplica o relatório automaticamente. Veja [segmentos e fluxos](SEGMENTOS%20E%20FLUXOS.md).

## Conectar e atualizar

1. Conclua a carga do Analytics e confira o resultado da execução.
2. Conecte cada aba necessária como fonte do Google Sheets no Data Studio.
3. Se a base usa três arquivos, selecione as abas `BI_*` do arquivo **Dashboard**. Operação e Histórico ficam nos destinos descritos no [guia de divisão](planilhas_separadas.md).
4. Confira os tipos: datas como datas, medidas como números e identificadores como texto. Formate valores monetários com duas casas decimais.
5. Atualize os dados do relatório. Quando uma atualização acrescentar colunas, atualize também os campos das fontes.

A conta usada pelo conector do Data Studio precisa ter acesso à planilha de dashboard. O compartilhamento da conta de serviço do NexoFlow é configurado separadamente em [Google Sheets](GOOGLE%20SETUP.md).

## Escolher a fonte

| Fonte | Uma linha representa | Uso |
| --- | --- | --- |
| `BI_Publico` | Um contato atual | Base de contatos, compra identificada, canal e perfil. |
| `BI_Clientes` | Uma pessoa no histórico disponível | Totais acumulados e última compra identificada; não usar para indicadores filtrados por data de compra. |
| `BI_Clientes_Vendas` | Uma venda válida | Clientes compradores, pedidos, faturamento, ticket e rankings no período do relatório. |
| `BI_Itens` | Um item de venda válida | Produtos, quantidades, receita por item e rankings por data. |
| `BI_Produtos_ABC` | Um produto no período calculado | Receita, participação, ranking e classe ABC. |
| `BI_Produtos_Juntos` | Um par de SKUs no período calculado | Produtos comprados juntos, contando pedidos distintos. |
| `BI_KPIs_Periodo` | Os indicadores do período calculado | Clientes, pedidos, faturamento, ticket, SKUs e concentração de receita. |
| `BI_Vendas` | Um dia de vendas | Evolução diária de pedidos, produtos, frete e faturamento. |
| `BI_Pedidos` | Um pedido para consulta | Detalhamento e conferência; filtre `venda_valida = 1` para indicadores de vendas. |
| `BI_Qualidade` | Indicadores de cobertura dos dados | Pendências, cadastro, itens, histórico e disponibilidade dos cálculos. |
| `BI_Status` | O estado da última execução | Data, resultado e saúde da sincronização. |

`BI_Canais`, `BI_Conversao` e os indicadores de base de `BI_Resumo_Diario` contêm snapshots diários. Não some bases acumuladas de vários dias. CPF válido e cliente encontrado na FarmaLíder são indicadores independentes, pois identificadores inválidos também podem ter identidade confirmada.

`BI_Ads` depende de evidência de atribuição. Investimento e atribuição compatíveis são necessários para ROAS e custos; ausência de informação não significa custo zero.

## Indicadores de clientes e vendas

Em `BI_Clientes_Vendas`, use `cliente_chave` para identificar a pessoa e `cliente` para apresentar seu nome. Para agrupar clientes, não inclua a data nem use somente o nome.

| Indicador | Cálculo |
| --- | --- |
| Pedidos | `SUM(pedidos)` |
| Clientes compradores | `COUNT_DISTINCT(cliente_chave)` |
| Faturamento | `SUM(faturamento)` |
| Ticket médio | `SUM(faturamento) / SUM(pedidos)` |
| Pedidos por cliente | `SUM(pedidos) / COUNT_DISTINCT(cliente_chave)` |
| Receita média por cliente | `SUM(faturamento) / COUNT_DISTINCT(cliente_chave)` |
| Última compra no período | `MAX(data)` |

Trate divisões sem denominador no relatório. Não some compradores diários nem faça média de tickets diários para obter o total do período. A última compra em todo o histórico vem de `BI_Clientes`.

Nos cards de `BI_Publico`, use contagem de contatos, soma de `compra_identificada`, diferença para os sem compra e percentual sobre a base. Não aplique o período de vendas à base atual. `criado_em` é cadastro na Weni, sem comprovar aquisição por Marketing.

Para receita por produto, use os valores dos itens de `BI_Itens`. Não repita o faturamento inteiro do pedido em cada linha de produto. Chaves técnicas podem ficar ocultas na apresentação, mantendo o agrupamento.

## Períodos e Curva ABC

`BI_Clientes_Vendas` e `BI_Itens` aceitam filtros de data do relatório. ABC, produtos juntos e `BI_KPIs_Periodo` usam `periodo_inicio` e `periodo_fim`, com os últimos 30 dias, inclusive hoje, como padrão.

Para recalcular outro período pelo histórico do Sheets:

```text
nexo looker --inicio AAAA-MM-DD --fim AAAA-MM-DD
```

O nome técnico `nexo looker` foi mantido para compatibilidade. Substitua as datas pelo intervalo desejado. O comando não consulta Weni nem FarmaLíder. O filtro do Data Studio não recalcula automaticamente essas tabelas; confira as datas antes de apresentar os resultados. O [conector opcional](../connectors/looker_abc/README.md) permite cálculos por período no próprio relatório quando configurado.

A Curva ABC usa a receita de todos os itens, sem frete: A até 80%, B até 95% e C depois. O produto que cruza um limite permanece na classe iniciada antes dele. Empates mantêm ranking e classe iguais, podendo ultrapassar o limite.

Sem cobertura completa, SKU ou receita positiva, ou com divergência entre itens e valor dos produtos acima de R$ 0,01, a ABC fica indisponível e as classes permanecem vazias. A concentração nos cinco produtos também depende da cobertura completa. Confira `pedidos_sem_itens`, `pedidos_com_itens_divergentes`, `abc_disponivel` e `abc_periodo_disponivel` na fonte correspondente. Receita não representa lucro.

## Regras e limites dos dados

- **Vendas:** status documentados -2, -1, 0, 4, 1 e 2 contam após validação. Status 3, pagamento cancelado e pedidos oficialmente sem itens ficam fora. Em `BI_Delivery_Pedidos`, use `venda_realizada = 1`.
- **Pets Líder:** produtos PET são preservados no perfil PET; os destinos não se misturam com Farma.
- **Farmácia:** pedidos apenas pet ou veterinários são excluídos; pedidos mistos mantêm itens humanos e seu valor, sem o frete do pedido inteiro.
- **Valores:** produtos e frete são separados. O faturamento total inclui frete quando aplicável; não o some novamente. Quantidades fracionárias devem ser preservadas.
- **Histórico:** a API retorna o último pedido, não todas as compras. O Analytics acumula o que identifica nas coletas, sem declarar cobertura histórica completa. Compras podem não ser capturadas entre coletas.
- **Status:** pedidos já registrados são reconsultados de hoje até 20 dias atrás, no fuso `America/Belem`. Os anteriores permanecem preservados; novas compras continuam sendo buscadas.
- **Cadastro:** localização, gênero e idade refletem o perfil atual disponível, não necessariamente o endereço ou a idade na data da compra. Dados ausentes permanecem vazios; não deduza gênero pelo nome nem some idades.

O início das novas coletas é registrado em `Controle.historico_observado_desde`. Indicadores de recompra completa e comparações exigem cobertura comprovada. `clientes_com_multiplas_compras_identificadas` descreve somente o histórico identificado.

## Se o número parecer incorreto

Confira o resultado e a data da última carga, a fonte conectada, o período, os filtros de venda e a cobertura em `BI_Qualidade`. Uma carga parcial pode preservar registros anteriores. Siga o [guia de operação](Documentacao%20NexoFlow.md) antes de apresentar os resultados.
