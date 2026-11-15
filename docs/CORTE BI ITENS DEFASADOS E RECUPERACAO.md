# Corte com BI_Itens defasada: prevenção e simulação direcionada

Entrega de código de 15/11/2026, sobre `6c75838b082358bfa5f9cf1d5337dd985432d260`. Sem implantação, recuperação comercial, reenvio ou novo fechamento. Windows distribuído continua 1.5.40; mudanças de exportação/auditoria/preparo/aplicação precisam de **nova release e instalação pelo Setup Preserve** para chegar ao operador. Não substituir módulos avulsos. Não foi publicada release nesta etapa.

## Evidência e limite da conclusão

O Work confirmou a transferência para `/home/nexoadmin/corte.sqlite`, o manifesto interno igual ao da publicação FARMA e a igualdade entre corte, fatos v1 e projeções. Os itens operacionais existem; BI_Itens já não os contém no corte. Portanto a ausência não nasceu apenas na projeção PostgreSQL.

| Data | Pedidos | Linhas operacionais | Produtos em centavos |
|---|---:|---:|---:|
| 2026-11-09 | 63 | 174 | 1326034 |
| 2026-11-10 | 63 | 196 | 1445984 |
| 2026-11-11 | 56 | 148 | 895343 |
| 2026-11-12 | 22 | 61 | 516617 |
| TOTAL | 204 | 579 | 4183978 |

Segundo o Work, cada pedido reconcilia valor_total dos itens operacionais com faturamento_produtos. Não há cabeçalho histórico para esses pedidos. Esses são controles recebidos do ambiente comercial, não uma auditoria direta do Codex na VPS.

`main.py` deixa BI_Itens fora da gravação Sheets quando o publicador piloto PostgreSQL está habilitado; `export_sheets` lê a aba física. Esse caminho explica como pode haver defasagem, mas seu uso na execução que gerou o corte ainda requer log/configuração daquela execução. Não mudar destino nem iniciar escrita dupla para contornar o problema.

## Guardas implementadas

- Exportação: após conferir versões Drive e manifesto, valida BI_Clientes_Vendas contra BI_Itens por venda, data, cliente, chave, quantidade positiva e soma exata em centavos. Uma venda exclusivamente operacional sem itens ou divergente gera `DS_BI_ITENS_DEFASADOS`. A nova cópia permanece **sem selo**, com diagnóstico sanitizado por data. Nada é escrito no Sheets.
- Auditoria/preparo: a mesma leitura local bloqueia cortes antigos inconsistentes antes da auditoria pesada e da criação do plano. Não modifica o corte selado original.
- Aplicação/simulação de plano antigo: revalida a relação antes do primeiro HTTP. Não basta ter um plano anteriormente preparado.
- Servidor: a guarda equivalente participa da transação de fechamento de **novas revisões**. Em falha, fatos, materialização e ponteiro ativo voltam ao estado anterior; staging/recibos continuam em WRITING. Nenhuma revisão parcial vira READY.
- Histórico mantém precedência por venda inteira, exclusões e validação própria de itens e LTV. Não somar frete aos produtos. Cancelamentos históricos não são recuperados por fallback operacional.
- Um READY já confirmado continua auditável e seu recibo é idempotente. Esta entrega **não reabre nem refaz** a v1 `ca214c78-e590-4056-b58e-31877714facc`.

A guarda detecta ausência e divergência nas informações conservadas; não comprova que a API retornou todos os pedidos ou itens. `DS_ABC_BASE_INCOMPLETA` permanece no leitor. Compras juntas anual, ds136, aliases, conector e relatório não mudam nesta entrega.

## Dry-run dos 204 pedidos: Work

