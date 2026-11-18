# Conversas diárias do Delivery FarmaLíder · homologação

O perfil FARMA coleta classificações de conversas da API Flows v2 com o token do projeto. A fonte conta cada conversa uma vez por dia encerrado no calendário America/Belem. A comparação de 01 a 06/11/2026 com as quatro métricas do Insights fechou nos seis dias. Esse recorte teve 2.002 conversas, 465 resolvidas, 316 não resolvidas e 1.221 transferidas.

## Acesso pelo perfil

O cliente usa o cabeçalho Token em GET no host flows.weni.ai. Confere nome e fuso do workspace em /api/v2/org.json. O UUID retornado identifica o workspace Flows. A opção privada WENI_FLOWS_ORG_UUID permite também fixar esse UUID. O UUID do projeto Insights em WENI_INSIGHTS_PROJECT_UUID continua identificando os dias no cache e no destino e pode ser diferente.

A leitura de /api/v2/events.json seleciona a chave conversation_classification, valida o evento weni_nexus_data e pagina por limit/offset até receber uma página vazia. O dia é delimitado em UTC a partir da meia-noite de Belém. O UUID da conversa identifica repetições. Os valores resolved, unresolved e Has Chat Room classificam as conversas. O último requer human_support verdadeiro, e os demais exigem falso. A data do evento e a de encerramento devem pertencer ao mesmo dia de referência. Uma classificação divergente, data ambígua ou página incompleta deixa o dia pendente. Um GET transitório pode repetir a mesma página. O SQLite recebe somente as contagens após concluir o dia. Nenhum URN, UUID de conversa ou texto de evento integra o cache ou a publicação.

A rota de grupo retornou HTTP 500 durante a conferência e não é usada. A opção existente WENI_INSIGHTS_CREDENTIAL_SOURCE = "arquivo" continua reservada ao bearer dedicado do Insights. Esse transporte depende de autorização do fornecedor. Não há troca automática de credencial em caso de erro.

## Windows

Baixe o Setup da [release Windows 1.5.43](https://github.com/felipetelesbarbosa/NexoFlow/releases/tag/v1.5.43). Confira o SHA-256 com o arquivo de hashes da release. Extraia o ZIP completo, execute **NexoFlow Setup.exe** e escolha **Preserve**. A prévia de homologação 7b3d4bc também mostrava 1.5.43. Nesse caso, reinstale o Setup público e confira a coleta de um dia com o comando abaixo.

Somente no ambiente de homologação, em `PERFIS["FARMA"]` do secrets_config.py, configure `WENI_INSIGHTS_PROJECT_UUID` com o UUID oficial do projeto, `WENI_INSIGHTS_START_DATE = "2026-11-01"` e `WENI_INSIGHTS_ENABLED = True`. Use as opções existentes `ARMAZENAMENTO_BACKEND = "postgres"`, `DATASTUDIO_AMBIENTE = "homologacao"` e a credencial exclusiva de publicação desse ambiente. Para o teste curto use uma instalação/perfil de homologação que não esteja executando o Noturno comercial. A opção fica desligada por padrão. PET é excluído no código.

Com `WENI_INSIGHTS_CREDENTIAL_SOURCE = "perfil"` (padrão), use o token existente e dispense o JSON de Insights. Somente se a Weni fornecer um bearer exclusivo, configure `WENI_INSIGHTS_CREDENTIAL_SOURCE = "arquivo"`. Nesse caso, provisione `C:\NexoFlow\credentials\weni\FARMA\insights.json` com os campos `segment` (FARMA), `project_uuid` (mesmo UUID), `timezone` (America/Belem) e `access_token` (bearer de serviço autorizado). Limite o acesso ao operador e à conta que executa o Noturno. Mantenha esse arquivo fora do Git, suporte e logs.

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

A última chamada deve informar zero novos recibos. O Weni normal coleta na etapa de aplicação. Check-only, simulação e Recompra não coletam dias. O incremental pesquisa lacunas desde a data configurada até ontem em Belém. Uma reconsulta explícita de intervalo atualiza os dias com resposta integral. O SQLite privado `logs/privado/weni_insights.sqlite` usa projeto e data como chave e só registra o recibo do destino após o commit e a confirmação da API. Dias antigos e seus recibos conservam a origem WENI_INSIGHTS. A coleta com token do perfil registra WENI_FLOWS_V2. Se faltar resposta, repetir publicar. O Analytics com backend PostgreSQL drena esse banco mesmo no incremental sem novos contatos. No backend Sheets a aba original permanece com seu produtor anterior.

## VPS e cópia do Looker

Usar a mesma imagem do commit aprovado no leitor e no publicador de homologação. Com o banco Data Studio de homologação, roles já provisionadas, arquivo de DSN administrativo privado e rede privada existentes, o Work executa:

```bash
docker build --build-arg NEXOFLOW_SOURCE_SHA="$(git rev-parse HEAD)" -t "nf-ds:$(git rev-parse HEAD)" -f integrations/datastudio/Dockerfile .
docker run --rm --network "${REDE_PG:?}" -v "${DSN_ADMIN:?}:/run/secrets/admin-dsn:ro" "nf-ds:$(git rev-parse HEAD)" python -m integrations.datastudio.admin --dsn-file /run/secrets/admin-dsn --ambiente homologacao --segmento FARMA --instalar-conversas-projeto "${PROJETO_FARMA:?}"
```

Mesmo que a prévia já esteja instalada, reaplicar o comando administrativo com o mesmo UUID e atualizar o serviço de publicação antes do primeiro envio Flows. A migração aditiva conserva dias e recibos antigos e acrescenta a origem física da coleta à visão. A instalação vincula um único UUID à fonte. Uma segunda execução com UUID diferente falha. O leitor recebe SELECT na visão dos oito campos. O publicador recebe acesso aos dias do projeto autorizado. O contrato manual `Conversas_Diarias`, a assinatura do catálogo de fatos e a READY financeira permanecem independentes. Use a implantação privada do conector da cópia com Code.js e Schemas.js deste commit e os demais arquivos do mesmo diretório. Selecione FARMA, homologacao, BI_Weni_Conversas_Diarias. O leitor requer uma publicação financeira ativa já existente como as demais fontes. Solicite os seis dias com dimensão data, confira cada métrica, o total das seis linhas e o reenvio sem duplicidade. Um zero recebido vale zero; uma data solicitada sem registro confirmado bloqueia o resultado com DS_INSIGHTS_COBERTURA_INCOMPLETA. Consulta Weni falha conserva o último valor válido do dia.

Para suspender, desligue WENI_INSIGHTS_ENABLED no perfil FARMA e restaure a fonte anterior na cópia. Mantenha cache, recibos, tabelas e dados. O teste não requer reenviar pedidos ou reabrir a READY.
