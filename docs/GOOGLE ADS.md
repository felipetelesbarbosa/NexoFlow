# Google Ads no NexoFlow

## Objetivo

No NexoFlow 1.5.2, o NexoFlow consegue reconhecer contatos originados por Google Ads quando a evidência do clique chega às mensagens/metadados da Weni. A identidade do canal continua independente: um anúncio do Google pode terminar em WhatsApp, Instagram Direct ou Facebook/Messenger sem alterar a regra de URN.

## Evidências aceitas

O detector é conservador e considera Google Ads quando encontra pelo menos uma evidência explícita:

- `gclid`;
- `gbraid`;
- `wbraid`;
- `utm_source=google`/Google Ads com meio pago;
- metadado explícito de Google Ads/AdWords recebido pela Weni.

A leitura é feita em campos/metadados estruturados da mensagem. Um link comum `google.com` não é tratado como anúncio e um URL com `gclid` apenas colado pelo cliente no texto livre da conversa não é usado como prova de origem. Mensagens de saída do atendimento também não são usadas como prova de atribuição.

## Tipos de campanha

Quando a informação é explícita, o NexoFlow normaliza:

- `Performance Max`;
- `Search`;
- `Display/Banner`;
- `YouTube`;
- `Demand Gen`;
- `Shopping`.

`utm_medium=cpc` sozinho não diferencia Search de Performance Max, portanto o tipo fica vazio em vez de ser adivinhado.

## Campos

Os campos genéricos já existentes continuam sendo a fonte principal de atribuição:

```text
primeiro_anuncio_origem
primeiro_anuncio_id
primeiro_anuncio_titulo
primeiro_anuncio_url
primeiro_anuncio_clique_id
primeiro_anuncio_data
ultimo_anuncio_origem
ultimo_anuncio_id
ultimo_anuncio_titulo
ultimo_anuncio_url
ultimo_anuncio_clique_id
ultimo_anuncio_data
```

Para enriquecer o detalhe, podem ser criados na Weni como **Texto**:

```text
primeiro_anuncio_tipo_campanha
primeiro_anuncio_canal_destino
ultimo_anuncio_tipo_campanha
ultimo_anuncio_canal_destino
```

Esses quatro campos extras são opcionais. Se não existirem, o teste de acesso mostra um aviso e a rotina continua.

## Canal de destino

O canal é obtido da URN da mensagem entregue pela Weni:

```text
whatsapp -> WhatsApp
instagram -> Instagram Direct
facebook/messenger -> Facebook/Messenger
outro -> outro esquema nativo
```

Se a mensagem não trouxer URN e o contato possuir exatamente um canal conhecido, esse único canal pode ser usado como fallback. Se o contato for multicanal, o NexoFlow não escolhe um destino sem evidência.

## Primeiro e último anúncio

- o primeiro anúncio válido não é substituído;
- uma evidência do mesmo primeiro anúncio pode apenas completar campos vazios;
- o último anúncio é atualizado somente quando a nova evidência possui data posterior;
- nenhum anúncio altera `contact_urn` ou as URNs específicas de canal.

## Limitação de rastreamento

Abrir WhatsApp, Instagram ou Messenger diretamente a partir de um anúncio do Google não garante que o identificador do clique chegue à Weni. Se `gclid`, `gbraid`, `wbraid`, UTM ou metadado equivalente for perdido no redirecionamento, o NexoFlow não atribui o contato ao Google Ads.

Para atribuição garantida, a rota do anúncio precisa preservar um identificador do clique até a conversa, por exemplo através de uma landing/redirecionador de rastreamento ou integração dedicada.
