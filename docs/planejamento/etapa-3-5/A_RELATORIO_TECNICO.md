# A. Relatório técnico | Etapa 3.5
07/11/2026 | America/Belem | VPS 2132956 | Ubuntu 24.04 | KVM 4

## Parecer e escopo
A infraestrutura operacional está apta à preparação da Etapa 4, com ressalvas. O Hub foi atualizado e homologado com fontes sintéticas. A Etapa 3.5 não deve ser considerada integralmente encerrada enquanto faltarem a validação do cliente Windows/DBeaver e as lacunas da matriz BI. O desenvolvimento dos conectores reais continua sendo trabalho do Codex. Nenhuma leitura comercial nova foi executada.

## Estado inicial
Sete contêineres saudáveis; Hub no SHA 23f28068b20caaa1af853e6b13af9479d12aae79. Banco Hub separado do n8n, schema 1+2, 24 tarefas e 2.406 pedidos sintéticos. Sete workflows inativos, sem tokens comerciais no Hub. Disco 5,7 GiB/193 GiB, RAM usada aproximadamente 1.204 MiB de 15.992 MiB, sem swap. UFW permite somente SSH público, com política de entrada deny. Nenhuma porta Docker publicada.

Os seis Compose originais e os helpers foram inventariados. Foram preservadas as identidades dos quatro serviços originais durante a atualização Hub. O n8n foi posteriormente recriado uma vez para aplicar sua própria retenção/rede. PostgreSQL, runners e cloudflared não foram recriados.

## Código e proveniência
Tag v1.5.18 confirmada no SHA d89af58f9d6a73a4dd64309823cdba53f368a8e8. CI Hub 42333639324 aprovado, release 42333893508 aprovado. Main estava em 17e363fbb920cb1a7babca03238444b267f7091c, com documentação posterior; não foi usada como atualização automática.

Worktree novo: /srv/nexoflow/hub-hml/releases/d89af58. O worktree 23f2806 e a imagem anterior permanecem para rollback. Nova imagem nexoflow-hub:hml-d89af58. O nome histórico do projeto Docker continua nexoflow-hub-hml-23f2806 para preservar redes e volume; o sufixo do nome não identifica mais a versão executada. O manifesto deployment.json identifica o SHA real.

Diff entre a versão anterior e a tag: contrato compartilhado de data final civil, limite 1–500, posições de itens e frete; mudanças API/history/testes. Nenhuma mudança em migrations ou Compose base. Não foi aplicada migração de schema. Hashes do módulo compartilhado e dos módulos API/history dentro da imagem foram comparados ao worktree do SHA e coincidiram.

## Implementado
1. Backup consistente anterior; cópias privadas para rollback em /srv/nexoflow/rollback/etapa35-20261107.
2. Build e ensaio descartável do SHA escolhido; atualização somente API/worker persistentes, mantendo ambiente homologacao e escrita_real=false.
3. Retenção n8n explícita, rede Hub declarada no Compose e preservação dos volumes.
4. Papéis de consulta distintos, views agregadas, SCRAM, limites de sessão e relays PostgreSQL em loopback. SSH continua com chave e validação da identidade do servidor.
5. Coletor local de métricas, timer, limites de recursos e armazenamento; detecção de coleta atrasada e aviso preventivo de disco em 70%.
6. Cobertura dos novos scripts/unidades no backup; limite do journal do sistema.
7. Três workflows sintéticos novos importados pela CLI nativa, executados e mantidos inativos. Nenhum workflow anterior foi substituído.

## Testes e evidências
- Ensaio Docker completo: PostgreSQL real, suíte Hub aprovada (51 casos coletados), API autenticada, worker real, histórico HTTP sintético, interrupção após checkpoint, lease e retomada, reinícios e healthchecks.
- API/worker atualizados saudáveis; hash dos três arquivos executados igual à origem versionada.
- Consulta Hub/n8n por loopback: views acessíveis; tabelas brutas, CREATE persistente e DELETE recusados, inclusive após desativar o default de transação read-only no ensaio. A proteção efetiva depende dos grants, não só dessa preferência.
- n8n real: FARMA, PET e histórico PET concluídos; externas_gravacoes=0. Dez workflows no total, zero ativos. Os três novos guardam dados sintéticos explicitamente; os anteriores preservam suas configurações.
- Telemetria: 91 séries reais, sem collection_error; testes de 30 dias de detalhe, agregado preservado, campo secreto desconhecido, label indevida, NaN, cardinalidade, coleta atrasada e disco preventivo aprovados.
- Restauração do snapshot 03106ced em PostgreSQL sem rede: 27 tarefas, 2.406 pedidos, 84 checkpoints, 169 auditorias, schema 1+2; contagens/hashes iguais, cinco segredos HML comparados sem valores e autenticação SCRAM da aplicação aprovada.
- Cloudflare: TLS mínimo 1.2, HTTPS ativo, Tunnel saudável com quatro conexões, Access e política administrativa presentes; bucket R2 sem r2.dev nem domínio público.
- Backup posterior à mudança terminou às 01h32m55s. O disparo natural das 03h30 ainda era futuro nessa leitura.

