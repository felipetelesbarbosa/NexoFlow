# NexoFlow Hub — núcleo de homologação Linux

Estado: desenvolvimento `0.1.0.dev0`, independente da versão Windows **1.5.15**. Não é um release operacional do Hub. API, worker e persistência são reais; as fontes comerciais são fixtures e todos os conectores de produção recusam leitura e escrita.

## Arquitetura implementada

- `nexoflow_hub/api.py`: API FastAPI interna, tokens diferentes por FARMA/PET, autenticação de gerenciamento e prontidão. `/saude` só informa liveness/modo; não expõe dados. Sem Swagger público.
- `store.py`: PostgreSQL, transações, fila, eleição por segmento, `FOR UPDATE SKIP LOCKED`, leases de 30s, token de proprietário e fencing. Uma tarefa por segmento por vez; segmentos diferentes podem coexistir.
- `worker.py`: processo Linux sem GUI, retoma etapas confirmadas, backoff limitado, heartbeat, SIGTERM/SIGINT e resultados parciais. Conexão/statement/lock têm prazo; steps desta fase só executam operações locais limitadas.
- `orders.py`: contrato **interno normalizado**, sem presumir o JSON/endpoint histórico. Confere identidade, proprietário, data, segmento, itens, frete, valores e pagamento; valores monetários usam Decimal. Política de marketing e calendário são compartilhados com o Windows.
- `core.py`: constrói fixtures fechadas. A API não recebe pedidos/clientes, URLs de fontes ou credenciais. Só aceita um cenário sintético enumerado.
- `migrations/`: schema Hub próprio e versionado. API/worker não migram ao iniciar. Migração explícita e atômica, com trava; repetição da versão existente é idempotente. Rollback de schema recusa qualquer tarefa/cobertura existente.

O PostgreSQL do n8n não é utilizado. A configuração só aceita nomes `nexoflow_hub_hml` ou `nexoflow_hub_hml_<sufixo>`. Não apontar nem executar migrações na VPS nesta etapa. Esse nome é uma guarda adicional; não substitui conferir host, banco, papel e autorização.

### Regras reutilizadas e limites

Reutilização direta: `pedido_utils`, `business_identity`, `business_recompra`, detector Meta `ad_attribution`, `urn_utils` e classificação explícita `is_animal_product`. As funções extraídas mantêm as interfaces Windows e são cobertas pela regressão existente. O Hub não troca `NEXOFLOW_PERFIL` durante uma execução; recebe o segmento explicitamente em cada tarefa.

CPF inválido preenchido só passa com identidade independente e vínculo único; ausente/zerado, divergente ou ambíguo permanece pendente. Pedido null e segmento não comprovado são ignorados; omissão de itens/dados não equivale a ausência de compra. Itens vazios só são interpretados depois da confirmação de identidade, fonte e data. Frete de item código zero sem descrição exige soma igual ao frete oficial; não duplica produtos/receita. Pagamento 0/status cancelado excluem venda; estados documentados não cancelados seguem o Windows.

D+25 FARMA/D+30 PET: mesma função pura de calendário, sem retroativos; recusa e Opt-Out prevalecem. Ausência de opt-in não vira recusa. PET não calcula nem grava maioridade. O núcleo ainda não migra todo o enriquecimento cadastral/guardas de escrita dos aplicativos: essas operações não estão habilitadas no Hub. Nenhum resultado desta API autoriza aplicação em Weni.

O detector de anúncio reconhece evidência estruturada; conversa/clique não comprovam venda. Não há coleta Google Ads nem ativação comercial. O histórico/LTV observado está disponível com fonte HTTP simulada nesta fase. `cobertura` prepara persistência, mas não recebe declarações de completude sem contrato. O contrato histórico paginado foi recebido e implementado em homologação; veja [histórico](HISTORICO.md). O tamanho de página é ajustável, sem teto fixo de 100. Os conectores futuros não inventam rotas nem compartilham tokens Windows/Meta.

## Contrato da API / n8n

Rotas: `GET /saude`, `GET /prontidao`, `POST /tarefas`, `GET /tarefas`, `GET /tarefas/{id}`, `GET /tarefas/{id}/resultado`, `GET /tarefas/{id}/erros`. Gerenciamento/prontidão exigem `Authorization: Bearer <chave do segmento>`. Uma chave FARMA não consulta tarefas PET (404) nem cria PET (403). Listagens são limitadas a 100.

