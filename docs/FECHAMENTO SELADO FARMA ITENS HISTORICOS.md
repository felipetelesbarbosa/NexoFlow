# Fechamento selado FARMA — itens completos e projeção em volume

## Ocorrência e correção

O operador informou a revisão selada `ca214c78-e590-4056-b58e-31877714facc`, com 2.775 recibos e 2.750.730 registros. Uma venda contém 149,90 em uma linha/unidade operacional, mas 162,80 em duas linhas/unidades históricas, reconciliadas com produtos do cabeçalho. Também houve timeout de 50 segundos no INSERT em nf_atuais. Esses números são referência operacional fornecida pelo usuário, não leitura da VPS pelo Codex.

A visão ds_bi_itens descartava todo o histórico de uma venda pela mera existência de qualquer item operacional. Regressão PostgreSQL com os valores acima falhou antes da correção em FARMA e PET.

A nova visão escolhe uma fonte para a venda inteira:

- Se os produtos operacionais reconciliam, conserva as chaves operacionais.
- Se não há operacional, ou se a soma operacional válida é menor que produtos do cabeçalho, usa todos os produtos históricos válidos/vigentes somente quando sua soma fecha exatamente com o cabeçalho.
- Não mistura o primeiro item operacional com o segundo histórico. Não inventa preço unitário, SKU, nome ou identidade de cliente. Itens históricos mantêm o namespace historico_item da chave publicada; a venda e o cliente mantêm suas chaves oficiais derivadas.
- Histórico divergente, item não vigente/cancelado e excesso operacional não autorizam fallback. A conferência financeira continua bloqueando diferenças.
- Frete técnico não é produto/unidade; o frete oficial continua no cabeçalho, uma única vez. Cabeçalhos cancelados, pendentes, não vigentes ou excluídos não reaparecem por essa seleção. FARMA e PET continuam em schemas separados.

Nenhum fato de BI_Itens, Historico_Itens, pedido ou SQLite é reescrito por essa escolha. A revisão inicial ainda precisa conferir os hashes de todas as tabelas contra a origem aprovada.

## Fechamento em volume

O gravador percorre nf_stage por cursor (tabela,chave), usando a chave primária existente. Cada instrução altera até 5.000 registros; não utiliza OFFSET nem carrega milhões de chaves em memória. nf_registros, upsert em nf_atuais e tombstones usam o mesmo intervalo limitado. Registros atuais idênticos não recebem UPDATE redundante.

Os blocos são instruções da **mesma transação**, não novos lotes comerciais nem commits parciais. Continuam os 2.775 recibos originais. As verificações de revisão/base, intenção selada, contrato, conjunto completo de recibos, membros de substituições, hashes da origem e igualdade financeira continuam obrigatórias. READY, recibo e ponteiro ativo só são confirmados no commit final. Uma falha desfaz os blocos daquela tentativa e conserva staging, intenção e recibos já enviados. O READY anterior permanece legível por MVCC.

Não houve aumento do statement_timeout global (50 s) nem do prazo HTTP. Para o volume informado, o comando administrativo local abaixo evita depender dos 65 s do cliente Windows e dos limites do proxy HTTP. Ele usa Store.finish, sem reconstruir manifestos ou reenviar lotes. Logs de progresso não são recibos READY.

## Procedimento do Work na VPS

Usar o SHA desta correção depois dos checks. O schema_hash do contrato permanece igual ao da 1.5.40; não editar nf_contrato, assinaturas, manifests ou journals. Esta correção é de servidor/visões, e o comando Windows de status existente pode ser usado na 1.5.40.

1. Conferir segmento, ambiente/banco e revisão reais. Verificar processo/pg_stat_activity antes de iniciar outra tentativa. Se um fechamento estiver ativo, acompanhá-lo; não concorrer com ele nem adotar WRITING pelo tempo do heartbeat.
2. Preservar o SQLite, planos, intenção selada, staging, versões e recibos. Fazer backup PostgreSQL consistente e conferir hash/catálogo/disco do volume. Confirmar ausência de outro gravador e pausar os serviços definitivos para a manutenção. Preservar piloto, Metabase, Hub, Métricas e n8n.
3. No checkout/imagem do SHA validado, preparar visões e permissões pelo admin existente, com DSN administrativo privado do **banco definitivo correto**. Não reaplicar 001. Não usar aprovar-origem para mudar a origem desta revisão. A criação/revisão das visões deve preceder o fechamento para que a validação financeira leia a regra corrigida.
4. Executar o novo fechamento local. `DSN_ADMIN` deve apontar para o arquivo já provisionado; o segredo não vai na linha de comando. `RECIBO_READY` deve ser um caminho privado novo da reserva operacional. Variáveis abaixo não são valores de credenciais.

