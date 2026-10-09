# NexoFlow 1.0

## Atendimentos Delivery com as tags Pedido e Pedido finalizado

O comando `run_delivery_tickets.py` reconcilia os clientes dos atendimentos humanos encerrados com essas tags. As tags são lidas na **API externa v2 do Weni Chats**, não nos tópicos/setores ou nas etiquetas de mensagens da API de Flows.

### Configuração local

Preencha em `secrets_config.py`, que permanece fora do Git e dos pacotes:

```python
WENI_CHATS_API_BASE_URL = "https://ORIGEM_DA_API_DO_SEU_CHATS"
WENI_CHATS_API_TOKEN = "TOKEN_DE_INTEGRACAO_DO_PROJETO"
WENI_CHATS_ORDER_ID_FIELD = "pedido_id"
```

O token de integração do Chats é um Bearer UUID do projeto **Delivery FarmaLíder**. Ele é diferente do `WENI_API_TOKEN` usado para contatos e mensagens. A origem deve ser a API, não a página do navegador, sem caminhos, parâmetros ou credenciais. O token restringe as consultas ao projeto: confirme essa organização antes de configurar. O comando lê `GET /v2/external/rooms_metrics/`, todas as páginas de atendimentos encerrados até o corte da execução, sem janela inicial de 90 dias. Redirecionamentos e paginação para outro destino são bloqueados.

**Como obter os dados:** no código oficial da Weni, o token de integração é chamado `project_auth` e fica na configuração do serviço de atendimento (`ticketer`) que conecta Chats e Flows. A API pública `/api/v2/ticketers.json` mostra UUID, nome, tipo e data de criação; não entrega esse segredo. Solicite ao administrador da integração ou ao suporte da Weni/VTEX o `project_auth` do projeto Delivery FarmaLíder e a origem HTTPS da API do Chats, com acesso de leitura a `GET /v2/external/rooms_metrics/`. Se a configuração administrativa já mostrar esse valor, copie-o diretamente para o arquivo local, sem publicar no GitHub.

Para identificar a origem da API, abra Atendimento/Chats no navegador, pressione F12, entre em Rede/Network e observe a URL de uma requisição de salas/atendimentos ao Chats. Use somente a origem (`https://host`), sem caminho ou parâmetros. O Bearer da sessão do navegador pode ser um JWT temporário de login; ele não substitui o UUID de integração exigido pela API externa.

