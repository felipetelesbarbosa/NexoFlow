# Reconciliação da cópia real FARMA

Complementa a auditoria anterior: a cópia compactada tornou-se acessível. Não altera as evidências históricas da publicação 1.5.17.

## Integridade — comprovada

Cópia com 175.140.864 bytes, perfil FARMA, `PRAGMA integrity_check = ok`. Todas as consultas usaram URI `mode=ro`, `query_only=ON` e fechamento explícito. Nenhuma migração, escrita, carga comercial ou consulta externa. SHA-256 antes/depois idêntico:

`6a3adf6b14536aec1a0b08b42b981a2e31139ee9174386f261dbb0a1d5f5748f`

## Composição comprovada

| Conjunto | Pedidos | Válidos | Cancelados | Pendentes | Receita válida |
|---|---:|---:|---:|---:|---:|
| Dez janelas paginadas | 31.285 | 20.358 | 10.926 | 1 | R$ 9.065.964,26 |
| Observações anteriores fora das janelas recebidas | 29.547 | 23.448 | 6.099 | 0 | R$ 2.843.751,39 |
| Acumulado | 60.832 | 43.806 | 17.025 | 1 | R$ 11.909.715,65 |

As dez janelas correspondem ao período investigado e totalizam 67 páginas, todas extraídas. `history_seen` contém 31.285 IDs distintos, sem repetição entre janelas. Chave primária segmento/ID impede duplicação do mesmo pedido em `history_orders`.

A tabela anterior `orders` contém 38.028 pedidos: 8.481 também aparecem nas janelas e 29.547 não aparecem. Existem 8.481 revisões no modo histórico, com digests distintos. Outros 22.804 IDs das janelas não estão em `orders`. A evidência é compatível com a incorporação de 22.804 pedidos novos sobre 38.028 observações; não existe `history_run_receipts` nesta cópia legada para comprovar causalmente cada inserção por execução. Digest distinto não significa necessariamente alteração financeira: inclui proveniência e outros atributos.

No período solicitado há 31.370 fatos armazenados: 20.423 válidos, 10.946 cancelados e uma pendência; 7.757 compradores distintos; receita R$ 9.086.896,90. Inclui 85 observações não recebidas nas janelas (65 válidas, R$ 20.932,64; 20 canceladas). Isso exige conferir o contrato de datas/cobertura e não permite certificar completude civil. Fora do período há 29.462 pedidos, dos quais 23.383 válidos, com R$ 2.822.818,75.

Os 50.854 vinculados e 9.978 sem vínculo são pedidos. Há 34.721 clientes oficiais com vínculo e 5.096 sem vínculo, conjuntos que podem se sobrepor; 34.721 contatos Weni distintos. O acumulado possui 31.130 compradores com compras válidas. Falta de Weni não exclui receita oficial.

## Pendência — motivo comprovado; valores divergentes não recuperáveis

A única linha de `history_issues` é `FRETE_DIVERGENTE`, originada do histórico paginado. O pedido permanece armazenado como pendente, não existe na tabela anterior `orders` e não há compra válida anterior preservada para esse ID. Não entra no LTV nem no faturamento. Status armazenado 0 e pagamento 5: a pendência não é cancelamento.

O normalizador gera esse motivo quando há lançamento de frete com produto zero/descrição vazia cuja soma difere do frete do cabeçalho. A representação persistida de erro limpa os itens e valores; portanto a cópia não conserva os dois valores originais para quantificar a divergência. Não se pode concluir erro da API versus formato legítimo ainda não documentado apenas pelo código do motivo.

Procedimento mínimo pendente: localizar privadamente esse único ID em `history_issues`, consultar sua resposta oficial somente após autorização, comparar frete do cabeçalho e lançamentos, confirmar o contrato e então preparar reconciliação explícita. Não foi feita essa consulta nem removida a pendência. Não é necessário repetir a carga anual.

## Financeiro e limites

Nenhuma divergência nas invariantes dos 43.806 fatos válidos: receita = produtos + frete; produtos = soma dos itens classificados como produtos. Cancelados e pendentes ficam fora da receita. Essas verificações confirmam a consistência interna; não substituem a conferência dos payloads oficiais originais, que não estão integralmente preservados para todos os pedidos, nem revalidam individualmente identidade Weni.

Integridade estrutural, contagens e reconciliação do acumulado: comprovadas. Completude do período civil, os 85 fatos não recebidos nas janelas e os valores da divergência de frete: pendentes de evidência externa. Não foi encontrado motivo para alterar regras financeiras, eliminar fatos ou modificar o Hub. A release 1.5.17 permanece intacta; esta entrega adiciona somente o relatório agregado, sem dados pessoais ou IDs comerciais.

## Cópia após rejeição HTTP 400 com limite 1.000

A nova cópia tem 175.149.056 bytes, perfil FARMA e integridade `ok`. SHA-256 antes/depois: `78d06667272825f54ebc5093655fcf97dbd810a13bc845143fb079c14f1c3b46`.

Comparação integral das linhas de `history_orders`, `history_seen`, `history_issues` e `history_revisions`: idênticas à cópia anterior, sem fatos removidos ou adicionados. As dez janelas com limite 500 continuam extraídas. A nova janela de 01/11/2026 a 06/11/2026, limite 1.000, está incompleta, cursor 1, sem totais recebidos, motivo `FALHA_LEITURA_API`. A tabela nova de recebimentos contém zero linhas. Portanto a requisição recusada não avançou página nem alterou pedidos, receita ou a pendência de frete anterior.

O log comprova HTTP 400, mas não identifica o parâmetro recusado. A orientação anterior afirmava indevidamente que 1.000 era aceito pela API com base em fixtures. O commit f5e9292 corrige a ajuda/documentação e adiciona diagnóstico seguro dos parâmetros, sem expor resposta bruta ou token e sem troca automática do limite. Regressão reproduzida antes da correção; 28 testes de histórico passaram, assim como Ruff, Pyright e varredura de segredos. Sem nova consulta comercial ou release. Próximo teste operacional: mesmo período com limite 500, que já funcionou na carga anterior, para isolar a rejeição; se persistir, obter validação oficial dos parâmetros.
