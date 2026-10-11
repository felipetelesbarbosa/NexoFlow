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
python -m unittest discover -s tests -t . -p "test_*.py" -v
```

Use `-t .` para carregar `tests/__init__.py` antes dos módulos do projeto. A suíte injeta configuração fictícia em memória, sem ler `secrets_config.py`, e bloqueia conexões reais de rede; clientes e planilhas são simulados. O `conftest.py` aplica o mesmo ambiente ao pytest. O check-up e o GitHub Actions usam esse modo de descoberta.

Os testes de pedidos verificam a normalização dos enums oficiais e a preservação dos valores brutos da API. Pagamento 0 ou `_` grava `pedido_forma_pagamento=Cancelado` e status efetivo 3 na Weni; pagamento 5 é **Pix por Link de Pagamento** e 6 é **Pix no POS**. A leitura e a auditoria continuam aceitando o literal legado `CANCELADO`, sem distinguir maiúsculas de minúsculas. Códigos numéricos Int32 desconhecidos a partir de 7 usam `Não identificado (código X)`. O status -1, `PendenteDePagamento`, permanece em rechecagem e fora das vendas; status efetivo 4 (Pronto para rota), 1 (Em trânsito) ou 2 (Concluído), validado pela API e sem cancelamento entra nas vendas e atualiza `ultima_compra`.

Consulte [Pedidos](../docs/PEDIDOS.md) para o contrato completo. A validação dos executáveis e os smoke tests de instalação são executados no Windows pelo [workflow da release v1.0](../.github/workflows/release-v1.yml).
