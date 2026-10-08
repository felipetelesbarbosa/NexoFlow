# FarmaLíder API - contrato usado pelo projeto

## Consulta de CPFs válidos e inválidos

Nas cargas Weni e Analytics, o NexoFlow consulta primeiro os CPFs matematicamente válidos e aguarda essa etapa terminar antes de consultar os inválidos preenchidos. A classificação usa 11 dígitos, rejeição de sequências repetidas e os dois dígitos verificadores. CPFs curtos, dígitos incorretos e valores como `0` ou `00000000000` também são consultados, na segunda etapa. Valores sem dígitos não geram GET. O CPF original permanece no cadastro; a consulta remove a formatação, sem completar, corrigir ou inventar dígitos.

O Analytics deduplica os identificadores por execução e separa os lotes das duas etapas. As cargas Weni em partes seguem essa prioridade dentro da parte selecionada, preservando o manifesto e a revisão humana. Evidência válida de CPF em mensagens entra na primeira etapa quando for o valor efetivo do plano. O incremental mantém o cache recente de CPFs válidos; CPFs inválidos exigem nova seleção por identidade. A carga completa reconsulta os identificadores.

`CPF_CONFIRMADO` identifica um CPF matematicamente válido encontrado na API; `CPF_INVALIDO_ENCONTRADO` identifica um CPF inválido cujo cliente foi confirmado também pelo nome e pelo e-mail ou telefone. Ambos alimentam o total de clientes encontrados, mas somente CPFs matematicamente válidos entram em `cpfs_validos`. HTTP 400 registra `CPF_REJEITADO_API`, sem retry e sem contar como falha 500; HTTP 404 registra `CPF_NAO_ENCONTRADO`; falhas de servidor/rede registram `ERRO_API`, sem autorizar um vínculo de cliente por CPF inválido. Os logs públicos mostram etapas e contagens, sem CPF. O diagnóstico privado de falhas 5xx aceita também identificadores curtos e zeros.

Para CPF inválido, a coincidência do CPF não confirma a pessoa. É obrigatório comparar **nome completo + e-mail**, ou **nome completo + telefone**. O nome é comparado integralmente após normalizar acentos, maiúsculas e espaços; não há aproximação por primeiro nome ou sobrenome. O e-mail precisa estar preenchido e ter formato de e-mail. O telefone compara número completo com DDD, aceitando a formatação e o prefixo brasileiro 55, sem completar dígitos nem inserir o nono dígito. Números nativos da Weni têm precedência sobre campos antigos de telefone/WhatsApp.

A resposta pode conter um cliente, uma lista de clientes ou listas em `cliente`/`clientes`. A seleção e a validação acontecem **por contato Weni**, mesmo quando a resposta GET é compartilhada por CPF. Somente uma correspondência é aceita; dados insuficientes geram `CPF_IDENTIDADE_INSUFICIENTE`, nenhuma correspondência gera `CPF_IDENTIDADE_DIVERGENTE` e múltiplas correspondências geram `CPF_IDENTIDADE_AMBIGUA`. Nesses casos, nenhuma atualização de pedido é autorizada. Um pedido de outro candidato nunca é aproveitado; a capa e os itens continuam sujeitos ao mesmo ID do cliente. Se a API devolver apenas um cadastro diferente, o NexoFlow bloqueia o vínculo: não presume que outros cadastros existam nem inventa uma consulta alternativa.

O cache persistente de vínculos por CPF inválido não é reutilizado, incluindo vínculos antigos que usavam somente o CPF. Falha na identificação também não pode ser contornada por `pedido_id` ou `ultimo_pedido`. A revisão humana guarda a identidade usada na validação; alterações relevantes de nome, e-mail ou telefone/URN após a revisão bloqueiam o apply daquele contato. Snapshots antigos de pedidos com CPF inválido exigem novo dry-run.

Pedidos antigos com CPF inválido permanecem preservados nas tabelas de origem, mas não entram nas vendas, na atribuição de anúncios nem em `BI_Pedidos` até serem revalidados pela nova regra. A origem de um novo pedido validado com CPF inválido recebe o marcador técnico `_IDENTIDADE_VALIDADA`, usado para distinguir esses registros. Após reinstalar, execute **carga completa da Weni, com revisão humana, e depois carga completa do Analytics** para revalidar a base e atualizar os indicadores.

Para aproveitar um pedido, o CPF retornado precisa corresponder ao identificador consultado, o cliente deve ter ID positivo e o pedido deve pertencer ao mesmo cliente. CPF numérico no JSON pode perder zeros à esquerda: somente essa representação numérica equivalente é aceita, sem mudar a classificação nem o CPF na Weni. A consulta não comprova emissão oficial do CPF ou titularidade da pessoa; identificadores genéricos como zero exigem atenção na revisão humana. A extração de mensagens e a gravação de um novo CPF na Weni continuam exigindo validade matemática e contexto explícito.

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

