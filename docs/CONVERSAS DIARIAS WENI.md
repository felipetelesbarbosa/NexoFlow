# Conversas diárias do Delivery FarmaLíder · homologação

O produtor é o Weni Insights. O conector oficial identifica o projeto por UUID e recebe datas civis inclusivas. A requisição de um único dia repete a data em `start_date` e `end_date`. O Work conferiu o fuso America/Belem no cadastro do projeto. Na conexão autorizada do conector, seis consultas de 01 a 06/11/2026 reproduziram as 24 contagens da referência privada. Os quatro totais são lidos de `total_conversations.value`, `resolved.value`, `unresolved.value` e `transferred_to_human.value`. Eventos de Flows, salas de Chats e atribuição de anúncios têm outros grãos.

## Acesso para o Windows

Solicitar à Weni/VTEX: “Precisamos de acesso de serviço **somente leitura**, sem sessão de usuário, para os quatro totais diários de conversas de Insights do projeto Delivery FarmaLíder, no fuso America/Belem. Confirmem o GET HTTPS em `insights-engine.weni.ai/v1/metrics/conversations/totals/`, os parâmetros project_uuid/start_date/end_date, o formato Bearer, audience, papel/escopo exato, emissão, expiração e renovação suportada para agendamento no Windows. Confirmem se nossa credencial existente de projeto permite essa consulta e quais são as cotas.”

A autenticação do conector do Work foi interativa. A rota REST provém de uma implementação pública de terceiro. A autorização de serviço precisa de confirmação do fornecedor e teste no Windows. O cliente deste commit lê um bearer provisionado pelo canal privado. Um bearer de curta duração exige renovação pelo mecanismo suportado pelo fornecedor e substituição atômica do arquivo privado antes da próxima execução. Se o fornecedor exigir outro fluxo, aguardar a adaptação. Não copiar tokens de navegador nem tentar a chave de Flows no serviço por suposição. [Guia oficial](https://developers.vtex.com/docs/guides/connect-the-vtex-cx-platform-mcp) · [Rota REST de referência](https://github.com/AlanJaeger/weni-mcp/blob/bc9b46f5642c999ccb5a21fbcbe5172146d98406/server.py).

## Windows

O código exige atualização do Windows pelo Setup. Para homologação, usar o artefato `NexoFlow-1.5.43-pacotes` do workflow oficial do SHA aprovado. Extraia o ZIP do artefato, confira o SHA-256 de `NexoFlow-Setup-1.5.43.zip` contra `SHA256SUMS-1.5.43.txt`, extraia o ZIP do Setup, execute **NexoFlow Setup.exe** e escolha **Preserve**. No Terminal FARMA, `nexo versao` deve mostrar 1.5.43.

Somente no ambiente de homologação, em `PERFIS["FARMA"]` do secrets_config.py, configure `WENI_INSIGHTS_PROJECT_UUID` com o UUID oficial do projeto, `WENI_INSIGHTS_START_DATE = "2026-11-01"` e `WENI_INSIGHTS_ENABLED = True`. Use as opções existentes `ARMAZENAMENTO_BACKEND = "postgres"`, `DATASTUDIO_AMBIENTE = "homologacao"` e a credencial exclusiva de publicação desse ambiente. Para o teste curto use uma instalação/perfil de homologação que não esteja executando o Noturno comercial. A opção fica desligada por padrão. PET é excluído no código.

Provisione `C:\NexoFlow\credentials\weni\FARMA\insights.json` com os campos `segment` (FARMA), `project_uuid` (mesmo UUID), `timezone` (America/Belem) e `access_token` (bearer de serviço autorizado). Limite o acesso ao operador e à conta que executa o Noturno. Mantenha esse arquivo fora do Git, suporte e logs.

No Terminal NexoFlow, no perfil FARMA, teste primeiro uma leitura de um dia encerrado. Use os comandos específicos para homologar apenas as conversas, sem acionar as outras tarefas comerciais dos executáveis.

```powershell
Set-Location C:\NexoFlow
$py = '.\.venv\Scripts\python.exe'
& $py -B app/weni_insights.py conferir-acesso --inicio 2026-11-01
if ($LASTEXITCODE) { throw 'Acesso Insights pendente.' }
& $py -B app/weni_insights.py coletar --inicio 2026-11-01 --fim 2026-11-06
if ($LASTEXITCODE) { throw 'Coleta incompleta. Os dias válidos estão guardados.' }
& $py -B app/weni_insights.py publicar
if ($LASTEXITCODE) { throw 'Publicação pendente. Repetir publicar no mesmo ambiente.' }
& $py -B app/weni_insights.py publicar
```

A última chamada deve informar zero novos recibos. O Weni normal coleta na etapa de aplicação. Check-only, simulação e Recompra não coletam dias. O incremental pesquisa lacunas desde a data configurada até ontem em Belém. Uma reconsulta explícita de intervalo atualiza os dias com resposta integral. O SQLite privado `logs/privado/weni_insights.sqlite` usa projeto e data como chave e só registra o recibo do destino após o commit e a confirmação da API. Se faltar resposta, repetir publicar. O Analytics com backend PostgreSQL drena esse banco mesmo no incremental sem novos contatos. No backend Sheets a aba original permanece com seu produtor anterior.

## VPS e cópia do Looker

Usar a mesma imagem do commit aprovado no leitor e no publicador de homologação. Com o banco Data Studio de homologação, roles já provisionadas, arquivo de DSN administrativo privado e rede privada existentes, o Work executa:

```bash
docker build --build-arg NEXOFLOW_SOURCE_SHA="$(git rev-parse HEAD)" -t "nf-ds:$(git rev-parse HEAD)" -f integrations/datastudio/Dockerfile .
docker run --rm --network "${REDE_PG:?}" -v "${DSN_ADMIN:?}:/run/secrets/admin-dsn:ro" "nf-ds:$(git rev-parse HEAD)" python -m integrations.datastudio.admin --dsn-file /run/secrets/admin-dsn --ambiente homologacao --segmento FARMA --instalar-conversas-projeto "${PROJETO_FARMA:?}"
```

A instalação vincula um único UUID à fonte. Uma segunda execução com UUID diferente falha. O leitor recebe SELECT na visão dos oito campos. O publicador recebe acesso aos dias do projeto autorizado. O contrato manual `Conversas_Diarias`, a assinatura do catálogo de fatos e a READY financeira permanecem independentes. Use a implantação privada do conector da cópia com Code.js e Schemas.js deste commit e os demais arquivos do mesmo diretório. Selecione FARMA, homologacao, BI_Weni_Conversas_Diarias. O leitor requer uma publicação financeira ativa já existente como as demais fontes. Solicite os seis dias com dimensão data, confira cada métrica, o total das seis linhas e o reenvio sem duplicidade. Um zero recebido vale zero; uma data solicitada sem registro confirmado bloqueia o resultado com DS_INSIGHTS_COBERTURA_INCOMPLETA. Consulta Weni falha conserva o último valor válido do dia.

Para suspender, desligue WENI_INSIGHTS_ENABLED no perfil FARMA e restaure a fonte anterior na cópia. Mantenha cache, recibos, tabelas e dados. O teste não requer reenviar pedidos ou reabrir a READY.
