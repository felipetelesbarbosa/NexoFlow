# NexoFlow 1.0 — Testes

Suíte automatizada do NexoFlow 1.0.

Os testes cobrem, entre outros pontos:

- atribuição de anúncios;
- Analytics e camada BI;
- enriquecimento de contatos;
- integração FarmaLíder;
- resolução e reconciliação de pedidos;
- proxy;
- schemas do Google Sheets;
- URNs e multicanal;
- cliente Weni;
- Update Weni, auditoria e segurança de escrita;
- preparação dos webhooks opcionais.

A suíte integra o `check-up.bat` e o fluxo de publicação do NexoFlow 1.0.

Na raiz do repositório, com as dependências instaladas, execute:

```text
python -m unittest discover -s tests -p "test_*.py" -v
```

Os testes de pedidos verificam a normalização dos enums oficiais e a preservação dos valores brutos da API. Pagamento 0 ou `_` grava `pedido_forma_pagamento=Cancelado` e status efetivo 3 na Weni; pagamento 5 é **Pix por Link de Pagamento** e 6 é **Pix no POS**. A leitura e a auditoria continuam aceitando o literal legado `CANCELADO`, sem distinguir maiúsculas de minúsculas. Códigos numéricos Int32 desconhecidos a partir de 7 usam `Não identificado (código X)`. O status -1, `PendentePagamento`, permanece em rechecagem e fora das vendas; somente status efetivo 2, Concluído, validado pela API e sem cancelamento entra nas vendas e atualiza `ultima_compra`.

Consulte [Pedidos](../docs/PEDIDOS.md) para o contrato completo. A validação dos executáveis e os smoke tests de instalação são executados no Windows pelo [workflow da release v1.0](../.github/workflows/release-v1.yml).
