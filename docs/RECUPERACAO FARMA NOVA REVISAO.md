# Recuperação dirigida FARMA em revisão nova

Código e testes isolados sobre a main `88570cbd85a772d9cd42ad392dd3c5027e2378a8`. **Nenhuma aplicação em produção nesta etapa.** A revisão origem `ca214c78-e590-4056-b58e-31877714facc`, READY v1, não é reaberta ou fechada novamente. Este roteiro entrega o procedimento para uma execução futura pelo Work, após sua liberação operacional.

## Evidência e escopo

O Work confirmou dry-run oficial, mesmo hash de plano: 204 pedidos, 579 inserções, zero atualizações/remoções, 4183978 centavos de produtos; 09/11: 63/174/1326034; 10/11: 63/196/1445984; 11/11: 56/148/895343; 12/11: 22/61/516617. A origem exata da defasagem continua pendente do log da geração do corte. Não inventar itens nem consultar novamente a API.

O módulo administrativo `integrations.datastudio.sales_recovery` usa o **plano detalhado privado** do dry-run (`pedidos`, `recuperacao.items`, `plan_hash`), e não o resumo sanitizado. Exige o hash já conferido pelo Work como argumento independente. Não editar `aplicavel=false` ou `autoriza_publicacao=false` no plano: a simulação fica intacta; o novo fluxo usa uma revisão nova explicitamente identificada.

Antes de abrir revisão, reproduz o diagnóstico com o corte original e com a origem READY na mesma versão ativa. Hash completo do plano, SHA-256 do corte, manifesto, hashes das camadas, identidade/data/centavos/frete de cada venda e chaves propostas precisam coincidir. Cada venda deve ter zero BI_Itens anterior e somente inserções previstas; atualizações ou remoções são recusadas. FARMA é obrigatório; PET bloqueado.

O `begin(..., expected_base=...)` compara a versão sob a trava da publicação antes de criar a revisão. A API antiga continua compatível, pois o argumento é opcional. Depois de abrir a revisão, o contrato bloqueia outro escritor do segmento. Staging, membros e recibos são conferidos contra o plano antes de selar. As únicas linhas permitidas são os 579 novos BI_Itens. Tabelas operacionais, histórico, LTV, exclusões, demais BIs e estado do Windows não são substituídos.

Lotes de até 200 linhas, por ordem estável de item_chave; UUID de lote deriva da nova revisão, hash de plano e posição. São três lotes para 579 itens. Retomada consulta recibos e não cria outro crédito/linha. A revisão permanece WRITING durante uma pausa; a versão v1 continua disponível. O ABC continua bloqueado por `DS_ABC_BASE_INCOMPLETA` até o fechamento da recuperação. A guarda financeira transacional do fechamento deve aprovar a base inteira antes de disponibilizar a versão nova.

Falha de resposta depois do commit: repetir plano/hash/UUID devolve o mesmo recibo READY. Outra versão ativa, outro hash, revisão de outra finalidade ou staging divergente bloqueiam. Falha antes do commit conserva WRITING e recibos. Falha na guarda financeira desfaz o fechamento e mantém a versão anterior. Não alterar selo, manifesto, hash ou assinatura para retomar.

## Pré-requisitos do Work

- CI/CodeQL aprovados no SHA exato desta entrega; construir uma imagem temporária pelo guia [ABC em volume](ABC%20POSTGRESQL%20EM%20VOLUME.md), com `NEXOFLOW_SOURCE_SHA` correto. Não trocar serviços ativos para executar o comando.
- Banco definitivo Data Studio privado e conta administrativa local existente; DSN em arquivo privado. Não usar piloto, Hub, Métricas, n8n ou credencial do conector. Não abrir porta PostgreSQL.
- Backup PostgreSQL consistente, SHA-256 e catálogo conferidos pelo Work antes da futura aplicação; preservar o corte original e evidências da simulação.
- Plano detalhado e seu hash oficial disponíveis; corte `/home/nexoadmin/corte.sqlite` com hash igual ao registrado no plano. Revisão origem ainda ativa v1 e nenhum escritor FARMA pendente.
- Serviços de rotina FARMA pausados durante a futura operação e conferência. Não alterar PET, ds136, relatório ou fontes nesta entrega.

