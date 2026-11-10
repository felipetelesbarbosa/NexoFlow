# Analytics, histórico e publicação automática — 1.5.31

A [1.5.31 foi publicada](https://github.com/felipetelesbarbosa/NexoFlow/releases/tag/v1.5.31) em 10/11/2026, no SHA a31237c088e4b699f166086d01abfbb7da0b9a18. A 1.5.30 permanece intacta. A carga anual FARMA concluída pelo operador não foi repetida durante o desenvolvimento.

## Rotina

Com `FARMALIDER_HISTORY_ENABLED = True` no perfil, o Analytics consulta os pedidos de hoje até 20 dias atrás, inclusive, em America/Belem, com limite padrão 500. Janelas antigas incompletas fora desse recorte permanecem no SQLite para retomada explícita pelo Terminal; o Analytics não as inclui automaticamente. Reconsulta os pedidos recentes para capturar alterações e cancelamentos. Não usa a data de modificação do contato como cursor de pedidos. Limites da API continuam não homologados; páginas completas não provam cobertura civil completa.

O Analytics conserva suas etapas de contatos, pedidos/itens, BI, Looker e Meta nativo. Depois executa o mesmo publicador histórico validado pelo Terminal, alimentando Historico_Pedidos, Historico_Itens, BI_LTV_Clientes, BI_Cobertura_Historica e BI_Historico_Resumo, com continuações. Não recria as planilhas. Tabelas opcionais continuam dependentes das respectivas credenciais, fontes e evidências; atualizar Analytics não inventa custos, CAC, atribuições ou conversas. O relatório Data Studio precisa atualizar sua leitura das fontes já conectadas; o Analytics não edita a diagramação.

`FARMALIDER_HISTORY_SHEETS_ENABLED` herda o valor de `FARMALIDER_HISTORY_ENABLED` quando ausente. Pode ser explicitamente False para coletar e manter a publicação manual. No exemplo distribuído ambos ficam False até conferir os destinos do perfil. Preserve não altera o secrets_config.py instalado. Em PET, habilitar somente dentro de PERFIS["PET"], após validar seus três destinos e fontes próprias. Nenhuma fonte FARMA é reutilizada.

A carga completa de contatos não significa carregar todos os anos de pedidos. Para histórico completo, o operador escolhe o período explicitamente:

```powershell
nexo analytics --historico-inicio 2020-04-20 --historico-fim 2026-11-07
```

O comando abre o fluxo normal do Analytics, herdando as datas no subprocesso. A coleta histórica usa o intervalo informado (janelas/paginação existentes), sem limitar o LTV acumulado a esse intervalo. O período explicitamente solicitado ativa também a publicação histórica nessa execução. Não inferir que repetir um período já concluído força uma reconciliação de todos os pedidos antigos; a retomada existente conserva seus checkpoints.

Para a rotina diária, basta abrir **NexoFlow Analytics** ou executar `nexo analytics`. O Noturno já chama o Analytics e recebe a mesma etapa quando habilitada. Não é necessário usar Terminal opção 10 diariamente. Não executar duas cargas do mesmo perfil simultaneamente.

## Publicação e recuperação

O publicador mantém snapshot consistente SQLite com WAL, journal, assinatura, manifesto, travas, capacidade, backups por lote, validação das células e conferência financeira. Grava somente diferenças de chaves/valores; uma execução idêntica não reenvia linhas. A conferência inicial ainda lê as partes: incremental não significa ausência de leituras remotas.

Estado privado por perfil: `logs/privado/historico_publicacoes/analytics_estado.json` (PET: `logs/PET/privado/...`). Cada nova revisão automática guarda `revisao.json`, `plano.sqlite`, evidência e `fechamento_analytics.json` em subpasta própria. O estado só é concluído após a releitura completa sem divergências. Não editar/apagar esses arquivos.

Se uma revisão automática foi interrompida, retoma seu snapshot antes de preparar outro. Novos pedidos coletados enquanto ela estava pendente serão publicados na próxima execução; o resumo retorna pendência explicitamente. Uma revisão manual ainda WRITING precisa ser concluída pelo Terminal na mesma revisão. A automação não toma posse dela. Respostas incertas passam pelas guardas do motor antes de qualquer nova gravação.

O manifesto identifica a última revisão publicada. Seu journal e sua evidência precisam continuar disponíveis localmente. Para exclusões autorizadas, copia a auditoria para o NOVO snapshot de publicação e remove apenas os mesmos fatos na cópia; o SQLite de coleta permanece intacto. Se proprietário, data, estado, itens ou valores mudaram, bloqueia com EXCLUSAO_ALTERADA_REQUER_REVISAO. A autorização anterior de exclusão era da publicação histórica: não redefine políticas dos validadores legados nem apaga fatos da API/Weni. As fontes operacionais têm seus próprios critérios; não unir universos financeiros diferentes como se fossem iguais.

Falha de publicação é isolada, registrada sem mensagem/URL do provedor, retorna código parcial 3 e impede avanço do checkpoint de sucesso do Analytics. Etapas já confirmadas continuam preservadas. Não afirmar que todas as fontes estão atualizadas se qualquer etapa estiver pendente. Dados sem evidência e pendências financeiras continuam excluídos dos indicadores pertinentes.

## Frações, lote e rollback

```powershell
# Publica até 25% do total original de lotes da revisão automática.
nexo analytics --percentual 25
# Coleta explicitamente um período e limita a aplicação histórica dessa execução.
nexo analytics --historico-inicio 2020-04-20 --historico-fim 2026-11-07 --percentual 25
```

Também aceita 50, 75 e 100. Uma fração é teto de lotes, arredondado para cima, não divisão garantida por datas/receita. Se o saldo for menor, conclui o saldo. Quatro chamadas de 25% podem terminar antes da quarta por arredondamento. Cada lote continua com até 200 linhas e backup próprio.

O Terminal conserva a operação manual:

```powershell
# $revisao deve apontar ao revisao.json efetivamente criado, sem inventar caminho.
nexo historico --planilhas aplicar --revisao $revisao --percentual 25
nexo historico --planilhas conferir --revisao $revisao --resumo-mensal $conferencia
nexo historico --planilhas aplicar --revisao $revisao --retomar-lote 33
nexo historico --planilhas rollback --revisao $revisao --lote 33
```

O número 33 é somente exemplo: use o primeiro lote pendente indicado no diagnóstico. Não pular lotes ou combinar percentual com max-lotes/retomar-lote. Rollback recusa sobrescrever edição posterior de terceiros. Para uma revisão automática, retomar preferencialmente pelo Analytics; a mesma revisão pode ser conferida/recuperada manualmente pelo Terminal. Após rollback, a automação não deve ser executada até terminar a revisão manualmente ou conferir seu estado.

## Tempo e quota

Cabeçalho e intervalos são relidos em uma chamada agrupada, preservando geometria e validações, sem cache de segurança. Os limites preventivos continuam ativos. Durações dos logs comuns e publicação passam de segundos para minutos/horas: `61s` → `1min 1s`; `68079s` → `18h 54min 39s`. JSON/SQLite e métricas numéricas permanecem em segundos; progresso que já usa HH:MM:SS mantém esse formato. Espera preventiva é acumulada, não uma nova espera a cada linha.

Não há promessa de prazo ou ausência absoluta de 429: outros processos/computadores também consomem a quota.

## Atualização e evidências para o Work

1. Encerrar execuções; guardar backup consistente e os journals/comprovantes da publicação anterior.
2. Atualizar somente pelo Setup **Preserve** e conferir `nexo versao`.
3. No perfil FARMA, conferir origens, status do armazenamento, cinco fontes e manifesto READY. Não usar confirmar-fontes sem conferir as conexões reais.
4. Conferir os flags locais e a presença do journal/snapshot da última revisão publicada; não copiar segredos para Git/CI.
5. Executar Analytics e conferir separadamente status das integrações e cinco tabelas históricas. Se fracionado, continuar na mesma revisão automática.
6. Comparar fechamento mensal/TOTAL e LTV em centavos; preservar exclusões, pendências e cobertura. Conferir no Data Studio atualização e grãos das fontes, sem somar mensal/ano/TOTAL.
7. Só depois replicar a ativação no PET com suas credenciais/destinos. Não coletar novamente a base anual só para validar a atualização.

Validação comercial posterior continua necessária. Os testes de código usam SQLite sintético e Sheets simulado; não são uma nova homologação dos totais comerciais nem da conta Google.
