# Migração Windows/PostgreSQL/Data Studio

**1.5.37 publicada; migração comercial pendente.** Base: `5b21d4799115a490447c483d5a40788cd59eb100`; distribuição anterior: 1.5.36. Código, teste, release, instalação, implantação e conciliação comercial são etapas distintas. O Codex não acessou C: nem executou carga comercial. O Work implanta/concilia VPS e relatório; o operador executa o Terminal Windows.

## Contrato e fronteiras

Contrato novo `nexoflow_datastudio_1`: produção em `nexoflow_datastudio`, teste curto em `nexoflow_datastudio_homologacao`, schemas farma/pet/controle. O Work cria somente o banco de homologação novo no PostgreSQL privado existente, se ausente. Preservar o piloto e seus contratos `bi_itens_farma_1`/`bi_itens_farma_leitura_1`; não reapontá-los por DSN. Preservar a visão/grants Metabase e os bancos Métricas, Hub e n8n.

O Work confirmou o 001 já aplicado em `/opt/nexoflow/datastudio/migrations/001_base.sql`: banco/schema pertencentes a nfds_admin e PUBLIC restrito. **Não reaplicar seus CREATE SCHEMA não idempotentes.** O novo `integrations/datastudio/002_backend.sql` é aditivo/idempotente e precisa do comando admin para completar hash do contrato, visões e grants.

A origem inicial é **histórico READY + base operacional acumulada dos três arquivos**, com leitura de todas as continuações. O SQLite recente não substitui o histórico publicado. O [inventário](ESTRUTURA%20POSTGRESQL%20DATA%20STUDIO.md) e `app/ds_backend/registry.json` documentam cada tabela/chave/grão/campo. A lista real das 37 fontes do relatório, inclusive as usadas só por mesclagens, precisa ser confrontada pelo Work. Abas ausentes são registradas separadamente de abas vazias; entradas manuais não são presumidas inexistentes.

Referências fornecidas: histórico 267.722 pedidos/552.261 itens; SQLite recente 38.877 pedidos; simulação BI_Itens 552.826 linhas, com 484.610 inserções, 181 atualizações e 68.035 mantidas. A diferença de 565 linhas é aritmética, **não causa comprovada**. Os 68.273 itens do piloto não são todo o histórico financeiro. A composição real depende da exportação/auditoria privada; nenhuma carga anual adicional foi executada.

## Persistência e leitura

`nf_registros` conserva versões por chave; `nf_stage` recebe a revisão WRITING; `nf_execucoes`, `nf_lotes` e `nf_publicacoes` controlam recibos/hash e a versão ativa por segmento. Somente o fechamento confirmado move o ponteiro, na transação que valida lotes, membros das substituições, corte inicial aprovado e igualdade financeira. O Data Studio mantém o READY anterior durante WRITING. Não há resposta parcial apresentada como completa.

Mesmo UUID/hash devolve o mesmo recibo, inclusive após resposta perdida; outro conteúdo é recusado. Revisão antiga não sobrescreve nova. Um gravador por segmento é imposto no PostgreSQL; lock local não coordena PCs diferentes. A ancestralidade evita ressuscitar revisões revertidas. Rollback só altera o ponteiro quando não há publicação posterior incompatível, mantendo fatos/recibos.

Weni/Recompra/campanha 25% usam estados CAS remotos. Estado ausente exige importação explícita; não se reinicializa silenciosamente. A confirmação precede a cópia local. O SQLite de trabalho é temporário, reconstruído do servidor, sem abrir o SQLite comercial original. Triggers temporários enviam somente mudanças de observações, janelas, revisões e recibos antes do commit do cache.

O transporte reutiliza os validadores existentes. Cache incompleto não apaga compra válida; fechamento antigo continua exigindo reconciliação. Exclusões migram com hash do fato original e não são reaplicadas a fatos alterados. Item usa chave própria, mesmo com SKU repetido; correção/cancelamento é conciliado por venda completa. Ausência em coleta parcial não autoriza remoção.

