# NexoFlow 1.0 — Weni

## Objetivo

A rotina **NexoFlow Weni** elimina o processo manual de exportar mensagens/contatos da Weni, tratar planilhas e importar uma nova planilha. Ela consulta a API da Weni, monta um plano de alterações, audita obrigatoriamente esse plano e só então permite gravar os campos.

## Execução recomendada

### Uso diário

Abra o atalho:

```text
NexoFlow Weni
```

O executável chama `atualizar_weni.bat` e executa:

```text
1. check-up.bat
2. testar_update_weni.bat
3. dry-run incremental
4. auditoria obrigatória do plano
5. confirmação manual: ATUALIZAR
6. apply incremental
```

O apply faz uma nova leitura e uma nova auditoria antes de qualquer POST.

### Primeira carga / reprocessamento integral

Use:

```text
atualizar_weni_carga_completa.bat
```

A rotina faz dry-run completo, gera um relatório detalhado para revisão humana e exige a confirmação literal `CARGA COMPLETA REVISADA` antes do apply. Use para primeira implantação, backfill ou revalidação integral.

Depois de atualizar ou reinstalar o NexoFlow 1.0, gere um novo dry-run completo com a política atual de pagamento/status e revise o novo relatório. Em seguida, execute a carga completa do Analytics para atualizar Google Sheets e BI. Snapshots anteriores à nova política de cancelamento por pagamento 0 devem ser regenerados.

Arquivos gerados:

```text
logs\weni_update_review_full.txt   relatório legível para o operador
logs\weni_update_review_full.json  snapshot verificável do plano revisado
```

O TXT é aberto automaticamente no Bloco de Notas. Ele mostra, por contato, valores anteriores e propostos, evidência técnica, ações de grupo e confirmação FarmaLíder. No NexoFlow 1.0, o plano revisado fica **congelado**. Depois da confirmação, o NexoFlow não recalcula mensagens nem inclui novos contatos no mesmo apply. Em vez disso, relê cada contato imediatamente antes de gravá-lo. Se os campos/URNs/fontes relevantes daquele contato mudaram, somente aquele contato é marcado como conflito e ignorado. Os demais continuam normalmente. O checkpoint usa o corte temporal do dry-run, permitindo que mensagens, contatos e conflitos posteriores sejam reprocessados na próxima incremental.

### Carga completa fragmentada em quatro partes

Ao abrir `atualizar_weni_carga_completa.bat`, escolha entre a carga tradicional de 100% ou as Partes 1/4, 2/4, 3/4 e 4/4. Cada parte continua usando o mesmo fluxo seguro de dry-run, auditoria, relatório humano, confirmação e apply do snapshot congelado.

A Parte 1 cria `logs\full_load_25_manifest.json` com a lista congelada de UUIDs da campanha. A segmentação usa ordem canônica por UUID, e não a ordem mutável de `modified_on` da API. Por isso, alterações ou novos contatos entre uma parte e outra não mudam os limites. A Parte 2 exige a Parte 1 concluída; a Parte 3 exige 1 e 2; a Parte 4 exige 1, 2 e 3.

Na carga Weni de 25%, o processamento pesado de contatos, pedidos e FarmaLíder fica restrito à parte selecionada. A listagem paginada global de mensagens pode continuar sendo lida para preservar o contexto com menos chamadas do que consultar milhares de contatos individualmente; somente mensagens/contatos pertencentes ao fragmento entram no plano e na validação de pedidos.

Se uma parte falhar, o manifesto não avança. Execute novamente a mesma parte; contatos já satisfeitos continuam protegidos pelas verificações `already_satisfied` e pelo snapshot revisado.

### Somente simulação

Use:

```text
atualizar_weni_dry_run.bat
```

Nenhuma alteração é gravada e o checkpoint não é avançado.

### Teste de acesso

Use:

```text
testar_update_weni.bat
```

