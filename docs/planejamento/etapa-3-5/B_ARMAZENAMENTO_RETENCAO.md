# B. Armazenamento, capacidade e retenção
07/11/2026. Valores medidos na entrada; crescimento abaixo é cenário de engenharia, não previsão comercial.

## Inventário por componente
| Componente | Consumo observado | Crescimento / risco | Política e recomendação |
| --- | ---: | --- | --- |
| Disco raiz | 5,7 GiB de 193 GiB, 188 GiB livres | Baseline de implantação, sem produção comercial | Alertar preventivamente em 70%, crítico existente em 85%; reservar espaço para restore e build |
| RAM | 1.204 MiB usados; 14.787 MiB disponíveis, 15.992 MiB totais | Baseline ocioso não dimensiona pico | Sem swap; limites API/worker 256 MiB cada e PG Hub 512 MiB; medir carga representativa |
| n8n | 337,5 MiB de RAM na amostra | Payloads/node executions podem dominar RAM e disco | Gravar referências e IDs, sem JSON integral de clientes; política explícita abaixo |
| PG original | volume 76,7 MB; banco n8n 18,9 MB | Execuções, índices, dead tuples | Autovacuum mantido; sem VACUUM FULL nem exclusões manuais |
| PG Hub | volume 75,0 MB; banco 17,3 MB | Pedidos, recebimentos e revisões crescem com carga e rechecagem | Preservar fatos, LTV, checkpoints e reconciliação; medir por tabela |
| historico_pedidos | 5.218.304 bytes / 2.406 pedidos sintéticos | JSON normalizado e índices; massa pequena | Não apagar como cache |
| historico_recebidos | 2.138.112 bytes / 7.206 linhas | Ledger por janela/página; reconsultas multiplicam observações | Preservar evidência de completude e deduplicação |
| historico_revisoes | 1.253.376 bytes / 5.011 linhas | Histórico de revisões | Política futura exige análise funcional; nenhuma limpeza agora |
| Docker n8n / runners | imagens 1,94 GB / 885 MB | Builds/versionamento, não RAM residente | Manter versão atual e rollback; inventário antes de limpeza seletiva |
| Docker PostgreSQL | cerca de 650 MB compartilhados | Imagem sem tag também está em uso | Não confundir dangling com descartável |
| Docker Hub | imagem anterior 235 MB; nova versão adicionada | Duas versões intencionais para rollback | Preservar ambas; builds futuros com inventário e prazo de rollback |
| Cache de build | 279,6 MB antes do novo build | Cresce por builds, reduzível | Documentada limpeza por ID/idade após revisão; nenhum prune genérico ativado |
| Logs Docker | menos de 0,1 MB ativos na entrada | Configuração efetiva 10m × 3 nos sete serviços | Limite aproximado 210 MiB + overhead; healthcheck logs também são limitados pelo Docker |
| Logs de aplicação/evidências | menos de 1 MB em infra inicialmente | Logs n8n de teste podem conter metadados e payloads sintéticos | Privados; não centralizar arquivos brutos em Loki |
| Journal | cerca de 36,7 MB inicialmente; 26,9 MB após rotação | Eventos OS/SSH e monitor | Drop-in 256 MB, 64 MB runtime, 30 dias e reserva de 2 GB; sem logging de SQL completo |
| Código/venv | 93,3 MB de código e 74,8 MB venv antes da atualização | Segundo worktree preservado | Manter SHA e rollback; sem resposta JSON comercial nesta VPS |
| Backups locais/staging | diretório vazio fora das execuções | Pico de dump + tar + restore; R2 é remoto | Cleanup verificado; dimensionar staging e restore antes de carga grande |
| Temporários/testes | sem volume de teste órfão na entrada | Ensaios isolados usam UUID e memória temporária | Recursos de restore removidos; volumes persistentes anteriores preservados |
| Telemetria nova | 28 KB no primeiro SQLite; 91 séries após expansão | Amostras a cada 5 min | Detalhe 30 dias, agregados diários 365, teto SQLite 256 MiB; sem dados comerciais |

Medição Docker de RAM na entrada: worker 24,65 MiB, API 42,71 MiB, PG Hub 45,96 MiB, runners 4,31 MiB, n8n 337,5 MiB, cloudflared 16,71 MiB, PG original 66,07 MiB. São amostras pontuais, e o MemPerc dos serviços limitados usa o limite do contêiner como denominador.