## Preparar a execução privada

Os comandos abaixo são para o terminal Linux da VPS, **não para PowerShell/Terminal Windows**. Os caminhos de plano/DSN/rede dependem dos arquivos privados existentes; não copiar tokens para o chat. O nome da saída deve ser novo em cada execução. Se uma etapa falhar, preservar a pasta e interromper a sequência.

```bash
set -euo pipefail
umask 077
: "${sha:?SHA exato aprovado desta entrega}"
: "${DSN_ADMIN:?Caminho do DSN administrativo privado do banco definitivo}"
: "${REDE_PG:?Rede Docker privada conferida}"
: "${PLANO:?Caminho do plano detalhado privado do dry-run oficial}"
: "${PLAN_HASH:?Hash oficial de plano já conferido pelo Work}"
CORTE=/home/nexoadmin/corte.sqlite
TRABALHO=$(mktemp -d /opt/nexoflow/datastudio/backups/recuperacao-aplicacao-XXXXXXXX)
cat /proc/sys/kernel/random/uuid > "$TRABALHO/nova-revisao.txt"
NOVA_REVISAO=$(cat "$TRABALHO/nova-revisao.txt")
printf '%s\n' "$sha" > "$TRABALHO/imagem-sha.txt"
printf '%s\n' "$PLAN_HASH" > "$TRABALHO/plano-hash.txt"
```

Guardar o caminho TRABALHO: na retomada usar **o mesmo** UUID salvo, plano, hash e imagem. Nunca gerar outro UUID para contornar uma pendência. Restaurar as variáveis verificadas em uma sessão nova; não executar novamente a criação de pasta/UUID para retomar.

Função de execução (processa argumentos de forma literal):

```bash
recuperar() {
  local acao="$1" recibo="$2"
  shift 2
  docker run --rm --read-only --cap-drop ALL --security-opt no-new-privileges \
    --network "$REDE_PG" --user "$(id -u):$(id -g)" \
    --tmpfs /tmp:rw,nosuid,noexec,size=32m \
    -v "$DSN_ADMIN:/run/secrets/admin-dsn:ro" \
    -v "$PLANO:/evidencia/plano.json:ro" \
    -v "$CORTE:/evidencia/corte.sqlite:ro" -v "$TRABALHO:/saida:rw" \
    "nexoflow-datastudio:$sha" python -m integrations.datastudio.sales_recovery \
    --dsn-file /run/secrets/admin-dsn --environment producao \
    --plan /evidencia/plano.json --plan-hash "$PLAN_HASH" \
    --new-revision "$NOVA_REVISAO" --export /evidencia/corte.sqlite \
    --action "$acao" --output "/saida/$recibo" "$@"
}
```

O usuário do contêiner precisa conseguir ler o DSN/plano/corte e escrever na pasta privada. Resolver pelo canal privado e permissões mínimas; não tornar os segredos públicos. Código de saída 2 é bloqueante. Código 0 significa que a ação terminou; ler `state` do recibo para distinguir VERIFICADA, PAUSADA, READY, CONFERIDA, ABORTADA e REVERTIDA. Recibo já existente é recusado antes de qualquer ação. Não declarar fechamento com PAUSADA.

### Verificação sem escrita

```bash
recuperar verificar preflight.json
```

Esperado: VERIFICADA, 204 orders e 579 items. Ainda não existe revisão nova no banco. O hash e totais coincidem com o plano oficial sem exigir nova exportação ou coleta. Esta etapa também pode ser executada agora pelo Work para validar o procedimento, sem aplicar produção.

### Aplicação futura, somente após liberação operacional

```bash
recuperar aplicar lote-seguranca.json --max-batches 1
```

Esperado: PAUSADA; exatamente um novo lote com 200 itens em staging, versão ativa ainda v1. Nada dessa revisão parcial está disponível ao relatório. Se a execução cair, usar a mesma revisão e outra saída; os recibos existentes são recuperados antes de qualquer repetição.

Retomada e fechamento da mesma revisão nova:

```bash
recuperar aplicar fechamento.json
```