As verificações atuais de infraestrutura e a suíte sintética não certificam acesso, atribuição, cobertura histórica anual, escala comercial ou reconciliação financeira real.

## Falhas encontradas e correções
A associação inicial do leitor ao grupo não herdou privilégios no PostgreSQL 18 porque foi criada enquanto o membro era NOINHERIT. Ajustada explicitamente com GRANT ... WITH INHERIT TRUE e repetida a conexão. O ensaio de DELETE em view agregada foi recusado como view não atualizável; o teste passou a aceitar essa recusa e a de privilégio insuficiente. Isso foi correção do teste, sem ampliar grants.

A importação de workflows inicialmente recebeu EACCES no arquivo temporário copiado como root. Ajustado somente o proprietário desse arquivo sintético para UID 1000; o serviço n8n continuou sem root. A importação e as execuções seguintes passaram.

A recuperação de globals com um bootstrap de nome diferente recusou o grantor original das associações. A cópia isolada passou a inicializar com bootstrap_hml e omitir somente a instrução redundante CREATE ROLE bootstrap_hml do fluxo de restauração. O arquivo de backup original foi preservado. O ensaio completo passou. Este requisito integra o procedimento de recuperação.

A tentativa de configurar log_connections por papel foi recusada pelo servidor. Não foi mantida. Auditoria de conexões/desconexões foi configurada por servidor com ALTER SYSTEM e reload, sem registrar textos de consultas. Scripts de ensaio temporários que falharam permanecem identificados nas evidências privadas.

## Alteração posterior não implantada
Durante o fechamento, main avançou para baafc61ca09b9e18ca5406a69687fc2478c402a5, com a correção “Avançar períodos vazios no histórico de pedidos [skip release]”. Mudou app/order_history.py, cliente/CLI Windows e hub/nexoflow_hub/history.py, com testes. Não foi aplicada automaticamente. O SHA executado continua d89af58, correspondente à tag v1.5.18. Antes de ler fontes reais, o Codex/Work deve homologar separadamente essa correção; este relatório não a certifica.

## Arquivos e serviços
Alterados: helper Hub, manifesto e override de homologação; helper de backup Hub para o novo SHA; compose.operations.yaml; helper do monitor Hub; script principal de backup para incluir novos helpers/unidades. Criados: nexoflow-telemetry e suas unidades, relays de consulta, schemas/views/papéis de leitura e limites journald.

Recriados: API e worker Hub; n8n uma vez. Reiniciado: systemd-journald. Reload: configurações de log dos dois PostgreSQL. Sem reboot, sem substituição do Windows, sem mudanças no Tunnel/DNS/Access, sem remoção de volumes, imagens de rollback, histórico ou snapshots.

## Rollback
Parar somente API/worker Hub e restaurar os arquivos .before do helper, override e manifesto; validar config e subir api worker com --no-deps. A versão de schema é a mesma, mas checkpoints da política de datas nova não devem ser forçados a uma política antiga. Não editar fatos/cursor para fazer rollback passar.

Para n8n, restaurar somente compose.operations.yaml.before, validar config e recriar n8n com --no-deps; a configuração antiga não declarava a rede Hub, então reconectá-la privadamente se necessário. Nunca restaurar o banco inteiro para remover três workflows; mantê-los inativos ou gerenciá-los pela CLI/API nativa.

Para observabilidade, desabilitar seu timer, preservar as métricas e restaurar apenas o helper de monitor afetado. Para leitores, NOLOGIN e encerramento das sessões individuais; desabilitar os sockets de consulta. Para logs PostgreSQL, restaurar os valores anteriores documentados (log_connections vazio, log_disconnections off) e reload. Para journald, retirar somente o drop-in novo e reiniciar journald. Nenhum rollback envolve apagar volumes/snapshots.

## Conferência complementar
A leitura integral Restic terminou com sucesso às 01h40m53s, com 14 snapshots e os seis originais preservados. No fechamento intermediário, sete serviços estavam saudáveis, disco com 6.283.657.216 bytes usados (4%) e 200.599.846.912 disponíveis; RAM usada 1.230 MiB e disponível 14.761 MiB. Os relays escutam apenas em 127.0.0.1:15432/15433; exposição externa continua restrita ao SSH.