Detalhes usam deltas e ignoram alteração só do marcador `atualizado_em`. As visões BI_Itens/BI_Clientes_Vendas/BI_Clientes/BI_Pedidos acrescentam o histórico ausente do BI operacional sem somar pedidos aos itens. Chaves operacionais existentes têm precedência por venda completa. Itens somente históricos têm namespace próprio; preço unitário, hora ou pagamento não conservados ficam indisponíveis. O commit bloqueia divergência de produtos por pedido ou LTV por cliente.

Dinheiro permanece decimal/centavos; frete oficial entra uma vez; frete técnico não é produto/unidade. Cancelados não geram faturamento. LTV usa cliente oficial, inclusive sem Weni, e independe do filtro mensal. `LIMITES_DA_API_NAO_HOMOLOGADOS` permanece.

## Implantação pelo Work

Conferir SHA, CI e pacotes; criar backup consistente do piloto/definitivo com hash e catálogo. Conferir disco **do volume PostgreSQL**, memória e conexões. Não recriar a infraestrutura ou alterar os seis arquivos do helper sem inspecionar a configuração real.

Organização proposta dentro da reserva existente:

```text
/opt/nexoflow/datastudio/codigo/<SHA>/
/opt/nexoflow/datastudio/migrations/002_backend.sql
/opt/nexoflow/datastudio/segredos/<ambiente>/FARMA/
  publicacao-config.json  publicacao-dsn  publicacao-token
  leitura-config.json     leitura-dsn     leitura-token
/opt/nexoflow/datastudio/segredos/<ambiente>/PET/
```

Pastas de segredo 0700; arquivos 0400, legíveis pelo UID 10001 dos serviços, com proprietário restrito. DSN/senha ficam somente na VPS. Não passar segredos na linha de comando. O exemplo `integrations/datastudio/runtime.example.json` usa mode publish/read e arquivos `/run/secrets/dsn` e `/run/secrets/token`.

No checkout do SHA validado, com DSN administrativo privado:

```bash
PYTHONPATH=app:. python -m integrations.datastudio.admin \
  --dsn-file /caminho/privado/admin-dsn --ambiente homologacao --segmento FARMA

docker build --build-arg NEXOFLOW_SOURCE_SHA="$sha" \
  -f integrations/datastudio/Dockerfile -t "nexoflow-datastudio:$sha" .
```

O admin cria papéis NOLOGIN `nf_ds_farma_publish` e `nf_ds_farma_read`, equivalentes PET, com RLS/visões e sem acesso cruzado. Recusa papéis superuser, CREATEDB/CREATEROLE/REPLICATION/BYPASSRLS ou memberships adicionais. O Work provisiona LOGIN/senha dedicada em sessão privada e limita conexões. Publicação recebe fatos/controles necessários; leitura somente visões autorizadas, sem caches/estados.

O overlay `integrations/datastudio/compose.services.yaml` não define PostgreSQL, volume operacional ou portas. `NEXOFLOW_DATASTUDIO_NETWORK` é a rede privada real, conferida pelo Work; `NEXOFLOW_DATASTUDIO_IMAGE` é a imagem do SHA; `NEXOFLOW_DATASTUDIO_SECRETS` aponta à pasta privada do ambiente. Anexar apenas os serviços novos ao Compose real e ao túnel existente, preservando os serviços anteriores. PET está em profile separado.

Criar aplicações Cloudflare Access Service Auth separadas para publicação/leitura, ambiente e segmento. Tokens Access são emitidos pelo provedor; bearer da API é dedicado. Não reutilizar tokens Weni/Meta/FarmaLíder/n8n/piloto. Conferir healthchecks, contas mínimas, autenticação e ausência de porta PostgreSQL pública. Repetir o admin para produção com o DSN do definitivo, **usando a mesma imagem do teste curto**. DSN para o piloto/outro banco deve falhar.