Esperado: READY com versão nova, `changed_rows=579`, três recibos de lotes. Não assumir número de versão sem ler o recibo (na fixture v1 → v2). A chamada sela o manifesto exato dos três lotes e passa pela guarda financeira transacional oficial. Não há endpoint para editar READY v1. Se houver resposta perdida, repetir o mesmo comando com outro nome de saída, por exemplo `fechamento-retomada.json`, devolve o recibo do mesmo commit.

### Conferência da revisão nova e ABC até 15/11

```bash
recuperar conferir conferencia-ate-15.json \
  --abc-start 2026-01-01 --abc-end 2026-11-15
```

É somente leitura: a versão ativa precisa ser a recuperação READY. Lê agregados ABC e controles diários dentro do mesmo snapshot, mantendo timeout de 50 s e todas as guardas. Devolve resumo ABC, linhas, pedidos, unidades e produtos em centavos por dia. Usar o resumo ABC para o período anual e os quatro dias para validar o incremento. No ambiente real, outros fatos de 01/01–08/11 continuam na base: os 4183978 centavos são o incremento, não o total anual esperado. Não inventar um total anual sem conferir a versão e cobertura reais. Unidades não se confundem com 579 linhas; o valor real vem dos itens conservados. A fixture usa uma unidade por linha.

O fechamento não altera frete: comparar separadamente os cabeçalhos. O teste sintético demonstrou 4183978 centavos de produtos, frete 161160 e faturamento 4345138. Esses dois últimos valores pertencem à fixture e **não são uma previsão de frete comercial**.

Uma nova falha `DS_ABC_BASE_INCOMPLETA` ou outro erro não pode virar vazio/total parcial nem autoriza troca de fonte do painel. Parar e investigar o recorte indicado. Compras juntas anual permanece uma pendência distinta desta recuperação.

### Reversão

Se ainda WRITING, cancelar somente a revisão nova:

```bash
recuperar abortar cancelamento-revisao.json
```

Esperado ABORTADA; versão anterior e fatos preservados. Não é reversão de READY, nem exclusão de registros/journals. Uma revisão abortada não pode ser reaplicada com o mesmo UUID.

Se já READY e **sem edição/publicação posterior**:

```bash
recuperar reverter reversao.json
```

Esperado REVERTIDA com versão anterior ativa. O histórico de revisões, os recibos e fatos da recuperação continuam armazenados; o ponteiro/materialização volta ao estado anterior pelo rollback oficial. Repetir com outra saída retorna o mesmo recibo de reversão. Uma publicação posterior ou outro escritor pendente bloqueiam a reversão. Não restaurar dump por cima de trabalho posterior, apagar revisões ou mexer no SQLite para contornar essa guarda. Voltar à v1 também restaura sua falta de itens e `DS_ABC_BASE_INCOMPLETA`.

## Evidências de teste e limites

Testes PostgreSQL descartáveis exercitam os 204 pedidos/579 itens e os controles diários, piloto de um lote, retomada, idempotência dos recibos, falha antes/depois do commit, edição entre preflight/begin, plano/hash/corte incorretos, identidade/data/centavos alterados, segmento PET, staging divergente, guarda financeira, ABC até 15/11, cancelamento da revisão e rollback protegido contra publicação posterior. CLI real verifica, aplica, relê e reverte, com recibos privados 0600 e stdout sem registros de clientes.

Testes sintéticos não são aplicação/homologação comercial. A main conserva Windows 1.5.41 e releases anteriores. Não é necessário novo Setup para usar esse módulo administrativo na imagem temporária da VPS; o roteiro não depende de atualizar C:\NexoFlow. Nada nesta entrega implanta API, altera fontes ou executa produção.

Validação local: suíte PostgreSQL com 143 aprovados e um smoke de imagem ignorado; após o último caso de falha de resposta de lote/selo, os dez testes dirigidos de recuperação passaram. Ruff, tipos app, consistência, schema sincronizado e diff aprovados. O CI também testa os dois módulos administrativos dentro da imagem mínima sem rede. A duração e o desempenho do fechamento/rollback no volume comercial ainda dependem da VPS; os timeouts permanecem protegidos e uma falha desfaz a transação. Não prometer conclusão por um tempo estimado de fixture.
