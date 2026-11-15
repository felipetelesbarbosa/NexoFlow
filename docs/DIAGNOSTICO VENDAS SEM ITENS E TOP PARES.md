# FARMA: vendas sem itens e compras juntas em volume

Entrega de código de 15/11/2026, continuando `8e8e7c734ca82d4e382e3178208300879fafe0af`. Não implanta serviços, não altera fatos, READY, cortes, assinaturas, publicador, credenciais, ds136 ou relatório oficial. A distribuição Windows permanece 1.5.40.

## Evidência recebida versus causa comprovada

O Work confirmou no leitor 8e8e7c7, conector privado v1 e READY v1 (`ca214c78-e590-4056-b58e-31877714facc`):

| Recorte | Pedidos sem itens projetados e sem cabeçalho histórico | Produtos (centavos) |
|---|---:|---:|
| 09/11/2026 | 63 | 1326034 |
| 10/11/2026 | 63 | 1445984 |
| 11/11/2026 | 56 | 895343 |
| 12/11/2026 | 22 | 516617 |
| Total | 204 | 4183978 |

São produtos, sem frete. Até 08/11, o resumo reconciliou 6.141 SKUs, 79.157 unidades e 415881384 centavos. Até 15/11, `DS_ABC_BASE_INCOMPLETA` é um bloqueio correto. O limite de compras juntas até 08/11 é outra condição: cardinalidade da saída, não comprovação de timeout.

Os três arquivos de evidência ficam em `/opt/nexoflow/datastudio/backups/abc-8e8e7c7-jjckxxxh/`. O Codex recebeu o resumo sanitizado; não abriu arquivos/terminal da VPS. O destino informado para a transferência do corte é `/home/nexoadmin/corte.sqlite`; **existência no destino não comprova transferência concluída**. Manifesto externo já informado: `/opt/nexoflow/datastudio/producao/corte-manifesto-farma-20261113.json`. Não editar nenhum deles.

Comprovado por código e fixture: `build_looker_tables` pode produzir BI_Clientes_Vendas de cabeçalho elegível e registrar falta de itens em BI_Qualidade. A exportação conserva as tabelas sem exigir essa relação; `assert_financial` do fechamento cobre cabeçalhos históricos, mas não todas as vendas exclusivamente operacionais. Assim, a falta pode atravessar o fluxo sem violar os hashes de cada tabela. As visões preservam a venda operacional sem histórico; apagá-la não resolveria a origem. **Isso identifica uma lacuna, mas não prova em qual camada desapareceram os itens dos 204 pedidos reais.**

## Diagnóstico e plano direcionado, somente leitura

Novo módulo: `integrations.datastudio.sales_diagnostic`. Não é endpoint público nem comando novo do Terminal. Executa localmente na VPS, sob transação PostgreSQL `REPEATABLE READ READ ONLY`, com destino/segmento/schema/READY/version conferidos. Mantém 50 s por instrução e recusa mais de 1.000 casos por recorte; reduzir o recorte não altera os fatos.

Compara:

1. Vendas/itens efetivamente projetados pelas visões financeiras.
2. `nf_atuais`: BI_Clientes_Vendas, BI_Itens, Pedidos_FarmaLider, Itens_Pedidos_FarmaLider, Historico_Pedidos, Historico_Itens e Exclusoes_Publicacao.
3. Fatos de `nf_registros` na ancestralidade da versão READY, preservando tombstones e sem ressuscitar revisões revertidas.
4. Opcionalmente o corte ORIGINAL, aberto mode=ro/query_only, integrity_check e hashes de todas as tabelas. Exige que o hash do manifesto interno corresponda ao `source_hash` da revisão; SHA-256 físico antes/depois deve permanecer igual. O manifesto externo pode ser conferido como evidência adicional, não é reescrito nem tomado como autorização para mudar hashes.

O relatório privado traz chaves de correlação, contagens/hashes por camada e candidatos de itens. O stdout traz apenas agregados por dia/camada/causa; **envie apenas esse resumo ao Codex**, nunca o relatório detalhado, DSN ou registros completos. Campos pessoais dos pedidos originais não são copiados para o relatório. Arquivo privado 0600, pasta criada sob umask 077, saída existente recusada.

Classificações:

- `PROJECAO_ATUAL_DIVERGE_FATOS`: diferença entre materialização atual e fatos versionados.
- `FATOS_DIVERGEM_CORTE`: diferença entre fatos e corte original comprovadamente ligado à revisão.
- `INCONSISTENCIA_JA_NO_CORTE_ORIGEM_OU_EXTRACAO_PENDENTE`: corte/fatos/atuais concordam. Ainda requer evidência do snapshot de origem para distinguir geração Analytics de extração; não inferir a origem a partir da planilha atual alterada.
- `ORIGEM_SEM_CORTE_NAO_COMPROVADA`: não há corte conferido disponível; ausência dessa prova fica explícita.