Corpo de homologação (não contém dados reais):

```json
{"segmento":"FARMA","origem":"n8n","chave":"ensaio-001","cenario":"normal"}
```

Resposta 202 somente após commit no banco. Repetir segmento+origem+chave com o mesmo cenário devolve a mesma tarefa; cenário divergente retorna 409. A origem é declarada pelo cliente autorizado, não uma prova criptográfica de provedor. O limite do corpo é 4 KiB; campos extras são recusados e erros de schema não ecoam entrada.

Estados: `pendente → executando → concluida/parcial/falhou/revisao_necessaria`; falha transitória vai a `aguardando`. Até três tentativas, backoff 2/4s (limite 60s), sem mudança automática de rota. Resposta incerta bloqueia reexecução automática. Crash recupera lease vencida e retoma checkpoint; fencing recusa o proprietário antigo. Resultado concluído não é selecionado novamente.

Os JSON em `n8n/` ficam **inativos**, com trigger manual, credenciais referenciadas por placeholder e prazo de 120s para polling. Configure no n8n uma credencial Header Auth por segmento, sem inserir tokens no JSON. Eles usam `http://hub-api:8000`, acessível apenas depois de preparar uma rede interna de homologação. A mudança de rede de um n8n existente exige conferência operacional; não execute isso automaticamente. A importação/execução do motor n8n real na VPS continua para o Work; o contrato HTTP e a estrutura dos arquivos são testados aqui. n8n não valida pedidos nem calcula receita.

## Executar em Linux

Python 3.12+, Docker/Compose. Dependências completas e transitivas estão fixadas em `requirements.lock`; ferramentas de teste em `requirements-dev.lock`. Não atualizar pip ou pacotes automaticamente. O módulo usa também as funções puras do diretório `app` do mesmo commit; não há suporte a um wheel Hub isolado nem dependência do Setup Windows.

```sh
python3 -m venv /caminho/privado/venv-hub
/caminho/privado/venv-hub/bin/python -m pip --disable-pip-version-check install -r hub/requirements.lock -r hub/requirements-dev.lock
PYTHONPATH=hub:app /caminho/privado/venv-hub/bin/python hub/tests/run_docker_hml.py --build --pytest
```

O ensaio cria um projeto Docker com UUID, PostgreSQL 18.6, usuário de aplicação sem superuser, API/worker sem privilégios, rede interna e nenhuma porta publicada. Gera segredos aleatórios em diretório privado temporário. Testa migração/reversão vazia, HTTP autenticado, interrupção real, lease/retomada, reinício de processos/PostgreSQL, persistência e healthchecks. No final, remove **somente** contêineres/rede/volume rotulados com o UUID criado pelo ensaio, nunca recursos da VPS. Não aceita nome de projeto externo.

Imagens Python/PostgreSQL estão fixadas por digest. CA corporativa opcional é montada só durante o build via segredo BuildKit `proxy_ca`; não usar `verify=False`, bypass de proxy ou inserir certificados/tokens em camadas. O helper mantém a rota autorizada e fixa o daemon Docker local; não usa um contexto salvo que possa apontar à VPS.

### Operação manual do Compose de homologação

`compose.homologacao.yaml` é **um projeto novo, isolado**, não uma extensão pronta da VPS. Defina `HUB_SEGREDOS_DIR` para um diretório privado com os arquivos `admin_password`, `runtime_password`, `dsn`, `farma` e `pet`. Gere senhas/chaves aleatórias; tokens distintos com pelo menos 32 caracteres. O diretório externo deve ser 0700, acessível só ao operador; os arquivos montados precisam ser legíveis pelos UIDs dos contêineres, sem conceder acesso a outros usuários pelo diretório externo.

`dsn` contém conexão PostgreSQL com banco `nexoflow_hub_hml`, papel `hub_hml` e host `postgres-hml`; sua senha deve coincidir com `runtime_password`. Esse papel não tem superuser/createdb/createrole e só possui o banco de homologação. É dono do schema para executar as migrações desta fase; antes de produção, separar papel migrador do papel runtime com grants CRUD explícitos.

