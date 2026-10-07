# Looker Studio — camada BI do NexoFlow Analytics

Desde o NexoFlow 1.0, o Google Sheets continua sendo a camada de dados e o Looker Studio fica responsável principalmente pela visualização. Para evitar cálculos pesados e regras espalhadas no relatório, o NexoFlow Analytics mantém sete abas específicas para BI.

## Fontes recomendadas

### BI_Resumo_Diario

Uma linha por dia. Se o Analytics rodar mais de uma vez no mesmo dia, a linha daquele dia é atualizada em vez de duplicada.

Principais campos:

- data
- contatos_total
- novos_contatos
- contatos_com_cpf
- cpfs_validos
- clientes_farmalider
- whatsapp / instagram / facebook / outro
- opt_in_lgpd / opt_out_lgpd
- maiores_18 / menores_18
- contatos_ads
- clientes_compradores_total
- pedidos_total
- faturamento_produtos_total
- faturamento_frete_total
- faturamento_total
- pedidos_dia
- faturamento_produtos_dia
- faturamento_frete_dia
- faturamento_total_dia
- faturamento_dia
- ticket_medio_dia

Use esta aba para a página **Visão Geral** e para séries de evolução diária da base.

### BI_Canais

Snapshot diário por canal de contato:

- data
- canal
- contatos
- contatos_com_cpf
- clientes_farmalider
- contatos_ads
- opt_in_lgpd

Use para participação por WhatsApp, Instagram, Facebook e outros canais.

### BI_Conversao

Funil diário pronto para o Looker Studio:

1. Contatos
2. CPF válido
3. Cliente FarmaLíder
4. Cliente comprador

Campos adicionais calculam a taxa sobre a base e a taxa em relação à etapa anterior.

### BI_Vendas

Série diária de vendas:

- data
- pedidos
- pedidos_confirmados_api
- clientes_compradores
- unidades_vendidas
- faturamento_produtos
- faturamento_frete
- faturamento_total
- faturamento
- faturamento_confirmado_api
- ticket_medio
- taxa_confirmacao_pct

Mesmo antes da primeira venda, o NexoFlow mantém uma linha zero para o dia atual, permitindo que o Looker reconheça o schema.

### BI_Ads

Consolidação atual por modelo de atribuição de primeiro/último anúncio:

- tipo_atribuicao
- origem
- tipo_campanha
- canal_destino
- anuncio_id
- anuncio_titulo
- contatos
- clientes_farmalider
- compradores
- pedidos
- faturamento

Enquanto ainda não houver conversas atribuídas a anúncios, a aba contém uma linha zero/placeholder para manter o schema disponível no Looker Studio.

### BI_Pedidos

Uma linha por pedido, preparada para páginas de **Pedidos**, **Compradores do dia** e detalhamento de vendas.

Campos principais:

- pedido_id
- pedido_data, no formato DD/MM/YY HH:MM:SS
- data
- hora
- cliente
- cpf
- pedido_produtos
- pedido_quantidade_itens
- pedido_valor_produtos
- pedido_valor, total dos produtos
- pedido_frete
- pedido_faturamento_total, produtos + frete
- pedido_status
- pedido_status_nome
- pedido_forma_pagamento
- pedido_forma_pagamento_nome
- canal
- primeiro_anuncio_origem
- ultimo_anuncio_origem

As listas de produto, quantidade e valor unitário mantêm a mesma ordem posicional. Para cálculos por item, prefira `Itens_Pedidos_FarmaLider`; para exibição de um pedido completo em uma linha, use `BI_Pedidos`.

Para faturamento, use preferencialmente os campos explícitos:
- **Produtos**: `pedido_valor` / `faturamento_produtos`;
- **Frete**: `pedido_frete` / `faturamento_frete`;
- **Total cobrado**: `pedido_faturamento_total` / `faturamento_total`.

O campo legado `faturamento` permanece como alias do faturamento total para não quebrar componentes existentes. O ticket médio também usa o total cobrado, incluindo frete.

O dashboard deve mostrar preferencialmente os nomes amigáveis, como **Cancelado** e **Débito**, mantendo os códigos disponíveis para auditoria e filtros técnicos.

Para pagamento, o dashboard usa: Dinheiro, Débito, Crédito, Ticket, Pix por Link de Pagamento, PIX no POS e CANCELADO. Quando a API retorna formaPagamento 0 (ou `_`), o BI mostra forma de pagamento **CANCELADO** e status **Cancelado**, e o pedido fica fora dos indicadores de venda. Status **Pendente pagamento (-1)** também não entra em faturamento enquanto não for pago.

### BI_Status

Uma linha com a saúde da última execução do Analytics:

- versão
- status
- modo_execucao
- duracao_segundos
- Weni recebidos/processados
- consultas e retries FarmaLíder
- leituras/escritas Google Sheets
- contatos inseridos/atualizados/sem mudança
- pedidos confirmados pela API

Use apenas em uma página técnica opcional.

## Base_Contatos

Desde o NexoFlow 1.0, a Base_Contatos preserva todos os contatos retornados pela Weni, inclusive os que ainda não possuem CPF, pedido ou anúncio. Também inclui `idade`, `maior_de_18_anos` e `opt_in_lgpd`.

Ela pode ser usada para drill-down e análises detalhadas, mas não é a fonte principal recomendada para os cards e gráficos executivos.

## Primeira carga do NexoFlow 1.0

Execute uma carga completa do Analytics uma única vez:

```powershell
cd C:\NexoFlow
.\executar_carga_completa.bat
```

Isso cria/migra as sete abas BI, incluindo `BI_Pedidos`, completa a Base_Contatos com os contatos historicamente excluídos e inicializa o dashboard. Depois, volte ao fluxo incremental normal com `executar_manual.bat` ou `nexo analytics`.
