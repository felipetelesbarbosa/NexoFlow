# Looker Studio — camada BI do NexoFlow Analytics

Clientes encontrados podem incluir CPFs inválidos. Portanto, “CPF válido” e “Cliente FarmaLíder” não são etapas aninhadas de um funil: apresente-os como indicadores independentes, mantendo explícita a validade matemática.

## Consulta de CPFs válidos e inválidos

Nas cargas Weni e Analytics, o NexoFlow consulta primeiro os CPFs matematicamente válidos e aguarda essa etapa terminar antes de consultar os inválidos preenchidos. A classificação usa 11 dígitos, rejeição de sequências repetidas e os dois dígitos verificadores. CPFs curtos, dígitos incorretos e valores como `0` ou `00000000000` também são consultados, na segunda etapa. Valores sem dígitos não geram GET. O CPF original permanece no cadastro; a consulta remove a formatação, sem completar, corrigir ou inventar dígitos.

O Analytics deduplica os identificadores por execução e separa os lotes das duas etapas. As cargas Weni em partes seguem essa prioridade dentro da parte selecionada, preservando o manifesto e a revisão humana. Evidência válida de CPF em mensagens entra na primeira etapa quando for o valor efetivo do plano. O incremental mantém o cache recente de CPFs válidos; CPFs inválidos exigem nova seleção por identidade. A carga completa reconsulta os identificadores.

`CPF_CONFIRMADO` identifica um CPF matematicamente válido encontrado na API; `CPF_INVALIDO_ENCONTRADO` identifica um CPF inválido cujo cliente foi confirmado também pelo nome e pelo e-mail ou telefone. Ambos alimentam o total de clientes encontrados, mas somente CPFs matematicamente válidos entram em `cpfs_validos`. HTTP 400 registra `CPF_REJEITADO_API`, sem retry e sem contar como falha 500; HTTP 404 registra `CPF_NAO_ENCONTRADO`; falhas de servidor/rede registram `ERRO_API`, sem autorizar um vínculo de cliente por CPF inválido. Os logs públicos mostram etapas e contagens, sem CPF. O diagnóstico privado de falhas 5xx aceita também identificadores curtos e zeros.

Para CPF inválido, a coincidência do CPF não confirma a pessoa. É obrigatório comparar **nome completo + e-mail**, ou **nome completo + telefone**. O nome é comparado integralmente após normalizar acentos, maiúsculas e espaços; não há aproximação por primeiro nome ou sobrenome. O e-mail precisa estar preenchido e ter formato de e-mail. O telefone compara número completo com DDD, aceitando a formatação e o prefixo brasileiro 55, sem completar dígitos nem inserir o nono dígito. Números nativos da Weni têm precedência sobre campos antigos de telefone/WhatsApp.

A resposta pode conter um cliente, uma lista de clientes ou listas em `cliente`/`clientes`. A seleção e a validação acontecem **por contato Weni**, mesmo quando a resposta GET é compartilhada por CPF. Somente uma correspondência é aceita; dados insuficientes geram `CPF_IDENTIDADE_INSUFICIENTE`, nenhuma correspondência gera `CPF_IDENTIDADE_DIVERGENTE` e múltiplas correspondências geram `CPF_IDENTIDADE_AMBIGUA`. Nesses casos, nenhuma atualização de pedido é autorizada. Um pedido de outro candidato nunca é aproveitado; a capa e os itens continuam sujeitos ao mesmo ID do cliente. Se a API devolver apenas um cadastro diferente, o NexoFlow bloqueia o vínculo: não presume que outros cadastros existam nem inventa uma consulta alternativa.

O cache persistente de vínculos por CPF inválido não é reutilizado, incluindo vínculos antigos que usavam somente o CPF. Falha na identificação também não pode ser contornada por `pedido_id` ou `ultimo_pedido`. A revisão humana guarda a identidade usada na validação; alterações relevantes de nome, e-mail ou telefone/URN após a revisão bloqueiam o apply daquele contato. Snapshots antigos de pedidos com CPF inválido exigem novo dry-run.

Pedidos antigos com CPF inválido permanecem preservados nas tabelas de origem, mas não entram nas vendas, na atribuição de anúncios nem em `BI_Pedidos` até serem revalidados pela nova regra. A origem de um novo pedido validado com CPF inválido recebe o marcador técnico `_IDENTIDADE_VALIDADA`, usado para distinguir esses registros. Após reinstalar, execute **carga completa da Weni, com revisão humana, e depois carga completa do Analytics** para revalidar a base e atualizar os indicadores.