O teste é somente leitura e valida acesso a contatos, mensagens, grupos Opt-In LGPD e Opt-Out LGPD e disponibilidade da FarmaLíder para confirmação de pedidos.

## Campos que a rotina pode escrever

A lista é fechada e auditada:

```text
contact_urn
contact_urn_whatsapp
contact_urn_instagram
contact_urn_facebook
contact_canal_principal
cpf
idade
maior_de_18_anos
opt_in_lgpd
pedido_id
pedido_data
pedido_status
pedido_forma_pagamento
pedido_produtos
pedido_quantidade_itens
pedido_valor_produtos
pedido_valor
ultima_compra
primeiro_anuncio_origem
primeiro_anuncio_id
primeiro_anuncio_titulo
primeiro_anuncio_url
primeiro_anuncio_clique_id
primeiro_anuncio_data
primeiro_anuncio_tipo_campanha
primeiro_anuncio_canal_destino
ultimo_anuncio_origem
ultimo_anuncio_id
ultimo_anuncio_titulo
ultimo_anuncio_url
ultimo_anuncio_clique_id
ultimo_anuncio_data
ultimo_anuncio_tipo_campanha
ultimo_anuncio_canal_destino
```

Qualquer tentativa de escrever outro campo bloqueia a execução antes do primeiro POST.

## Regras de URN e canais

A Weni continua sendo a fonte de verdade das URNs. O NexoFlow apenas classifica as identidades que a API realmente retorna, sem fabricar endereço de canal.

Prioridade da URN principal quando existem vários canais:

```text
WhatsApp > Instagram > Facebook/Messenger > outra URN nativa
```

Campos mantidos pela rotina:

```text
contact_urn            URN principal
contact_urn_whatsapp   URN oficial de WhatsApp
contact_urn_instagram  URN oficial de Instagram
contact_urn_facebook   URN oficial de Facebook/Messenger
contact_canal_principal  whatsapp | instagram | facebook | outro
```

Antes do dry-run ou apply, o NexoFlow consulta a API de campos da Weni e exige que os quatro campos multicanal específicos existam. Eles devem ser criados como **Texto** na Weni. Se algum estiver ausente, a execução é interrompida antes de qualquer escrita em contatos.

Regras:

- a URN é preservada exatamente como recebida da Weni;
- `messenger:` e variantes reconhecidas de Facebook são classificadas como `facebook`, mas o valor original da URN não é reescrito;
- se o contato tiver WhatsApp e Instagram, `contact_urn` usa WhatsApp e os dois canais permanecem registrados nos campos específicos;
- se houver apenas Instagram, o Instagram vira a URN principal;
- se houver apenas Facebook/Messenger, esse canal vira o principal;
- sem URN nativa reconhecida, o NexoFlow pode manter a `contact_urn` já existente ou usar outra URN nativa como `outro`;
- um campo específico não é apagado por ausência temporária da URN numa resposta da API;
- clique/anúncio não é URN. `primeiro_anuncio_*` e `ultimo_anuncio_*` continuam registrando atribuição de mídia separadamente.

A revisão humana mostra a URN e o canal principal, contabiliza alterações de identificação de canal e também informa quantos contatos receberam atribuição Google Ads. O snapshot de revisão do NexoFlow 1.0 usa schema 6, inclui guardas de concorrência e o corte temporal do dry-run. Snapshots incompatíveis são rejeitados para evitar apply com semântica incorreta.



## Atendimento 24h e concorrência
A carga completa foi adaptada para ambientes em que a Weni continua recebendo mensagens e contatos durante toda a revisão. O dry-run fixa um corte temporal (`captured_at_utc`) e gera o snapshot schema 6. O apply usa os planos armazenados nesse JSON, valida seu SHA-256 e não volta a montar o plano a partir do histórico.

