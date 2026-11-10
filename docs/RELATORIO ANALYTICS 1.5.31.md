# Relatório de desenvolvimento — 1.5.31

Em validação em 10/11/2026 (America/Sao_Paulo). Código, fixtures e pacotes; nenhuma execução comercial, nova coleta anual ou alteração de relatório/VPS.

## Causa e mudança

O Analytics já chamava `analytics_history` para pedidos recentes, mas não chamava o publicador das cinco tabelas históricas. Elas dependiam da operação manual Terminal. A fachada nova `analytics_history_sync` liga essas etapas sem substituir o motor e sem modificar os dez módulos que assinam os recibos 1.5.29/30.

A coleta agora usa trava histórica também no Analytics. Datas completas são explícitas via CLI e herdadas por subprocessos; a execução incremental mantém hoje..D-20, limite padrão 500. Uma carga completa de contatos não dispara automaticamente coleta anual. A revisão encontrou que collect_windows também retomava janelas antigas incompletas: o Analytics agora usa resume_pending=False e consulta somente o período autorizado; o Terminal mantém a retomada antiga. Regressão semeia uma janela pendente de 2020 e comprova que a carga diária consulta só D-20, nos dois perfis.

A publicação cria uma cópia consistente, herda exclusões comprovadas do journal publicado, prepara capacidade e revisão, salva o estado antes de escrever e retoma o mesmo plano após falha. Uma revisão manual WRITING bloqueia tomada automática. Fatos excluídos alterados exigem revisão. Na retomada, pedidos posteriores ao snapshot são explicitamente pendentes para a próxima execução. Só após conferência integral o estado muda para conferida. Falhas geram código 3 e mantêm o checkpoint de sucesso.

`history_sheets_bulk` e `history_batch_progress`, já na main antes desta entrega, acrescentam frações e diagnóstico do lote; incluídos na distribuição. `duration_display` centraliza apresentação em minutos/horas nos logs comuns e no histórico, preservando dados numéricos e formatos HH:MM:SS existentes.

## Arquivos principais

- Novos: app/analytics_history_sync.py, app/duration_display.py, tests/test_analytics_history_sync.py e guia ANALYTICS HISTORICO AUTOMATICO.
- Integração: app/main.py, app/order_history_store.py, app/nexo_cli.py.
- Apresentação: app/logging_config.py, app/run_order_history.py, app/history_publish_cli.py, app/history_sheets_quota.py e mensagem parcial do BAT.
- Distribuição: VERSION, pyproject, instalador, workflow, scripts/contrato de pacotes e metadados alinhados 1.5.31. Preserve não sobrescreve credenciais/configurações existentes.

## Evidências locais

Fixtures SQLite e Sheets executam o motor real: fração, pausa, fechamento, execução idêntica sem reenvio, resposta perdida, revisão manual, alterações posteriores à coleta, fontes FARMA/PET e exclusões. Testes da CLI verificam validação de datas, propagação e restauração do ambiente. Testes do pipeline Analytics verificam publicação parcial sem avançar checkpoint e confirmação com avanço; rotinas BI existentes permanecem executadas.

Entrada nativa do publicador testada com transporte real sobre três arquivos simulados (grade inicial de 18.413.260 células), criação de continuações e repetição sem novas gravações.

Teste real da coleta sobre API simulada verifica janela D-20, novo pedido e cancelamento reconsultado nos dois perfis. Testes anteriores cobrem quota/429, rollback protegido, partes, idempotência e assinaturas. Não substituem validação do Google comercial.

Lint, tipos, Node (33 testes), consistência, dependências e segredos aprovados localmente. Resultado completo Python e Windows/CI deve ser conferido no SHA final antes de publicar; não considerar este documento aprovação antecipada dos jobs.

## Limites

- Configuração inicial continua necessária: três arquivos, OAuth, origens, capacidade e cinco fontes reais confirmadas. Não afirmar atualização de tabelas opcionais desabilitadas ou sem dados.
- O journal/snapshot da última publicação é necessário para herdar exclusões. Perda desses arquivos bloqueia a automação, não autoriza esquecer exclusões.
- Incremental escreve diferenças, mas a preparação ainda precisa ler as partes e conferir. Não há prazo garantido nem promessa de zero429 com concorrência externa.
- Pendências e LIMITES_DA_API_NAO_HOMOLOGADOS permanecem. Não alterar filtros/atribuição para preencher métricas ausentes.
- O Hub não foi implantado; alterações Windows não ativam fluxos comerciais na VPS. Os módulos financeiros compartilhados não tiveram mudança de política.
- A diagramação do Data Studio e a homologação comercial pós-atualização permanecem com o Work.

Operação: consultar [o guia](ANALYTICS%20HISTORICO%20AUTOMATICO.md). Primeiro FARMA; ativação PET separada.

## Conferência de codificação no Windows

A matriz com UTF-8 desativado identificou duas verificações de teste que reabriam o estado privado UTF-8 com a codificação padrão do sistema, alterando os acentos e produzindo REVISAO_ALTERADA. As quatro leituras do estado na fixture agora especificam UTF-8, como já faz a implementação operacional. A assinatura e as guardas do publicador não foram alteradas. A distribuição exige repetir a matriz no commit corrigido.

O build de publicação também revelou uma corrida na fixture Windows de revisão XLSX: Test-Path podia encontrar dialog_open durante o Set-Content, e a leitura Python recebia PermissionError. O sinal simulado agora é escrito em arquivo temporário e renomeado somente após fechar a escrita, como já ocorria com a resposta decision. Nenhum script operacional, regra de aprovação ou timeout foi relaxado; a matriz e o pacote devem ser revalidados no novo SHA.

A fixture publica o sinal somente na primeira abertura: a segunda tentativa de confirmação deve reutilizá-lo. O cenário de cancelamento foi reproduzido diretamente com PowerShell isolado (código 3 antes, código 2 após a correção); a aprovação retorna 0 em ambos. Isso não altera o diálogo operacional.