## Windows, configuração e corte

Instalar o Setup oficial validado em **Preserve**, sem módulos avulsos. Preservar SQLite, configuração, credenciais, journals e importações. Pausar rotinas FARMA durante o corte; PET permanece separado. Os arquivos privados Windows usam o modelo `configuracao/datastudio/publicacao.example.json`:

```text
C:\NexoFlow\credentials\datastudio\FARMA\homologacao\publicacao.json
C:\NexoFlow\credentials\datastudio\FARMA\producao\publicacao.json
C:\NexoFlow\credentials\datastudio\PET\homologacao\publicacao.json
C:\NexoFlow\credentials\datastudio\PET\producao\publicacao.json
```

O Work preenche endpoint HTTPS, bearer e Client ID/Secret Access por canal privado. Campos vazios nos exemplos são deliberados, sem chaves inventadas. O Windows recebe somente publicação; leitor usa outra credencial no Apps Script. Google Sheets não é exigido depois do corte, salvo APIs Google independentes realmente utilizadas.

No Terminal FARMA:

```powershell
nexo versao
nexo armazenamento postgres --help
nexo armazenamento postgres configurar --ambiente homologacao `
  --credencial "credentials\datastudio\FARMA\homologacao\publicacao.json"
nexo armazenamento postgres diagnosticar
```

Configurar não ativa o backend. O comando preserva tokens/perfis, edita só o bloco correspondente sem executar o arquivo para editá-lo e guarda backup em `credentials\datastudio\backup-configuracao`.

Use a revisão histórica READY e **a cópia cujo SHA consta em evidence dessa revisão**. Manter ambos os planos/bancos antigos. Vincular as variáveis abaixo aos caminhos reais privados; não usar o SQLite recente de cobertura menor:

```powershell
$p = "C:\NexoFlow\logs\privado\migracao-postgres"
New-Item -ItemType Directory -Force $p | Out-Null
nexo armazenamento postgres extrair-exclusoes `
  --revisao-publicada $revisaoHistoricaReady --banco $sqliteDaRevisaoReady `
  --origem-revisao $idHistoricoReady --saida "$p\exclusoes.json"
nexo armazenamento postgres exportar-sheets `
  --origem-revisao $idHistoricoReady --exclusoes "$p\exclusoes.json" `
  --exportacao "$p\corte.sqlite" --saida "$p\corte-manifesto.json"
nexo armazenamento postgres auditar-exportacao `
  --exportacao "$p\corte.sqlite" --saida "$p\corte-conferencia.json"
```

A exportação lê as partes em blocos de até 1.000 linhas, confere origens/cabeçalhos, manifesto READY, ausência de gravador/recuperação e versões Drive antes/depois. Não escreve em Sheets, não coleta a API anual e não sela corte alterado durante a leitura. Abas desconhecidas não viram fontes automaticamente. Se a cópia da revisão READY estiver indisponível, localizar a evidência preservada; não fabricar exclusões ou substituir o corte.

## Teste curto e carga completa

Escolher privadamente um pedido válido completo; não colocar seu ID em Git/CI. O recorte recalcula LTV/resumo para esse subconjunto e não pode ser publicado como produção:

```powershell
nexo armazenamento postgres recortar-piloto --exportacao "$p\corte.sqlite" `
  --pedido $pedidoPiloto --saida "$p\piloto.sqlite"
nexo armazenamento postgres auditar-exportacao --exportacao "$p\piloto.sqlite" `
  --saida "$p\piloto-conferencia.json"
nexo armazenamento postgres manifesto --exportacao "$p\piloto.sqlite" `
  --saida "$p\piloto-manifesto.json"
```

Enviar o manifesto privadamente ao Work. Aprovação administrativa no banco de homologação:

```bash
PYTHONPATH=app:. python -m integrations.datastudio.admin \
  --dsn-file /caminho/privado/admin-dsn --ambiente homologacao --segmento FARMA \
  --aprovar-origem /caminho/privado/piloto-manifesto.json
