# Central de Operações do NexoFlow Hub

A primeira entrega para homologação reúne as execuções do Hub e os eventos recebidos do fluxo FARMA. O frontend React/TypeScript consulta uma API FastAPI dedicada. Cada resposta cobre até as 50 tarefas e os 50 eventos mais recentes do segmento autorizado. Uma falha de leitura tem estado próprio na interface. O NexoFlow Métricas dispõe de um piloto privado opcional para Vendas FARMA.

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

## Documentação do Hub

A aba **Documentação** da Central reúne as rotas por assunto, com busca e referência OpenAPI. **Abrir Swagger** usa os arquivos distribuídos com a Central e exige a sessão individual do operador para consultar o contrato e os exemplos. O Swagger exibe as rotas em modo de consulta. O endpoint de documentação é `GET /api/central/v1/documentacao/openapi.json?api=hub`. Use `api=central` para consultar o contrato da Central.

Para clientes como n8n, use `Authorization: Bearer SEU_TOKEN` nas rotas de execução do Hub. O token determina o segmento. O webhook recebe a credencial exclusiva da Weni FARMA. A Central usa identidade individual assinada pelo Cloudflare Access. O endpoint interno `GET /saude` é a verificação básica para o ambiente Docker.

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

## Infraestrutura da VPS

