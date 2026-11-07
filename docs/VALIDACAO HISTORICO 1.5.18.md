# Validação do histórico FARMA — Windows 1.5.18

## Escopo

Continuação de f3fc32f: reordenação de itens, limites de página e semântica do dia final. Publicação Windows autorizada, mantendo a tag e os pacotes 1.5.17. Hub recebe somente código/homologação, sem implantação VPS ou integrações comerciais.

Foram feitos sete GETs pontuais na mesma rota de produção FARMA usada em conexão pessoal, com TLS, token privado em query e sem redirecionamentos. Utilizou-se a rede herdada do ambiente; nenhum proxy, certificado ou proteção foi contornado. Nenhuma consulta geral de clientes, consulta individual de pedido, escrita Weni/Sheets ou carga anual foi executada. Respostas e identificadores de comparação ficaram em diretório privado fora do Git e dos pacotes.

## Evidência real

| Início | Fim enviado | Limite | Resultado |
|---|---|---:|---|
| 01/11/2026 | 06/11/2026, sem hora | 500 | HTTP 200, 404 IDs; datas de 02 a 05/11 |
| 06/11/2026 | 07/11/2026, sem hora | 500 | HTTP 200, 111 IDs de 06/11 |
| 06/11/2026 | 06/11/2026 23:59:59.999999 | 500 | HTTP 200, os mesmos 111 IDs |
| 01/11/2026 | 06/11/2026, sem hora | 1.000 | HTTP 400: “Limite inválido. Informe um valor entre 1 e 500.” |

Todos os **85 IDs** de 06/11 ausentes das páginas anteriores apareceram nos dois GETs que incluem o dia 06. Nenhum faltou. Vieram outros **26 IDs fora da cópia anterior**; isso não comprova que sejam clientes novos ou vendas válidas. Não foi feita atualização do banco a partir dessas respostas.

A consulta ampliada de 01 a 07/11 e duas tentativas da faixa 06 a 07/11 receberam HTTP 503 de conexão upstream antes de cabeçalhos. A faixa reduzida foi concluída com sessão nova, retentativas limitadas e mesma rota/TLS. Total: três HTTP 200, um HTTP 400 e três HTTP 503. Os 503 não foram interpretados como ausência de pedidos nem como validação de parâmetros.

Conclusões comprovadas na amostra FARMA: o término sem hora não cobre o restante do dia final; o término explícito usado pelo cliente inclui os 85 pedidos; o limite de 1.000 é recusado pelo intervalo oficial de 1 a 500. O operador exato de comparação do servidor em um instante de meia-noite, precisão além de microssegundos, cobertura anual e comportamento comercial PET não foram homologados. O aviso geral de cobertura permanece; não se presume completude financeira por terminar a paginação.

## Correções

- `HistoryQuery.api_end` transforma somente fim civil em `T23:59:59.999999`; data-hora explícita é preservada. Solicitação/resumo continuam mostrando o período escolhido e informam o fim efetivamente enviado.
- A chave de cursor distingue essa política. Uma janela antiga concluída à meia-noite não autoriza pular a nova consulta. Estados anteriores não são apagados; a migração não reinicia uma carga anual automaticamente. O Analytics mantém a faixa recente e as pendências válidas do fluxo existente.
- Limite de 1 a 500 é validado no módulo compartilhado, menu e API interna Hub. CLI/configuração inválida falha antes de iniciar a consulta. Não há troca automática de tamanho de página após rejeição.
- Tentativas legadas acima de 500, sem dados/totais/avanço, continuam visíveis no diagnóstico e não são retomadas automaticamente. Se houver evidência de recebimento em estado incompatível, exigir revisão, sem descartar fatos ou cursor.
- O resumo identifica o limite de cada janela persistida para distinguir a tentativa antiga de 1.000 da coleta válida de 500.
- A correção f3fc32f conserva posições e chaves analíticas de itens idênticos reordenados. Foram 105 registros reais, com 382 posições diferentes e nenhuma mudança de valores/quantidades/status. Confirmações recentes mantêm seu horário para precedência sobre snapshots antigos; mudanças financeiras reais continuam sujeitas às guardas.
- Hub usa o mesmo contrato e serialização, limitado a fontes sintéticas. Tarefa interrompida com checkpoint de outra política exige tarefa com nova chave, antes de ler/gravar novas páginas. Não alterar manualmente o checkpoint antigo.