Antes de cada contato ser gravado, o NexoFlow consulta novamente aquele contato na Weni. Para cada campo planejado, o valor atual precisa continuar igual ao valor anterior revisado ou já ter chegado ao próprio valor proposto. Também são protegidas as URNs nativas, `opt_in_lgpd` quando governa grupos e os campos `pedido_*` usados como snapshot operacional. Se houver divergência, o contato recebe status de auditoria `conflict_skipped` e a carga continua para os demais. Se outra automação já aplicou exatamente o mesmo resultado, o status é `already_satisfied` e não há regravação.

Ao final, o checkpoint avança para o **corte do dry-run**, não para o horário final da aplicação. Assim, tudo que chegou ou mudou depois do snapshot é elegível para a próxima execução incremental, inclusive os contatos que foram isolados por conflito. Uma falha real de POST continua interrompendo a execução e impede o avanço do checkpoint.

## Google Ads e canal de destino

O NexoFlow 1.0 pode reconhecer um contato como vindo de **Google Ads** quando a evidência do clique chega à Weni em campos/metadados estruturados. São aceitos marcadores explícitos como `gclid`, `gbraid`, `wbraid`, `utm_source=google` com meio pago ou metadados equivalentes de Google Ads. Um URL comum do Google é ignorado. Para evitar falso positivo, um link com `gclid` simplesmente colado pelo cliente no texto livre da conversa também não é usado como prova de origem.

O anúncio e o canal continuam separados. Exemplos:

```text
Google Ads Performance Max -> WhatsApp
  primeiro_anuncio_origem = Google Ads
  primeiro_anuncio_tipo_campanha = Performance Max
  primeiro_anuncio_canal_destino = whatsapp
  contact_urn = whatsapp:...

Google Ads Search -> Instagram Direct
  ultimo_anuncio_origem = Google Ads
  ultimo_anuncio_tipo_campanha = Search
  ultimo_anuncio_canal_destino = instagram
  contact_urn_instagram = <URN oficial da Weni>

Google Ads YouTube -> Messenger
  ultimo_anuncio_origem = Google Ads
  ultimo_anuncio_tipo_campanha = YouTube
  ultimo_anuncio_canal_destino = facebook
  contact_urn_facebook = <URN Facebook/Messenger da Weni>
```

Tipos reconhecidos quando a evidência é explícita: **Performance Max**, **Search**, **Display/Banner**, **YouTube**, **Demand Gen** e **Shopping**. `utm_medium=cpc` sozinho não distingue Search de Performance Max, por isso o NexoFlow não adivinha o tipo nesse caso.

O primeiro anúncio válido é preservado. O último anúncio só é substituído por uma evidência realmente mais recente. Os campos `primeiro_anuncio_tipo_campanha`, `primeiro_anuncio_canal_destino`, `ultimo_anuncio_tipo_campanha` e `ultimo_anuncio_canal_destino` são opcionais: se não existirem na Weni, a rotina avisa e continua com os campos genéricos de anúncio disponíveis.

**Limitação importante:** se o Google Ads abrir diretamente WhatsApp, Instagram ou Messenger e nenhum `gclid`/`gbraid`/`wbraid`/UTM/metadado chegar à Weni, o NexoFlow não consegue provar a origem e não marca o contato como Google Ads. Para atribuição garantida nesses casos é necessário preservar a informação do clique em um redirecionador/landing de rastreamento ou integração equivalente.

## Regras de CPF

- o campo autorizado é `cpf` (`@fields.cpf` na Weni);
- o NexoFlow aceita CPF com ou sem pontuação, mas grava sempre 11 dígitos sem pontuação;
- o documento precisa passar pela validação oficial dos dois dígitos verificadores;
- em uma mensagem comum, o número só é considerado CPF quando o próprio texto o identifica como CPF, por exemplo `Meu CPF é 529.982.247-25`;
- um CPF isolado, por exemplo `52998224725`, só é aceito quando existe uma solicitação contextual anterior de CPF;
- se uma mesma mensagem contiver mais de um CPF válido, ela é tratada como ambígua e não altera o cadastro;
- se o campo `cpf` estiver vazio, o CPF válido mais recente encontrado pode preenchê-lo;
- se o cliente informar depois um CPF válido diferente do que está salvo, o CPF mais recente substitui o anterior;
- o mesmo CPF em outra formatação não é regravado;
- nenhuma mensagem sem CPF válido limpa ou substitui um valor já existente.

