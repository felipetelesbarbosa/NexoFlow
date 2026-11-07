# Auditoria da primeira importação FARMA 1.5.16

Referência: release v1.5.16, commit 23f2806. A main conferida não tinha commits posteriores ao marco. A tag/release e a versão instalada foram preservadas; as correções de código são preparatórias, sem nova publicação nesta auditoria.

## Evidências e limites

O transcript recebido mostra 10 janelas, 67 páginas concluídas e soma de 31.285 registros declarados/recebidos. Não há evidência de página faltante nesse log. A inclusividade do filtro continua não homologada. O SQLite dessa execução ainda não foi fornecido: não é possível identificar a pendência exata, reconstruir a quantidade real de pedidos novos/atualizados nem demonstrar a composição individual do acumulado só pelo transcript.

A leitura do código confirma:

| Indicador antigo | Significado comprovado na implementação |
|---|---|
| 31.285 | Soma das dez janelas, incluindo possíveis fronteiras repetidas, antes dos filtros |
| 43.806 pedidos válidos | Toda a tabela local `history_orders`, sem filtro da execução/período, após regras de LTV |
| 31.130 clientes oficiais | Clientes distintos com ao menos uma compra válida no acumulado; não total cadastral da API |
| 50.854 vinculados + 9.978 sem vínculo | 60.832 **pedidos** acumulados; um cliente com vários pedidos é contado várias vezes |
| 1.190.971.565 centavos | R$ 11.909.715,65 de faturamento observado acumulado, não somente das janelas |
| pendências = 1 | Uma linha em `history_issues`; o motivo não foi impresso pela versão 1.5.16 |
| próxima página = 7 | Cursor após seis páginas; correto internamente, enganoso na tela após concluir |

`seed_observations()` adota snapshots anteriores por segmento/ID sem duplicar uma chave existente. Depois, o endpoint paginado atualiza/concilia esses mesmos IDs. `history_seen` pertence a cada janela; `history_orders` pertence à base inteira do segmento. Portanto os dois totalizadores têm escopos diferentes. A participação real de snapshots antigos, execuções anteriores e pedidos fora do período exige o banco. Ao menos 12.521 das 43.806 compras válidas não cabem nos 31.285 recebimentos como compras distintas; isso não identifica sua origem nem comprova que não existam outras divergências.

## Correções

- Resumo separado: execução corrente, período solicitado e acumulado. Receita do período não trunca LTV. Vínculos por pedido, clientes compradores e contatos Weni distintos têm rótulos próprios; grupos de clientes com cancelamentos/pendências podem se sobrepor.
- Recebimentos da nova execução são auditados em tabela aditiva `history_run_receipts`: ID oficial, repetições, existência anterior, mudança financeira e estado recebido. Commit junto com a página e o cursor. Não reconstrói artificialmente contagens de execuções anteriores à tabela.
- Progresso global por janela/página; janela concluída não exibe cursor como próxima página pendente. Nenhuma mudança no contrato do cursor.
- Pendências agrupadas por motivo/origem do fato/efeito, preservando fatos e o problema. Uma atualização recusada pode preservar uma compra válida anterior no LTV; uma compra pendente não entra como venda validada.
- Terminal aceita 0/sair/exit em qualquer campo, EOF/CTRL+C, repete entradas inválidas e informa código 3 para pendências. CLI valida `--max-paginas 0` antes da rede. O menu conserva o código da operação de histórico ao sair.
- LTV acumulado calculado ao final da coleta entre janelas, em vez de repetir em cada janela. Vínculos idênticos não regravam JSON desnecessariamente.
- Métricas agrupam tentativas e tempo por rótulo estático do endpoint, sem URLs/queries. Não foram alterados timeout, política financeira, TLS, identidade ou seleção de rede.

## Auditoria offline sem modificar o banco

No código corrigido, após selecionar FARMA no Terminal:

```text
nexo historico --auditar-banco "C:\pasta-privada\historico-auditoria.sqlite" --inicio 2026-01-01 --fim 2026-11-06
```