Se o GET por CPF não puder ser usado, a recuperação segue a ordem `pedido_id` da Weni e, por último, o ID extraído de `ultimo_pedido`. Esses campos servem apenas como **localizadores**. O conteúdo oficial do pedido ainda precisa vir de `GET /api/Delivery/pedido/{codigo}`.

## Mapeamento para Weni

| Campo Weni | Campo API |
|---|---|
| `pedido_id` | `capa.id` / `ultimoPedido.id` |
| `pedido_produtos` | `itens[].descricao` |
| `pedido_quantidade_itens` | `itens[].quantidade` |
| `pedido_valor_produtos` | `itens[].valor` |
| `pedido_valor` | soma de `itens[].total` |
| `pedido_data` | `emissao` |
| `pedido_status` | status efetivo de `status`; cancelamento explícito ou pagamento 0 força 3 |
| `pedido_forma_pagamento` | `formaPagamento`; pagamento 0 grava o texto `Cancelado` |

Produtos, quantidades e valores unitários são serializados como listas separadas por vírgula, preservando a mesma ordem posicional.

`pedido_valor` representa a soma dos totais dos itens. O frete continua separado e não é somado ao campo Weni.

No Google Sheets o pedido mantém:
- `valor_total_compra`: total dos produtos;
- `farmalider_frete`: frete retornado pela API;
- `valor_total_faturamento`: produtos + frete.

Assim, o Looker Studio consegue exibir produto e frete separadamente e, ao mesmo tempo, usar o total faturado correto.

## Status do pedido

De-para usado pela integração:

| Código | Identificador oficial | Rótulo |
|---:|---|---|
| -2 | `EmAberto` | Em aberto |
| -1 | `PendenteDePagamento` | Pendente de pagamento |
| 0 | `EmProcessamento` | Em processamento |
| 4 | `ProntoParaRota` | Pronto para rota |
| 1 | `EmTransito` | Em trânsito |
| 2 | `Concluido` | Concluído |
| 3 | `Cancelado` | Cancelado |

A Weni armazena o código efetivo em `pedido_status`. O normalizador aceita os códigos -2 a 4 e os nomes oficiais `EmAberto`, `PendenteDePagamento`, `EmProcessamento`, `ProntoParaRota`, `EmTransito`, `Concluido` e `Cancelado`. Cancelamento explícito ou `formaPagamento=0` ou `_` força o código 3, Cancelado. O helper `effective_order_status_code(order)` aplica essa regra para Weni/BI; o Analytics deriva o nome amigável. `Pedidos_FarmaLider` preserva o status bruto retornado pela API em `farmalider_status_pedido`, inclusive quando ele difere do status efetivo.

Pedidos validados pela API com status efetivo 4 (Pronto para rota), 1 (Em trânsito) ou 2 (Concluído), sem cancelamento, entram nas métricas de venda e atualizam `ultima_compra`. Os estados -2, -1, 0, 1 e 4 permanecem em rechecagem até Concluído ou Cancelado. Os estados -2, -1 e 0 não contam como venda; 4 e 1 já contam. O estado 3 e o pagamento 0 ficam fora das vendas e encerram a rechecagem.

## Forma de pagamento

De-para confirmado para a integração:

| Código | Nome oficial do enum | Forma |
|---:|---|---|
| 0 | `_` | Cancelado |
| 1 | `Dinheiro` | Dinheiro |
| 2 | `Debito` | Débito |
| 3 | `Credito` | Crédito |
| 4 | `Ticket` | Ticket |
| 5 | `PixPorLinkDePagamento` | Pix por Link de Pagamento |
| 6 | `PixNoPOS` | Pix no POS |

A Weni armazena o código normalizado em `pedido_forma_pagamento`, exceto `formaPagamento=0` ou `_`, que grava o texto literal `Cancelado` e força `pedido_status=3`. O normalizador aceita os nomes oficiais do enum acima, inclusive `_` como equivalente a 0. `Pedidos_FarmaLider` preserva o valor bruto em `farmalider_forma_pagamento`. O Analytics mantém também `farmalider_forma_pagamento_nome` e disponibiliza a descrição amigável na camada BI.

