# Conferência de BI_Vendas e BI_Pedidos FARMA

O Work encontrou um resumo diário acima da receita de produtos e um pedido duplicado no detalhe, apesar da contagem distinta correta. A planilha e o PostgreSQL reproduziam o mesmo resumo importado. O problema atinge as consultas do relatório. A recuperação dos itens de novembro já foi conciliada pelo Work.

## O que muda na leitura

- `farma.ds_bi_vendas` agrupa as vendas válidas de `ds_bi_clientes_vendas` por dia, com produtos, frete e total em colunas separadas. A quantidade vem de `ds_bi_itens`, agregada por venda antes do vínculo com o cabeçalho. O histórico vigente e as exclusões já fazem parte dessas duas fontes. Uma venda apenas operacional continua entrando se elegível. O histórico LTV continua com seu universo próprio.
- A contagem de compradores é distinta no dia. Para compradores distintos em um período, usar a identidade do cliente no detalhe de vendas. O agregado antigo conserva o texto original de `atualizado_em` e o dia explicitamente registrado com zero pedidos. Uma data sem cobertura não ganha movimento artificial.
- `farma.ds_bi_pedidos` projeta o cabeçalho histórico vigente uma vez por ID oficial e aplica as exclusões. Reutiliza metadados operacionais do mesmo cliente quando a associação é inequívoca. Sem histórico, chaves concorrentes que não permitem identificar a venda com segurança produzem erro de leitura. Registros de contingência sem ID conservam sua chave.
- Os dois nomes, tipos, campos, permissões e dependências das fontes permanecem compatíveis. O modo de consulta ABC, a visão de LTV e o conector Apps Script conservam o contrato em uso.

## Procedimento para o Work

Executar na VPS pelo canal privado existente. Registrar SHA da imagem anterior do **leitor FARMA**, cópia do relatório, data de corte em America/Belem e UUID/versão da recuperação **atualmente READY**. O UUID da v1 anterior à recuperação não serve para este procedimento. Usar primeiro o ambiente de homologação representativo quando disponível. Em banco compartilhado, instalar as definições altera imediatamente a leitura daqueles que já consultam essas duas visões PostgreSQL.

No checkout limpo do SHA aprovado, conferir CI e CodeQL. No shell Linux, definir `sha`, `REVISAO`, `AMBIENTE` (`homologacao` ou `producao`), `BANCO`, `PG_CONTAINER`, `PG_ADMIN`, `REDE_PG` e `DSN_ADMIN` com o ambiente e o arquivo de DSN privados já conferidos. O cliente psql abaixo usa a autenticação local já provisionada no contêiner PostgreSQL. Os comandos exigem acesso administrativo ao banco Data Studio correspondente e espaço para evidências agregadas.

```bash
set -euo pipefail
umask 077
: "${REVISAO:?UUID da publicação ativa após a recuperação}"
: "${PG_CONTAINER:?}" "${PG_ADMIN:?}" "${REDE_PG:?}" "${DSN_ADMIN:?}"
case "${AMBIENTE:?}:${BANCO:?}" in
  homologacao:nexoflow_datastudio_homologacao|producao:nexoflow_datastudio) ;;
  *) exit 2 ;;
esac
test "$(git rev-parse HEAD)" = "${sha:?SHA aprovado}"
git diff --quiet HEAD
EVIDENCIA=$(mktemp -d /opt/nexoflow/datastudio/backups/conferencia-visoes-XXXXXXXX)
pg() { docker exec -i "$PG_CONTAINER" psql -X -v ON_ERROR_STOP=on -U "$PG_ADMIN" -d "$BANCO" "$@"; }
auditar() {
  pg -v revisao="$REVISAO" -v inicio="$1" -v fim="$2" -v somente_diferencas="$3" -f - \
    < integrations/datastudio/auditar_projecoes_farma.sql
}
definicoes() {
  pg -qAt <<'SQL'
SET search_path=pg_catalog;
SELECT format('CREATE OR REPLACE VIEW %s WITH (security_barrier=true) AS %s',
              v,pg_get_viewdef(v,false))
FROM (VALUES ('farma.ds_bi_pedidos'::regclass),('farma.ds_bi_vendas'::regclass)) AS views(v)
ORDER BY v::text;
SQL
}
definicoes > "$EVIDENCIA/antes.sql"
test "$(grep -c '^CREATE OR REPLACE VIEW' "$EVIDENCIA/antes.sql")" = 2
(cd "$EVIDENCIA" && sha256sum antes.sql > antes.sha256)
echo "$EVIDENCIA"
```

1. Rodar a conferência inicial e guardar stdout/stderr em arquivo privado. Em banco anterior à correção, o bloqueio financeiro esperado é `DS_AUDITORIA_PROJECOES_DIVERGENTES`, com as datas e os agregados já emitidos. Conferir o UUID, os desvios e a origem da diferença antes de instalar. Preservar o backup do banco e `antes.sql` para reversão.

```bash
if auditar 2026-01-01 2026-11-15 true > "$EVIDENCIA/antes.txt" 2> "$EVIDENCIA/antes.err"; then
  echo 'Leitura inicial conciliada. Confira se as definições já foram atualizadas.'
else
  rc=$?
  if [ "$rc" -ne 3 ] || ! grep -q 'ERROR: *DS_AUDITORIA_PROJECOES_DIVERGENTES' "$EVIDENCIA/antes.err"; then
    cat "$EVIDENCIA/antes.err" >&2
    exit "$rc"
  fi
  cat "$EVIDENCIA/antes.txt"
fi
```

2. Construir a imagem e instalar somente as duas visões. O comando verifica banco, hash do contrato, UUID e estado, impede outro escritor no segmento e executa as duas definições na mesma transação. A modalidade de instalação não executa migração geral, importação, fechamento ou alteração de grants.

