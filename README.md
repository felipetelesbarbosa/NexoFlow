# NexoFlow 1.0

O **NexoFlow 1.0** é a camada de integração, atualização de dados e analytics que conecta **Weni**, **FarmaLíder API**, **Google Sheets** e **Looker Studio** em um fluxo único, auditável e preparado para operação contínua.

Ele possui duas responsabilidades principais:

```text
Weni -> NexoFlow Weni -> Weni
Weni -> NexoFlow Analytics -> FarmaLíder API -> Google Sheets -> Looker Studio
```

O **NexoFlow Weni** enriquece e atualiza contatos com regras controladas.  
O **NexoFlow Analytics** organiza os dados operacionais, pedidos, atribuição de anúncios e indicadores usados no Google Sheets e no Looker Studio.

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
pedido_produtos
pedido_quantidade_itens
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

`ultimo_pedido` é tratado como fonte estruturada e não é reescrito pelo NexoFlow Weni.

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

O NexoFlow usa dois caminhos controlados.

### Caminho 1 — `ultimo_pedido`

Quando `ultimo_pedido` está preenchido e possui ID válido:

1. o JSON da Weni fornece ID, data, produtos, quantidades e valores;
2. o NexoFlow consulta **somente o mesmo `pedido_id`** na FarmaLíder API;
3. a API confirma o status atual;
4. os campos `pedido_*` são preservados/atualizados com o mesmo pedido.

### Caminho 2 — CPF

Somente quando `ultimo_pedido` estiver ausente, vazio ou `null`:

```text
CPF
-> GET cliente/cpf/{cpf}
-> ultimoPedido.id
-> GET pedido/{codigo}
```

O NexoFlow valida vínculo do titular, CPF e identificador antes de considerar o pedido confirmado.

### Status oficiais

| Código | Status |
|---:|---|
| 0 | Em processamento |
| 1 | Em trânsito |
| 2 | Concluído |
| 3 | Cancelado |
| 4 | Pronto para rota |

Para os indicadores, **0, 1, 2 e 4** contam como pedido feito quando confirmados pela API e sem cancelamento explícito. **3 — Cancelado** fica fora.

Pedidos abertos em **Em processamento**, **Em trânsito** ou **Pronto para rota** permanecem em fila de rechecagem até chegarem a **Concluído** ou **Cancelado**.

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
- status dos pedidos;
- saúde da sincronização.

`BI_Status` é indicada para uma página técnica opcional.

## Performance e resiliência

### FarmaLíder API

- concorrência controlada;
- até 4 workers;
- lotes de até 500 CPFs;
- sessão HTTP por thread;
- rate limiter global;
- retry;
- cooldown após HTTP 429;
- throttle adaptativo;
- circuit breaker;
- telemetria de latência.

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

### Primeira carga

```text
1. Instalar NexoFlow 1.0
2. testar_conexoes.bat
3. atualizar_weni_carga_completa.bat
4. revisar logs\weni_update_review_full.txt
5. confirmar CARGA COMPLETA REVISADA
6. executar carga completa do Analytics
```

### Rotina

```text
1. NexoFlow Weni.exe
2. NexoFlow Analytics.exe
```

## Documentação

- [NexoFlow Weni](README%20WENI.md)
- [NexoFlow Terminal](README%20TERMINAL.md)
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
