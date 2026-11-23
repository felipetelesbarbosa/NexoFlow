# Central de Operações do NexoFlow Hub

A primeira entrega para homologação reúne as execuções do Hub e os eventos recebidos do fluxo FARMA. O frontend React/TypeScript consulta uma API FastAPI dedicada. Cada resposta cobre até as 50 tarefas e os 50 eventos mais recentes do segmento autorizado. Uma falha de leitura tem estado próprio na interface. O NexoFlow Métricas aparece desabilitado. Seu backend, frontend, usuários e relatórios ficam para uma etapa posterior.

Para a futura paridade com o Looker Studio, a recomendação para FARMA é uma API de leitura do Métricas sobre a mesma revisão comercial READY do PostgreSQL que alimenta o relatório. Visões SQL podem agregar os fatos por período. Uma fonte ainda mantida em planilha deve ser inventariada, inclusive se houver entrada manual. Os dois painéis podem compartilhar uma única entrada. O inventário e a homologação do PET são independentes.

## Hospedagem e processamento

O Work homologou a primeira interface em 23/11/2026 no SHA `105ddfa27980aae6645d5ada7407a9047ba0aa7e`. O acesso individual com MFA funcionou no PC e no celular. O ensaio manual no n8n recebeu o mesmo recibo nas duas entregas e exibiu uma ocorrência em FARMA e zero em PET. [Central privada](https://central-hml.nexoflowhub.com.br)

Em 23/11/2026, o Work homologou a reentrega pelo simulador do fluxo Weni FARMA. Dois POSTs da mesma ocorrência retornaram HTTP 200, o mesmo recibo e o mesmo horário de recebimento. A Central mostrou uma ocorrência em FARMA e zero em PET para esse evento. O fluxo guardou o corpo em `nexoflow_evento_json` antes do primeiro POST e reutilizou esse resultado no segundo. O Work retirou a rota temporária e revogou a autorização descartável após o teste. [Contrato do webhook](WEBHOOK_WENI_HML.md)

A seção **Processamento do Hub** mostra o último ciclo bem-sucedido de algum worker do Hub. Em execução normal, o sinal é gravado após um ciclo completo, no máximo uma vez a cada dez segundos por processo. Após 30 segundos sem novo registro, a interface mostra sinal atrasado. Um ciclo longo também pode atrasar o sinal. O horário vale para o serviço compartilhado. Os contadores da fila e a última conclusão são do segmento selecionado e abrangem toda a fila do Hub, independentemente do período do gráfico. **Prontas** já atingiram o horário de execução. **Aguardando horário** ainda estão no período de espera. O painel também mostra a maior espera entre prontas e as execuções com prazo de lease expirado. A última execução concluída considera tarefas em estado `concluida`. Backups e serviços Docker dependem de outras fontes de telemetria.

Em 23/11/2026, o Work implantou o painel no SHA `3ce23805a4894bc10739c95946a4662a632d9e19`, aplicou a migração 004 em `nexoflow_hub_hml` e conferiu a Central no PC e no celular. O worker registrou ciclos recentes. `central-api` e `central-web` estavam saudáveis. FARMA e PET tinham filas vazias e nenhuma conclusão registrada. No ensaio isolado, a tentativa de ler o outro segmento recebeu HTTP 403. Após 31 segundos com o worker parado, o sinal ficou atrasado. Com o reinício, o sinal voltou a recente, o prazo expirado zerou e a tarefa foi concluída na segunda tentativa.

O dump dedicado anterior à migração passou na leitura e na verificação SHA-256. Para concluir a conferência do ambiente, falta validar a rota autenticada `/prontidao` do serviço `api`, repetir o ensaio de recuperação no projeto Docker descartável e localizar o dump do banco dedicado da Central no snapshot diário do Restic/R2, gerado pela rotina das 03h30 de Belém. [Rotina de backup do Hub](../docs/planejamento/etapa-3-5/B_ARMAZENAMENTO_RETENCAO.md)

## Interface e aceite visual

A referência da Iota.hub registrada no [cronograma da Central](../docs/planejamento/CRONOGRAMA_MESTRE_HUB_METRICAS.md) orienta a navegação, os filtros de período, os cartões compactos e o painel de detalhes. As cores de marca vêm do [ícone oficial NexoFlow](../assets/NexoFlow.ico). A primeira visita abre no tema claro. Quem preferir o escuro pode selecioná-lo e conservar a preferência no navegador. O desenho começa no celular. Em 320 e 375 px, testar o percurso de consultar execuções, aplicar um filtro, abrir os detalhes e retornar à lista. Conferir os controles por toque e teclado, o foco e a ausência de rolagem horizontal na página. Repetir o percurso no tema escuro, recarregar a página para conferir que a preferência se mantém e comparar com o desktop de 1440 px. O operador com acesso a duas marcas usa o seletor. Com apenas uma marca, a interface identifica o segmento em uso.

Capturas da homologação com registros sintéticos. [Desktop em tema claro](central-web/docs/central-desktop.png) · [Celular em tema escuro](central-web/docs/central-celular.png).

## Caminhos dos dados

| Caminho | Comportamento desta entrega |
| --- | --- |
| Operador → frontend → `GET /api/central/v1/resumo` | Mesma origem. O backend valida a assinatura RS256 da identidade individual do Cloudflare Access, o emissor, a audiência e a validade. O identificador do operador determina os segmentos autorizados. Cada consulta lê um único segmento. |
| Central → PostgreSQL do Hub | Transação de leitura consistente com tempo limite, usando `hub_central_leitor`. Três visões filtradas pelo segmento expõem tarefas, eventos e a situação do processamento. |
| Fluxo FARMA → `POST /v1/webhooks/weni/farma` → PostgreSQL do Hub | O Hub fornece o endpoint. O fluxo envia um evento após confirmar a transferência. O identificador da ocorrência e o instante original devem ser estáveis em uma repetição. O recibo confirma a gravação no Hub. |
| n8n de homologação → mesmo endpoint | O [workflow manual inativo](n8n/webhook-weni-farma-hml.json) permite testar uma ocorrência sintética e repetir a entrega. O evento aparece na Central pela consulta ao banco. |

A contagem de eventos recebidos representa os pontos instrumentados do fluxo. Cobertura de conversas Weni, saúde do worker, telemetria de VPS, backups, dados financeiros e o histórico do Windows têm fontes e critérios próprios. O contrato desta tela pode ser consultado sem acessar o Docker, enviar comandos ao worker ou ler contatos.

## Ensaio descartável para o Work

Em um checkout do SHA do Hub e com Docker Linux, execute a partir da raiz. Use a mesma instalação de Python 3.12+ para instalar as dependências e rodar o ensaio.

```sh
python -m pip install -r hub/requirements.lock -r hub/central-requirements.lock -r hub/requirements-dev.lock
PYTHONPATH=hub:app python hub/tests/run_docker_hml.py --build --pytest --central
```

O runner cria seu próprio projeto Docker, banco, chaves de assinatura e identidades sintéticas. Confira a execução com código zero. Nos controles de acesso, uma identidade FARMA vê somente FARMA, uma identidade PET vê somente PET e um operador com as duas permissões pode alternar entre elas e uma requisição sem autenticação recebe 401. Duas entregas do mesmo evento retornam o mesmo recibo e geram uma linha. Reutilizar o identificador com outro instante retorna 409. Uma falha de acesso deve aparecer como indisponibilidade. O objeto `metricas.habilitado` permanece `false`.

Para testar um fluxo Weni no futuro, configure no fluxo de homologação uma ação HTTP que faça o POST com `Content-Type: application/json` e autenticação Bearer em campo privado. Use um UUID para cada ocorrência, inclusive quando o mesmo contato passar duas vezes pelo fluxo. Fixe esse UUID e a data antes da primeira tentativa. A homologação precisa comprovar que o fluxo consegue conservar ambos em uma reentrega. Um exemplo de corpo sintético:

```json
{"evento_id":"69ded3a1-26cf-4a89-b2d8-de9ada96b108","tipo":"atendimento_transferido","ocorrido_em":"2026-11-23T09:15:00-03:00"}
```

O token do webhook é exclusivo da ingestão FARMA. As credenciais de gerenciamento do Hub e do n8n não servem como credenciais do fluxo. Para o ensaio via n8n, associe a credencial privada Header Auth no editor. A ativação do fluxo real, sua rota HTTPS e a autorização do operador são etapas posteriores.

## Subir uma cópia privada dedicada

O [Compose da Central](compose.central-hml.yaml) complementa o do Hub. Para o Work, use um projeto isolado, com banco e volume de homologação próprios, e o commit homologado. Confira `docker compose ls` e o nome do projeto antes de criar os serviços. Os comandos abaixo usam `nexoflow-central-hml` e o banco `nexoflow_hub_hml` interno desse projeto. A revisão comercial do Data Studio pertence a outro banco.

No diretório privado `HUB_SEGREDOS_DIR`, prepare os arquivos da homologação do Hub descritos no [guia do núcleo](README.md) e estes arquivos adicionais:

| Arquivo | Conteúdo e uso |
| --- | --- |
| `central_password` | Senha aleatória exclusiva, com pelo menos 32 caracteres. Somente o bootstrap do banco a usa para criar o usuário de leitura. |
| `central_dsn` | DSN de `hub_central_leitor` no host interno `postgres-hml`, banco `nexoflow_hub_hml`, com a senha correspondente. |
| `central_identidades.json` | Objeto JSON que mapeia cada `sub` individual verificado do Access a `"FARMA"`, `"PET"` ou a uma lista explícita de segmentos autorizados como `["FARMA","PET"]`. O primeiro segmento é o inicial. A ausência do identificador recusa o acesso. |
| `central_jwks.json` | JWKS público de assinatura do emissor configurado, obtido de `/cdn-cgi/access/certs` por HTTPS verificado. Conserve as chaves simultaneamente válidas e acompanhe a rotação. |
| `weni_farma` | Token aleatório exclusivo do fluxo FARMA de homologação, com pelo menos 32 caracteres. |

Use um diretório 0700 e permissões compatíveis com os UIDs dos serviços que recebem cada montagem. Exporte o caminho em `HUB_SEGREDOS_DIR`, o emissor HTTPS da equipe em `CENTRAL_ACCESS_ISSUER` e a audiência específica da aplicação em `CENTRAL_ACCESS_AUD`. Proteja a origem por Access e exija MFA para operadores antes do teste interativo. As chaves e identidades são relidas pelo backend. Se trocar um arquivo montado por substituição de inode, recrie somente o serviço que usa o arquivo para o novo conteúdo ser montado. A sessão, o painel de convites e o RBAC completos de produção continuam no [planejamento de identidade dos produtos](../docs/planejamento/etapa-3-5/E_ARQUITETURA_WEB.md).

```sh
set -eu
central() {
  docker compose -p nexoflow-central-hml -f hub/compose.homologacao.yaml -f hub/compose.central-hml.yaml "$@"
}
central config --quiet
central build api worker central-api central-web
central up -d --wait postgres-hml
central --profile migracao run --rm migracao
central exec -T postgres-hml psql -X -U bootstrap_hml -d nexoflow_hub_hml < hub/provisionar-central-hml.sql
central up -d api worker central-api central-web
central ps
```

O backend usa as três visões. O script de provisionamento pode ser repetido e aborta se o leitor já tiver privilégios excessivos. Em uma instalação com migrador ou administrador diferente, o Work deve conferir os papéis antes de aplicar o procedimento correspondente. O Compose mantém as redes internas, sem publicar portas. Para a interface, a origem de homologação autorizada deve encaminhar à `central-web:8080` e preservar a asserção assinada. A rota de webhook, se homologada, deve encaminhar somente o POST específico à API do Hub. A escolha e a exposição dessas rotas na VPS ficam a cargo do Work e do operador.

### Atualizar a cópia existente para a migração 004

No projeto já homologado, confira o nome do projeto e o volume em uso com `central ps` e `docker compose ls`. Use a função `central` com os arquivos e parâmetros efetivos da implantação existente. Confira o backup do banco da Central. Compile os serviços do novo checkout antes da troca. Aplique a migração com `central --profile migracao run --rm migracao`, reaplique `hub/provisionar-central-hml.sql` com o mesmo papel de bootstrap usado na implantação e atualize `api`, `worker`, `central-api` e `central-web`. Confira os três painéis como operador autorizado. Testes de interrupção e recuperação com fila sintética devem usar o projeto Docker descartável.

### Reversão

No projeto de homologação, desabilite a ação de envio do fluxo de teste e retire a rota da Central no ingresso de homologação, se configurada. Use `central stop central-web central-api` para desligar a interface e a API leitora. Para desabilitar o webhook, retire `HUB_WENI_FARMA_TOKEN_FILE` da configuração da API e recrie apenas esse serviço. Preserve o volume, os recibos e o PostgreSQL. Mantenha os binários da API e do worker compatíveis com a migração 004. O rollback de schema para banco vazio recusa a operação se houver eventos registrados.

Para reverter a interface, restaure as imagens anteriores de `central-api` e `central-web`, mantendo o núcleo compatível com o schema 004. O núcleo anterior exige o schema 003 para declarar prontidão. A reversão completa dos binários requer um procedimento de migração próprio.