Hostinger retornou 56 amostras no intervalo solicitado de 06/11 a 07/11 04h UTC: CPU 0,37–4,03%, RAM 0,62–1,55 GB, disco 2,28–6,08 GB. Aumento de disco coincide com preparação/build; não é uma tendência diária estável. O inventário incluiu vmstat e contadores de rede; não foi feito benchmark de IOPS nem teste de saturação em produção.

## n8n: política efetiva
EXECUTIONS_DATA_PRUNE=true; MAX_AGE=720 horas; PRUNE_MAX_COUNT=10000; HARD_DELETE_BUFFER=24 horas; SAVE_ON_SUCCESS=none; SAVE_ON_ERROR=all; SAVE_ON_PROGRESS=false; SAVE_MANUAL_EXECUTIONS=true.

A primeira condição de idade ou quantidade pode limitar a janela efetiva. Workflows podem sobrescrever os defaults: os três novos ensaios sintéticos guardam sucesso/erro para evidência; os anteriores foram preservados. Não interpretar o default global como prova da configuração de todos os workflows futuros.

Não havia execução persistida nem em andamento antes da mudança; nenhuma execução existente foi removida por comando. Estados new/running/waiting e execuções anotadas ficam fora do pruning nativo conforme a documentação; checkpoints Hub vivem no PostgreSQL do Hub e não dependem do payload de execução n8n. Para investigações futuras, preservar/anotar evidência necessária antes da expiração e manter referência opaca em trilha durável.

## Restic e R2
Backup criptografado, timer diário às 03h30 America/Belem; último backup manual e restauração aprovados. Retenção 7 diários, 4 semanais, 6 mensais, pelo menos 2 recentes continua apenas em dry-run. Snapshots originais protegidos, sem exclusão real e sem prune. A simulação usa tag nexoflow-policy-v1 e grupo host,tags. O relatório não autoriza excluir nada do R2.

O dump do Hub, globals, manifesto, código do SHA, configurações privadas e automação entram na cobertura. Credenciais R2 e senha Restic permanecem fora desses tars e dependem do cofre externo já confirmado. Os novos segredos de consulta precisam de custódia pessoal adicional; não estão neste documento.

## Capacidade projetada
Hipótese conservadora: 8–32 KiB por pedido novo incluindo índices, itens normalizados, revisões e ledger em regime de rechecagem limitado. A amostra sintética de aproximadamente 2 KiB por pedido em sua tabela principal não comprova esse regime; o intervalo é orçamento, a validar com amostra representativa.

| Volume combinado FARMA+PET | Pedidos/ano | Dados adicionais/ano |
| --- | ---: | ---: |
| 1.000 pedidos/dia | 365.000 | 2,8–11,1 GiB |
| 10.000 pedidos/dia | 3.650.000 | 27,8–111,4 GiB |
| 50.000 pedidos/dia | 18.250.000 | 139–557 GiB |

Não estão incluídos nesses valores: retenção de execuções grandes n8n, novas fontes de anúncios, cópias locais de restauração, WAL excepcional, imagens novas e rechecagens ilimitadas. Reservar pelo menos espaço para dois dumps/arquivos do maior conjunto e uma restauração, além de 20% de folga. Antes de 60 GiB de dados de negócio, revisar partições, índices, consultas e RTO.

Conclusão: 200 GB/16 GB são adequados à homologação e a um piloto limitado. Não há evidência para prometer capacidade anual a 10 mil pedidos/dia no cenário superior. A próxima fase deve medir p95 de consulta, throughput, memória de pico, WAL e bytes/pedido com revisões em amostra autorizada. Escalar apenas depois de medir.

## Limpeza seletiva
Não foi removida imagem de rollback nem volume. Não executar docker volume prune, down -v ou system prune --volumes. Antes de remover uma imagem específica: conferir todos os contêineres, referências/digests, snapshot do código e janela de rollback, registrar ID e tamanho e remover somente o ID aprovado. Cache antigo pode ser revisto por idade, sem timer destrutivo nesta etapa. Não tratar ledger, fatos financeiros ou pendências como dados temporários.

Fontes: inventários Docker/du/SQL da VPS; métricas Hostinger; [documentação n8n](https://docs.n8n.io/hosting/scaling/execution-data/).


## Confirmação do agendamento natural
O timer diário foi observado disparando em 07/11/2026 às 03h30min02s. O serviço terminou às 03h30min14s com sucesso, snapshot 9956088d; o marcador de dump Hub avançou às 03h30min03s. Próximo disparo: 08/11 às 03h30. Nenhuma retenção destrutiva foi ativada. Essa prova não substitui ensaio de recuperação ou leitura integral do snapshot novo.
