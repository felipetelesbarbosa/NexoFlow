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

Quando a resposta possui `ultimoPedido`, essa referência pode ser usada para
consultar o último pedido específico. Na resposta oficial, `cliente` e
`ultimoPedido` são objetos separados; o objeto legado com campos do cliente
diretamente na resposta também é aceito para validar o vínculo. O NexoFlow
confere o CPF do retorno e o cliente antes de aceitar essa associação.

## Pedido por código

```text
GET /api/Delivery/pedido/{codigo}?token=...
```

O identificador pode vir do JSON `ultimo_pedido`, dos campos `pedido_*` da Weni
ou do fallback `ultimoPedido` da resposta por CPF. O projeto usa esse endpoint para confirmar
e enriquecer o pedido, conferindo o identificador retornado e o titular.

O retorno usado possui informações de capa e itens. Entre os dados persistidos
estão emissão, filial, cliente, status, forma de pagamento, cupom, frete,
cancelamento, entrega e totais derivados dos itens.

### Status do Pedido

A documentação fornecida pelo usuário, **Integração API Líder.pdf**, seção **Status do Pedido**, define:

| Código | Identificador oficial | Rótulo em português |
|---|---|---|
| 0 | `EmProcessamento` | Em processamento |
| 1 | `EmTransito` | Em trânsito |
| 2 | `Concluido` | Concluído |
| 3 | `Cancelado` | Cancelado |
| 4 | `ProntoParaRota` | Pronto para rota |

O NexoFlow preserva o código em `farmalider_status_pedido` e acrescenta o rótulo oficial conhecido em `farmalider_status_pedido_nome`. Para código ausente ou desconhecido, o nome fica vazio; “Status não conhecido” pode ser exibido pelo dashboard como aviso derivado, sem criar um estado oficial. O código **3** é tratado como cancelado independentemente de existir timestamp de cancelamento. Valores fora desse de-para mantêm o código original sem atribuir um significado por suposição.

Os indicadores de vendas do NexoFlow admitem somente **Concluído (código 2)**, com dados válidos e sem cancelamento. Estados 0, 1 e 4 continuam sendo capturados para os campos de pedido e auditoria, mas ficam fora desses indicadores; código 3, status ausente ou desconhecido também ficam fora. Um cancelamento explícito prevalece sobre um eventual código 2.

`ultima_compra` exige adicionalmente confirmação pela API. Concluído descreve o estado operacional/logístico do pedido e, por si só, não comprova pagamento. A cobertura é dos pedidos identificados pelo NexoFlow, sem presumir todas as vendas da FarmaLíder ou origem causal em anúncios. Veja as regras completas em [Pedidos no NexoFlow 1.0](PEDIDOS.md).

## Limitação atual

O contrato usado pelo projeto não fornece uma rota para listar todo o histórico
de pedidos por CPF/cliente.

Consequência:

```text
CPF → confirma/vincula cliente → ultimoPedido, quando disponível
pedido_id → confirma/enriquece pedido específico
```

Se os campos da Weni não fornecerem um pedido utilizável com identificador
oficial, a referência de último pedido do cliente pode suprir essa informação.
Isso não recupera automaticamente todos os pedidos anteriores. Cancelamentos,
valores, frete e origem do total são preservados; cancelamentos não entram nas
métricas de venda. Datas de pedidos usam `America/Belem` (UTC−3).
Consulte [Pedidos no NexoFlow 1.0](PEDIDOS.md).

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

A API usada permite localizar cliente por CPF, obter sua referência de último pedido quando disponível e consultar pedido por código, mas não lista o histórico de pedidos de um cliente. Como evolução recomendada da FarmaLíder API, criar uma rota de consulta por CPF, preferencialmente paginada e com filtros de período/status, por exemplo:

```text
GET /api/Delivery/pedidos/cpf/{cpf}
```

Filtros desejáveis: `inicio`, `fim`, `status`, `pagina` e `tamanhoPagina`. Essa rota é uma proposta de evolução, não uma integração atualmente implementada.
