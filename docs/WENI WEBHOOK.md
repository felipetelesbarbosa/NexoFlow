# Captura exata de cada conversa originada por anúncio

A rotina diária mantém corretamente o primeiro anúncio e o anúncio mais recente, mas não preserva anúncios intermediários.

Para responder com precisão **quantas conversas cada anúncio gerou**, o referral precisa ser registrado no momento em que chega à Weni.

O projeto já inclui `webhook_eventos.py` com o endpoint:

`POST /weni/meta-event`

Para usar:

1. Instale `requirements-webhook.txt`.
2. Publique o serviço em uma URL HTTPS acessível pela Weni.
3. Configure o fluxo da Weni para enviar o referral para essa URL.
4. Envie o header `X-Webhook-Secret`.

Payload esperado:

```json
{
  "contact_uuid": "...",
  "contact_urn": "...",
  "source_type": "ad",
  "source_id": "...",
  "headline": "...",
  "source_url": "...",
  "ctwa_clid": "...",
  "received_at": "..."
}
```

Não altere o fluxo da Weni até a URL HTTPS do servidor estar definida.
