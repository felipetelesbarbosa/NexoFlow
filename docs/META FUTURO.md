# Meta Marketing API: evolução futura

A Weni entrega `source_id`, `headline`, `source_url` e `ctwa_clid`.
O `source_id` poderá ser usado para enriquecer a base com a Meta Marketing API.

A aba `Campanhas_Meta` já está preparada para:

- anúncio
- conjunto de anúncios
- campanha
- investimento
- impressões
- cliques

Isso permitirá no Data Studio métricas como campanhas que mais trouxeram clientes, custo por contato e, com `Eventos_Anuncios`, custo por conversa.

Nenhuma credencial da Meta é necessária para a primeira fase.
## Separação entre anúncio e canal

A origem de anúncio nunca deve ser usada para fabricar `contact_urn`. Se um anúncio do Instagram abrir WhatsApp, a URN continua sendo de WhatsApp e a origem do anúncio permanece nos campos `primeiro_anuncio_*`/`ultimo_anuncio_*`. Se a conversa ocorrer no Instagram ou Facebook/Messenger, o canal é determinado exclusivamente pela URN que a Weni retornar.


## Convivência com Google Ads
Os campos genéricos `primeiro_anuncio_*` e `ultimo_anuncio_*` também podem receber Google Ads quando houver evidência explícita na Weni. Isso não transforma a aba `Campanhas_Meta` em uma integração Google Ads: custos, impressões e cliques de campanhas Google continuam exigindo uma integração própria com Google Ads.