```bash
set -euo pipefail
: "${DSN_ADMIN:?Defina o caminho do DSN administrativo privado existente}"
: "${RECIBO_READY:?Defina o caminho privado do recibo desta revisão}"
test -f "$DSN_ADMIN"
export NEXOFLOW_SOURCE_SHA="$(git rev-parse HEAD)"

PYTHONPATH=app:. python -m integrations.datastudio.admin \
  --dsn-file "$DSN_ADMIN" --ambiente producao --segmento FARMA

PYTHONPATH=app:. python -m integrations.datastudio.admin \
  --dsn-file "$DSN_ADMIN" --ambiente producao --segmento FARMA \
  --finalizar-selada ca214c78-e590-4056-b58e-31877714facc \
  --recibos-esperados 2775 --registros-esperados 2750730 \
  --saida "$RECIBO_READY"
```

Executar em sessão persistente e privada da VPS, fora do caminho HTTP, com o runtime Python das dependências bloqueadas da mesma imagem/checkout. Não presumir que o Python do host tem essas dependências. Se usar docker exec, executar esses comandos no contêiner administrativo autorizado, com os arquivos privados montados; não inventar nome de contêiner ou caminho de DSN. Em homologação, trocar ambiente e usar o banco/DSN de homologação, nunca reapontar o piloto.

O comando exige intenção selada existente. Confere as contagens esperadas antes da primeira tentativa de commit, além de todas as verificações de Store.finish. Contagens divergentes ou revisão não selada interrompem sem publicar. Se a revisão já estiver READY, devolve o recibo conservado idempotentemente; não interpreta tombstones adicionados no fechamento como mudança dos registros originalmente enviados.

Uma falha na gravação do arquivo de recibo não desfaz um commit já confirmado. Nesse caso, consultar a mesma revisão e repetir o comando para recuperar o mesmo recibo; não reenviar lotes. Não marcar READY manualmente. Timeout mantém código de saída 3 e exige inspeção/retomada da mesma revisão; não apagar staging nem ampliar os timeouts indiscriminadamente.

5. Conferir no recibo state=READY, UUID esperado, manifest_hash da intenção selada e versão ativa. Conferir novamente os 2.775 recibos e hashes conservados, contagens por tabela, finanças por venda/cliente/período, cancelamentos e exclusões. Não usar changed_rows como substituto da soma de linhas exportadas: tombstones/substituições podem fazer parte do fechamento.
6. Reiniciar serviços definitivos no mesmo SHA e validar diagnóstico/contrato e leitura. No Windows FARMA:

```powershell
nexo armazenamento postgres status --id-revisao ca214c78-e590-4056-b58e-31877714facc
```

Somente com state=READY e recibo conferido retomar a comparação no Data Studio. Não executar finalizar-selada pelo Windows para este volume enquanto o fechamento local estiver ativo. Não executar nova exportação, coleta FarmaLíder, Weni, Analytics, Noturno, Recompra ou nova revisão para recuperar estes dados.

## Evidência de testes

Dados exclusivamente sintéticos, PostgreSQL Docker descartável:

- Caso 149,90 → 162,80 em FARMA/PET, duas linhas do mesmo SKU com IDs distintos, duas unidades, frete técnico separado e preço unitário histórico indisponível.
- Operacional completo preserva as chaves; histórico divergente/não vigente/cancelado e excesso operacional mantêm bloqueio financeiro. Cancelamento de cabeçalho e exclusão não reaparecem na visão.
- Blocos reais atravessam duas fronteiras com 12.001 registros e limite padrão de 5.000 por instrução. Statement timeout continua 50 s.
- Simulação de 2.750.730 registros comprova cursor limitado, ausência de OFFSET e tamanho máximo dos blocos. Não é um benchmark comercial nem execução desse volume real na VPS.
- Interrupção após escrever nf_atuais desfaz toda a transação; retomada da mesma intenção preserva recibos. Atualizações e tombstones atravessam fronteiras, READY é idempotente e a perda do arquivo de resposta após commit recupera o mesmo recibo.
- CLI administrativa real em banco descartável, sem executar migrações no caminho de fechamento; contagem divergente impede commit.

Os testes não substituem a execução do Work no banco real. Codex não acessou a VPS nem concluiu a revisão comercial.

Resultado local final: **86 testes aprovados**, um smoke de imagem HTTP ignorado, PostgreSQL descartável com guardas de instância. O Dockerfile oficial compilou usando a CA do ambiente por secret de build, sem desativar TLS. A rodada adicional do smoke HTTP não iniciou por falta de espaço no armazenamento Docker local; não foi tratada como aprovação. O job PostgreSQL/API do CI deve confirmar esse smoke no SHA enviado antes da implantação. Ruff, tipos da aplicação, sincronização do catálogo, consistência e documentação aprovados; 14 testes Node do conector Data Studio aprovados. Não foi executado o fechamento comercial de 2.750.730 registros; esse volume foi simulado para verificar os limites dos blocos.
