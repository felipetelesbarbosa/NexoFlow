# NexoFlow 1.0 — Pedidos na Weni

As regras compartilhadas de pedidos atendem **FarmaLíder e Pets Líder**, com organizações e planilhas separadas. Farma usa `ultima_compra`; Pets usa `compra_recente`. A referência dos eventos é `pedido_data`: D+25 na Farma e D+30 no Pets. Veja [segmentos e fluxos](SEGMENTOS%20E%20FLUXOS.md).

## Consulta de CPFs válidos e inválidos

Nas cargas Weni e Analytics, o NexoFlow consulta primeiro os CPFs matematicamente válidos e aguarda essa etapa terminar antes de consultar os inválidos preenchidos. Antes de classificar um CPF curto, o NexoFlow testa a reposição de zeros à esquerda até 11 dígitos; aceita essa forma somente quando os dois dígitos verificadores são válidos. A classificação rejeita sequências repetidas e dígitos incorretos. Identificadores preenchidos, não zerados e com formato utilizável que continuam inválidos após essa verificação são consultados na segunda etapa. CPF ausente, inteiramente zerado ou malformado é pendência cadastral e não gera GET por CPF. O CPF original permanece no cadastro; a consulta remove a formatação e usa zeros à esquerda somente quando a validação matemática comprova a forma de 11 dígitos. Não troca dígitos existentes.

O Analytics deduplica os identificadores por execução e separa os lotes das duas etapas. As cargas Weni em partes seguem essa prioridade dentro da parte selecionada, preservando o manifesto e a revisão humana. Evidência válida de CPF em mensagens entra na primeira etapa quando for o valor efetivo do plano. Toda nova carga reconsulta os identificadores no escopo selecionado; respostas duplicadas só são compartilhadas dentro da mesma execução. CPFs válidos dispensam comparação de nome, telefone e e-mail. CPFs inválidos exigem nome ou telefone correspondente.

`CPF_CONFIRMADO` identifica um CPF matematicamente válido encontrado na API; `CPF_INVALIDO_ENCONTRADO` identifica um CPF inválido cujo cliente foi confirmado também pelo primeiro nome ou pelo número local do telefone. Ambos alimentam o total de clientes encontrados, mas somente CPFs matematicamente válidos entram em `cpfs_validos`. HTTP 400 registra `CPF_REJEITADO_API`, sem retry e sem contar como falha 500; HTTP 404 registra `CPF_NAO_ENCONTRADO`; falhas de servidor/rede registram `ERRO_API`, sem autorizar um vínculo de cliente por CPF inválido. Os logs públicos mostram etapas e contagens, sem CPF. O diagnóstico privado de falhas 5xx aceita identificadores curtos consultáveis, sem enviar zeros à API.

Para CPF inválido, a coincidência do CPF não confirma a pessoa. É obrigatório comparar **primeiro nome correspondente ou número local do telefone correspondente**. A comparação de nome usa somente o primeiro nome, desconsiderando acentos, maiúsculas e símbolos; sobrenomes não precisam coincidir. O e-mail não é obrigatório para essa validação. O telefone compara apenas o número local, ignorando o prefixo brasileiro +55 e o DDD, sem completar dígitos nem inserir o nono dígito. Números nativos da Weni têm precedência sobre campos antigos de telefone/WhatsApp.

A resposta pode conter um cliente, uma lista de clientes ou listas em `cliente`/`clientes`. A seleção e a validação acontecem **por contato Weni**, mesmo quando a resposta GET é compartilhada por CPF. Somente uma correspondência é aceita; dados insuficientes geram `CPF_IDENTIDADE_INSUFICIENTE`, nenhuma correspondência gera `CPF_IDENTIDADE_DIVERGENTE` e múltiplas correspondências geram `CPF_IDENTIDADE_AMBIGUA`. Nesses casos, nenhuma atualização de pedido é autorizada. Um pedido de outro candidato nunca é aproveitado; a capa e os itens continuam sujeitos ao mesmo ID do cliente. Se a API devolver apenas um cadastro diferente, o NexoFlow bloqueia o vínculo: não presume que outros cadastros existam nem inventa uma consulta alternativa.

O cache persistente de vínculos por CPF inválido não é reutilizado, incluindo vínculos antigos que usavam somente o CPF. Falha na identificação também não pode ser contornada por `pedido_id` ou `ultimo_pedido`. A revisão humana guarda a identidade usada na validação; alterações relevantes de nome, e-mail ou telefone/URN após a revisão bloqueiam o apply daquele contato. Snapshots antigos de pedidos com CPF inválido exigem novo dry-run.