Além dos nomes oficiais, o normalizador de `formaPagamento` aceita códigos Int32 não negativos. Códigos numéricos válidos sem de-para a partir de 7 continuam sendo preservados como Int32 na Weni e apresentados no Google Sheets/BI como `Não identificado (código X)`. Textos fora dos nomes de enum aceitos, valores fracionários, negativos e números fora de Int32 continuam inválidos; o literal operacional `Cancelado` na Weni é aceito como resultado da regra de pagamento 0. A leitura e a auditoria ignoram diferenças entre maiúsculas e minúsculas e continuam aceitando o valor legado `CANCELADO`. Valores ausentes ou inválidos mantêm a descrição vazia.

O nome antigo `PendentePagamento` permanece aceito como alias de `PendenteDePagamento` para leitura de registros existentes. O helper `farmalider_payment_method_name` retorna somente os rótulos documentados. O helper de apresentação `farmalider_payment_method_display` usa esses rótulos e acrescenta a descrição explícita para códigos válidos desconhecidos, sem modificar o código recebido.

No NexoFlow Weni, cada código sem de-para gera `INFO` uma vez por execução, com totais por código no resumo. A contagem usa o código retornado pela API para cada contato com pedido validado, inclusive quando não há alteração; não representa pedidos únicos. A falta de de-para não bloqueia a preparação, a auditoria ou a gravação dos demais campos válidos.

## Listas de itens na Weni

Os campos `pedido_produtos`, `pedido_quantidade_itens` e `pedido_valor_produtos` mantêm a mesma ordem dos itens e usam listas CSV separadas por vírgula. Nomes contendo vírgula são delimitados por aspas; aspas internas são duplicadas. Exemplo de dois produtos:

```text
pedido_produtos: "Produto 0,5 MG", Produto B
pedido_quantidade_itens: 2, 1
pedido_valor_produtos: 10, 5.5
pedido_valor: 25.5
```

A vírgula em `0,5 MG` faz parte do nome. Weni e Analytics usam o mesmo parser CSV para não transformá-la em outro item. Listas simples anteriores continuam compatíveis. Snapshots legados ambíguos não são reconstruídos por adivinhação; uma nova consulta validada à API pode regravá-los no formato correto. A auditoria mantém o bloqueio de desalinhamento real, inclusive quando apenas uma das listas muda.

## Data

Timestamps sem offset retornados pela API são interpretados em
**America/Belem (UTC-3)**. Esse também é o fuso dos horários operacionais e
dos logs do NexoFlow.

Exemplo:

```text
API:  2026-06-05T15:45:27.497
Weni: 05/06/26 15:45:27
```

Internamente, o NexoFlow preserva data/hora canônica para agregações e filtros.

## Recuperação por campos Weni

Quando o endpoint por CPF estiver temporariamente indisponível, o NexoFlow tenta:

```text
1. pedido_id
2. ultimo_pedido -> extrair somente o ID
3. GET pedido/{id}
```

`ultimo_pedido` pode ser alimentado por outra integração e por isso é útil para recuperar um pedido ocorrido enquanto o NexoFlow estava fora do ar. Ele nunca substitui a FarmaLíder API como fonte dos detalhes. Se `GET pedido/{id}` também estiver indisponível, os campos `pedido_*` não são sobrescritos.

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
- até quatro tentativas para erros transitórios;
- cooldown global após 429, 5xx e falhas de conexão;
- recuperação serial e retorno gradual da concorrência;
- redução gradual do intervalo quando a API se recupera;
- circuit breaker por rota e por taxa de erros do lote;
- telemetria de latência;
- aviso de requisição lenta acima do limite configurado.

Os valores operacionais ficam em `config.py`.

### Recuperação após falha

Uma resposta `5xx` ativa uma pausa compartilhada por todas as threads:
**5 segundos após a primeira tentativa, 10 após a segunda e 20 após a
terceira**. Se a quarta e última tentativa também falhar, a pausa de
20 segundos continua valendo para as próximas consultas. O `Retry-After`
da API é respeitado quando pede uma espera maior.

Ao mesmo tempo, novas requisições passam a entrar **uma por vez**. Requisições
que já estavam em andamento podem concluir; a ativação do modo serial não
cancela uma consulta que já chegou ao servidor. O limite sobe de **1 para 2
após 6 respostas saudáveis consecutivas** e de **2 para 4 após outras 12**.
Somente respostas de requisições iniciadas na geração atual de recuperação
contam para liberar a concorrência: respostas antigas em andamento não
desfazem a proteção. Uma nova falha reinicia essa contagem.

Respostas `200` com JSON válido no formato esperado e respostas `404`
representam uma rota que respondeu corretamente. `404` não recebe retry.
Durante a recuperação de `5xx`, o intervalo global entre inícios aumenta
até, no máximo, **1 segundo**. A cada 6 respostas saudáveis, ele é reduzido
pela metade até voltar ao valor normal. A pausa global e o tempo de resposta
do servidor são separados desse intervalo.

