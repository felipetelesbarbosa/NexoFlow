# Webhook de pedidos - preparado, não ativado

O projeto está preparado para capturar cada pedido em tempo real no futuro, mas o funcionamento atual continua sendo feito por sincronização periódica da API da Weni.

## Situação atual

Ativo agora:

Weni → API de contatos → Python → Google Sheets

O Python lê `ultimo_pedido` e salva o histórico nas abas:

- `Pedidos_FarmaLider`
- `Itens_Pedidos_FarmaLider`
- `Metricas_Vendas`

Nenhum fluxo da Weni precisa ser alterado nesta etapa.

## O que ficou preparado

Endpoint futuro:

`POST /weni/pedido`

Health check:

`GET /health`

Arquivos:

- `webhook_pedidos.py`
- `run_webhook_pedidos.py`
- `requirements-webhook.txt`

O webhook reutiliza o mesmo parser de `ultimo_pedido` usado pela
sincronização normal. Assim, os dados gerados pelas duas rotas têm
a mesma estrutura.

## Segurança futura

Quando o webhook for ativado, ele exigirá:

`X-Webhook-Secret`

O segredo ficará em `secrets_config.py`, que não entra no Git.

Enquanto:

`WEBHOOK_PEDIDOS_ENABLED = False`

o endpoint de pedidos responde `503` e não grava nada.

## Payload previsto

Exemplo:

```json
{
  "contact_uuid": "UUID_DO_CONTATO",
  "contact_urn": "tel:+5591...",
  "cliente": "Nome do cliente",
  "cpf": "",
  "ultimo_pedido": {
    "data_hora": "2026-09-30T16:07:00Z",
    "valor_total_compra": 110.80,
    "produtos": [
      {
        "nome": "Dipirona Gotas 20ml",
        "quantidade": 2,
        "valor_unitario": 8.50,
        "valor_total": 17.00
      }
    ]
  }
}
```

`ultimo_pedido` pode ser enviado como objeto JSON ou como texto contendo
o JSON.

## Quando formos ativar

A ativação futura exigirá, nessa ordem:

1. definir onde o endpoint ficará hospedado;
2. disponibilizar HTTPS público;
3. gerar `WEBHOOK_SHARED_SECRET`;
4. instalar `requirements-webhook.txt`;
5. definir `WEBHOOK_PEDIDOS_ENABLED = True`;
6. configurar na Weni a chamada ao endpoint após gravar `ultimo_pedido`;
7. testar duplicidade e concorrência com a sincronização periódica;
8. somente depois colocar em produção.

## Importante

Não execute `run_webhook_pedidos.py` agora.

A sincronização periódica continua sendo o processo oficial nesta fase.