Pedidos antigos com CPF inválido permanecem preservados nas tabelas de origem, mas não entram nas vendas, na atribuição de anúncios nem em `BI_Pedidos` até serem revalidados pela nova regra. A origem de um novo pedido validado com CPF inválido recebe o marcador técnico `_IDENTIDADE_VALIDADA`, usado para distinguir esses registros. Após reinstalar, execute **carga completa da Weni, com revisão humana, e depois carga completa do Analytics** para revalidar a base e atualizar os indicadores.

Para aproveitar um pedido, o CPF retornado precisa corresponder ao identificador consultado, o cliente deve ter ID positivo e o pedido deve pertencer ao mesmo cliente. CPF numérico no JSON pode perder zeros à esquerda: somente essa representação numérica equivalente é aceita, sem mudar a classificação nem o CPF na Weni. A consulta não comprova emissão oficial do CPF ou titularidade da pessoa; identificadores genéricos como zero permanecem como pendência cadastral, sem autorizar vínculo de cliente ou pedido. A extração de mensagens e a gravação de um novo CPF na Weni continuam exigindo validade matemática e contexto explícito.

Os campos de pedido da Weni são o snapshot operacional do último pedido obtido pela FarmaLíder API. Eles não são mais a fonte prioritária da resolução quando a API está disponível.

## Fluxo

```text
CPF
-> GET cliente/cpf/{cpf}
-> ultimoPedido + itens
-> GET pedido/{pedido_id}
-> plano auditado
-> campos pedido_* na Weni
```

## Campos

| Campo | Conteúdo |
|---|---|
| `pedido_id` | ID oficial do pedido |
| `pedido_produtos` | `descricao` dos itens, separados por vírgula |
| `pedido_quantidade_itens` | quantidades posicionais, separadas por vírgula |
| `pedido_valor_produtos` | valores unitários posicionais, separados por vírgula |
| `pedido_valor` | soma de `itens[].total` |
| `pedido_data` | `DD/MM/YY HH:MM:SS` |
| `pedido_status` | status efetivo de -2 a 4 |
| `pedido_forma_pagamento` | código Int32 não negativo normalizado; pagamento 0 grava `Cancelado` |

Pagamento 5 é **Pix por Link de Pagamento** e pagamento 6 é **Pix no POS**. Pagamento 0 grava o texto literal `Cancelado` em `pedido_forma_pagamento` e força o status efetivo 3, Cancelado. `Pedidos_FarmaLider` mantém os valores brutos de pagamento e status da API; Weni e `BI_Pedidos` usam o status efetivo.

Pagamentos válidos sem de-para a partir de 7 mantêm seu código na Weni e recebem a descrição `Não identificado (código X)` no Google Sheets/BI. Pagamento ausente ou inválido mantém a descrição vazia.

Pedidos validados pela API com status efetivo -2 (Em aberto), -1 (Pendente de pagamento), 0 (Em processamento), 4 (Pronto para rota), 1 (Em trânsito) ou 2 (Concluído) contam como venda e atualizam `ultima_compra` (Farma) ou `compra_recente` (Pets). Entre os estados documentados, somente o status efetivo 3 (Cancelado) exclui a venda; cancelamento explícito ou pagamento 0 força esse status. Os estados -2, -1, 0, 4 e 1 permanecem em rechecagem até Concluído ou Cancelado. Cada nova carga reconsulta os pedidos atuais no seu escopo, mesmo sem modificação do contato na Weni. Estados desconhecidos continuam pendentes de validação.

Exemplo:

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

`ultimo_pedido` continua aceito apenas para compatibilidade/fallback offline. O NexoFlow Weni não depende dele para escolher o pedido quando a FarmaLíder API está disponível.

A escrita continua protegida por dry-run, auditoria, confirmação e verificação de conflito por contato.

Os logs de preparação e auditoria precedem as gravações. O total de contatos com pedido validado pela API inclui os que não precisam de alteração. Cada código de pagamento sem de-para aparece em `INFO` uma vez por execução, com totais por código no resumo, sem bloquear a atualização.

Veja [PEDIDOS.md](PEDIDOS.md) para regras completas.

<!-- NexoFlow 1.0 -->