Depois de build, inicie somente `postgres-hml`, confira a prontidão, execute explicitamente `compose run --rm migracao` e então suba `api worker`. Todos os comandos usam `docker compose -f hub/compose.homologacao.yaml` com os segredos e o projeto conferidos. Não executar `down -v`; parar serviços preserva o volume. A API manual fora do Docker deve usar loopback `127.0.0.1`, nunca bind público.

Configuração: `HUB_AMBIENTE=homologacao`, `HUB_ESCRITA_REAL=false`, `HUB_DSN_FILE`, `HUB_FARMA_TOKEN_FILE`, `HUB_PET_TOKEN_FILE`. Arquivos privados são externos ao repositório. Modo real é recusado e não existe adaptador de escrita habilitado. Logs estruturados contêm somente execução, segmento, evento e tentativa; não incluem corpos/CPFs/tokens/DSN. stdout/stderr dos subprocessos do ensaio não são reproduzidos em falhas.

## Preparar homologação na VPS — execução posterior pelo Work

Materiais revisados: PDF e ZIP da Etapa 1 de 06/11/2026; scripts inspecionados sem execução. O relatório aprova infraestrutura **com ressalvas**, não aplicação Python. Não foi acessada/modificada a VPS nesta implementação.

Preservar o projeto `nexoflow` e a ordem atual: `compose.yaml`, `compose.n8n.yaml`, `compose.runners.yaml`, `compose.cloudflared.yaml`, `compose.n8n-url.yaml`, `compose.operations.yaml`. O helper `/usr/local/sbin/nexoflow-compose` já combina os seis; não alterá-lo nem anexar este Compose cegamente. O ZIP não fornece os seis arquivos efetivos, nomes de redes/volumes/usuários ou grants do PostgreSQL real.

Antes de criar qualquer extensão operacional, o Work deverá conferir `nexoflow-compose config` sem exibir valores privados, redes, papéis e configuração efetiva. Preparar banco/usuário próprios do Hub separados do n8n, segredos em `/srv/nexoflow/configuracoes/hub-hml`, dados de homologação em `/srv/nexoflow/dados/hub-hml` e código por SHA. Não reutilizar credenciais administrativas/n8n. Não executar migração no banco atual nem compartilhar volume PostgreSQL com outro servidor.

Para o primeiro ensaio, usar o projeto isolado com UUID e fontes sintéticas. Não anexar Tunnel, DNS, ingress ou portas; não ativar workflows comerciais. Verificar recursos disponíveis antes do build/ensaio e os alertas existentes. O backup natural de 07/11 às 03:30 America/Belem, kernel, retenção destrutiva e varredura Monarx são pendências da Etapa 1, não resolvidas por estes testes.

### Backup e rollback

Novos dados: banco Hub (tarefas, idempotência, tentativas, checkpoints, auditoria e cobertura), segredos externos e configuração de implantação. O backup existente já declara dumps dos bancos elegíveis e `/srv/nexoflow/{infra,configuracoes,dados}`; o Work deve comprovar inclusão do novo banco/papel e caminhos, sem mudar política de retenção ou apagar snapshots. Testar restauração em outro banco **de homologação** sem egress, antes de ligar workers.

Rollback de aplicação: parar API/worker Hub e voltar ao SHA anterior, preservando banco/volume/segredos. Não reiniciar banco, n8n ou Tunnel por rotina. O rollback de schema é explícito por `python -m nexoflow_hub.migrate --rollback-schema-vazio`, somente no banco temporário conferido e sem dados. Com dados, recusa; usar backup/restauração isolada e um plano aprovado, sem DROP destrutivo.

## Limites de coordenação / ativação futura

Locks PostgreSQL protegem **somente participantes Hub**. Win32 não participa desse contrato. A escrita real do Hub permanece bloqueada mesmo com lease; Windows continua autônomo. Antes de migração comercial: definir proprietário único por destino/segmento, revisão/aplicação equivalente ao Windows, reconciliação de respostas incertas, identidade e direitos dos conectores, observabilidade e rollback; só então solicitar ativação específica. Nenhum lock local ou PostgreSQL sozinho garante exclusividade Windows/VPS.

## Marco histórico

Contrato e migração 002 implementados após a regressão Windows: [histórico paginado](HISTORICO.md). A API aceita tarefas históricas parametrizadas de homologação, sem credenciais/destinos comerciais.
