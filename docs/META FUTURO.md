# Meta Marketing API: contexto e evolução

A integração nativa Meta Ads está disponível no NexoFlow Windows. Consulte o [guia operacional](META%20ADS%20NATIVO.md) para ativação, bootstrap, revisão e limites; este documento preserva o contexto do planejamento anterior. Ela funciona sem Codex ou MCP e não depende do NexoFlow Hub futuro.

A Weni pode entregar `source_id`, `headline`, `source_url` e `ctwa_clid`. Campos ausentes não são inventados; IDs e eventos oficiais sustentam o vínculo com anúncios.

A aba `Campanhas_Meta` já está preparada para:

- anúncio
- conjunto de anúncios
- campanha
- investimento
- impressões
- cliques

A integração nativa utiliza fontes adicionais, preservando os contratos legados. Indicadores do Data Studio dependem da cobertura e dos vínculos comprovados. Custo por conversa exige IDs oficiais de conversa; eventos CTWA e cliques não comprovam, sozinhos, conversas distintas.

A reconciliação dos eventos Weni usa o acesso Weni configurado. A consulta à Marketing API exige a credencial Meta local e uma allowlist autorizada, conforme o guia nativo.
## Separação entre anúncio e canal

A origem de anúncio nunca deve ser usada para fabricar `contact_urn`. Se um anúncio do Instagram abrir WhatsApp, a URN continua sendo de WhatsApp e a origem do anúncio permanece nos campos `primeiro_anuncio_*`/`ultimo_anuncio_*`. Se a conversa ocorrer no Instagram ou Facebook/Messenger, o canal é determinado exclusivamente pela URN que a Weni retornar.


## Convivência com Google Ads
Os campos genéricos `primeiro_anuncio_*` e `ultimo_anuncio_*` também podem receber Google Ads quando houver evidência explícita na Weni. Isso não transforma a aba `Campanhas_Meta` em uma integração Google Ads: custos, impressões e cliques de campanhas Google continuam exigindo uma integração própria com Google Ads.