Usar o SHA final desta entrega com CI/CodeQL aprovados em **contêiner temporário**, conforme [comando privado de diagnóstico](DIAGNOSTICO%20VENDAS%20SEM%20ITENS%20E%20TOP%20PARES.md#comandos-do-work). Não substituir agora o publicador ou leitor em produção. A imagem inclui o módulo `integrations.datastudio.sales_diagnostic`; não exige migração SQL.

Pré-requisitos: DSN administrativo existente do banco definitivo em arquivo privado; rede Docker privada; hash físico do corte conferido com o Windows; versão ativa FARMA ainda v1; hash do manifesto do corte igual a source_hash da revisão. Nenhum segredo deve ir para o chat. O script exige `--export-sha256`, abre corte somente leitura/query_only, confere integridade/manifesto e compara SHA antes/depois. A consulta PostgreSQL usa transação consistente somente leitura.

Crie uma pasta privada nova e uma referência **somente de agregados**, sem editar o manifesto comercial:

```bash
set -euo pipefail
umask 077
: "${sha:?SHA final validado desta entrega}"
: "${DSN_ADMIN:?Arquivo privado DSN existente, banco definitivo}"
: "${REDE_PG:?Rede Docker privada conferida}"
: "${CORTE_SHA256:?SHA-256 físico do corte, conferido no Windows}"
CORTE=/home/nexoadmin/corte.sqlite
printf '%s  %s\n' "$CORTE_SHA256" "$CORTE" | sha256sum --check --status
SAIDA=$(mktemp -d /opt/nexoflow/datastudio/backups/recuperacao-dryrun-XXXXXXXX)
cat > "$SAIDA/referencia-204.json" <<'JSON'
{"segment":"FARMA","revision":"ca214c78-e590-4056-b58e-31877714facc","version":1,"days":{
"2026-11-09":{"orders":63,"operational_items":174,"product_cents":1326034},
"2026-11-10":{"orders":63,"operational_items":196,"product_cents":1445984},
"2026-11-11":{"orders":56,"operational_items":148,"product_cents":895343},
"2026-11-12":{"orders":22,"operational_items":61,"product_cents":516617}}}
JSON
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
  --expected-summary /saida/referencia-204.json \
  --output /saida/plano-dryrun.json > "$SAIDA/resumo-sanitizado.json"
rc=$?
set -e
case "$rc" in
  3) echo 'Diagnóstico com pendências concluído; nenhuma recuperação aplicada.' ;;
  0) echo 'Recorte sem casos; difere da referência esperada. Conferir antes de prosseguir.' ;;
  *) echo 'Falha bloqueante. Preserve a evidência.'; exit "$rc" ;;
esac
printf '%s  %s\n' "$CORTE_SHA256" "$CORTE" | sha256sum --check --status
printf 'Devolver somente o resumo sanitizado: %s/resumo-sanitizado.json\n' "$SAIDA"
```

A imagem `nexoflow-datastudio:$sha` deve ter sido construída do checkout exato validado, pelo procedimento oficial de imagem do guia [ABC em volume](ABC%20POSTGRESQL%20EM%20VOLUME.md). Não é um comando para o Terminal Windows. O arquivo DSN precisa ser legível pelo usuário do contêiner; não ampliar permissões públicas para isso.

Critérios da simulação: `referencia_confere=true`, `todos_candidatos_conciliados=true`; 204 candidatos, 579 itens e 4183978 centavos; nenhum conflito de chave/diferença entre camadas. Cada pedido valida separadamente cliente/data/produtos/frete/total. A reconstrução usa `build_looker_tables` oficial, não inventa itens nem distribui valores. Chaves operacionais duplicadas são bloqueadas antes da deduplicação do Analytics; chaves BI ocupadas por outra venda e duplicidades entre candidatos também bloqueiam. Cancelamento, exclusão ou histórico exigem reconciliação específica.

`inseridos`, `atualizados`, `mantidos` são **previsões**; `aplicavel=false`, `autoriza_publicacao=false`, `remocoes_autorizadas=0`. Código 3 significa diagnóstico completo com pendências, não recuperação efetuada. Repetir com nova saída deve conservar plan_hash se nenhuma evidência mudou. Não há `--apply`; não reenviar lotes nem fechar a v1. Uma futura recuperação exige revisão nova e autorização de execução própria.

## Testes e distribuição

Testes sintéticos exercitam exportação real sobre serviços simulados, corte preservado sem selo, plano antigo bloqueado antes de HTTP, fechamento PostgreSQL com rollback/recibo anterior, CLI real com referência por dia, duplicidade e colisão de chave. Fixture de 204 vendas e 579 itens fecha 4183978 centavos e produz o mesmo plano sem escrita. Regressão adicional confere 60.003 itens no SQLite e PostgreSQL; no SQLite limita instruções, não tempo arbitrário. Guardas e testes históricos/frete/LTV permanecem.

O relatório final do commit informa resultados e CI do mesmo SHA. Aprovação sintética não comprova simulação comercial. O Work ainda precisa executar o comando acima e devolver somente o resumo sanitizado. Reversão do diagnóstico: parar o contêiner temporário e manter seus arquivos privados; banco, serviços e relatório não foram alterados. A implantação futura da guarda no publicador e distribuição Windows são etapas separadas e não recuperam automaticamente os 204 pedidos.

Validação local: suíte PostgreSQL descartável com 133 aprovados e um smoke Docker ignorado (executado pelo CI com imagem compilada); 42 testes de adaptador/Analytics/guarda aprovados, dois testes dependentes de PostgreSQL ignorados nessa execução separada; 108 testes Node aprovados. Ruff, tipos do escopo app, schema sincronizado, consistência e diff aprovados. O tmpfs do PostgreSQL exclusivamente sintético passou de 512 MiB para 1 GiB para acomodar a regressão adicional; produção permanece inalterada.

O primeiro CI sinalizou como generic-api-key o identificador literal `faturamento_produtos=` em uma chamada de teste sintético, sem credencial. O teste usa dicionário explícito; a varredura de todo o histórico conserva exceção ancorada somente para esse texto exato. Nenhum arquivo, commit ou regra foi ignorado.

A suíte Windows `tests/test_datastudio_windows.py` inclui os casos novos de corte legado bloqueado no preparo/envio (simulado e real, antes de HTTP), SHA preservado, soma exata de produtos sem frete e identidade divergente. Os oito testes unittest desse módulo passaram localmente; o CI do SHA final executa o módulo nas quatro combinações Windows.

## Distribuição Windows publicada

Publicada em **15/11/2026, 12:53:30 (America/Fortaleza)**, SHA `abdb789c20c42f4e0c22799c47a73993f23b2d04`. [Release](https://github.com/felipetelesbarbosa/NexoFlow/releases/tag/v1.5.41), [preparação e pacotes](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/43730215188), [CodeQL](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/43730215202), [Meta](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/43730215178) e [publicação com os mesmos artefatos](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/43732329821) aprovados. Downloads públicos conferidos: SHA-256, CRC, 593 entradas do manifesto, 124 módulos e 586 arquivos do commit por pacote, executáveis x64 1.5.41.0. Sem instalador Python ou dados comerciais nos ZIPs. A 1.5.40 e anteriores preservadas. Nenhuma implantação/recuperação comercial executada.

Instalar o Setup 1.5.41 em Preserve e conferir `nexo versao`. Não executar nova exportação ou carga dos 204 pedidos: o Work usa o dry-run acima com o corte original. A guarda transacional no servidor exige implantação própria; instalar Windows não atualiza a VPS.