## Regras de idade e maioridade

- idade explícita, como `Tenho 27 anos`, pode preencher `idade = 27` e `maior_de_18_anos = sim`;
- idade abaixo de 18 gera `maior_de_18_anos = não`;
- declaração explícita de maioridade pode atualizar apenas `maior_de_18_anos`;
- respostas curtas como `27`, `Sim` e `Não` só são aceitas quando existe uma pergunta contextual clara imediatamente anterior;
- mensagens ambíguas são ignoradas.

## Regras de LGPD

- aceite inequívoco em contexto explícito de LGPD/consentimento pode definir `opt_in_lgpd = ativo`;
- recusa inequívoca pode definir `opt_in_lgpd = recusado`;
- `Sim`/`Não` sem contexto de LGPD nunca altera consentimento;
- `opt_in_lgpd_status` não é escrito pelo NexoFlow;
- `ativo` -> garantir associação ao grupo **Opt-In LGPD** e remover do **Opt-Out LGPD**, caso esteja nele;
- `recusado` -> garantir associação ao grupo **Opt-Out LGPD** e remover do **Opt-In LGPD**, caso esteja nele;
- o valor de `opt_in_lgpd` é a fonte de verdade: a rotina também corrige contatos já existentes com grupos incompatíveis;
- quando precisar trocar de grupo, o NexoFlow tenta primeiro adicionar o grupo correto e depois remover o incompatível.

## Regras de pedido e última compra

A FarmaLíder API é a fonte prioritária dos dados de pedido. A Weni recebe um snapshot operacional simples, legível e alinhado por posição.

Fluxo:

```text
CPF
-> GET cliente/cpf/{cpf}
-> ultimoPedido + itens
-> GET pedido/{pedido_id}
-> campos pedido_* na Weni
```

O endpoint por CPF já possui dados suficientes para montar o pedido. O endpoint por código é preferido como confirmação final do mesmo pedido e fornece também `formaPagamento`.

Campos atualizados:

```text
pedido_id                 340793
pedido_produtos           Produto A, Produto B
pedido_quantidade_itens   1, 1
pedido_valor_produtos     53.9, 58.9
pedido_valor              112.8
pedido_data               05/06/26 15:45:27
pedido_status             3
pedido_forma_pagamento    2
```

Regras:

- `pedido_produtos` usa somente `itens[].descricao`; `codProduto` não é usado como nome;
- produtos, quantidades e valores unitários são listas separadas por vírgula e mantêm a mesma ordem;
- `pedido_valor` é a soma de `itens[].total`, sem adicionar frete;
- o frete não é gravado nos campos Weni de pedido; ele é preservado no Google Sheets como `farmalider_frete` e usado pelo Analytics para calcular `valor_total_faturamento = pedido_valor + frete`;
- `pedido_data` é gravada no formato `DD/MM/YY HH:MM:SS`, usando America/Belem;
- `pedido_status` guarda o status efetivo: -2 Em aberto, -1 Pendente de pagamento, 0 Em processamento, 4 Pronto para rota, 1 Em trânsito, 2 Concluído, 3 Cancelado;
- `pedido_forma_pagamento` guarda o código Int32 não negativo normalizado da API: 1 Dinheiro, 2 Débito, 3 Crédito, 4 Ticket, 5 Pix por Link de Pagamento, 6 Pix no POS; a exceção é pagamento 0 ou `_`, que grava o texto `Cancelado` e força `pedido_status=3`;
- os normalizadores aceitam os nomes oficiais dos enums, como `PendenteDePagamento`, `EmProcessamento`, `Concluido`, `PixPorLinkDePagamento` e `PixNoPOS`; pagamento `_` é normalizado para 0;
- `Pedidos_FarmaLider` preserva status e pagamento brutos da API; Weni e `BI_Pedidos` usam o status efetivo Cancelado quando o pagamento é 0;
- os rótulos amigáveis de status e pagamento são derivados no Analytics/BI; pagamento válido sem de-para a partir de 7 aparece como `Não identificado (código X)`;
- `pedido_id` é o primeiro localizador de fallback quando o GET por CPF não puder ser usado;
- `ultimo_pedido` é o **último localizador**: ele pode vir de outra integração e serve somente para recuperar um ID de pedido que depois será confirmado em `GET pedido/{id}`;
- `ultimo_pedido` nunca substitui a API como fonte de produtos, valores, status, data ou pagamento; se a FarmaLíder estiver indisponível, os campos `pedido_*` existentes são preservados e não são reconstruídos a partir do snapshot legado;
- `ultima_compra` avança somente para pedido confirmado pela FarmaLíder com status efetivo 4, 1 ou 2, sem cancelamento explícito e sem pagamento 0; somente esses pedidos entram nas métricas de venda.