A recuperação é **um plano dry-run, não um envio**. Se os fatos conservam exatamente um pedido operacional elegível e seus itens, usa o próprio `build_looker_tables`, confere identidade, data, produtos, frete e total contra a venda, e prepara os candidatos normalizados. Header histórico/exclusão, cancelamento, falta de fonte, valores ou identidade divergentes bloqueiam candidatos. Não inventa itens de cabeçalho, não distribui receita e não chama APIs. Sem comprovante de completude oficial, um candidato continua sem autorização de aplicação.

`plan_hash` determinístico + revisão/versão + hashes por camada permitem repetir o diagnóstico e reconhecer o mesmo plano. Simulação conta inserções/atualizações/mantidos; remoções autorizadas são sempre zero. Todos os planos têm `aplicavel=false`. Uma aplicação futura exige revisão NOVA, comparação desses hashes e recibos idempotentes do contrato existente; **nunca reabrir/reenviar a revisão READY v1**. Nesta etapa não há opção `--apply`.

### Comandos do Work

No Windows, apenas para conferir a transferência existente (não reexportar):

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath 'C:\NexoFlow\logs\privado\migracao-postgres\exportacao-1.5.40-20261113-005329\corte.sqlite'
```

Na VPS, após o SCP terminar, conferir o hash acima com `sha256sum /home/nexoadmin/corte.sqlite`. Construir a imagem do SHA final validado conforme o guia ABC em volume. Para o diagnóstico, **um contêiner temporário**, sem portas, no mesmo network privado do PostgreSQL, e não um rebuild/restart do publicador. O DSN administrativo já existente precisa apontar a `nexoflow_datastudio`; não usar DSN do piloto/Hub/Métricas. Não imprimir o conteúdo dos segredos.

```bash
set -euo pipefail
umask 077
: "${sha:?SHA final com CI e CodeQL aprovados}"
: "${DSN_ADMIN:?Caminho do arquivo privado DSN administrativo existente}"
: "${REDE_PG:?Nome conferido da rede Docker privada do PostgreSQL Data Studio}"
: "${CORTE_SHA256:?SHA-256 físico conferido no Windows}"
CORTE=/home/nexoadmin/corte.sqlite
printf '%s  %s\n' "$CORTE_SHA256" "$CORTE" | sha256sum --check --status
SAIDA=$(mktemp -d /opt/nexoflow/datastudio/backups/diagnostico-vendas-XXXXXXXX)
set +e
docker run --rm --read-only --cap-drop ALL --security-opt no-new-privileges \
  --network "$REDE_PG" --user "$(id -u):$(id -g)" --tmpfs /tmp:rw,nosuid,noexec,size=32m \
  -v "$DSN_ADMIN:/run/secrets/admin-dsn:ro" \
  -v "$CORTE:/evidencia/corte.sqlite:ro" -v "$SAIDA:/saida:rw" \
  "nexoflow-datastudio:$sha" python -m integrations.datastudio.sales_diagnostic \
  --dsn-file /run/secrets/admin-dsn --environment producao --segment FARMA \
  --revision ca214c78-e590-4056-b58e-31877714facc --version 1 \
  --start 2026-11-09 --end 2026-11-12 \
  --export /evidencia/corte.sqlite --export-sha256 "$CORTE_SHA256" \
  --output /saida/diagnostico-vendas.json > "$SAIDA/resumo-sanitizado.json"
rc=$?
set -e
case "$rc" in
  0) echo 'Recorte sem vendas incompletas; não é autorização de publicação.' ;;
  3) echo 'Diagnóstico concluído com pendências; recuperação não aplicada.' ;;
  *) echo 'Diagnóstico falhou; preservar saída e não prosseguir.'; exit "$rc" ;;