O circuito avalia cada rota separadamente. Ele abre após **12 respostas
`5xx` envolvendo pelo menos 3 referências de consulta distintas**, sem uma
resposta válida `200` ou `404` entre elas. O Analytics interrompe a carga antes
de gravar contatos e pedidos no Google Sheets. O limite de erros por lote
continua sendo uma proteção adicional, avaliada após sublotes completos.

### Diagnóstico de HTTP 500

O Swagger 3.0.4 fornecido para esta integração descreve `404` como *não
encontrado* e `500` como *erro interno*, mas não especifica o corpo nem a causa
de uma resposta `500`. Seu schema de `200` para `cliente/cpf` também não inclui
o envelope `cliente`, `ultimoPedido` e `itens` observado nas respostas reais.
Por isso, um `500` não é interpretado como CPF inexistente.

Cada consulta recebe uma referência HMAC, produzida com uma chave aleatória
da execução, para reunir os retries sem registrar CPF ou token. O log
classifica o corpo `5xx` por tipo, tamanho, categoria conhecida e assinatura
HMAC. Texto livre da resposta não é copiado para o log, pois pode conter
dados pessoais. Após falha definitiva, o Analytics registra referências HMAC
dos contatos Weni afetados, sem publicar seus UUIDs. Essas referências mudam
entre execuções.

O log também informa latência e concorrência no início da requisição, para
distinguir uma falha que começou antes da recuperação de outra ocorrida em
modo serial. Um `X-Request-ID` ou `X-Correlation-ID` enviado pelo servidor só
é registrado se corresponder a um UUID estrito; valores arbitrários são
descartados. Quando disponível, esse identificador permite à equipe
FarmaLíder localizar a requisição nos próprios logs.

Se um CPF já havia sido confirmado e permanece igual, uma falha transitória
preserva apenas o ID, nome e horário da **última validação bem-sucedida** na
Base_Contatos. O status atual fica `ERRO_API`: uma confirmação ou um `404`
antigo não é apresentado como resultado da consulta atual. O Controle registra
separadamente quantos detalhes anteriores foram mantidos. A etapa de pedidos
não repete o GET por CPF que já terminou em `404` ou erro nesta mesma execução;
um pedido identificado na Weni ainda pode ser confirmado pelo endpoint por
código. A taxa de falhas é avaliada após sublotes completos de até 100 CPFs,
para que respostas `500` mais rápidas não distorçam a amostra. Se a taxa
atingir o limite configurado, a carga é interrompida antes de gravar contatos
e pedidos no Google Sheets.

Se alguns CPFs ou consultas de pedido falharem abaixo desse limite, a
execução é marcada `parcial` nas abas de status e controle e termina com
código de saída `3`. O marco de sincronização incremental anterior permanece
inalterado, de modo que esses contatos voltem a ser considerados na próxima
execução. A nova tentativa pode repetir parte da consulta à Weni e da API
FarmaLíder, pois o cache de clientes não armazena o payload do pedido.

Essas medidas reduzem a carga e preservam informações. Elas podem reduzir
erros causados por sobrecarga, mas o Swagger e os logs de status não comprovam
a causa interna. Se a mesma referência por CPF continuar falhando em modo
serial enquanto outras consultas retornam `200` ou `404` no mesmo intervalo,
isso sugere uma inconsistência específica no cadastro ou pedido; não prova
qual campo ou relacionamento falhou. Uma melhoria após reduzir a
concorrência sugere sensibilidade à carga, sem excluir outras causas.

Para confirmar a causa, a equipe FarmaLíder precisa correlacionar horário em
**America/Belem (UTC-3)**, rota, identificador de requisição quando disponível
e logs do servidor. Não é necessário compartilhar CPF ou tokens nos logs de
diagnóstico. Um schema de erro documentado tornaria a análise mais precisa.

## Melhoria futura: histórico de pedidos por CPF

A API usada permite localizar cliente por CPF, obter sua referência de último pedido quando disponível e consultar pedido por código, mas não lista o histórico de pedidos de um cliente. Como evolução recomendada da FarmaLíder API, criar uma rota de consulta por CPF, preferencialmente paginada e com filtros de período/status, por exemplo:

```text
GET /api/Delivery/pedidos/cpf/{cpf}
```

Filtros desejáveis: `inicio`, `fim`, `status`, `pagina` e `tamanhoPagina`. Essa rota é uma proposta de evolução, não uma integração atualmente implementada.
<!-- NexoFlow 1.0 -->
