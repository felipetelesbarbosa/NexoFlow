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

A suíte integra o `comandos/check-up.bat` e o fluxo de publicação do NexoFlow 1.0.

Na raiz do repositório, com as dependências instaladas, execute:

```text
python -m unittest discover -s tests -t . -p "test_*.py" -v
```

Use `-t .` para carregar `tests/__init__.py` antes dos módulos do projeto. A suíte injeta configuração fictícia em memória, sem ler `secrets_config.py`, e bloqueia conexões reais de rede; clientes e planilhas são simulados. O `conftest.py` aplica o mesmo ambiente ao pytest. O check-up e o GitHub Actions usam esse modo de descoberta.

Os testes de pedidos verificam a normalização dos enums oficiais e a preservação dos valores brutos da API. Pagamento 0 ou `_` grava `pedido_forma_pagamento=Cancelado` e status efetivo 3 na Weni; pagamento 5 é **Pix por Link de Pagamento** e 6 é **Pix no POS**. A leitura e a auditoria continuam aceitando o literal legado `CANCELADO`, sem distinguir maiúsculas de minúsculas. Códigos numéricos Int32 desconhecidos a partir de 7 usam `Não identificado (código X)`. Pedidos validados pela API com status efetivo -2, -1, 0, 4, 1 ou 2 entram nas vendas e atualizam `ultima_compra`; entre os estados documentados, somente 3 exclui a venda, incluindo cancelamento explícito ou pagamento 0. Os estados -2, -1, 0, 4 e 1 permanecem em rechecagem a cada nova carga.

Os testes de identidade usam somente valores fictícios. CPF matematicamente válido dispensa comparação de nome, telefone ou e-mail; a reposição de zeros à esquerda só é aceita quando os dígitos verificadores são válidos. CPF inválido exige primeiro nome correspondente ou número local do telefone correspondente do mesmo cliente, ignorando +55 e DDD e preservando os bloqueios por ambiguidade.

Consulte [Pedidos](../docs/PEDIDOS.md) para o contrato completo. A validação dos executáveis e os smoke tests de instalação são executados no Windows pelo [workflow da release v1.0](../.github/workflows/release-v1.yml).

A reconsulta do histórico no Analytics usa a data do pedido em America/Belem, incluindo hoje e os 20 dias anteriores. Pedidos já registrados fora dessa janela são preservados; a consulta por CPF continua detectando compras novas. Os testes cobrem o limite de 20/21 dias, fuso horário, cancelamentos com itens incompletos, checkpoint parcial e preservação das chaves legadas.