A página **Infraestrutura** consulta `GET /api/central/v1/infraestrutura` com a sessão individual da Central. A VPS é compartilhada pelos segmentos. O painel mostra estado, sistema, localização, IPv4, plano, capacidade, renovação e último backup listado no provedor. CPU, memória, disco, tráfego e uptime usam a última amostra e as séries disponíveis nas últimas 24 horas. Os cartões de tráfego mostram bytes da última amostra. A cota de banda vem do plano. Campos ausentes ficam indisponíveis. O backup do provedor e o backup PostgreSQL do Hub têm fontes próprias. A cobertura do banco dedicado no Restic/R2 continua em conferência. [API Hostinger](https://github.com/hostinger/api-python-sdk/blob/main/docs/VPSVirtualMachineApi.md)

O coletor roda no host ou em outro ambiente autorizado com HTTPS de saída. Use a credencial Hostinger dedicada e de menor escopo disponível, injetada no processo como `HOSTINGER_API_TOKEN` pelo mecanismo privado do ambiente. Apenas o coletor precisa dessa credencial. O coletor consulta a VPS selecionada e grava um JSON de campos permitidos por troca atômica. A Central lê o diretório como volume somente leitura e indica coleta atrasada acima de 20 minutos.

Na homologação existente, prepare um diretório privado para o snapshot, com escrita para o usuário do coletor e leitura para o UID 10001 do contêiner da Central. O exemplo assume que o ambiente Python do coletor já instalou `hub/requirements.lock`, que a credencial foi injetada e que o ID real e o caminho do diretório foram definidos no ambiente. Rode a coleta manual uma vez no host antes de agendá-la a cada cinco minutos.

```sh
PYTHONPATH=hub python -m nexoflow_hub.collect_vps --vps "$HOSTINGER_VPS_ID" --diretorio "$CENTRAL_INFRA_DIR"
```

Use os mesmos arquivos Compose e nome de projeto já conferidos. Acrescente `-f hub/compose.infra-hml.yaml` à função `central` e rode:

```sh
central config --quiet
central build central-api central-web
central up -d --no-deps central-api central-web
```

Confira **Infraestrutura** com o acesso autenticado da Central, a hora da coleta e as amostras mais recentes. O botão **Atualizar** relê o último snapshot gravado. Se a coleta falhar, o processo conserva o snapshot anterior. Para desligar a coleta, suspenda o agendamento e recrie a API da Central com os arquivos Compose anteriores.

## Consumo de APIs

A Central tem uma aba própria para o tráfego autenticado recebido pela **API do Hub** e pelo **webhook Weni FARMA**. A página apresenta totais, gráficos por hora com tabela acessível e explicações para códigos técnicos conhecidos. O inventário abaixo dos gráficos identifica integrações que ainda precisam de instrumentação. A instrumentação cobre as rotas de execuções e de eventos instrumentadas. Tráfego externo ao Hub, como as chamadas do Analytics Windows, precisa de sua própria instrumentação para aparecer nesta tela.

Em 23/11/2026 às 17h23 de Belém, o Work aplicou a migração 005 após verificar o backup. Os quatro serviços estavam operacionais no SHA `8ac4b41b49b02bd2f1b72ed9ed12bc85c31b0503`. No Chrome, o Work conferiu uma chamada `GET /tarefas` com HTTP 200 por segmento, os detalhes, o log textual e o filtro **Somente erros**. [Consumo de APIs em homologação](https://central-hml.nexoflowhub.com.br/#consumo)

O reenvio do webhook e a sanitização passaram no Docker do CI no mesmo SHA. A repetição na VPS parou na conexão com o PostgreSQL descartável, e a janela do webhook na Central implantada estava vazia. A conferência dessa fonte na Central privada continua pendente. [Ensaio CI do Hub](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/45250129611)

Às 17h40 de 23/11/2026, horário de Belém, o Work atualizou o `central-web` para `e7b488ab270415526e8fbbc41d5d726240b8b8d7`, com a migração 005 já aplicada. No Chrome, conferiu os totais, o gráfico e a tabela por hora, o destaque de HTTP 200 e o log textual. A janela do webhook Weni apareceu vazia e o inventário exibiu as sete integrações que ainda precisam de telemetria. O cenário HTTP 409 foi conferido no Chromium do CI. [Aba de homologação](https://central-hml.nexoflowhub.com.br/#consumo) · [CI da interface](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/45260882275)

Os cartões usam as **últimas 24 horas** de registros no segmento selecionado. Uma resposta 2xx entra no numerador de sucesso. As demais respostas registradas entram no numerador de erro. Cada tentativa HTTP é contada, inclusive reentregas idempotentes. O total se refere às chamadas registradas. O percentil 95 é a primeira duração observada que cobre pelo menos 95% da amostra. A interface distingue janela vazia de falha de leitura. As verificações de saúde e prontidão ficam fora dos totais.

Em **Detalhes**, a consulta pagina 50 registros, com opção de mostrar só erros. A linha abre o método, a rota registrada, o horário, a duração, os campos técnicos permitidos do corpo e a resposta técnica com HTTP e código de erro. O log textual pode ser copiado. A rota usa o modelo como `/tarefas/{uid}`. Dados de clientes, chaves de idempotência, parâmetros de URL, cabeçalhos e corpos integrais ficam fora da tabela. A contagem de tentativas é independente dos eventos únicos da Weni e do resultado comercial de uma tarefa.

A migração **005** cria a tabela técnica e a visão de leitura por segmento. O registro ocorre depois da resposta, preservando o resultado da API mesmo se a telemetria falhar. O worker limpa registros técnicos com mais de sete dias. Para conferir a atualização, use o dump e o projeto de homologação já existentes. Compile os quatro serviços do Hub e da Central, aplique a migração, reaplique `provisionar-central-hml.sql` e suba as novas imagens. Conserve os arquivos Compose efetivos, inclusive o complemento de Infraestrutura se estiver em uso.

Valide com o projeto Docker descartável. Envie uma chamada autorizada que retorna 2xx, repita um webhook idempotente e provoque uma rejeição de schema com dados sintéticos. Confira taxas, paginação, filtro de erros, detalhe e log textual. Uma identidade FARMA deve receber 403 ao consultar o segmento PET. Para reverter a interface, restaure as imagens anteriores de `central-api` e `central-web` e mantenha o núcleo compatível com o schema 005.

## Ambientes e Minha Conta

A Central abre em **Homologação**. O endereço `central-hml.nexoflowhub.com.br` fica dedicado a homologação. No endereço oficial `central.nexoflowhub.com.br`, **Produção** só fica disponível com uma fonte configurada e uma autorização específica por operador e segmento. As consultas usam o banco e os escopos do ambiente escolhido. A troca limpa a seleção de segmento e os resultados exibidos. Infraestrutura mostra a VPS compartilhada e Documentação mostra os contratos do software.

Para disponibilizar a opção, monte separadamente `CENTRAL_PROD_DSN_FILE` e `CENTRAL_PROD_IDENTIDADES_FILE` na API da Central. Use o banco operacional do Hub `nexoflow_hub_prod`, com as visões da Central e um login `hub_central_leitor` limitado a consultas, credenciais de produção e acesso privado. O arquivo de escopos de produção tem o mesmo formato da homologação (identidade do Access por segmento), em arquivo próprio. Aplique as permissões às visões antes de disponibilizar a opção. Dois operadores de ensaio, um com autorização de produção e outro somente de homologação, devem verificar a separação entre ambientes e segmentos. Para retirar a opção, retire as duas configurações e recrie apenas a API da Central.

Em **Minha Conta**, o nome de exibição fica associado à identidade autenticada e persistido no volume `central_profiles`. Inclua esse volume no backup da Central. A instalação mantém a credencial operacional do PostgreSQL dedicada à leitura. A conta Cloudflare continua sendo a fonte do e-mail de login e da senha. Ao mudar o e-mail, confirme o acesso com o administrador antes de encerrar sua sessão atual. O atalho de MFA abre o cadastro de dispositivos na Cloudflare e respeita os métodos configurados para a aplicação.

## Gerenciar Usuários

**Gerenciar Usuários** é uma área exclusiva do Super Admin. Para habilitá-la, use também `compose.usuarios-hml.yaml` e armazene no arquivo privado `central_super_admin` apenas o identificador (`sub`) da identidade autenticada do proprietário. Confirme a identidade antes de vincular esse valor. O proprietário precisa continuar autorizado no arquivo normal de escopos. O volume `central_profiles` passa a guardar também convites, concessões, revogações e auditoria. Inclua-o no backup. A revogação é consultada a cada requisição e prevalece sobre concessões antigas.

Os papéis da Central são:

| Papel | Hub | Métricas | Gerenciar Usuários |
| --- | --- | --- | --- |
| Convidado | Consultas nos segmentos autorizados | Não | Não |
| Admin | Consultas nos segmentos autorizados | Consultas nos segmentos autorizados com fonte habilitada | Não |
| Super Admin | Consultas nos segmentos autorizados | Consultas nos segmentos autorizados com fonte habilitada | Sim |

O Super Admin cria um convite para um e-mail, escolhe o papel (Convidado por padrão ou Admin) e FARMA, PET ou ambos. A Central gera um link de uso único com validade de sete dias. O papel é gravado junto ao aceite, vinculado ao identificador autenticado, sem ampliar os segmentos. Convites e vínculos antigos permanecem Convidado, salvo as concessões privadas de Métricas já existentes. O Super Admin também pode alterar o papel de um operador ativo; a alteração e a revogação valem na próxima requisição. Nenhum convite nem alteração de papel pode criar outro Super Admin.

Em **Autorizar na Cloudflare**, adicione o mesmo e-mail na política correspondente ao papel: **Central | Admins OTP** ou **Central | Convidados OTP**. Quem preferir o login Cloudflare e tiver identidade elegível pode ser autorizado também em **Central | Admins MFA** ou **Central | Convidados MFA**; mantenha MFA adicional habilitado nessas políticas. A entrada por código de e-mail permanece disponível. As políticas de Access permitem chegar à Central; não concedem o papel dentro do NexoFlow, nem acesso à conta administrativa Cloudflare ou ao editor n8n. Ao alterar o papel de um operador, alinhe também suas políticas de Access e retire o e-mail das políticas do papel anterior.

Depois de autorizado, o convidado abre o link e aceita com a identidade Cloudflare correspondente. Se a autenticação eliminar o fragmento do endereço, abra novamente o link recebido após autenticar. A concessão feita por convite permite consultar homologação. A liberação de produção segue a configuração separada de leitura.

Ao revogar na Central, o operador perde o acesso a seus dados na próxima requisição. Retire o e-mail da política da aplicação Central na Cloudflare se quiser bloquear também a chegada à página. Os convites desta área não concedem acesso ao n8n. O Super Admin não pode revogar o próprio acesso pelo painel.

Para suspender a administração, retire o Compose adicional e preserve `central_profiles`. Antes de voltar para uma imagem anterior a este recurso, reconcilie as revogações com o arquivo de concessões antigas e com a política da Cloudflare. Uma imagem anterior só consulta o arquivo de concessões.

## Piloto privado de Vendas FARMA

O piloto abre pelo link **NexoFlow Métricas** da Central de **homologação** e consulta os dados reais publicados no PostgreSQL comercial. O acesso de leitura está disponível para todo Admin ou Super Admin ativo com permissão FARMA. Convidados e operadores sem FARMA não podem consultar a API nem abrir Vendas. A primeira página exibe pedidos válidos, receita de produtos, frete e faturamento, com filtros inclusivos de até 366 dias. A impressão A4 e a opção **Exportar PDF** usam a caixa de impressão do navegador. Para gravar um arquivo, selecione **Salvar como PDF**.

Para conceder leitura, o Super Admin define o papel Admin em **Gerenciar Usuários** ou já emite o convite com esse papel. Não é necessário acrescentar credenciais ou exceções por produto a cada Admin. Por compatibilidade, `central_metricas_leitores.json` e [compose.metricas-leitores-hml.yaml](compose.metricas-leitores-hml.yaml) continuam suportados para identidades ativas ainda sem papel explícito: as chaves com valor `true` são Admins legados. Um papel explícito no volume da Central prevalece inclusive sobre esse arquivo. Para revogar somente o Métricas, altere o papel para Convidado; a revogação de acesso à Central encerra ambos. Preserve o volume `central_profiles` no backup; as tabelas de papéis são aditivas. Antes de reverter a uma imagem anterior aos papéis, reconcilie o arquivo de leitores com as concessões atualmente válidas, para não reativar acesso revogado.

**Preparação na VPS.** Confirme a revisão READY e a fonte da página Vendas do Looker oficial. No banco `nexoflow_datastudio`, um administrador do banco cria o papel dedicado `nf_metricas_farma_leitor` e, pelo proprietário das visões, aplica [provisionar-metricas-farma.sql](provisionar-metricas-farma.sql). O script acrescenta uma visão que só expõe a publicação FARMA em READY. A conta lê essa visão e cinco colunas de `farma.ds_bi_vendas`. Antes de prosseguir, confira que o papel não lê tabelas brutas, cadastros, PET, nem o schema de controle e que não tem permissão de escrita. Configure a senha em canal privado e monte a conexão no arquivo `central_metricas_dsn` do diretório de segredos vigente. Use o host interno PostgreSQL e a rede privada verificada, sem publicar uma porta PostgreSQL.

Inclua [compose.metricas-hml.yaml](compose.metricas-hml.yaml) depois dos complementos em uso e defina `CENTRAL_METRICAS_REDE` com o nome da rede privada existente. Confira o Compose resultante, a imagem anterior para reversão e os volumes atuais. Atualize apenas `central-api` e `central-web` do projeto da Central. O Analytics e o Looker continuam usando suas próprias credenciais e rotinas.

**Aceite real.** Com a conta do Felipe, abra `/#metricas`, registre a versão e o UUID da publicação e compare Métricas, PostgreSQL e Vendas no Looker oficial. Use dois períodos sobrepostos (por exemplo, 01–24/11 e 10–24/11/2026) e um intervalo comprovadamente vazio. Para cada recorte, execute [conferir-metricas-farma.sql](conferir-metricas-farma.sql) com o UUID observado. A API também aceita `revisao=<UUID>` e responde 409 se a publicação mudar. Confirme o UUID ativo antes e depois de conferir os cartões do Looker. Se houver troca no meio, repita na mesma READY. Registre pedidos, produtos, frete, faturamento e diferenças em centavos. Confira o PDF, incluindo gráficos, datas, fonte, revisão e tabela. Valide um Admin FARMA ativo: Vendas deve abrir e a API de gestão de usuários deve responder 403; um Convidado FARMA e um Admin sem FARMA devem receber 403 em Vendas. Teste a redução de papel e a revogação, mantendo a fonte READY e Produção preservadas.

**Reversão.** Retire o complemento da API e recrie os serviços da Central com as imagens anteriores. O acesso de leitura pode ser revogado separadamente. Preserve o volume de perfis e as revisões comerciais.