Para aproveitar um pedido, o CPF retornado precisa corresponder ao identificador consultado, o cliente deve ter ID positivo e o pedido deve pertencer ao mesmo cliente. CPF numérico no JSON pode perder zeros à esquerda: somente essa representação numérica equivalente é aceita, sem mudar a classificação nem o CPF na Weni. A consulta não comprova emissão oficial do CPF ou titularidade da pessoa; identificadores genéricos como zero exigem atenção na revisão humana. A extração de mensagens e a gravação de um novo CPF na Weni continuam exigindo validade matemática e contexto explícito.

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

Os indicadores de compradores, pedidos e faturamento consideram pedidos validados pela API com status efetivo 4 (Pronto para rota), 1 (Em trânsito) ou 2 (Concluído), sem cancelamento. Pagamento 0 força Cancelado e fica fora das vendas; -2 (Em aberto), -1 (Pendente de pagamento) e 0 (Em processamento) também ficam fora enquanto permanecerem nesses estados.

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

Pagamento 5 aparece como **Pix por Link de Pagamento** e pagamento 6 como **Pix no POS**. Os normalizadores aceitam também nomes oficiais como `PixPorLinkDePagamento` e `PixNoPOS`. Pagamento 0 ou `_` representa **Cancelado**: Weni grava esse texto literal em `pedido_forma_pagamento` e o status efetivo 3, Cancelado. `BI_Pedidos` também usa o status efetivo 3; `Pedidos_FarmaLider` preserva os valores brutos de status e pagamento retornados pela API.

Para pagamento Int32 não negativo sem de-para a partir de 7, `pedido_forma_pagamento_nome` exibe `Não identificado (código X)` e o código é preservado. Pagamentos ausentes ou inválidos mantêm a descrição vazia.

`BI_Pedidos` mantém os pedidos para consulta, inclusive pendentes e cancelados. Páginas de compradores e vendas devem filtrar status efetivo 4 (Pronto para rota), 1 (Em trânsito) e 2 (Concluído); os estados -2, Em aberto, -1, Pendente de pagamento, 0, Em processamento, 4, Pronto para rota, e 1, Em trânsito, permanecem em rechecagem; -2, -1 e 0 ficam fora das vendas, e 4 e 1 já são vendas realizadas. Nomes oficiais do enum de status, como `PendenteDePagamento` e `Concluido`, são normalizados para os códigos -2 a 4.

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

## Localização e idade dos clientes

O Analytics envia `cidade`, `estado`, `cep`, `bairro` e `idade` dos campos personalizados da Weni para `Base_Contatos` e para a camada `BI_Pedidos`. O histórico de alterações também preserva a localização. Os pedidos recebem o perfil do contato vinculado pelo `contact_uuid`, sem criar novas linhas por produto nem multiplicar os valores da venda.

| Campo | Campo Weni | Tipo no Looker Studio |
|---|---|---|
| `cidade` | `@fields.cidade` | Texto; cidade para mapas quando a localização puder ser identificada |
| `estado` | `@fields.estado` | Texto; UF para contextualizar a cidade brasileira |
| `cep` | `@fields.cep` | Texto, preservando zeros iniciais e a formatação recebida |
| `bairro` | `@fields.bairro` | Texto |
| `idade` | `@fields.idade` | Número; dimensão, sem somar idades |

A localização e a idade correspondem ao **cadastro atual na Weni**, inclusive para pedidos antigos. Não representam necessariamente endereço de entrega ou idade na data da compra. Valores ausentes continuam vazios; idade inválida na camada BI também fica vazia, sem virar zero. A idade zero informada é preservada. A data real do pedido continua em `pedido_data` e `data`, separada de `atualizado_em`.

Depois de instalar a distribuição atualizada, execute uma **carga completa do Analytics** para preencher esses campos nos contatos já existentes. A carga Analytics por planilhas também exporta os campos dos contatos selecionados e relidos na Weni, após revisão humana. As colunas novas são acrescentadas sem deslocar os cabeçalhos existentes.

No Looker Studio, atualize os campos das fontes `Base_Contatos` e `BI_Pedidos` uma vez após a migração. Use cidade, bairro, CEP e faixa etária como dimensões e filtros; para pedidos e faturamento por região, use `BI_Pedidos`, filtre vendas nos status 4, 1 e 2 e utilize `data` como dimensão de período. Não some snapshots da base ou idades. Para contagem de clientes, use pessoas únicas no contexto da fonte, não a quantidade de linhas de pedidos. O relatório não recebe automaticamente componentes novos apenas porque as colunas foram adicionadas.
