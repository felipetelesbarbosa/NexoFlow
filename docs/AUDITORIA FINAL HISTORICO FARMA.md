# Auditoria final do histórico FARMA — distribuição Windows 1.5.17

## Alcance e evidência disponível

Referências de software: v1.5.16/23f2806 e correções f1da4f7, 7d06041 e 0ba9ed7. A entrega 1.5.17 incorpora essas correções sem substituir a tag ou os pacotes anteriores. O commit distribuído é o apontado pela tag v1.5.17, conferido pelo workflow oficial antes da publicação.

**A auditoria da cópia real continua pendente.** O usuário forneceu `historico-auditoria.sqlite`, mas o serviço de transferência recusou o arquivo por exceder 32 MiB. Não foi possível abrir a cópia, confirmar o perfil, executar `integrity_check`, calcular SHA-256 ou consultar as tabelas reais. Não foi acessado o disco Windows, executada nova carga comercial ou utilizada uma base antiga como substituta dessa evidência. A publicação de correções de software com essa limitação foi expressamente autorizada.

Para continuar, fornecer a mesma cópia consistente compactada em ZIP, se o resultado ficar abaixo de 32 MiB. Não enviar credenciais. Se ainda exceder o limite, produzir no computador um relatório agregado de leitura, preservando o arquivo original; não publicar banco ou dump no GitHub. Não é necessário reimportar o ano.

## Reconciliação e classificação das conclusões

| Conclusão | Classificação | Evidência e limite |
|---|---|---|
| Dez janelas, 67 páginas e 31.285 recebimentos declarados | Parcialmente comprovada | Transcript fornecido; falta conferir `history_windows` e `history_seen` reais. |
| 43.806 compras válidas são acumuladas | Comprovada no código; composição real pendente | `totals()`/`ltv()` usam todos os fatos do segmento, não apenas as janelas atuais. |
| 31.130 representa compradores distintos com compras válidas | Comprovada no código; contagem real pendente | Não representa o total cadastral da API. |
| 50.854 + 9.978 = 60.832 registros classificados são pedidos | Comprovada no código; distribuição real pendente | `link()` percorre pedidos acumulados, incluindo estados não elegíveis; clientes podem ter vários pedidos. |
| R$ 11.909.715,65 representa receita observada acumulada | Comprovada no contrato; composição real pendente | Soma em centavos dos pedidos válidos. Não comprova receita somente entre janeiro e novembro. |
| Histórico pode conter snapshots anteriores | Comprovada no código; quantidade/origem real pendente | `seed_observations()` usa observações anteriores e deduplica por segmento/ID. A origem atual do fato não comprova quando ele entrou. |
| Motivo da única pendência | Pendente | Depende da linha real de `history_issues`, fato preservado e revisões. Não é possível classificá-la por inferência. |
| Integridade local e ausência de duplicação financeira real | Pendente | Requer integridade, chaves, estados e reconciliação financeira da cópia. Testes sintéticos não substituem essa conferência. |

A diferença aritmética entre 43.806 e 31.285 é 12.521. Esse número é um limite mínimo de compras acumuladas que não cabem nos recebimentos atuais como IDs distintos; **não é uma contagem comprovada de snapshots anteriores**. Cancelamentos, fronteiras repetidas e pedidos já conhecidos impedem reconstruir a composição apenas por subtração. Sem metadados antigos, algumas contagens de novos/atualizados podem permanecer irrecuperáveis mesmo após abrir o banco.

## Pendência e política financeira

Não foi removida ou reclassificada a pendência real. O código preserva um fato anterior quando uma atualização não pode ser conciliada. Nesse caso, pode existir compra válida mantida no LTV; quando o próprio fato é pendente, não entra como compra válida. O efeito específico exige o banco. Uma eventual consulta pontual oficial deverá ser justificada após identificar a divergência e não é executada automaticamente por esta auditoria.

Permanecem as regras de status 3 ou pagamento 0 para cancelamento, validação de itens, frete uma única vez, descontos não comprovados pendentes, Decimal/centavos, proprietário oficial e vínculo Weni sem relaxamento de identidade. A falta de contato Weni não exclui uma compra oficial válida do LTV.

## Correções verificadas

- Resumos por execução/período/acumulado; métricas monetárias em reais e centavos internos. LTV independente do filtro mensal.
- Recebimentos das novas execuções persistidos junto com página e cursor, sem retroatribuir fatos antigos a uma execução.
- Menu valida números/datas, ENTER e cancelamento; CLI mantém erro explícito para `--max-paginas 0`; códigos parciais são propagados.
- Progresso global e janela concluída sem página pendente fictícia; retomada e cursores preservados.
- Menos recálculos de LTV entre janelas e ausência de regravação de vínculo idêntico.
- Auditoria offline usa `mode=ro`, `query_only=ON` e fechamento explícito da conexão, inclusive no Windows.
- **Correção final:** o resumo calculava origens, mas não as imprimia, apesar da documentação. Regressão reproduzida antes da correção; passa a exibir contagens por origem e origem do fato da pendência, deixando claro que não identifica a execução de entrada. Não modifica fatos, normalização, valores ou checkpoints.

## Validação e distribuição

As regressões sintéticas incluem SQLite legado, base acumulada, 31.285 recebimentos sobre histórico maior, múltiplas janelas/fronteiras, cancelamentos, pendências preservadas, compradores/vínculos distintos, leitura sem alteração de hash, menu e retomada. O relatório anterior detalha o benchmark local com limites 100/500/1.000; não é uma medição da rede real.

A publicação depende dos resultados do mesmo commit no workflow Windows: Ruff, Pyright, dependências, segredos do histórico e dos ZIPs, Python 3.11/3.14, console, launchers, executáveis, Setup Preserve/Clean e rollback. CodeQL e homologação Hub são conferidos separadamente no mesmo commit. Resultados e hashes definitivos ficam nos registros de CI e na release, evitando afirmar sucesso antes da execução. Aprovação no CI não comprova Kaspersky, proxy ou APIs comerciais do usuário.

Não há alteração em `app/order_history.py` nem no contrato compartilhado com o Hub nesta revisão. O Hub permanece sintético; testar Linux/PostgreSQL/API/worker em ambiente descartável não implanta serviços na VPS. O Work pode homologar o SHA da tag v1.5.17 após conferir o workflow Hub correspondente. A operação Windows permanece independente.

## Atualização e conclusão pendente

1. Encerrar rotinas e fazer backup privado consistente do SQLite pelo mecanismo de backup SQLite, além das configurações locais.
2. Conferir SHA-256 do ZIP oficial e executar Setup em **Preserve**. Não substituir o banco, apagar logs/checkpoints ou reiniciar janelas.
3. Selecionar FARMA no Terminal e executar a auditoria offline na cópia: `nexo historico --auditar-banco "C:\pasta-privada\historico-auditoria.sqlite" --inicio 2026-01-01 --fim 2026-11-06`.
4. Código 3 significa pendências preservadas; não significa perda da carga. Registrar o resumo agregado, sem enviar banco/credenciais a repositórios públicos.
5. Para a auditoria técnica completa, abrir a cópia em leitura, registrar SHA-256 antes/depois e `PRAGMA integrity_check`, conferir segmentos, janelas, fatos, origens e revisões. Não executar migrações no arquivo auditado.

Ainda dependem da API: inclusividade dos limites de datas e semântica de descontos não demonstrados. Todas as páginas declaradas recebidas não equivalem a comprovar cobertura do período civil. A homologação financeira completa, a ação sobre a pendência real e a composição do acumulado continuam abertas até o acesso à cópia.