```bash
docker build --build-arg NEXOFLOW_SOURCE_SHA="$sha" \
  -f integrations/datastudio/Dockerfile -t "nexoflow-datastudio:$sha" .
docker run --rm --network "$REDE_PG" --read-only --cap-drop ALL \
  --security-opt no-new-privileges --user "$(id -u):$(id -g)" \
  -v "$DSN_ADMIN:/run/secrets/admin-dsn:ro" "nexoflow-datastudio:$sha" \
  python -m integrations.datastudio.admin --dsn-file /run/secrets/admin-dsn \
  --ambiente "$AMBIENTE" --segmento FARMA --atualizar-visoes-farma "$REVISAO"
definicoes > "$EVIDENCIA/instaladas.sql"
```

3. No Compose e projeto privados em uso, apontar **somente** `datastudio-farma-read` à imagem desse SHA e executar `docker compose up -d --no-deps datastudio-farma-read`. Conferir o healthcheck e o SHA da imagem efetivamente em execução. O leitor utiliza o plano de consulta apropriado ao volume, o mesmo limite de tempo e a revisão consistente. O publicador continua na imagem anterior.
4. Executar na mesma READY. O SQL usa uma transação somente leitura por execução e compara cada dia e o período inteiro. Com `true` emite os desvios e TOTAL; com `false`, todos os recortes. O código zero exige concordância diária e do LTV. Preservar os arquivos inclusive quando houver erro.

```bash
auditar 2026-01-01 2026-11-15 true > "$EVIDENCIA/conferencia-anual.txt"
auditar 2026-04-11 2026-04-11 false > "$EVIDENCIA/conferencia-11-04.txt"
auditar 2026-04-29 2026-04-29 false > "$EVIDENCIA/conferencia-29-04.txt"
auditar 2026-11-09 2026-11-12 false > "$EVIDENCIA/conferencia-recuperacao.txt"
```

5. Na cópia do Looker, atualizar as cinco fontes PostgreSQL na mesma revisão e conferir produtos, frete, faturamento e pedidos por dia. Em Pedidos, usar `venda_valida = 1` para receita e comparar contagem de linhas com distintos de `pedido_id`. Em Itens usar `SUM(receita_item)`. Em Vendas comparar `SUM(faturamento_produtos)` com Itens e ABC; somar frete separadamente. Conferir exatamente os cinco dias que o Work identificou, inclusive o pedido excluído em 29/04 e o frete repetido em 11/04. Conferir as vendas por cliente e o LTV acumulado no próprio universo histórico.
6. Repetir no gráfico de Compras juntas, de 01/01 a 15/11/2026, com `pares_escopo=TOP`, `pares_limite=25` e escopo explícito no título. Conferir ordenação, contagens por par, versão e universo com o leitor do mesmo corte. Validar também o período curto e o período vazio. Só liberar a troca dos gráficos após conferir as evidências na cópia.

Comparar com a planilha de controles e o recibo privados do Work para o mesmo corte. Usar o recibo para isolar o subconjunto recuperado quando houver outras vendas nas mesmas datas. Um acordo entre Planilhas e PostgreSQL no agregado importado não demonstra sua consistência com os itens. O alias ds1 (Metricas_Vendas) é outra fonte operacional; conferir suas dependências separadamente antes de usá-lo como resumo financeiro.

## Reversão das consultas

Usar uma janela administrativa sem outras alterações de visões. Conferir novamente que a publicação ativa tem o UUID auditado e que não existe escritor FARMA. Verificar o checksum privado e que as definições instaladas ainda coincidem com a evidência. Havendo alteração posterior, interromper e revisar o novo estado. Repor as duas definições anteriores na mesma transação e conferir o resultado.

```bash
(cd "$EVIDENCIA" && sha256sum -c antes.sha256)
definicoes > "$EVIDENCIA/conferencia-reversao.sql"
cmp "$EVIDENCIA/instaladas.sql" "$EVIDENCIA/conferencia-reversao.sql"
{
  cat <<'SQL'
SET LOCAL statement_timeout='50s';
SET LOCAL lock_timeout='5s';
SET LOCAL nexoflow.revisao = :'revisao';
DO $$BEGIN
  PERFORM 1 FROM controle.nf_publicacoes WHERE segmento='FARMA'
    AND execucao=current_setting('nexoflow.revisao')::uuid FOR UPDATE;
  IF NOT FOUND OR EXISTS (SELECT 1 FROM controle.nf_execucoes WHERE segmento='FARMA' AND estado='WRITING')
    THEN RAISE EXCEPTION 'DS_REVISAO_FORA_DE_ORDEM'; END IF;
END$$;
SQL
  cat "$EVIDENCIA/antes.sql"
} | pg -1 -v revisao="$REVISAO" -f -
definicoes > "$EVIDENCIA/restauradas.sql"
cmp "$EVIDENCIA/antes.sql" "$EVIDENCIA/restauradas.sql"
```

Voltar a imagem anterior **somente do leitor FARMA** no Compose privado e verificar seu healthcheck. A reversão de consultas não exige reverter a recuperação de itens. Se ainda houver divergências, manter a fonte anterior nos gráficos oficiais e preservar todas as evidências.

## Evidência sintética

Em PostgreSQL 18.6, oito dos nove casos de regressão da projeção falharam sobre a versão anterior ao ajuste. As fixtures exercitam o cabeçalho repetido com frete, a venda excluída, cancelamento, correção histórica em valor e quantidade, venda presente só no operacional, cliente que compra duas vezes no dia, campos desconhecidos e dias vazios. A conta leitora restrita executou o próprio roteiro psql. Os testes administrativos verificam repetição, revisão incorreta, escritor pendente e rollback da transação caso a segunda visão falhe.