Os campos `pedido_id`, `pedido_data`, `pedido_status`, `pedido_produtos`, `pedido_quantidade_itens`, `pedido_valor_produtos`, `pedido_valor` e `pedido_forma_pagamento` são obrigatórios na Weni. Se qualquer um estiver ausente, o preflight bloqueia a execução antes de qualquer atualização de pedido.

Pedidos com status -2, -1, 0, 1 ou 4 permanecem na fila de rechecagem até chegarem a 2, Concluído, ou 3, Cancelado. Os estados -2, -1 e 0 não contam como vendas; 4 e 1 já contam, mas continuam em rechecagem.

## Incremental e checkpoint

O estado fica em:

```text
logs\weni_update_state.json
```

A rotina usa uma sobreposição de segurança no período consultado e é idempotente: valores idênticos não são regravados. O checkpoint só avança depois que todas as gravações terminam sem erro.

## Auditoria e logs

Log operacional:

```text
logs\nexoflow_update_weni.log
```

Trilha de auditoria estruturada:

```text
logs\weni_update_audit.jsonl
```

A auditoria registra contato, campos anteriores/novos, evidência técnica, ações de grupo e confirmação de pedido. O corpo completo das mensagens do cliente não é salvo nessa trilha.

Preparação e auditoria do plano acontecem antes das gravações. O total de contatos com pedido validado pela API inclui os que não precisam de alteração; o total de contatos com alterações é informado separadamente.

Pagamento sem de-para é informativo: cada código aparece em `INFO` uma vez por execução, com totais por código no resumo. O código é preservado e esse registro não bloqueia a atualização.

## Princípios de segurança

- nunca inventar dados;
- nunca gravar vazio sobre um valor válido;
- preferir API/flow oficial a interpretação de conversa;
- pedido só atualiza campos de compra com confirmação FarmaLíder;
- nenhuma escrita acontece antes de `audit_plans`;
- carga completa aplica exatamente o snapshot congelado revisado pelo operador, sem recalcular todo o histórico;
- falha de escrita bloqueia o checkpoint;
- nenhuma credencial é incorporada ao executável.


## Atalho

O executável/atalho **NexoFlow Weni** usa o ícone exclusivo `assets\NexoFlow_Weni.ico`.

## Uso pelo NexoFlow Terminal

No NexoFlow 1.0, as rotinas desta documentação também podem ser chamadas por comandos amigáveis:

```text
nexo weni testar
nexo weni dry-run
nexo weni atualizar
nexo weni carga-completa
```

Para investigar um contato sem alterar a Weni:

```text
nexo api weni contato --uuid <UUID>
nexo api weni mensagens --uuid <UUID> --limite 10
nexo api weni grupos
nexo api weni campos
```

As consultas `nexo api` são somente leitura. Consulte `README TERMINAL.md` para a referência completa.