Referências oficiais: [configuração `project_auth` da integração com Flows](https://github.com/weni-ai/chats-engine/blob/main/chats/apps/projects/usecases/integrate_ticketers.py) e [autenticação do projeto na API externa](https://github.com/weni-ai/chats-engine/blob/main/chats/apps/accounts/authentication/drf/authorization.py). O índice de API v2 de Flows enviado no chat não contém instruções para obter o token de Chats.

A API externa também documenta o filtro `tag_name`, por exemplo `GET /v2/external/rooms_metrics/?is_active=false&tag_name=Pedido`. Para a segunda tag, o valor é `Pedido%20finalizado`, respeitando o nome cadastrado. O NexoFlow lê todas as páginas encerradas e compara as duas tags localmente, para lidar com capitalização, tickets com ambas as tags e diferenças de espaços sem duplicação.

O campo opcional `WENI_CHATS_ORDER_ID_FIELD` identifica o campo estruturado do ticket que contém o ID oficial do pedido. O NexoFlow não inventa esse campo: se não existir, o vínculo do pedido com aquele atendimento continua pendente.

### Preparação e revisão

No terminal do projeto:

```powershell
python run_delivery_tickets.py --dry-run
```

Revise `logs/delivery_review.txt`. O JSON correspondente contém o plano congelado, os pedidos, itens, tickets e hashes; ambos são privados. Nenhuma alteração na Weni ou no Google Sheets ocorre nessa etapa. O log exibe totais, não nomes, CPFs ou conteúdo de conversas.

Depois de revisar:

```powershell
python run_delivery_tickets.py --apply --require-review logs/delivery_review.json
```

O apply relê cada contato e bloqueia alterações nas informações usadas para identificar o cliente ou validar o pedido. Contatos em conflito não são gravados nem publicados como reconciliação bem-sucedida. As gravações são idempotentes; se uma integração falhar depois de outras gravações, retome com o mesmo snapshot. Esse comando não altera o checkpoint da carga geral, grupos ou consentimento LGPD.

### Validação e limitações

- Seleciona exatamente as tags Pedido e Pedido finalizado, desconsiderando maiúsculas e espaços duplicados. Exige encerramento, evidência de atendente e `contact.external_id` válido para o UUID de contato da Weni. IDs internos de contato do Chats não substituem esse vínculo.
- Deduplica tickets e clientes; consulta primeiro CPFs válidos e depois os inválidos preenchidos, incluindo zero. CPF inválido mantém a exigência de nome completo + e-mail ou nome completo + telefone, do mesmo cliente. Ambiguidade, divergência e dados insuficientes bloqueiam o pedido.
- Usa a lógica oficial de confirmação FarmaLíder já existente, preservando proprietário, itens, descrição, quantidades, preços, status, pagamento e emissão. Uma tag não confirma venda. HTTP 500 não significa ausência de cliente ou pedido.
- Atualiza os campos `pedido_*` e `ultima_compra` conforme as regras do NexoFlow. Não substitui um pedido mais recente na Weni por outro mais antigo. Vendas são status 4, 1 e 2, sem cancelamento ou pagamento 0.
- `cliente/cpf` informa **somente o último pedido**. Quando o ticket contém um ID estruturado de outro pedido, o comando consulta `pedido/{id}` e exige o mesmo cliente identificado nesta execução. O campo mais recente da Weni é preservado; o pedido histórico entra na planilha. Sem ID, a API não recupera automaticamente todos os pedidos históricos dos tickets. O comando não interpreta a última compra como compra gerada naquele atendimento.
- `CONFIRMADO_POR_ID`: o ID estruturado do ticket corresponde ao pedido confirmado pela API para o cliente. `COMPATIVEL_COM_PERIODO_SEM_ID`: emissão dentro do atendimento, apenas indício. `FORA_DO_PERIODO_DO_ATENDIMENTO` ou `OUTRO_PEDIDO_NO_TICKET`: o último pedido não comprova aquela compra. Sem ID e sem histórico consultável, registre a pendência.

### Google Sheets e Looker Studio

Após o apply, pedidos e itens entram em `Pedidos_FarmaLider` e `Itens_Pedidos_FarmaLider`; contatos entram em `Base_Contatos`. `BI_Vendas` e `BI_Pedidos` são reconstruídas preservando os demais pedidos históricos, com a data real de emissão da API. Datas operacionais usam `America/Belem` (UTC-3).

As métricas de vendas são recalculadas; o resumo e a conversão recebem um snapshot da base no corte revisado. Esses snapshots continuam distintos das datas de emissão: gráficos de vendas por período devem usar `BI_Vendas`, `BI_Pedidos` ou a fonte de pedidos de Delivery, não totais acumulados do resumo.

Duas fontes adicionais são criadas apenas ao aplicar essa reconciliação:

| Aba | Granularidade e uso |
| --- | --- |
| `Tickets_Delivery_Weni` | Uma linha por ticket, com tags, datas do atendimento, resultado da checagem e vínculo do pedido. Permite contar atendimentos marcados, pedidos encontrados e pendências. |
| `BI_Delivery_Pedidos` | Uma linha por pedido único confirmado de clientes atendidos com essas tags, com ID de cliente, data real de emissão, valor, status e indicador de venda. Não replica o valor por ticket. |

No Looker, conecte as novas abas na mesma planilha. Para **vendas vinculadas aos atendimentos**, filtre `venda_realizada = 1` e `vinculo_atendimento = CONFIRMADO_POR_ID`; use a dimensão de período `data`, some `pedido_valor` e conte pedidos distintos. Compradores do período são `COUNT_DISTINCT(cliente_id)`, sem somar compradores diários. Sem o filtro de vínculo, o título deve dizer “Pedidos confirmados de clientes com atendimentos marcados”, pois inclui pedidos cuja origem no atendimento não foi comprovada.

Após criar essas fontes, a carga normal do Analytics atualiza a BI de Delivery com os status e valores atuais dos pedidos já armazenados. Para buscar **novos tickets e alterações de tags**, repita a reconciliação Delivery com novo dry-run e revisão; a carga normal não lê as tags automaticamente.

Para indicadores de atendimento, use `encerrado_em` na fonte de tickets. Não use essa data para faturamento. Configure os campos ISO como Data/Data e hora conforme o conteúdo e exiba pt-BR. Acrescente cards de tickets sem pedido validado, divergência de identidade e vínculo pendente. Não some valores monetários da aba de tickets, pois um pedido pode aparecer em várias conversas.

O comando atualiza as fontes do Google Sheets. A conexão e configuração dos gráficos no Looker são feitas no editor do relatório; ele não altera permissões de compartilhamento.

Referência de schema e autenticação: [Weni Chats Engine, API externa v2](https://github.com/weni-ai/chats-engine/tree/main/chats/apps/api/v2/external/rooms).
