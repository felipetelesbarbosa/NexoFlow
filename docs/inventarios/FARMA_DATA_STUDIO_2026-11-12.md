# Inventário do Data Studio | NexoFlow FarmaLíder

Relatório **NexoFlow Analytics - FarmaLíder** · Conferência em 12/11/2026 · [Abrir relatório](https://datastudio.google.com/reporting/e60ba3bc-fe88-417d-8a39-d8512debf175/page/oeZAG).

Foram conferidas **37 fontes**, **5 mesclagens**, **14 filtros** e **3 substituições de IDs** nos gerenciadores do relatório. O anexo registra 75 componentes com dados e 8 controles de período em 14 páginas. A fonte ou mesclagem foi confirmada em 75 componentes. Os campos listados vêm das configurações de gráficos, controles e mesclagens que puderam ser lidas. Os rótulos do editor podem corresponder a cálculos ou aliases. Fórmulas, IDs de campos e vínculos físicos que a interface não expôs exigem conferência antes da troca.

## Fontes

A coluna Usos reproduz o contador do Data Studio, que pode incluir dependências via mesclagem. Preserve os aliases individualmente. As fontes `ds74`, `ds103` e `ds123` têm a mesma aba lógica `Base_Contatos`. As fontes `ds141` e `ds175` têm a mesma tabela lógica `BI_LTV_Clientes` e conectores diferentes.

| Alias | Nome no relatório | Tabela, aba ou conjunto lógico | Conector e escopo | Usos | Campos observados em uso | Mesclagem |
|---|---|---|---|---:|---|---|
| `ds0` | NexoFlow - Metricas_Diarias | `Metricas_Diarias` | Planilhas · Incorporada | 0 | Sem uso observado | — |
| `ds1` | NexoFlow - Metricas_Vendas | `Metricas_Vendas` | Planilhas · Incorporada | 0 | Sem uso observado | — |
| `ds2` | NexoFlow - BI_Resumo_Diario | `BI_Resumo_Diario` | Planilhas · Incorporada | 0 | Sem uso observado | — |
| `ds13` | FarmaLíder - WhatsApp Analytics (Weni) - BI_Canais | `BI_Canais` | Planilhas · Incorporada | 0 | Sem uso observado | — |
| `ds14` | FarmaLíder - WhatsApp Analytics (Weni) - BI_Conversao | `BI_Conversao` | Planilhas · Incorporada | 0 | Sem uso observado | — |
| `ds15` | FarmaLíder - WhatsApp Analytics (Weni) - BI_Vendas | `BI_Vendas` | Planilhas · Incorporada | 8 | `Clientes que compraram`, `data`, `Data do pedido`, `Faturamento`, `Pedidos`, `Ticket médio`, `Ticket médio do período`, `Unidades vendidas` | — |
| `ds16` | FarmaLíder - WhatsApp Analytics (Weni) - BI_Ads | `BI_Ads` | Planilhas · Incorporada | 0 | Sem uso observado | — |
| `ds17` | FarmaLíder - WhatsApp Analytics (Weni) - BI_Status | `BI_Status` | Planilhas · Incorporada | 1 | `atualizado_em`, `Situação`, `Último processamento registrado` | — |
| `ds72` | FarmaLíder - WhatsApp Analytics (Weni) - Pedidos_FarmaLider | `Pedidos_FarmaLider` | Planilhas · Incorporada | 0 | `Clientes que já compraram`, `contact_uuid`, `pedido_chave` | Produtos de pedidos válidos<br>Público e compras identificadas |
| `ds73` | FarmaLíder - WhatsApp Analytics (Weni) - Itens_Pedidos_FarmaLider | `Itens_Pedidos_FarmaLider` | Planilhas · Incorporada | 0 | `data`, `pedido_chave`, `produto_codigo`, `produto_nome`, `quantidade`, `Record Count`, `valor_total` | Produtos de pedidos válidos |
| `ds74` | FarmaLíder - WhatsApp Analytics (Weni) - Base_Contatos | `Base_Contatos` | Planilhas · Incorporada | 0 | `contact_canal_principal`, `contact_uuid`, `Contatos criados no período`, `Faixa etária` | Público e compras identificadas |
| `ds80` | FarmaLíder - WhatsApp Analytics (Weni) - BI_Clientes_Vendas | `BI_Clientes_Vendas` | Planilhas · Incorporada | 15 | `Buscar cliente pelo nome`, `cliente`, `cliente_chave`, `Clientes que compraram`, `data`, `faturamento`, `Faturamento`, `Nome`, `Pedidos`, `Pedidos por cliente`, `Receita gerada`, `Receita média por cliente`, `Registros`, `Ticket médio`, `venda_chave` | NexoFlow - Pedidos e produtos por cliente |
| `ds81` | FarmaLíder - WhatsApp Analytics (Weni) - BI_Clientes | `BI_Clientes` | Planilhas · Incorporada | 0 | Sem uso observado | — |
| `ds82` | FarmaLíder - WhatsApp Analytics (Weni) - BI_Publico | `BI_Publico` | Planilhas · Incorporada | 12 | `Canal`, `Canal de contato`, `Cidade`, `Com compra identificada`, `Contatos`, `Contatos com compra (%)`, `Contatos com compra identificada`, `Contatos com idade informada`, `Contatos na base`, `Contatos que já compraram (%)`, `Contatos sem cidade`, `Faixa etária`, `Idades informadas`, `Novo campo`, `Participação na seleção`, `Sem compra identificada` | — |
| `ds83` | FarmaLíder - WhatsApp Analytics (Weni) - BI_Itens | `BI_Itens` | Planilhas · Incorporada | 9 | `Buscar produto pelo nome`, `data`, `Novo campo`, `Participação acumulada`, `Produto`, `produto_nome`, `Produtos diferentes`, `quantidade`, `Receita de produtos`, `receita_item`, `Registros`, `Unidades`, `Unidades vendidas`, `venda_chave` | NexoFlow - Pedidos e produtos por cliente |
| `ds84` | FarmaLíder - WhatsApp Analytics (Weni) - BI_Qualidade | `BI_Qualidade` | Planilhas · Incorporada | 0 | Sem uso observado | — |
| `ds86` | FarmaLíder - WhatsApp Analytics (Weni) - BI_Produtos_ABC | `BI_Produtos_ABC` | Planilhas · Incorporada | 0 | Sem uso observado | — |
| `ds88` | FarmaLíder - WhatsApp Analytics (Weni) - BI_KPIs_Periodo | `BI_KPIs_Periodo` | Planilhas · Incorporada | 0 | Sem uso observado | — |
| `ds90` | FarmaLíder - WhatsApp Analytics (Weni) - BI_Produtos_Juntos | `BI_Produtos_Juntos` | Planilhas · Incorporada | 0 | Sem uso observado | — |
| `ds103` | NexoFlow — Operação - Base_Contatos | `Base_Contatos` | Planilhas · Incorporada | 1 | `Bairro do contato`, `Contatos`, `Novo campo`, `Participação na seleção`, `weni_created_on (Data)` | — |
| `ds106` | NexoFlow 1.0 - ABC por período | ABC por período (conjunto do conector Apps Script) | Apps Script · Reutilizável | 0 | Sem uso observado | — |
| `ds107` | NexoFlow 1.0 - ABC dinâmico | ABC dinâmico (conjunto do conector Apps Script) | Apps Script · Reutilizável | 2 | `Acumulada (%)`, `Classe`, `Filtrar por classe ABC`, `Participação (%)`, `Produto`, `Receita`, `Receita de produtos`, `SKU`, `Unidades` | — |
| `ds109` | NexoFlow 1.0 - Resumo ABC por período | Resumo ABC por período (conjunto do conector Apps Script) | Apps Script · Reutilizável | 7 | `Período`, `Produtos diferentes`, `Produtos na classe A`, `Produtos na classe B`, `Produtos na classe C`, `Receita classe A (%)`, `Receita classe B (%)`, `Receita classe C (%)`, `Receita de produtos`, `Top 5 na receita (%)` | — |
| `ds110` | NexoFlow 1.0 - Compras juntas por período | Compras juntas por período (conjunto do conector Apps Script) | Apps Script · Reutilizável | 1 | `Pedidos juntos`, `Período`, `Produto A`, `Produto B`, `SKU A`, `SKU B` | — |
| `ds121` | NexoFlow FarmaLíder — Dashboard - BI_Pedidos | `BI_Pedidos` | Planilhas · Incorporada | 4 | `cliente`, `cliente_chave`, `data`, `pedido_faturamento_total`, `pedido_id`, `pedido_produtos` | Anúncios - contatos e pedidos identificados |
| `ds123` | NexoFlow FarmaLíder — Operação - Base_Contatos | `Base_Contatos` | Planilhas · Incorporada | 4 | `contact_uuid`, `farmalider_cliente_id`, `farmalider_cliente_nome`, `Pedido após anúncio`, `pedido_id`, `primeiro_anuncio_data`, `primeiro_anuncio_id` | Anúncios - contatos e pedidos identificados<br>FARMA \| LTV por cliente |
| `ds133` | NexoFlow FarmaLíder — Dashboard - BI_Meta_Resultados | `BI_Meta_Resultados` | Planilhas · Incorporada | 7 | `Anúncio (ID)`, `Campanha`, `Conversas iniciadas na Meta`, `CPA`, `CPA geral`, `data`, `Investimento`, `Investimento na Meta`, `investimento_atribuivel`, `Meta \| Anúncios classificados como FARMA`, `Pedidos`, `Pedidos confirmados`, `Receita`, `Receita confirmada`, `ROAS (%)` | — |
| `ds136` | NexoFlow FarmaLíder — Dashboard - BI_Weni_Conversas_Diarias | `BI_Weni_Conversas_Diarias` | Planilhas · Incorporada | 0 | Sem uso observado | — |
| `ds139` | NexoFlow FarmaLíder – BI_Historico_Resumo TOTAL | `BI_Historico_Resumo` · `TOTAL` | Apps Script · Reutilizável | 4 | `Compradores distintos`, `Faturamento observado`, `Pedidos válidos`, `periodo_inicio`, `Ticket médio histórico` | — |
| `ds140` | NexoFlow FarmaLíder – Historico_Itens | `Historico_Itens` | Apps Script · Reutilizável | 0 | Sem uso observado | — |
| `ds141` | NexoFlow FarmaLíder – BI_LTV_Clientes | `BI_LTV_Clientes` | Apps Script · Reutilizável | 0 | Sem uso observado | — |
| `ds142` | NexoFlow FarmaLíder – BI_Cobertura_Historica | `BI_Cobertura_Historica` | Apps Script · Reutilizável | 1 | `calendario`, `extracao`, `inicio`, `motivo`, `Registros de cobertura` | — |
| `ds143` | NexoFlow FarmaLíder – Historico_Pedidos | `Historico_Pedidos` | Apps Script · Reutilizável | 0 | Sem uso observado | — |
| `ds175` | NexoFlow FarmaLíder — Dashboard - BI_LTV_Clientes | `BI_LTV_Clientes` | Planilhas · Incorporada | 2 | `cliente_id`, `LTV`, `Pedidos`, `segmento`, `Ticket médio`, `vigente` | FARMA \| LTV por cliente |
| `ds190` | NexoFlow FARMA - Resumo MES | `BI_Historico_Resumo` · `MES` (mapeamento lógico pelo nome) | Apps Script · Incorporada | 3 | `competencia`, `Compradores distintos`, `Compras válidas`, `Faturamento observado`, `periodo_inicio`, `Ticket médio` | — |
| `ds191` | NexoFlow FARMA - Resumo ANO | `BI_Historico_Resumo` · `ANO` (mapeamento lógico pelo nome) | Apps Script · Incorporada | 1 | `competencia`, `Compradores distintos`, `Compras válidas`, `Faturamento observado`, `periodo_inicio`, `Ticket médio` | — |
| `ds192` | NexoFlow FARMA - Resumo SEM EMISSAO | `BI_Historico_Resumo` · `SEM EMISSAO` (mapeamento lógico pelo nome) | Apps Script · Incorporada | 0 | Sem uso observado | — |

## Mesclagens

### Produtos de pedidos válidos

0 gráfico(s) no gerenciador. INNER JOIN · `pedido_chave` = `pedido_chave`

| Fonte | Dimensões | Métricas | Campo de período | Filtros |
|---|---|---|---|---|
| `ds73` FarmaLíder - WhatsApp Analytics (Weni) - Itens_Pedidos_FarmaLider | `pedido_chave`, `produto_codigo`, `produto_nome`, `data` | `Record Count`, `quantidade`, `valor_total` | `data` | — |
| `ds72` FarmaLíder - WhatsApp Analytics (Weni) - Pedidos_FarmaLider | `pedido_chave` | — | — | `Pedidos confirmados e elegíveis` |

### Público e compras identificadas

0 gráfico(s) no gerenciador. LEFT JOIN · `contact_uuid` = `contact_uuid`

| Fonte | Dimensões | Métricas | Campo de período | Filtros |
|---|---|---|---|---|
| `ds74` FarmaLíder - WhatsApp Analytics (Weni) - Base_Contatos | `contact_uuid`, `contact_canal_principal`, `Faixa etária` | `Contatos criados no período` | — | — |
| `ds72` FarmaLíder - WhatsApp Analytics (Weni) - Pedidos_FarmaLider | `contact_uuid` | `Clientes que já compraram` | — | `Pedidos confirmados e elegíveis` |

### NexoFlow - Pedidos e produtos por cliente

1 gráfico(s) no gerenciador. LEFT JOIN · `data` = `data` e `venda_chave` = `venda_chave`

| Fonte | Dimensões | Métricas | Campo de período | Filtros |
|---|---|---|---|---|
| `ds80` FarmaLíder - WhatsApp Analytics (Weni) - BI_Clientes_Vendas | `venda_chave`, `data`, `cliente`, `cliente_chave` | — | `data` | — |
| `ds83` FarmaLíder - WhatsApp Analytics (Weni) - BI_Itens | `data`, `venda_chave`, `produto_nome` | `quantidade`, `receita_item` | — | — |

### Anúncios - contatos e pedidos identificados

2 gráfico(s) no gerenciador. LEFT JOIN · `Pedido após anúncio` = `pedido_id`

| Fonte | Dimensões | Métricas | Campo de período | Filtros |
|---|---|---|---|---|
| `ds123` NexoFlow FarmaLíder — Operação - Base_Contatos | `contact_uuid`, `primeiro_anuncio_id`, `pedido_id`, `Pedido após anúncio` | — | `primeiro_anuncio_data` | `Anúncios \| Contatos Meta` |
| `ds121` NexoFlow FarmaLíder — Dashboard - BI_Pedidos | `pedido_id`, `cliente`, `cliente_chave`, `data`, `pedido_produtos` | `pedido_faturamento_total` | — | `Anúncios \| Pedidos válidos` |

### FARMA \| LTV por cliente

2 gráfico(s) no gerenciador. LEFT JOIN · `cliente_id` = `farmalider_cliente_id`

| Fonte | Dimensões | Métricas | Campo de período | Filtros |
|---|---|---|---|---|
| `ds175` NexoFlow FarmaLíder — Dashboard - BI_LTV_Clientes | `cliente_id`, `segmento`, `vigente` | `LTV`, `Pedidos`, `Ticket médio` | — | `FARMA \| Clientes atuais` |
| `ds123` NexoFlow FarmaLíder — Operação - Base_Contatos | `farmalider_cliente_id`, `farmalider_cliente_nome` | — | — | — |

## Filtros cadastrados

| Filtro | Usos | Condição exibida no gerenciador |
|---|---:|---|
| Pedidos confirmados e elegíveis | 0 | Incluir · Venda elegível · Igual a (=) · Sim |
| ABC disponível no período selecionado | 0 | Incluir · classe_abc · Correspondência RegExp · ^[ABC]$ |
| Idades informadas | 2 | Incluir · idade_informada · Igual a (=) · "1" |
| Cidades informadas no ranking | 0 | Excluir · cidade · Igual a (=) |
| Anúncios \| Primeiro anúncio | 0 | Incluir · tipo_atribuicao · Igual a (=) · Primeiro anúncio |
| Anúncios \| Contatos Meta | 2 | Incluir · primeiro_anuncio_origem · Correspondência RegExp · ^Meta Ads$ |
| Anúncios \| Pedidos válidos | 2 | Incluir · venda_valida · Maior que (>) · "0" |
| Anúncios \| Só pedidos identificados | 1 | A conferir no editor do filtro |
| Anúncios \| Pedidos disponíveis | 1 | A conferir no editor do filtro |
| Anúncios \| IDs de pedidos | 1 | A conferir no editor do filtro |
| Meta \| Anúncios classificados como FARMA | 2 | Incluir · classificacao · Igual a (=) · FARMA |
| FARMA \| Clientes atuais | 2 | "Composto: 2 cláusulas" |
| LTV \| Clientes com nome | 1 | A conferir no editor do filtro |
| Delivery FarmaLíder \| Campanhas verificadas | 1 | "Composto: 2 cláusulas" |

## Substituições de IDs de campos

| Nome original | ID original | ID substituto | Tipo |
|---|---|---|---|
| `Canal para filtros` | `calc_ic8v2uva8d` | `nxf_canal` | Texto |
| `Faixa para filtros` | `calc_iagp6vva8d` | `nxf_faixa` | Texto |
| `contact_canal_principal` | `_1602682571_` | `_94427131_` | Texto |

## Componentes do relatório

Campos exibidos na configuração. As agregações aparecem entre parênteses quando identificáveis. Rótulos repetidos como `Novo campo` pertencem ao componente onde aparecem. Confirme suas fórmulas e IDs no editor antes de mapear para PostgreSQL.

### 1. Resumo

[Abrir página](https://datastudio.google.com/reporting/e60ba3bc-fe88-417d-8a39-d8512debf175/page/oeZAG/edit)

| Componente | Tipo | Fonte ou mesclagem | Campos e configuração |
|---|---|---|---|
| `cd-1d5gnzq27d` | kpi-metric | ds80 | Campo principal: `Faturamento` (sum)<br>Dimensão do período: `data` |
| `cd-27fm84q27d` | kpi-metric | ds80 | Campo principal: `Pedidos` (sum)<br>Dimensão do período: `data` |
| `cd-2phs48q27d` | kpi-metric | ds80 | Campo principal: `Clientes que compraram` (aut)<br>Dimensão do período: `data` |
| `cd-jaxecar27d` | kpi-metric | ds80 | Campo principal: `Ticket médio` (aut)<br>Dimensão do período: `data` |
| `cd-doo6ycr27d` | simple-daterangepicker | — | Filtro de período padrão: Este mês, até agora (incluir hoje) |
| `cd-xma9ddr27d` | simple-linechart | ds80 | Dimensão (eixo X): `data`<br>Métrica (eixo Y): `Faturamento` (sum)<br>Dimensão do período: `data` |
| `cd-d7ziiiy67d` | simple-table | ds83 | Métrica: `Produto` (aut), `Receita de produtos` (aut)<br>Dimensão do período: `data`<br>Classificar: `Novo campo` (aut)<br>Classificação nº 1: `Novo campo` (aut) |
| `cd-qiedv2y67d` | simple-table | ds80 | Métrica: `Nome` (aut), `Receita gerada` (sum)<br>Dimensão do período: `data`<br>Classificar: `faturamento` (sum)<br>Classificação nº 1: `faturamento` (sum) |

### 2. Vendas

[Abrir página](https://datastudio.google.com/reporting/e60ba3bc-fe88-417d-8a39-d8512debf175/page/p_2prt8y427d/edit)

| Componente | Tipo | Fonte ou mesclagem | Campos e configuração |
|---|---|---|---|
| `cd-ottrefr57d` | kpi-metric | ds15 | Campo principal: `Faturamento` (sum)<br>Dimensão do período: `data` |
| `cd-rttrefr57d` | kpi-metric | ds15 | Campo principal: `Pedidos` (sum)<br>Dimensão do período: `data` |
| `cd-zttrefr57d` | kpi-metric | ds15 | Campo principal: `Ticket médio do período` (aut)<br>Dimensão do período: `data` |
| `cd-4ttrefr57d` | simple-daterangepicker | — | Filtro de período padrão: Este mês, até agora (incluir hoje) |
| `cd-5ttrefr57d` | simple-linechart | ds15 | Dimensão (eixo X): `data`<br>Métrica (eixo Y): `Faturamento` (sum)<br>Dimensão do período: `data` |
| `cd-9ttrefr57d` | simple-linechart | ds15 | Dimensão (eixo X): `data`<br>Métrica (eixo Y): `Pedidos` (sum)<br>Dimensão do período: `data` |
| `cd-7lurefr57d` | simple-table | ds15 | Dimensão: `Data do pedido`<br>Métrica: `Faturamento` (sum), `Pedidos` (sum), `Clientes que compraram` (sum), `Ticket médio` (aut)<br>Dimensão do período: `data`<br>Classificar: `data`<br>Classificação nº 1: `data` |
| `cd-jz45bqx67d` | kpi-metric | ds15 | Campo principal: `Unidades vendidas` (sum)<br>Dimensão do período: `data` |
| `cd-xxysesma8d` | simple-linechart | ds15 | Dimensão (eixo X): `data`<br>Métrica (eixo Y): `Ticket médio` (aut)<br>Dimensão do período: `data` |

### 3. Meus clientes

[Abrir página](https://datastudio.google.com/reporting/e60ba3bc-fe88-417d-8a39-d8512debf175/page/p_zn4bgmm37d/edit)

| Componente | Tipo | Fonte ou mesclagem | Campos e configuração |
|---|---|---|---|
| `cd-187b1bh67d` | kpi-metric | ds80 | Campo principal: `Clientes que compraram` (aut)<br>Dimensão do período: `data` |
| `cd-a97b1bh67d` | simple-daterangepicker | — | Filtro de período padrão: Este mês, até agora (incluir hoje) |
| `cd-4sdu5qn77d` | kpi-metric | ds80 | Campo principal: `Receita média por cliente` (aut)<br>Dimensão do período: `data` |
| `cd-3ea0ktn77d` | kpi-metric | ds80 | Campo principal: `Pedidos por cliente` (aut)<br>Dimensão do período: `data` |
| `cd-qw8fjko77d` | dimension-filter | ds80 | Campo "Controle": `Buscar cliente pelo nome`<br>Métrica: `Registros` (aut)<br>Dimensão do período: `data`<br>Classificar: `cliente` |
| `cd-mwlhg9v97d` | simple-table | ds80 | Métrica: `Nome` (aut), `Receita gerada` (sum), `Pedidos` (aut), `Ticket médio` (aut)<br>Dimensão do período: `data`<br>Classificar: `faturamento` (sum)<br>Classificação nº 1: `faturamento` (sum) |

### 4. Pedidos por cliente

[Abrir página](https://datastudio.google.com/reporting/e60ba3bc-fe88-417d-8a39-d8512debf175/page/p_qjz77l2r8d/edit)

| Componente | Tipo | Fonte ou mesclagem | Campos e configuração |
|---|---|---|---|
| `cd-2m0p6l2r8d` | simple-daterangepicker | — | Filtro de período padrão: Este mês, até agora (incluir hoje) |
| `cd-ze1p6l2r8d` | simple-table | ds80 | Métrica: `Nome` (aut), `Receita gerada` (sum)<br>Dimensão do período: `data`<br>Classificar: `faturamento` (sum)<br>Classificação nº 1: `faturamento` (sum) |
| `cd-0e1p6l2r8d` | dimension-filter | ds80 | Campo "Controle": `Buscar cliente pelo nome`<br>Métrica: `Registros` (aut)<br>Dimensão do período: `data`<br>Classificar: `cliente` |
| `cd-1e1p6l2r8d` | simple-table | NexoFlow - Pedidos e produtos por cliente | Dimensão: `Cliente`, `Data do pedido`, `Produto`<br>Métrica: `Qtd.` (sum), `Valor (R$)` (sum)<br>Classificar: `data`<br>Classificação nº 1: `data` |
| `cd-o6rzfn3r8d` | dimension-filter | ds80 | Campo "Controle": `Buscar cliente pelo nome`<br>Métrica: `Registros` (aut)<br>Dimensão do período: `data`<br>Classificar: `cliente` |

### 5. Produtos mais vendidos

[Abrir página](https://datastudio.google.com/reporting/e60ba3bc-fe88-417d-8a39-d8512debf175/page/p_xbks8f427d/edit)

| Componente | Tipo | Fonte ou mesclagem | Campos e configuração |
|---|---|---|---|
| `cd-5jxb8f427d` | simple-daterangepicker | — | Filtro de período padrão: Este mês, até agora (incluir hoje) |
| `cd-zbyb8f427d` | simple-table | ds83 | Métrica: `Produto` (aut), `Receita de produtos` (aut), `Unidades` (aut), `Participação acumulada` (aut)<br>Dimensão do período: `data`<br>Classificar: `Novo campo` (aut)<br>Classificação nº 1: `Novo campo` (aut) |
| `cd-dh5fz9k67d` | simple-table | ds83 | Métrica: `Produto` (aut), `Unidades` (sum), `Receita de produtos` (aut)<br>Dimensão do período: `data`<br>Classificar: `quantidade` (sum), `Novo campo` (aut)<br>Classificação nº 1: `quantidade` (sum)<br>Classificação nº 2: `Novo campo` (aut) |
| `cd-mli8wgga8d` | simple-table | ds83 | Métrica: `Produto` (aut), `Receita de produtos` (aut), `Unidades` (aut)<br>Dimensão do período: `data`<br>Classificar: `Novo campo` (aut)<br>Classificação nº 1: `Novo campo` (aut) |
| `cd-uqdlxzma8d` | kpi-metric | ds83 | Campo principal: `Produtos diferentes` (aut)<br>Dimensão do período: `data` |
| `cd-tyy2h1ma8d` | kpi-metric | ds83 | Campo principal: `Receita de produtos` (aut)<br>Dimensão do período: `data` |
| `cd-36qnu1ma8d` | kpi-metric | ds83 | Campo principal: `Unidades vendidas` (aut)<br>Dimensão do período: `data` |
| `cd-2zpk2p3b8d` | dimension-filter | ds83 | Campo "Controle": `Buscar produto pelo nome`<br>Métrica: `Registros` (aut)<br>Dimensão do período: `data`<br>Classificar: `produto_nome` |

### 6. Curva ABC

[Abrir página](https://datastudio.google.com/reporting/e60ba3bc-fe88-417d-8a39-d8512debf175/page/p_ifcey02b8d/edit)

| Componente | Tipo | Fonte ou mesclagem | Campos e configuração |
|---|---|---|---|
| `cd-0rcosvwf8d` | simple-daterangepicker | — | Controle de período |
| `cd-3mp4ey1f8d` | kpi-metric | ds109 | Campo principal: `Produtos na classe A` (sum) |
| `cd-c2kr295f8d` | kpi-metric | ds109 | Campo principal: `Produtos na classe B` (sum) |
| `cd-detb3a6f8d` | kpi-metric | ds109 | Campo principal: `Produtos na classe C` (sum) |
| `cd-i9wblb6f8d` | kpi-metric | ds109 | Campo principal: `Receita classe A (%)` (max) |
| `cd-j5ll6b6f8d` | kpi-metric | ds109 | Campo principal: `Receita classe B (%)` (max) |
| `cd-yjg1mc6f8d` | kpi-metric | ds109 | Campo principal: `Receita classe C (%)` (max) |
| `cd-ir1ajd6f8d` | simple-table | ds109 | Dimensão: `Período`<br>Métrica: `Produtos diferentes` (sum), `Top 5 na receita (%)` (max), `Receita de produtos` (sum)<br>Classificar: `Produtos na classe A` (sum)<br>Classificação nº 1: `Produtos na classe A` (sum) |
| `cd-p503ag6f8d` | simple-table | ds107 | Dimensão: `Classe`, `SKU`, `Produto`<br>Métrica: `Unidades` (sum), `Receita` (sum), `Participação (%)` (sum), `Acumulada (%)` (max)<br>Classificar: `Receita de produtos` (sum)<br>Classificação nº 1: `Receita de produtos` (sum) |
| `cd-8e66pl6f8d` | simple-table | ds110 | Dimensão: `Produto A`, `Produto B`, `SKU A`, `SKU B`, `Período`<br>Métrica: `Pedidos juntos` (sum)<br>Classificar: `Pedidos juntos` (sum)<br>Classificação nº 1: `Pedidos juntos` (sum) |
| `cd-sr57pa4r8d` | dimension-filter | ds107 | Campo "Controle": `Filtrar por classe ABC`<br>Métrica: `Unidades` (sum)<br>Classificar: `Classe` |

### 7. Anúncios

[Abrir página](https://datastudio.google.com/reporting/e60ba3bc-fe88-417d-8a39-d8512debf175/page/p_jinjw5427d/edit)

| Componente | Tipo | Fonte ou mesclagem | Campos e configuração |
|---|---|---|---|
| `cd-g9ezqclz8d` | kpi-metric | ds133 | Campo principal: `Investimento na Meta` (sum)<br>Filtro: `Filtro da página`, `Herdar filtros`<br>Dimensão do período: `data` |
| `cd-qlf8kvlz8d` | simple-daterangepicker | — | Filtro de período padrão: Este mês, até agora (incluir hoje) |
| `cd-sn6sh0lz8d` | kpi-metric | ds133 | Campo principal: `Pedidos confirmados` (sum)<br>Filtro: `Filtro da página`, `Herdar filtros`<br>Dimensão do período: `data` |
| `cd-zexsk1lz8d` | kpi-metric | ds133 | Campo principal: `Receita confirmada` (sum)<br>Filtro: `Filtro da página`, `Herdar filtros`<br>Dimensão do período: `data` |
| `cd-qyrf07lz8d` | kpi-metric | ds133 | Campo principal: `CPA geral` (aut)<br>Filtro: `Filtro da página`, `Herdar filtros`<br>Dimensão do período: `data` |
| `cd-s7buycmz8d` | simple-table | ds133 | Dimensão: `Anúncio (ID)`, `Campanha`<br>Métrica: `Investimento` (sum), `Pedidos` (sum), `Receita` (sum), `CPA` (aut), `ROAS (%)` (aut)<br>Filtro: `Filtro da página`, `Herdar filtros`<br>Dimensão do período: `data`<br>Classificar: `investimento_atribuivel` (sum)<br>Classificação nº 1: `investimento_atribuivel` (sum) |
| `cd-m2o5u9328d` | kpi-metric | ds133 | Campo principal: `Conversas iniciadas na Meta` (sum)<br>Filtro: `Meta \| Anúncios classificados como FARMA`<br>Dimensão do período: `data` |
| `cd-edoimn428d` | kpi-metric | ds133 | Campo principal: `ROAS (%)` (aut)<br>Filtro: `Meta \| Anúncios classificados como FARMA`<br>Dimensão do período: `data` |

### 8. Pedidos dos anúncios

[Abrir página](https://datastudio.google.com/reporting/e60ba3bc-fe88-417d-8a39-d8512debf175/page/p_58ownmmz8d/edit)

| Componente | Tipo | Fonte ou mesclagem | Campos e configuração |
|---|---|---|---|
| `cd-vb5hnmmz8d` | simple-daterangepicker | — | Filtro de período padrão: Este mês, até agora (incluir hoje) |
| `cd-s35hnmmz8d` | simple-table | Anúncios - contatos e pedidos identificados | Dimensão: `Anúncio (ID)`, `Pedido`, `Data`, `Cliente`, `Produtos`<br>Métrica: `Valor do pedido` (max)<br>Filtro: `Anúncios \| Só pedidos identificados`<br>Classificar: `Novo campo` (aut)<br>Classificação nº 1: `Novo campo` (aut) |
| `cd-i9u6uymz8d` | dimension-filter | Anúncios - contatos e pedidos identificados | Campo "Controle": `Pedido`<br>Métrica: `pedido_faturamento_total` (sum)<br>Filtro: `Anúncios \| Pedidos disponíveis`, `Anúncios \| IDs de pedidos`<br>Classificar: `pedido_faturamento_total` (sum) |

### 9. Base de clientes

[Abrir página](https://datastudio.google.com/reporting/e60ba3bc-fe88-417d-8a39-d8512debf175/page/p_jqd5pqu27d/edit)

| Componente | Tipo | Fonte ou mesclagem | Campos e configuração |
|---|---|---|---|
| `cd-q2trpqu27d` | kpi-metric | ds82 | Campo principal: `Contatos na base` (aut) |
| `cd-0vau7zw67d` | simple-table | ds82 | Dimensão: `Canal`<br>Métrica: `Contatos` (aut), `Com compra identificada` (aut), `Contatos com compra (%)` (aut), `Participação na seleção` (aut)<br>Classificar: `Novo campo` (aut)<br>Classificação nº 1: `Novo campo` (aut) |
| `cd-57m5b7w67d` | simple-table | ds82 | Dimensão: `Faixa etária`<br>Métrica: `Contatos com idade informada` (aut)<br>Filtro: `Idades informadas`<br>Classificar: `Novo campo`<br>Classificação nº 1: `Novo campo` |
| `cd-tefmjqea8d` | kpi-metric | ds82 | Campo principal: `Contatos com compra identificada` (aut) |
| `cd-jw98usea8d` | kpi-metric | ds82 | Campo principal: `Sem compra identificada` (aut) |
| `cd-4nddr8ea8d` | kpi-metric | ds82 | Campo principal: `Contatos que já compraram (%)` (aut) |
| `cd-golewrna8d` | dimension-filter | ds82 | Campo "Controle": `Cidade`<br>Métrica: `Contatos` (aut)<br>Classificar: `Novo campo` (aut) |
| `cd-1108funa8d` | dimension-filter | ds82 | Campo "Controle": `Canal de contato`<br>Métrica: `Contatos` (aut)<br>Classificar: `Novo campo` (aut) |
| `cd-61m1qioa8d` | dimension-filter | ds82 | Campo "Controle": `Faixa etária`<br>Métrica: `Contatos` (aut)<br>Classificar: `Novo campo` (aut) |
| `cd-8qltwe6d8d` | kpi-metric | ds82 | Campo principal: `Contatos com idade informada` (aut)<br>Filtro: `Idades informadas` |
| `cd-cj7ofn6d8d` | simple-table | ds82 | Dimensão: `Cidade`<br>Métrica: `Contatos` (aut), `Participação na seleção` (aut)<br>Classificar: `Novo campo`<br>Classificação nº 1: `Novo campo` |
| `cd-2g1cap6d8d` | kpi-metric | ds82 | Campo principal: `Contatos sem cidade` (aut) |
| `cd-j617se5e8d` | simple-table | ds103 | Dimensão: `Bairro do contato`<br>Métrica: `Contatos` (aut), `Participação na seleção` (aut)<br>Dimensão do período: `weni_created_on (Data)`<br>Classificar: `Novo campo` (aut)<br>Classificação nº 1: `Novo campo` (aut) |
| `cd-uqslmzj68d` | simple-table | FARMA \| LTV por cliente | Métrica: `Nome` (aut), `LTV` (max), `Pedidos` (max), `Ticket médio` (max)<br>Filtro: `LTV \| Clientes com nome`<br>Classificar: `LTV` (max)<br>Classificação nº 1: `LTV` (max) |
| `cd-1qslmzj68d` | dimension-filter | FARMA \| LTV por cliente | Campo "Controle": `Buscar cliente pelo nome` |

### 10. Histórico

[Abrir página](https://datastudio.google.com/reporting/e60ba3bc-fe88-417d-8a39-d8512debf175/page/p_ojuh4gl58d/edit)

| Componente | Tipo | Fonte ou mesclagem | Campos e configuração |
|---|---|---|---|
| `cd-8n323gl58d` | kpi-metric | ds139 | Campo principal: `Faturamento observado` (sum)<br>Dimensão do período: `periodo_inicio` |
| `cd-3o3v25a68d` | kpi-metric | ds139 | Campo principal: `Pedidos válidos` (sum)<br>Dimensão do período: `periodo_inicio` |
| `cd-2blu16a68d` | kpi-metric | ds139 | Campo principal: `Compradores distintos` (max)<br>Dimensão do período: `periodo_inicio` |
| `cd-jpinzab68d` | kpi-metric | ds139 | Campo principal: `Ticket médio histórico` (aut)<br>Dimensão do período: `periodo_inicio` |

### 11. Evolução

[Abrir página](https://datastudio.google.com/reporting/e60ba3bc-fe88-417d-8a39-d8512debf175/page/p_3thm8sb68d/edit)

| Componente | Tipo | Fonte ou mesclagem | Campos e configuração |
|---|---|---|---|
| `cd-fpr47sb68d` | simple-table | ds191 | Dimensão: `competencia`<br>Métrica: `Faturamento observado` (sum), `Compras válidas` (sum), `Compradores distintos` (max), `Ticket médio` (aut)<br>Dimensão do período: `periodo_inicio`<br>Classificar: `competencia`<br>Classificação nº 1: `competencia` |
| `cd-38xkq4b68d` | simple-table | ds190 | Dimensão: `competencia`<br>Métrica: `Faturamento observado` (sum), `Compras válidas` (sum), `Compradores distintos` (max), `Ticket médio` (aut)<br>Dimensão do período: `periodo_inicio`<br>Classificar: `competencia`<br>Classificação nº 1: `competencia` |

### 12. Evolução

[Abrir página](https://datastudio.google.com/reporting/e60ba3bc-fe88-417d-8a39-d8512debf175/page/p_fwapt7b68d/edit)

| Componente | Tipo | Fonte ou mesclagem | Campos e configuração |
|---|---|---|---|
| `cd-8do9s7b68d` | simple-combochart | ds190 | Dimensão (eixo X): `competencia`<br>Métrica (eixo Y): `Faturamento observado` (sum)<br>Dimensão do período: `periodo_inicio`<br>Classificar: `competencia` |
| `cd-deo9s7b68d` | simple-combochart | ds190 | Dimensão (eixo X): `competencia`<br>Métrica (eixo Y): `Compras válidas` (sum)<br>Dimensão do período: `periodo_inicio`<br>Classificar: `competencia` |

### 13. Atualização dos dados

[Abrir página](https://datastudio.google.com/reporting/e60ba3bc-fe88-417d-8a39-d8512debf175/page/p_bdn537427d/edit)

| Componente | Tipo | Fonte ou mesclagem | Campos e configuração |
|---|---|---|---|
| `cd-ik7r37427d` | simple-table | ds17 | Dimensão: `Situação`, `Último processamento registrado`<br>Classificar: `atualizado_em`<br>Classificação nº 1: `atualizado_em` |

### 14. Cobertura histórica

[Abrir página](https://datastudio.google.com/reporting/e60ba3bc-fe88-417d-8a39-d8512debf175/page/p_iekn9hc68d/edit)

| Componente | Tipo | Fonte ou mesclagem | Campos e configuração |
|---|---|---|---|
| `cd-wib78hc68d` | simple-table | ds142 | Dimensão: `extracao`, `motivo`, `calendario`<br>Métrica: `Registros de cobertura` (ct)<br>Dimensão do período: `inicio`<br>Classificar: `extracao`<br>Classificação nº 1: `extracao` |

## Pontos para homologação

- Validar cada alias, campo calculado, agregação, substituição de ID, filtro e condição de junção antes da troca. As mesclagens com zero uso direto fazem parte do relatório.
- Preservar os recortes TOTAL, MES, ANO e SEM EMISSAO do histórico. Comparar totais e evoluções na granularidade de cada fonte.
- Preservar os filtros de anúncios FARMA, a atribuição por primeiro anúncio e a distinção entre receita e investimento. Manter os campos de Receita gerada formatados como moeda BRL (R$).
- Registrar a falha de leitura já observada na Curva ABC no teste de referência para comparar o comportamento após a troca.
- Usar somente metadados e comparações agregadas no roteiro e nos testes compartilhados.
