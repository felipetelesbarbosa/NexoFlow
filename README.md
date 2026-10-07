# NexoFlow 1.0

O **NexoFlow 1.0** é a camada de integração, atualização de dados e analytics que conecta **Weni**, **FarmaLíder API**, **Google Sheets** e **Looker Studio** em um fluxo único, auditável e preparado para operação contínua.

Ele possui duas responsabilidades principais:

```text
Weni -> NexoFlow Weni -> Weni
Weni -> NexoFlow Analytics -> FarmaLíder API -> Google Sheets -> Looker Studio
```

O **NexoFlow Weni** enriquece e atualiza contatos com regras controladas.  
O **NexoFlow Analytics** organiza os dados operacionais, pedidos, atribuição de anúncios e indicadores usados no Google Sheets e no Looker Studio.

## Downloads do NexoFlow 1.0

- [Setup instalável](https://github.com/felipetelesbarbosa/NexoFlow/releases/download/v1.0/NexoFlow-Setup-1.0.zip)
- [Projeto completo](https://github.com/felipetelesbarbosa/NexoFlow/releases/download/v1.0/NexoFlow-1.0.zip)
- [Checksums SHA-256](https://github.com/felipetelesbarbosa/NexoFlow/releases/download/v1.0/SHA256SUMS-1.0.txt)

Os pacotes são atualizados no [release NexoFlow 1.0](https://github.com/felipetelesbarbosa/NexoFlow/releases/tag/v1.0) após testes, auditoria e validação do Setup no Windows. A versão permanece **1.0**.

## Integrações do NexoFlow 1.0

| Integração | Uso no NexoFlow |
|---|---|
| **Weni** | Contatos, mensagens, URNs, campos personalizados, grupos LGPD e atualização auditada de contatos. |
| **FarmaLíder API** | Validação de cliente por CPF, confirmação de pedido por ID, status, itens, valores, frete e última compra. |
| **Google Sheets** | Base operacional, histórico, pedidos, itens, métricas e camada BI. |
| **Looker Studio** | Visualização de Marketing, Vendas, conversão, canais, pedidos, compradores, Ads e saúde da integração. |
| **Google Ads** | Atribuição quando a Weni recebe evidência explícita como `gclid`, `gbraid`, `wbraid`, UTM paga ou metadado equivalente. |
| **Meta Ads / referrals Weni** | Campos de primeiro/último anúncio e estrutura para eventos de anúncios. O webhook opcional está preparado; integração direta com Meta Marketing API não é tratada como ativa. |
| **Windows / PowerShell / Python** | Setup, executáveis, ambiente virtual, diagnóstico, operação e desinstalação. |
| **Proxy corporativo** | Detecção automática de proxy e seleção da rota correta para a FarmaLíder API. |

## Componentes

### NexoFlow Weni

Atualiza contatos diretamente pela API da Weni sem depender de exportação/importação manual de planilhas.

Fluxo protegido:

```text
check-up
-> teste de acesso e conexões
-> dry-run
-> auditoria
-> confirmação humana
-> apply
```

Na carga completa, o plano é congelado em JSON, protegido por SHA-256 e revisado antes da aplicação. Cada contato é relido imediatamente antes da gravação para evitar sobrescrever alterações ocorridas durante a revisão.

Os logs de preparação e auditoria aparecem antes das gravações. O total de contatos com pedido validado pela API inclui os que já estavam atualizados; ele é diferente do total de contatos com alterações.

### NexoFlow Analytics

Executa a sincronização analítica e mantém as estruturas usadas por Google Sheets e Looker Studio.

Responsabilidades principais:

- preservar os contatos retornados pela Weni;
- normalizar CPF, identidade e canais;
- enriquecer clientes pela FarmaLíder API;
- resolver e confirmar pedidos;
- reconciliar itens;
- manter métricas de vendas;
- consolidar atribuição de anúncios;
- manter as abas BI prontas para o Looker Studio;
- registrar telemetria da execução.

### NexoFlow Terminal

Interface de linha de comando para operação e diagnóstico:

```text
nexo
nexo ajuda
nexo status
nexo diagnostico
nexo versao

nexo weni testar
nexo weni dry-run
nexo weni atualizar
nexo weni carga-completa

nexo analytics

nexo api weni status
nexo api weni contato --uuid <UUID>
nexo api weni contato --urn <URN>
nexo api weni mensagens --uuid <UUID> --limite 10
nexo api weni grupos
nexo api weni campos

nexo api farmalider status
nexo api farmalider cliente --cpf <CPF>
nexo api farmalider pedido <CODIGO>

nexo logs weni
nexo logs weni --seguir
nexo logs analytics
```

A família `nexo api` é **somente leitura**. Atualizações da Weni continuam obrigatoriamente usando o fluxo auditado do NexoFlow Weni.

## Identidade multicanal

A Weni é a fonte de verdade para URNs. O NexoFlow não fabrica identificadores de canal.

Prioridade da URN principal:

```text
WhatsApp > Instagram > Facebook/Messenger > outra URN nativa
```

Campos mantidos:

```text
contact_urn
contact_urn_whatsapp
contact_urn_instagram
contact_urn_facebook
contact_canal_principal
```

`contact_canal_principal` pode receber:

```text
whatsapp
instagram
facebook
outro
```

Origem de anúncio e canal de conversa permanecem separados. Um anúncio pode ter origem Google Ads ou Meta e terminar em WhatsApp, Instagram ou Messenger sem alterar a identidade real do contato.

## Campos que o NexoFlow Weni pode escrever

A escrita usa uma allowlist fechada:

### Identidade e cadastro

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
```

### Pedido e compra

```text
pedido_id
pedido_data
pedido_status
pedido_forma_pagamento
pedido_produtos
pedido_quantidade_itens
pedido_valor_produtos
pedido_valor
ultima_compra
```

### Primeiro anúncio

```text
primeiro_anuncio_origem
primeiro_anuncio_id
primeiro_anuncio_titulo
primeiro_anuncio_url
primeiro_anuncio_clique_id
primeiro_anuncio_data
primeiro_anuncio_tipo_campanha
primeiro_anuncio_canal_destino
```

### Último anúncio

```text
ultimo_anuncio_origem
ultimo_anuncio_id
ultimo_anuncio_titulo
ultimo_anuncio_url
ultimo_anuncio_clique_id
ultimo_anuncio_data
ultimo_anuncio_tipo_campanha
ultimo_anuncio_canal_destino
```

Qualquer tentativa de escrever fora da allowlist bloqueia a execução antes do primeiro POST.

### Campos preservados

`ultimo_pedido` continua preservado por compatibilidade, mas não é mais a fonte prioritária do pedido quando a FarmaLíder API está disponível.

`opt_in_lgpd_status` permanece sob controle dos flows/agentes da Weni.

## CPF, idade e LGPD

O NexoFlow usa interpretação conservadora:

- CPF precisa ser válido pelos dígitos verificadores;
- CPF em mensagem livre precisa estar explicitamente identificado ou responder a uma solicitação contextual;
- mensagens ambíguas não atualizam cadastro;
- idade explícita pode preencher `idade` e `maior_de_18_anos`;
- respostas como “Sim”, “Não” ou um número isolado só são usadas quando existe contexto claro;
- `opt_in_lgpd = ativo` sincroniza o contato com **Opt-In LGPD**;
- `opt_in_lgpd = recusado` sincroniza o contato com **Opt-Out LGPD**;
- os dois grupos são mutuamente exclusivos.

## Pedidos e FarmaLíder API

A **FarmaLíder API é a fonte de verdade dos pedidos**. Os campos de pedido da Weni funcionam como destino/cache operacional e são atualizados pela rotina auditada.

Fluxo principal:

```text
CPF
-> GET /api/Delivery/cliente/cpf/{cpf}
-> valida cliente e obtém ultimoPedido + itens
-> GET /api/Delivery/pedido/{pedido_id}
-> confirma o snapshot mais atual do mesmo pedido
-> atualiza Weni
-> alimenta Google Sheets / Looker Studio
```

O retorno de `cliente/cpf` já contém `ultimoPedido` e `itens`, portanto pode servir como fallback completo quando a segunda consulta sofre falha transitória. O endpoint de pedido é preferido como snapshot final.

Se o GET por CPF não puder ser usado, o NexoFlow tenta primeiro o `pedido_id` já gravado pelo próprio NexoFlow. Somente se esse localizador não estiver disponível ou não puder ser validado, `ultimo_pedido` é usado como **último localizador de ID**. Como `ultimo_pedido` é alimentado por outra integração, ele ajuda a recuperar um pedido criado enquanto o NexoFlow esteve indisponível. Mesmo nesse fallback, os produtos, valores, status, data e pagamento só são aceitos após um GET oficial de `pedido/{id}`; `ultimo_pedido` não substitui a FarmaLíder API como fonte de verdade.

Os oito campos `pedido_*` abaixo são obrigatórios na Weni. Se qualquer um estiver ausente, o NexoFlow Weni bloqueia o apply para evitar um snapshot parcial de pedido.

### Contrato dos campos Weni

| Campo Weni | Origem FarmaLíder | Formato |
|---|---|---|
| `pedido_id` | `ultimoPedido.id` / `capa.id` | código do pedido |
| `pedido_produtos` | `itens[].descricao` | nomes em lista CSV; aspas preservam vírgulas no nome |
| `pedido_quantidade_itens` | `itens[].quantidade` | quantidades na mesma ordem, separadas por vírgula |
| `pedido_valor_produtos` | `itens[].valor` | valores unitários na mesma ordem, separados por vírgula |
| `pedido_valor` | soma de `itens[].total` | valor total dos itens do pedido |
| `pedido_data` | `emissao` | `DD/MM/YY HH:MM:SS` |
| `pedido_status` | `status` e regra de cancelamento | status efetivo de -2 a 4 |
| `pedido_forma_pagamento` | `formaPagamento` | código Int32 não negativo normalizado; 0 grava `Cancelado` |

`codProduto` não é usado como nome do produto. O nome exibido vem exclusivamente de `descricao`. O código do produto pode continuar armazenado internamente para auditoria, sem alimentar `pedido_produtos`.

Nomes como `Produto 0,5 MG` são escritos entre aspas na lista: `"Produto 0,5 MG", Produto B`. A Weni e o Analytics interpretam isso como dois produtos, preservando a ordem das quantidades e dos valores. A auditoria informa as contagens e continua bloqueando desalinhamentos reais, inclusive em alterações parciais.

Exemplo de um pedido com dois itens:

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

As três listas de item são posicionais: o primeiro produto corresponde à primeira quantidade e ao primeiro valor, o segundo produto corresponde à segunda quantidade e ao segundo valor, e assim por diante.

### Status do pedido

| Código | Status |
|---:|---|
| -2 | Em aberto |
| -1 | Pendente de pagamento |
| 0 | Em processamento |
| 4 | Pronto para rota |
| 1 | Em trânsito |
| 2 | Concluído |
| 3 | Cancelado |

### Formas de pagamento

| Código | Forma de pagamento |
|---:|---|
| 0 | Cancelado |
| 1 | Dinheiro |
| 2 | Débito |
| 3 | Crédito |
| 4 | Ticket |
| 5 | Pix por Link de Pagamento |
| 6 | Pix no POS |

A Weni guarda os códigos de pagamento normalizados, exceto `formaPagamento=0` ou `_`, que grava o texto `Cancelado` em `pedido_forma_pagamento` e o status efetivo `3`, Cancelado. O Analytics cria os rótulos amigáveis para o Google Sheets e o Looker Studio. `Pedidos_FarmaLider` preserva os valores brutos de pagamento e status da API; Weni e `BI_Pedidos` usam o status efetivo, inclusive o cancelamento por pagamento 0.

Os normalizadores aceitam códigos e nomes dos enums oficiais, como `PendenteDePagamento`, `EmProcessamento`, `Concluido`, `PixPorLinkDePagamento` e `PixNoPOS`. O nome antigo `PendentePagamento` permanece aceito como alias de `PendenteDePagamento` para leitura de registros existentes. O nome de pagamento `_` corresponde ao código 0 e aplica a mesma regra de cancelamento.

Códigos numéricos de pagamento válidos sem de-para a partir de 7 continuam sendo preservados como Int32 na Weni e exibidos no Google Sheets/BI como `Não identificado (código X)`, sem impedir a atualização dos demais campos válidos. Pagamento ausente ou inválido mantém a descrição vazia.

Cada código sem de-para aparece em `INFO` uma vez por execução, seguido dos totais por código; esse registro informa a falta de descrição documentada e não indica falha na atualização.

### Frete e faturamento

`pedido_valor` continua representando **somente os produtos**, conforme o contrato da Weni. O campo `frete` retornado pela FarmaLíder é armazenado no Google Sheets em `farmalider_frete` e o Analytics calcula também `valor_total_faturamento = produtos + frete`.

No BI, a separação fica explícita:

```text
pedido_valor            = total dos produtos
pedido_frete            = frete
pedido_faturamento_total = produtos + frete
```

As abas `BI_Resumo_Diario` e `BI_Vendas` também separam faturamento de produtos, faturamento de frete e faturamento total. O campo de faturamento usado nos indicadores gerais passa a considerar **produtos + frete**, para bater com o valor total cobrado do pedido.

Pedidos validados pela API com status efetivo **4, Pronto para rota**, **1, Em trânsito**, ou **2, Concluído**, sem cancelamento explícito e sem pagamento 0 entram nas métricas de venda e atualizam `ultima_compra`. Pedidos em aberto, pendentes de pagamento, em processamento ou cancelados ficam fora.

Pedidos abertos em **Em aberto (-2)**, **Pendente de pagamento (-1)**, **Em processamento (0)**, **Pronto para rota (4)** ou **Em trânsito (1)** permanecem em fila de rechecagem até chegarem a **Concluído** ou **Cancelado**.

Datas operacionais de pedidos usam **America/Belem (UTC-3)**.

## Google Ads

A atribuição é propositalmente conservadora.

O NexoFlow aceita evidência explícita em dados estruturados recebidos pela Weni, como:

```text
gclid
gbraid
wbraid
utm_source=google + contexto pago
metadado explícito Google Ads / AdWords
```

Tipos reconhecidos quando a evidência permite:

```text
Performance Max
Search
Display/Banner
YouTube
Demand Gen
Shopping
```

Um domínio do Google, um link comum ou um URL com `gclid` apenas colado pelo cliente no texto livre não são suficientes para atribuição.

O primeiro anúncio válido é preservado. O último anúncio só muda quando existe evidência mais recente.

**Importante:** o NexoFlow 1.0 faz atribuição a partir dos dados recebidos pela Weni. Custos, impressões e cliques do Google Ads exigem uma integração própria com a API do Google Ads e não são inferidos.

## Meta Ads e eventos de anúncio

Os campos genéricos `primeiro_anuncio_*` e `ultimo_anuncio_*` também preservam dados de anúncio disponibilizados pela Weni.

O projeto inclui estrutura para captura exata de referrals:

```text
POST /weni/meta-event
GET /health
```

O módulo opcional aceita dados como:

```text
source_id
headline
source_url
ctwa_clid
contact_uuid
contact_urn
received_at
```

A aba `Campanhas_Meta` já possui schema para anúncio, conjunto, campanha, investimento, impressões e cliques.

A **Meta Marketing API direta** é tratada como evolução preparada, não como integração ativa do NexoFlow 1.0.

## Google Sheets

### Bases operacionais

```text
Base_Contatos
Historico_Alteracoes
Metricas_Diarias
Eventos_Anuncios
Campanhas_Meta
Controle
Pedidos_FarmaLider
Itens_Pedidos_FarmaLider
Metricas_Vendas
```

### Camada BI

```text
BI_Resumo_Diario
BI_Canais
BI_Conversao
BI_Vendas
BI_Ads
BI_Pedidos
BI_Status
```

A camada BI concentra as regras no NexoFlow para que o Looker Studio fique principalmente responsável pela visualização.

### Base_Contatos

Além dos campos Weni, a base preserva dados como:

```text
contact_uuid
telefone
weni_name
nome
cpf
cpf_normalizado
email
idade
maior_de_18_anos
opt_in_lgpd
farmalider_cliente_id
farmalider_cliente_nome
farmalider_cliente_status
farmalider_cliente_consultado_em
ultimo_pedido
pedido_*
campos de anúncio
weni_created_on
weni_modified_on
sincronizado_em
```

## Looker Studio

O dashboard pode trabalhar diretamente sobre as abas BI para priorizar Marketing e Vendas:

- faturamento;
- pedidos;
- compradores;
- ticket médio;
- unidades vendidas;
- conversão;
- canais;
- origem e atribuição de anúncios;
- compradores do dia;
- detalhe do pedido, produtos, quantidades e valores;
- status dos pedidos com código e descrição;
- forma de pagamento com código e descrição;
- saúde da sincronização.

`BI_Status` é indicada para uma página técnica opcional.

## Performance e resiliência

### FarmaLíder API

- concorrência controlada;
- até 4 workers;
- lotes de até 500 CPFs;
- sessão HTTP por thread;
- rate limiter global;
- até quatro tentativas para falhas transitórias;
- cooldown global após HTTP 429, falhas 5xx e erros de conexão;
- recuperação serial e retorno gradual da concorrência;
- intervalo adaptativo limitado, com redução após a recuperação;
- circuit breaker por rota e por taxa de erros do lote;
- telemetria de latência.

Após uma resposta `5xx`, a espera global segue **5, 10 e 20 segundos** nas
tentativas seguintes e permanece ativa mesmo se a última tentativa falhar.
`Retry-After`, quando informado, pode aumentar essa espera. Novas requisições
passam a entrar uma por vez; as que já estavam em andamento podem concluir.
Depois de **6 respostas saudáveis consecutivas iniciadas após a falha**, o
limite passa de 1 para 2. Outras **12 respostas saudáveis** permitem voltar
a 4. Uma nova falha reinicia a recuperação. O intervalo entre requisições
durante a recuperação de `5xx` chega a, no máximo, **1 segundo** e diminui
gradualmente até o valor normal quando a API se recupera.

`404` é tratado como cliente ou pedido não encontrado, sem retry. `500`
continua sendo falha da API e nunca é convertido em ausência de cadastro.
O circuito da rota abre após **12 respostas `5xx` envolvendo pelo menos
3 consultas distintas**, sem uma resposta válida `200` ou `404` entre elas,
e interrompe o Analytics antes de gravar contatos ou pedidos no Google Sheets.

O log usa referências HMAC com chave aleatória por execução e categorias
seguras da resposta, sem copiar CPF, UUID de contato, token ou texto livre do
servidor. Um identificador de correlação enviado pela API só é registrado se
estiver no formato UUID estrito. Datas e horários operacionais e de log usam
**America/Belem (UTC-3)**.

Se restarem consultas de cliente ou pedido com erro, a execução termina como
`parcial` (código `3`) e mantém o marco incremental para nova tentativa. A
próxima execução pode repetir consultas à FarmaLíder, pois o cache não guarda
o conteúdo completo dos pedidos. Essas proteções mitigam sobrecarga e ajudam
no diagnóstico; a causa do erro interno só pode ser confirmada com os logs
do backend. Consulte [o diagnóstico da API](docs/FARMALIDER%20API.md).

### Google Sheets

- timeout explícito;
- retry de leitura e escrita;
- proteção para HTTP 429/5xx;
- batches adaptativos;
- limite conservador de payload;
- redução de leituras redundantes;
- upsert somente quando há mudança real;
- fingerprint de schema;
- progresso operacional em cargas grandes.

## Rede e proxy

### Identificar CPFs com falhas persistentes da FarmaLíder

Após esgotar tentativas por CPF com respostas 5xx, o NexoFlow registra um diagnóstico **privado local**, separado do log normal. Consultas com 5xx interrompidas pelo circuito também são registradas. Uma consulta recuperada por retry não cria registro de falha persistente.

No Windows, abra no Explorador:

```text
%LOCALAPPDATA%\NexoFlow\diagnosticos_privados
```

Cada execução cria `farmalider_falhas_<execucao_id>.jsonl`. Cada linha é um JSON com `cpf`, `consulta_ref`, horário em America/Belem, ambiente, último HTTP 5xx, tentativas, motivo do encerramento, assinatura e campos diagnósticos sanitizados da resposta. O log normal mostra a referência e o caminho do arquivo, sem CPF nem corpo da resposta. A mesma referência é gravada uma única vez por execução.

O arquivo contém CPF e deve permanecer privado. URLs, credenciais, objetos de cliente e identificadores no texto da resposta são removidos; somente campos diagnósticos conhecidos são preservados. Corpos maiores que 4 KiB, HTML, formatos desconhecidos e conteúdo sensível não são copiados integralmente. Em Linux, o diretório é `logs/privado`, criado com permissões restritas.

Os arquivos começam a ser criados nas próximas execuções; referências de logs antigos não permitem recuperar CPFs. A gravação do diagnóstico não altera o tratamento de HTTP 500 como falha da API nem os dados existentes na Weni. O Git ignora esses arquivos, e o empacotamento bloqueia sua inclusão mesmo se forem adicionados ao índice por engano. A pasta Windows fica fora da instalação e não é enviada automaticamente para nenhum serviço.

O NexoFlow pode operar em rede corporativa ou conexão direta.

Com proxy corporativo:

```text
https://api.farmalider.net.br/farmalider
```

Sem proxy:

```text
https://api.farmalider.net.br:3200/farmalider
```

O modo `auto` detecta o ambiente e seleciona a rota adequada.

O teste TCP do proxy confirma somente que sua porta responde. `nexo diagnostico` testa cada serviço separadamente e mostra a rota efetiva para a Weni. Os logs usam America/Belem (UTC-3).

| Diagnóstico | Significado e ação |
|---|---|
| `PROXY_AUTENTICACAO` / HTTP 407 | Proxy exige autenticação ou recusou as credenciais; conferir usuário, senha e método de autenticação. |
| `PROXY_ACESSO_NEGADO` / HTTP 403 no túnel | Proxy negou HTTPS; conferir liberação do domínio com a equipe de rede. |
| `TLS_CERTIFICADO` | Conferir certificados, CA corporativa e relógio; não desativar validação TLS. |
| `DNS` | Conferir resolução dos endereços na rota. |
| `TIMEOUT` | Conexão ou resposta excedeu o limite. |
| `CONEXAO_RECUSADA` | Conferir host, porta, firewall e disponibilidade. |
| `PROXY_CONEXAO` | Falha do proxy sem detalhe suficiente para identificar a causa. |

A classificação analisa erros aninhados sem imprimir mensagens originais, URLs autenticadas, senhas ou tokens. A Weni evita repetir falhas explícitas de autenticação do proxy, bloqueio do túnel e certificado; falhas transitórias continuam com retry. O diagnóstico não muda a rota nem tenta contornar o proxy automaticamente. HTTP 400/404 da FarmaLíder no CPF fictício confirma uma resposta do servidor, mas não confirma autenticação e aparece como aviso.

## Instalação

O pacote **NexoFlow Setup** instala o projeto em:

```text
C:\NexoFlow
```

Requisitos:

- Windows x64;
- Python 3.11 ou superior, 64 bits;
- credenciais e tokens configurados localmente.

Se nenhum Python compatível for encontrado, o Setup pode oferecer o Python 3.14.8 x64 incluído no pacote.

Executáveis:

```text
NexoFlow Analytics.exe
NexoFlow Weni.exe
NexoFlow Terminal.exe
NexoFlow Uninstall.exe
```

O `NexoFlow Uninstall.exe` é uma conveniência. A desinstalação também permanece disponível por:

```text
desinstalar_nexoflow.cmd
installer\uninstall.ps1
```

## Segurança e auditoria

O NexoFlow 1.0 não deve versionar:

```text
secrets_config.py
credentials/google_credentials.json
tokens
senhas de proxy
```

Proteções principais:

- allowlist explícita de campos;
- dry-run antes de escrita;
- auditoria obrigatória;
- confirmação humana;
- snapshot congelado na carga completa;
- SHA-256;
- releitura por contato;
- isolamento de conflitos;
- checkpoint somente após sucesso;
- logs operacionais;
- trilha JSONL de auditoria;
- executáveis sem credenciais embutidas.

## Operação recomendada

### Primeira carga ou revalidação após atualização

```text
1. Instalar NexoFlow 1.0
2. testar_conexoes.bat
3. atualizar_weni_carga_completa.bat
4. revisar logs\weni_update_review_full.txt
5. confirmar CARGA COMPLETA REVISADA
6. executar carga completa do Analytics
```

Após atualizar ou reinstalar, essa sequência gera um novo dry-run com o de-para atual antes do apply. Refaça a revisão do plano e execute o Analytics completo; snapshots antigos não devem aplicar a política anterior de pagamento 0.

### Rotina

```text
1. NexoFlow Weni.exe
2. NexoFlow Analytics.exe
```

## Documentação

- [NexoFlow Weni](README%20WENI.md)
- [NexoFlow Terminal](README%20TERMINAL.md) — arquivo `README TERMINAL.md`
- [Instalação](README%20INSTALACAO.md)
- [Pedidos](docs/PEDIDOS.md)
- [FarmaLíder API](docs/FARMALIDER%20API.md)
- [Google Ads](docs/GOOGLE%20ADS.md)
- [Google Sheets / Service Account](docs/GOOGLE%20SETUP.md)
- [Looker Studio](docs/LOOKER%20STUDIO.md)
- [Proxy e rede](README%20PROXY.md)
- [VS Code](README%20VSCODE.md)
- [Antivírus e confiança](docs/ANTIVIRUS%20E%20CONFIANCA.md)

## NexoFlow 1.0

O repositório, a documentação, os executáveis, o Setup, a CLI e a distribuição oficial usam a identificação **NexoFlow 1.0**.