```

```powershell
nexo armazenamento postgres preparar --exportacao "$p\piloto.sqlite" --revisao "$p\piloto-plano.json"
nexo armazenamento postgres simular --revisao "$p\piloto-plano.json"
nexo armazenamento postgres aplicar --revisao "$p\piloto-plano.json" --max-lotes 1
nexo armazenamento postgres retomar --revisao "$p\piloto-plano.json"
nexo armazenamento postgres conferir --saida "$p\piloto-observado.json"
```

Conferir recibo, repetição sem duplicação, pedido completo, unidades/receita/contagem no SQL e no Data Studio piloto. Comparar com o piloto/Metabase no mesmo universo possível. Um teste curto não comprova os demais pedidos.

Depois desse teste, aprovar o **corte-manifesto completo** com o mesmo admin em `--ambiente producao`. Não confundir relatório agregado com manifesto. Configurar a publicação de produção ainda sem ativar o Analytics:

```powershell
nexo armazenamento postgres configurar --ambiente producao `
  --credencial "credentials\datastudio\FARMA\producao\publicacao.json"
nexo armazenamento postgres diagnosticar
nexo armazenamento postgres capacidade --exportacao "$p\corte.sqlite"
nexo armazenamento postgres preparar --exportacao "$p\corte.sqlite" --revisao "$p\producao-plano.json"
nexo armazenamento postgres simular --revisao "$p\producao-plano.json"
nexo armazenamento postgres aplicar --revisao "$p\producao-plano.json" --max-lotes 1
nexo armazenamento postgres retomar --revisao "$p\producao-plano.json"
nexo armazenamento postgres conferir --saida "$p\producao-conferencia.json"
```

Lotes de até 1.000 registros e corpo HTTP até 7 MB, ordem por tabela/chave e UUID determinístico. Não há truncamento. O piloto não libera a revisão parcial: READY somente após todos os lotes e a conferência na transação. A API informa tamanho do banco e do plano; **espaço livre do volume é conferência administrativa do Work**, não estimativa do filesystem do contêiner.

Com rotinas paradas, importar estados atuais privados. Ausência comprovada de campanha pode ser registrada como `{}`; não descartar uma campanha ativa:

```powershell
nexo armazenamento postgres importar-estado --estado weni_update --arquivo $estadoWeniAtual
nexo armazenamento postgres importar-estado --estado recompra --arquivo $estadoRecompraAtual
nexo armazenamento postgres importar-estado --estado carga_fracionada --arquivo $campanhaAtualOuAusenciaComprovada
nexo armazenamento postgres configurar --ambiente producao `
  --credencial "credentials\datastudio\FARMA\producao\publicacao.json" `
  --backend postgres --ativar
```

Ativar exige READY, nenhuma revisão pendente e estados existentes. Analytics passa a usar base acumulada/deltas/BI/Controle/histórico pela API; Noturno mantém Weni → Analytics → Recompra. Incremental histórico continua hoje..D−20 conforme configuração. Histórico completo exige período explícito. A instalação não executa essas rotinas. O transporte novo não depende da gravação anterior em Sheets e não faz fallback silencioso.

## Conector, corte do painel e reversão

Implantar `connectors/datastudio_api/Code.js`, `Schemas.js`, `appsscript.json` em projeto privado novo. Não substituir os projetos Sheets/piloto. Conferir `python scripts/sync_datastudio_schema.py --check` no SHA validado. Script Properties: `NFDS_FARMA_HOMOLOGACAO`, `NFDS_FARMA_PRODUCAO`, equivalentes PET, com JSON **leitor**, nunca publicação.

Na cópia do relatório, selecionar segmento/ambiente/tabela e grão explícito MES/ANO/TOTAL/SEM_EMISSAO em BI_Historico_Resumo. Não somar meses ao TOTAL ou compradores entre meses. O cartão `produtos_distintos_periodo` usa COUNT DISTINCT SQL em todo o período, com SKU informado. `atualizado_em` segue Texto; LTV é acumulado. Códigos de produto permanecem texto.

