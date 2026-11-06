# Histórico paginado — homologação do Hub

O marco Windows foi validado antes desta implementação. A rota/envelope agora são conhecidos: `GET /api/Delivery/pedidos/{segmento}` com período, página e limite ajustável. O módulo puro `app/order_history.py` é compartilhado, incluindo dinheiro em centavos, identidade oficial, paginação, status, itens, calendário e regras de LTV. `OrderEvidence` não recebe CPF artificial para aprovar compras históricas.

## API interna

`POST /tarefas/historico`, autenticado com a chave do próprio segmento:

```json
{"segmento":"PET","origem":"n8n","chave":"historico-hml-001","inicio":"2026-11-01","fim":"2026-11-06","limite":100,"max_paginas":2,"modo":"historica","reiniciar":false,"quantidade_sintetica":205}
```

A resposta é 202 e informa a tarefa persistida. Consulte as rotas existentes `/tarefas/{id}`, `/resultado` e `/erros`. Nenhum segredo, URL de destino ou pedido comercial é aceito no corpo. `quantidade_sintetica` é exclusivo da fixture de homologação, limitado a 1.200 registros; **não é limite da API comercial**. `limite` aceita int32 positivo, incluindo 500 e 1.000.

Com 205 registros/limite 100/orçamento duas páginas, a primeira tarefa termina parcial com 200. Uma nova chave, mesmos parâmetros de janela e `reiniciar=false`, retoma na página 3 e fecha em 205. Repetir a mesma chave é idempotente. Alterar parâmetros da mesma chave retorna 409. `reiniciar=true` reabre explicitamente a faixa, mantendo os fatos deduplicados. Trocar limite usa outra chave de cursor e começa na página 1.

O modo incremental exige a faixa de hoje até D−20 em America/Belem, reconsulta janelas concluídas e retoma as incompletas. Datas arbitrárias são recusadas nesse modo.

O worker desta fase usa exclusivamente `SyntheticHistorySource`, com `httpx.MockTransport`, GET e query serializados para domínio `.invalid`; zero chamadas comerciais. A interface `get_pedidos_history(query,page)` é compatível com o cliente Windows. A futura conexão comercial requer injeção do cliente/credenciais por segmento e homologação de rede; não está ativada. A lógica de validação financeira e de paginação não é duplicada no n8n.

## Persistência e retomada

A migração `002_up.sql` adiciona tipo/parâmetros às tarefas e tabelas `historico_janelas`, `historico_recebidos`, `historico_pedidos`, `historico_pendencias`, `historico_revisoes`, `historico_ltv`. Itens mínimos são persistidos dentro do JSON normalizado do pedido, preservando seus IDs; não há endereços ou observações. Chaves incluem segmento. Cada página, revisão, LTV dos clientes afetados e checkpoint são uma transação PostgreSQL.

O worker valida proprietário/lease sob lock antes de gravar. Worker antigo é recusado. Crash após página confirmada retoma da próxima; falha antes do commit não deixa faturamento nem cursor parcial. A extração só fecha quando IDs únicos recebidos coincidem com o total declarado, antes de excluir cancelados. A tabela `hub.cobertura` continua `incompleta` para cobertura **temporal**, mesmo quando a extração do envelope termina: inclusividade da data final ainda não foi demonstrada.

Pedidos oficiais sem Weni integram LTV por `codCliente`. Não inventar contato, CPF, Opt-In ou anúncio. O índice puro de vínculo Weni está disponível para a futura fase cadastral; não há leitura nem escrita comercial Weni no worker sintético. As regras de valor/cancelamento seguem o Windows. Cancelamento antigo requer reconciliação explícita; omissões ou dados inválidos preservam fato anterior e registram pendência.

## Executar e verificar

Use os comandos Docker e os segredos temporários do [guia do Hub](README.md). O helper `hub/tests/run_docker_hml.py --build --pytest` inclui os testes históricos, API HTTP real no contêiner, worker real e PostgreSQL 18.6. Após reinício dos serviços, confere a tarefa e os resultados persistidos. Nenhuma porta pública ou infraestrutura existente é alterada.

A instalação de versão 1 do schema é testada, recebe uma tarefa normal e migra para 2 sem perdê-la. A reversão recusa dados históricos/tarefas existentes. Rollback de aplicação: parar somente API/worker de homologação e preservar volume/banco; não tentar rodar um binário de schema 1 sobre schema 2. Restaurar backup em banco temporário separado para voltar ao schema anterior. `002_down.sql` só é aplicável em ambiente de homologação sem histórico; não executar sobre banco de produção.

O workflow `n8n/historico-homologacao.json` fica inativo, manual e com credencial Header Auth a configurar. Não importar/ativar automaticamente no n8n da VPS. Os locks PostgreSQL continuam sem coordenação com Windows; escrita comercial do Hub segue bloqueada.
