# FarmaLíder API - contrato usado pelo projeto

Documentação atual do uso da API pelo **NexoFlow**.

## Autenticação

A integração atual usa token pela QueryString:

```text
?token=...
```

Não envia `Authorization: Bearer`.

## URLs

Com proxy corporativo:

```text
https://api.farmalider.net.br/farmalider
```

Sem proxy:

```text
https://api.farmalider.net.br:3200/farmalider
```

## Cliente por CPF

```text
GET /api/Delivery/cliente/cpf/{cpf}?token=...
```

O CPF normalizado é a ponte de identidade entre os sistemas. O `contact_uuid`
continua sendo a chave principal da Weni.

Quando localizado, o projeto registra o `farmalider_cliente_id` e dados/status de
vínculo na `Base_Contatos`.

## Pedido por código

```text
GET /api/Delivery/pedido/{codigo}?token=...
```

Quando `ultimo_pedido` possui identificador oficial, o projeto usa esse endpoint
para confirmar/enriquecer o pedido.

O retorno usado possui informações de capa e itens. Entre os dados persistidos
estão emissão, filial, cliente, status, forma de pagamento, cupom, frete,
cancelamento, entrega e totais derivados dos itens.

## Limitação atual

O contrato usado pelo projeto não fornece uma rota para listar todo o histórico
de pedidos por CPF/cliente.

Consequência:

```text
CPF → confirma/vincula cliente
pedido_id → confirma/enriquece pedido específico
```

## Concorrência e proteção

A integração usa concorrência controlada:

- até 4 workers;
- lotes de até 500 CPFs;
- paralelismo somente a partir do limiar configurado;
- delay global mínimo de 10 ms entre inícios;
- sessão HTTP por thread;
- retry;
- cooldown e throttle após 429;
- circuit breaker;
- telemetria de latência;
- aviso de requisição lenta acima do limite configurado.

Os valores operacionais ficam em `config.py`.

## Melhoria futura: histórico de pedidos por CPF

A API publicada atualmente permite localizar cliente por CPF e consultar pedido por código, mas não lista o histórico de pedidos de um cliente. Como evolução recomendada da FarmaLíder API, criar uma rota de consulta por CPF, preferencialmente paginada e com filtros de período/status, por exemplo:

```text
GET /api/Delivery/pedidos/cpf/{cpf}
```

Filtros desejáveis: `inicio`, `fim`, `status`, `pagina` e `tamanhoPagina`. Uma rota opcional para apenas o último pedido também pode ser útil: `GET /api/Delivery/pedidos/cpf/{cpf}/ultimo`.