Conferir todos os campos/formatos, filtros de período, rankings, períodos vazios e mesclagens. Sem linhas, receita/unidades ficam sem dados. Não inventar custo zero, CAC/ROAS, crédito de anúncio ou conversas atribuídas por join de data. Histórico financeiro e snapshots operacionais não são o mesmo corte sem evidência de cobertura. IDs individuais de clique ficam no armazenamento privado, fora da visão leitora Base_Contatos.

Consulta detalhada acima de 50 mil linhas/7 MB exige resumo/período menor e falha explicitamente. Trava/schema/permissão/erro SQL nunca libera total parcial. O READY anterior continua disponível durante WRITING; o contrato antigo do piloto mantém suas guardas próprias.

Antes da migração, preservar e conferir as 37 fontes, incluindo as três mesclagens informadas: pedidos/produtos por cliente (BI_Clientes_Vendas + BI_Itens), anúncios/contatos/pedidos (Base_Contatos + BI_Pedidos), e LTV por cliente (fontes integrantes ainda a reconferir). Zero gráficos diretos não autoriza remover fonte. Após teste curto, corte completo READY e totais objetivos conciliados, o Work troca as conexões oficiais preservando componentes e a fonte anterior para reversão.

Retomada de publicação preparada não chama APIs comerciais:

```powershell
nexo armazenamento postgres status --id-revisao $idRevisaoPostgres
nexo armazenamento postgres retomar --revisao "$p\producao-plano.json"
# Só para Analytics já totalmente calculado/selado antes de resposta perdida:
nexo armazenamento postgres finalizar-selada --id-revisao $idRevisaoPostgres
nexo armazenamento postgres reverter --id-revisao $idRevisaoPostgres --versao $versaoAtivaConferida
# Após análise, abortar somente WRITING; fatos READY ficam preservados:
nexo armazenamento postgres abortar --id-revisao $idRevisaoPostgres
```

Revisão não selada não pode ser declarada completa. Recuperar evidências/checkpoints e completar o trabalho faltante, sem criar READY manualmente. Rollback mantém versões e não sobrescreve publicação posterior. Para voltar a Sheets depois de incrementais PostgreSQL, conciliar antes o delta pós-corte; a fonte antiga não fica automaticamente atualizada. `configurar --backend sheets ...` é reversão explícita, não sincronização inversa automática.

## Backup e limites da comprovação

Incluir o banco definitivo inteiro, papéis/grants, imagem/SHA, configs privadas, exportações/revisões e `credentials/datastudio/backup-configuracao` nas rotinas existentes. `pg_dump` consistente, SHA/catálogo, criptografia/R2 privado e restore em banco descartável. Não excluir volumes/backups antigos. Restore administrativo é distinto do rollback do aplicativo.

Os testes locais/CI usam dados sintéticos e serviços simulados/PostgreSQL descartável. Ainda dependem do Work/operador: conciliação dos cortes reais, fontes/campos do relatório, presença de dados manuais, Access implantado, capacidade física, estados atuais e troca de fontes. PET tem contrato/credenciais/isolamento preparados; seu corte ocorre depois da validação FARMA. Não declarar migração comercial concluída por causa de release ou teste aprovado.

## Distribuição conferida

Publicada em **12/11/2026, 19:18:38 (America/Fortaleza)**, SHA `2683717431b1c4313efaaaef35cfaaf20236958a`. [Release](https://github.com/felipetelesbarbosa/NexoFlow/releases/tag/v1.5.37), [CI e pacotes](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/43314024652), [CodeQL](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/43314024795), [Meta](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/43314026009) e [publicação reutilizando os artefatos](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/43318519275). Downloads públicos conferidos: hashes, CRC, 571 entradas do manifesto, 123 módulos e versões dos executáveis. Sem implantação ou migração comercial.