esac
printf '%s  %s\n' "$CORTE_SHA256" "$CORTE" | sha256sum --check --status
printf 'Resumo para devolver ao Codex: %s/resumo-sanitizado.json\n' "$SAIDA"
```

Sem corte transferido, omitir **os dois** argumentos `--export`/`--export-sha256` e o mount do corte para um diagnóstico limitado às camadas PostgreSQL; não concluir origem/extração. Se a versão ativa mudou, o comando falha explicitamente: conferir a nova revisão/corte antes de mudar parâmetros. Nunca forçar v1 em banco com versão posterior.

### Prevenção e limite deliberado desta entrega

Para novas publicações, a relação venda elegível → itens válidos completos precisa ser uma guarda transacional, além dos hashes/recibos por tabela. A mesma conferência deve abranger vendas operacionais e históricas, com exclusões e cancelamentos, antes de disponibilizar READY. A ausência de itens por falha de extração não equivale a cancelamento oficial.

O diagnóstico fornece um bloqueio operacional explícito (código 3) e a consulta `CHECK` reutilizável para essa conferência. **Não foi alterado o publicador 4afd3c1 nem acrescentada uma guarda automática ao seu fechamento nesta entrega**, respeitando o escopo de preservação. Portanto não afirmar que as futuras cargas já estão automaticamente protegidas por essa nova verificação. Enquanto houver pendências, não publicar novos deltas como completos; a guarda futura deve ser integrada/testada no publicador em alteração própria, depois de identificar o universo real e preparar sua recuperação. Não basta ignorar o código 3, zerar receita ou remover vendas.

## Compras juntas: escopo Top N explícito

Nova rota leitora autenticada **POST /v1/abc/pares**, corpo exato:

```json
{"fields":["produto_a_codigo","produto_b_codigo","produto_a_nome","produto_b_nome","pedidos_juntos","periodo_rotulo"],"start":"2026-01-01","end":"2026-11-08","top":25}
```

A consulta valida toda a base e agrega **todos os pares** do período no mesmo snapshot READY; só então seleciona os N maiores. Deduplica SKU por venda. Ordem de seleção: pedidos_juntos decrescente, códigos a/b em collation C como desempate determinístico deste novo escopo. O conjunto completo antigo conserva seu cálculo/ordem. Não somar pares para obter pedidos distintos.

Resposta mantém contrato, versão, campos e `complete=true` **do escopo solicitado**, com `scope.kind=TOP_PARES`, `requested`, `universe_pairs`, `selected_pairs` e `all_pairs_returned`. O rótulo do período inclui `Top N de M pares`. Não declara total integral de pares quando retorna Top. Limite de seleção 1..1000, sem aumentar os limites gerais. Full continua `/v1/abc` mode=juntos, recusa excesso sem retorno parcial. Timeout/503/429/base incompleta continuam erros; Top não reduz obrigatoriamente o custo de agregação de todos os pares e não garante latência comercial.

No Apps Script privado, os **quatro arquivos do mesmo SHA** continuam Code.js, Schemas.js, AbcCore.js e appsscript.json. Só Code.js muda; schemas/cálculo de referência e IDs não mudam. Em `ABC_juntos`, escolher explicitamente `pares_escopo=TOP` e `pares_limite=25` (10/25/50/100/250/500/1000). Padrão/ausente = COMPLETO, sem migração silenciosa. O conector exige os metadados de escopo, valida quantidade retornada e registra apenas versão/contagens. Não permite filtros dimensionais no Top, pois filtrar após Top não equivale a Top do subconjunto. Preserve fontes filtradas em COMPLETO; não apague filtros de negócio só para passar o teste. Uma necessidade de Top filtrado exige contrato específico.

## Implantação, validação e reversão

1. Conferir CI/CodeQL do SHA final. Guardar imagem/implantação atuais (leitor 8e8e7c7). Construir e substituir **somente leitor FARMA** com o procedimento de `docs/ABC POSTGRESQL EM VOLUME.md`. Nenhum admin/migrate/grant/fechamento é necessário. Publicador permanece 4afd3c1; PET, ds136, dados e relatório oficial intactos.
2. Implantar os quatro arquivos em nova versão **privada** do conector. Manter credenciais de leitura atuais; não usar credencial publicadora no Apps Script.
3. Na cópia, ds110 pode testar o Top explícito com título visível **“Top 25 pares no período — não representa todos os pares”**, junto do periodo_rotulo com N/M. Preservar aliases/mesclagens. Se precisa de todos os pares, manter COMPLETO e período que caiba; Top não é substituto invisível.
4. Conferir 01/01–08/11 em v1: resumo e os valores recebidos do Work; Top contra SQL agregado na mesma versão. Conferir empate/SKU repetido, vazio e falha separadamente. Até 15/11, manter DS_ABC_BASE_INCOMPLETA enquanto os 204 casos não forem recuperados oficialmente. Não reduzir o universo sem rotular o corte.
5. Executar o diagnóstico acima e devolver o resumo sanitizado. Comparar quantidade/financeiro por dia com a tabela de referência. Não aplicar candidatos nesta etapa.
6. Reversão: voltar apenas à imagem leitora 8e8e7c7 e implantação privada anterior. Restaurar configuração COMPLETO na cópia antes de usar leitor sem a rota Top. Não restaurar banco, apagar revisões, recriar views ou mudar o publicador.

## Testes e comprovação

- PostgreSQL descartável: 121 aprovados, um smoke Docker ignorado localmente; o CI constrói a imagem e executa esse smoke e importação da CLI na imagem mínima. Depois da refatoração SQL, dez testes direcionados adicionais aprovados.
- Regressão de 52.650 pares: caminho completo bloqueado; Top 25 com universo exato; contagens deduplicam SKU repetido; base inconsistente bloqueia também o Top. A regressão falhou antes por inexistência do novo caminho. Testes anteriores de 60.003 itens e demais fontes longas preservados.
- Mudança de versão durante leitura: completo e Top terminam no mesmo snapshot original; próxima consulta vê a versão nova. API exige autenticação e conta leitora mínima, sem rota de escrita. Timeout não vira vazio.
- Diagnóstico executa a CLI real em PostgreSQL sintético: hashes/segmento/revisão, transferência não conferida, projeção diferente dos fatos, corte já inconsistente, cancelamento, divergência financeira, repetição determinística, arquivo 0600, agregados sem PII e fatos/READY preservados. Candidatos aplicados **somente em fixture e revisão nova** reconciliam o resumo; nenhum envio comercial.
- CI/CodeQL e links finais são informados junto ao SHA da entrega. Testes locais não comprovam causa dos 204 casos, a transferência do corte ou a homologação no Google.
