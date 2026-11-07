# Etapa 3.5 | Retomada e validação complementar
07/11/2026 | America/Fortaleza (UTC-3). VPS 2132956. Homologação isolada.

## Parecer
**Infraestrutura aprovada com ressalvas. A Etapa 3.5 permanece em validação parcial.** O motor do Hub funciona; não há liberação comercial. Este complemento precede o relatório original e prevalece nos pontos atualizados. As páginas originais preservam o registro da execução anterior, inclusive pendências que podem ter sido resolvidas neste complemento.

## O que esta retomada confirmou
| Item | Resultado comprovado |
| --- | --- |
| Serviços | Sete contêineres saudáveis. Nenhum recriado nesta retomada. |
| Código em execução | API/worker na imagem hml-d89af58; worktree no SHA d89af58f9d6a73a4dd64309823cdba53f368a8e8. |
| Proteções | HUB_AMBIENTE=homologacao; HUB_ESCRITA_REAL=false; 10 workflows, zero ativos; nenhuma porta Docker publicada. |
| Persistência | 27 tarefas, 2.406 pedidos sintéticos, 84 checkpoints e 169 auditorias, iguais à conferência anterior. |
| Consulta PostgreSQL | Autenticação e views agregadas acessíveis nos dois relays locais; tabelas brutas recusadas; leitores sem superuser, createdb, createrole ou bypassrls. |
| Retenção e coleta | Logs 10m x 3 nos sete serviços. n8n: 720h/10 mil execuções, sucesso none, erro all, manuais true, progresso false. Telemetria com Result=success; monitor sem problemas ativos. |
| Recursos | Amostra das 03h14: 6.290.685.952 bytes de disco usados (4%); 200.592.818.176 disponíveis; RAM usada 1.254 MiB e disponível 14.737 MiB. São amostras, não capacidade comercial certificada. |
| Persistência systemd | Timers de backup, monitor e telemetria e os dois sockets de consulta habilitados e ativos. |

## Backup automático
O timer disparou naturalmente em 07/11/2026 às 03h30min02s. O serviço terminou às 03h30min14s com Result=success e ExecMainStatus=0; o marcador do Hub avançou para 03h30min03s. O journal registra o snapshot 9956088d. O próximo disparo está agendado para 08/11 às 03h30. Sete contêineres continuavam saudáveis na conferência das 03h30min25s. A pendência do primeiro disparo natural está resolvida.

O ensaio de restauração isolada do snapshot 03106ced e a leitura integral Restic anteriormente aprovados permanecem registrados no relatório original. Confirmar um backup novo não equivale a repetir a restauração ou a leitura integral dele. Nenhum snapshot foi excluído, e a retenção destrutiva continua bloqueada.

## Documentação e inventário BI
O commit a24799d9749823e8ece2be7d41a40f6e9137cdde atualizou exclusivamente a matriz e seu relatório de inspeção, com [skip release]. A matriz conserva 106 linhas, 12 colunas e chaves únicas por marca/página/elemento. As cópias documentais foram sincronizadas na pasta de evidências da VPS sem trocar o worktree ou o código executado.

Foram reduzidas lacunas de bindings dos quatro cards de Resumo, joins de Pedidos por cliente em FARMA/PET, regra temporal e filtros da combinação de Anúncios FARMA, além de ensaios de período vazio e paginação. O complemento específico descreve cada prova.

Os diálogos de exportação PDF foram inspecionados e cancelados nas duas marcas, sem exportar clientes ou certificar permissões dos futuros perfis. Os filtros temporários foram redefinidos.

**Nenhuma das 19 páginas é declarada integralmente homologada em todos os critérios.** Dez páginas FARMA e nove PET foram percorridas; persistem lacunas de fórmulas upstream/comunitárias, unicidade e interações. Os Data Studio foram preservados. No Métricas, Pets terá as mesmas páginas do Farma e os KPIs adicionais especificados.

## Implementado versus planejado
Implementados na Etapa 3.5: atualização sintética 1.5.18, retenção n8n, leitores/views/relays PostgreSQL, coletor mínimo local, limites e monitoramento. Revalidados nesta retomada sem nova alteração de serviços.

Apenas especificados: Grafana/Prometheus/Loki, frontend da Central, frontend do Métricas, autenticação e autorização próprias dos produtos, telemetria de chamadas comerciais e KPIs que dependem de novas fontes. Nenhum domínio ou painel novo foi publicado.

## Pendências e próxima etapa
- Windows/DBeaver: instalação e teste do caminho SSH/PostgreSQL; custódia de segredos e chaves individuais.
- Codex: separar migrador/runtime; implementar conectores read-only, egress, orçamento de ensaio e telemetria; depois, autenticação, autorização e paridade BI.
- Homologar separadamente a correção baafc61 para janelas históricas vazias antes da leitura real. Ela está no repositório e não foi implantada automaticamente.
- FRETE_DIVERGENTE depende de resposta oficial; a base Windows não foi acessada.
- Etapa 4: confirmar autorização, credenciais, pequena janela e limites; FARMA/PET primeiro, depois Weni/Meta/Google. Sem cargas anuais ou escrita.
- Exposição pública, novos acessos, escrita, exclusões de snapshots e reboot dependem de autorização específica.

## Mudanças e rollback desta retomada
Nesta retomada mudaram apenas documentos e evidências. O rollback operacional permanece no relatório original; alterações documentais podem ser revertidas por commit, sem mudar a versão Windows.

A conexão com o navegador caiu após as validações. A cópia final dos documentos do commit 90c5bad para a VPS não foi executada. A cópia BI a24799d já havia sido sincronizada. Os entregáveis e o GitHub preservam o fechamento; última saúde confirmada às 03h30min25s.