## Dados preservados e pendência

As três cópias privadas continuam com seus hashes originais após as consultas. A cópia mais recente mantém SHA-256 `5dddcfbda8952a1a860b75dd659296e16c66d812863728544b2d2cf8b0319717`. Nenhum desses arquivos foi aberto para escrita/migração ou incluído em Git/artefatos.

`FRETE_DIVERGENTE` permanece preservada. O pedido não foi reconsultado; esta missão não obteve evidência oficial que permita resolver sua divergência. Não foi incorporado como receita ou LTV.

## Validação e atualização

Regressões reproduziram antes da correção: aceitação de 1.000, ausência de fim civil explícito e reutilização de cursor antigo. Fixtures cobrem limites, datas precisas, retomada/cursor novo, tentativa inválida legada com/sem recebimentos, menu, reordenação e mudança financeira real. PostgreSQL temporário verifica contrato equivalente, rejeição 422 e proteção de tarefa legada; API e worker usam somente dados fictícios. Um erro de chamada no novo teste Hub foi corrigido antes da repetição da suíte.

Checks de publicação: suíte completa Windows com Python 3.11/3.14 e dois modos de encoding, Ruff/Pyright, dependências, segredos do histórico e dos ZIPs, CodeQL, console, executáveis, Setup Preserve/Clean/rollback e regressões de histórico no pacote instalado. Resultados definitivos, SHA e hashes dos artefatos devem ser conferidos no workflow do commit apontado pela tag v1.5.18. Testes CI não comprovam Kaspersky, rede corporativa ou escrita em planilhas reais.

Para atualizar, fechar rotinas, fazer backup consistente e usar Setup **Preserve**. Não apagar SQLite, revisões ou checkpoints. Para conferir novamente 06/11, solicitar somente a faixa necessária; não repetir todo o ano. A opção 10 armazena fatos localmente. O Analytics os incorpora às tabelas normais de pedidos/itens; abas específicas Histórico/LTV/Cobertura requerem revisão separada conforme o guia.

Rollback: desativar coleta recente e restaurar somente o programa anterior via processo oficial preservando dados. Cursores das políticas coexistem; o programa antigo não deve ser usado para certificar cobertura do dia final. O Work deve homologar o SHA da tag v1.5.18 no Hub isolado antes de atualizar a VPS. Nenhum deploy foi realizado aqui.

## Ajuste de política de frete aprovado durante a validação

O usuário autorizou manter o pedido quando a única divergência é entre frete do cabeçalho e lançamentos técnicos código zero/descrição vazia. A fonte monetária é o cabeçalho oficial: produtos + frete do cabeçalho, sem somar outra vez o lançamento. Não foi inventado um limite de tolerância. O registro privado guarda aviso, ambos os valores e diferença em centavos; o resumo apresenta avisos separados de pendências. A mesma política vale no histórico FARMA/PET e no Hub sintético. Cancelamentos, descontos, itens inválidos e totais explícitos incompatíveis continuam protegidos.

Metadados dos lançamentos de frete e avisos não reabrem, sozinhos, o fechamento antigo; alteração real no frete do cabeçalho ou demais valores continua sujeita à reconciliação prevista. A cópia antiga ainda contém uma pendência, pois o erro descartou itens/valores e não é possível reconstruir sua compra válida sem resposta oficial. Nenhuma exclusão/limpeza automática dessa pendência foi executada.

A tentativa inicial do workflow 1.5.18 foi cancelada antes da publicação para incorporar essa regra. A versão não foi incrementada novamente. A validação completa será conferida no novo commit final, incluindo regressões com fretes 9,99/0,00, não duplicação, aviso não bloqueante e preservação das outras guardas, tanto SQLite quanto PostgreSQL temporário.