## Evidência de fechamento
Às 02h02 de 07/11/2026 (America/Belem), o último backup manual estava concluído com sucesso desde 01h56m48s, snapshot 3e3ecbbf. Há 15 snapshots, com os seis originais preservados. A leitura integral anterior cobriu os 14 snapshots então existentes; não deve ser confundida com nova leitura integral do snapshot final. Sete serviços continuavam saudáveis, logs limitados, nenhuma porta Docker publicada e homologacao/escrita_real=false mantidos. A documentação operacional já estava no GitHub no commit 6c43030801947e7f3d115f53e30a34bc16721da1 e foi incluída nesse backup. O disparo natural das 03h30 permanece pendente.

## Pendências e Etapa 4
- Instalação e teste do DBeaver no Windows, confirmação das chaves individuais dos demais desenvolvedores e custódia dos novos segredos de consulta.
- Separação de migrador/runtime antes de ampliar o uso comercial; runtime Hub ainda é dono do seu schema HML.
- Codex: injeção de clientes reais read-only por segmento, egress restrito, orçamento do ensaio, telemetria de chamadas e autorização backend dos produtos.
- Reconciliação da pendência antiga FRETE_DIVERGENTE apenas mediante resposta oficial; não foi acessada nem alterada a base privada Windows.
- Fórmulas/joins de fontes comunitárias e alguns comportamentos BI ainda pendentes; nenhuma paridade financeira comercial certificada.
- Retenção Restic destrutiva continua bloqueada; kernel/reboot e varredura Monarx conservam as ressalvas anteriores.

FARMA/PET: começar com janela pequena aprovada e limite 1–500, fim civil completo, IDs oficiais, identidade por segmento, orçamento de páginas, timeout/retry limitado, checkpoints por política e reconciliação. Weni, Meta e Google Ads seguem depois, com permissões oficiais e denominadores/atribuição comprovados. Não copiar SQLite nem credenciais comerciais para habilitar o worker sintético por simples configuração.


## Acesso externo e checklist de aceite
O navegador autenticado exibiu a tela “Log in to NexoFlow n8n” do Cloudflare Access. Uma sonda anônima Python feita da VPS recebeu HTTP 403 da borda Cloudflare, sem redirecionamento; isso foi registrado como bloqueio da sonda, não falha do n8n nem prova isolada do motivo do bloqueio. Nenhuma proteção foi reduzida.

| Critério solicitado | Estado e limite |
| --- | --- |
| Serviços anteriores e Hub funcionais | Validado por healthchecks e testes sintéticos |
| n8n operacional | Validado pelo motor real e três workflows novos |
| PostgreSQL preservado | Validado por contagens/hashes, sem migração ou exclusão |
| Backup e recuperação | Snapshot 03106ced recuperado sem rede; leitura integral Restic aprovada |
| Tunnel e Access | API saudável e login Access observado; sonda anônima 403 |
| Exposição pública | Sem porta Docker publicada; relays somente loopback; SSH externo preservado |
| Armazenamento e retenção | Inventário, cenários, limites e simulação documentados/validados |
| Recursos existentes preservados | Volumes e rollback preservados; sem limpeza destrutiva |
| Atualização 1.5.18 | SHA tag confirmado, ensaio aprovado, API/worker atualizados |
| PostgreSQL para DBeaver | Preparado e testado na VPS; cliente Windows pendente |
| Observabilidade mínima | Instalada, 91 séries, retenção/segurança testadas; stack completa apenas especificada |
| Arquitetura dos dois produtos | Documentada; frontend/login de produto ainda não implementados |
| Matriz FARMA/PET | 106 linhas; 19 páginas percorridas, com lacunas explícitas de fórmulas/interações |

As pendências não são convertidas em validações aprovadas. Este registro encerra a execução operacional autorizada, sem declarar homologação integral de tudo o que depende do Windows, das fontes reais ou da inspeção BI restante.

## Retomada e primeiro backup natural confirmados
Em 07/11/2026, o timer disparou às 03h30min02s e o backup concluiu às 03h30min14s, Result=success e ExecMainStatus=0. O marcador Hub avançou às 03h30min03s; snapshot 9956088d. O próximo disparo está previsto para 08/11 às 03h30. Essa prova resolve a pendência de agendamento natural mencionada no registro histórico acima; não equivale a novo teste de restauração ou leitura integral do novo snapshot.

Sete serviços saudáveis na conferência das 03h30min25s. Nesta retomada não houve mudança de serviços ou dados; foram revalidados os leitores por ambos os relays, contagens 27/2406/84/169, dez workflows inativos, rotação 10m x 3, retenção n8n, modo homologacao e escrita_real=false. Inspeção BI complementada e matriz de 106 linhas validada. Ver [complemento da retomada](G_RETOMADA_E_VALIDACOES.md). A Etapa 3.5 continua em validação parcial, sem liberação comercial.