Abre SQLite com `mode=ro` e `query_only=ON`, sem migração, rede ou criação de tabelas. Apresenta motivos, totais por origem, período/acumulado e janelas persistidas, incluindo IDs únicos e repetições nas janelas. Não imprime IDs, clientes, telefones, CPF, endereços ou tokens. Código 3 indica pendência existente.

Para fornecer uma cópia consistente, feche rotinas NexoFlow e execute no PowerShell de C:\NexoFlow (ajuste o caminho da origem se necessário):

```powershell
@'
import sqlite3
from pathlib import Path
src = Path(r"C:\NexoFlow\logs\privado\clientes_observados.sqlite")
dst = src.with_name("historico-auditoria.sqlite")
if dst.exists():
    raise SystemExit("A cópia já existe; escolha outro nome, sem sobrescrever.")
with sqlite3.connect(src.resolve().as_uri() + "?mode=ro", uri=True) as origin:
    with sqlite3.connect(dst) as target:
        origin.backup(target)
print("Cópia privada consistente criada.")
'@ | .\.venv\Scripts\python.exe -
```

A cópia contém dados comerciais e precisa permanecer privada. Não copiar apenas o SQLite enquanto estiver sendo escrito, nem publicar a cópia no GitHub. Não enviar secrets_config.py/credentials. Não é necessária nova carga integral para a auditoria.

## Testes e performance

A origem exibida é a do fato local preservado; a versão antiga não gravava metadados suficientes para reconstruir toda tentativa recusada.

Regressões sintéticas verificam 31.285 recebimentos/67 páginas sobre base maior resultando em 43.806 válidos; segunda execução sem novos GETs; sobreposição de fronteiras sem duplicar receita; cancelamentos, pendência preservada, compradores distintos, leitura de banco legado sem alterar seu SHA-256, cancelamento/entradas/defaults/códigos e retomada existente.

Ensaio local de 1.200 pedidos com transporte em memória e tracemalloc:

| Limite | Chamadas sintéticas | Tempo local | Pico adicional rastreado |
|---|---:|---:|---:|
| 100 | 12 | 5,582 s | 0,44 MiB |
| 500 | 3 | 4,888 s | 0,09 MiB |
| 1.000 | 2 | 4,611 s | 0,10 MiB |

Todos produziram 1.200 compras e 9.600.000 centavos. Uma rodada, processo aquecido, sem HTTP real, sem parsing JSON de rede: esses tempos não provam que 1.000 será mais rápido na API. O pico é alocação adicional rastreada, não RAM total do processo. O log real só informa duração de requisição; tamanho do payload, decomposição de rede/parsing e comparação direta/proxy não foram medidos. Não se atribui causa às respostas de 11,59s e 24,90s apenas por ultrapassarem o limiar atual.

Validação local: suíte de 1.796 testes Python aprovada, com 73 ignorados por ambiente; mais uma regressão específica aprovada para propagação de códigos do menu. Ruff, Pyright e consistência passaram. A falha original de `exit` foi reproduzida carregando o código da 1.5.16: `SystemExit(2)`; a versão corrigida retorna 130 sem consulta. O ensaio Hub com 46 casos, API/worker/PostgreSQL e reinício passou. Os testes Windows do commit serão conferidos no CI; nenhum executável corrigido foi homologado/distribuído nesta etapa. A regra pura compartilhada de normalização/paginação/LTV não mudou; Hub permanece sintético, sem deploy VPS ou escrita comercial.

## Atualização e próximos passos

Este código ainda não foi distribuído como executável Windows corrigido. Antes de publicar patch 1.5.17, validar o pacote pelo workflow oficial, incluindo Setup Preserve/Clean, rollback, launchers e pacote instalado; nunca substituir os ZIPs da 1.5.16. Backup privado antes de atualizar. A migração é aditiva, preserva pedidos, revisões e checkpoints. Versões antigas ignoram a tabela adicional.

Pendente: receber cópia consistente do banco dessa execução e conferir contagens por origem, janela/ID, estado e motivo da única pendência. Só depois decidir uma reconciliação pontual, sem apagar fatos/checkpoints ou reimportar todo o ano. Sheets/Weni/Recompra/VPS não foram alterados.
