# BI_Itens: leitura em blocos, cotas e diagnóstico seguro

## Evidência e limites — 11/11/2026

Referência investigada: `6738dff2b83a64856afb69355dd2152db474e154`. O Work informou que o schema abriu na implantação privada versão 2, mas `getData` falhou nos três recortes. Os identificadores de erro da interface não são códigos HTTP nem demonstram cota, timeout ou permissão. O Codex não abriu as planilhas comerciais nem os registros do Console Google Cloud nesta tarefa.

Problemas comprovados no código:

1. Uma grade com 500 mil linhas e 12 colunas exige 125 chamadas de dados por consulta de BI_Itens, mesmo com poucas linhas preenchidas e período curto. Sheets Values não filtra por data no servidor; restringir o período não elimina essa varredura necessária à conferência das chaves.
2. As chamadas do serviço avançado não possuíam recuperação limitada de falhas transitórias. Uma quota/timeout/5xx abortava a consulta.
3. O tratamento descartava a classificação da exceção Google e apresentava apenas uma mensagem genérica. Abrir o schema não comprova a leitura dos dados ou de todas as continuações.

**Cota foi reproduzida em simulação; a causa da falha comercial permanece pendente do novo diagnóstico.** Não há evidência para atribuir os três erros reais à mesma causa. Nenhum manifesto foi editado, nenhum `READY` foi criado e nenhum fato comercial foi publicado.

## Correção implementada

- Transporte de leitura compartilhado pelos conectores geral e ABC, preservando `spreadsheets.readonly` e o serviço avançado Sheets v4.
- Até oito intervalos de até 4 mil linhas/48 mil células por chamada `batchGet`. A resposta precisa conter todos os intervalos, na ordem, com os endereços, dimensões e comprimentos esperados. Não confundir resposta HTTP bem-sucedida com consulta conferida.
- A grade inteira continua examinada, inclusive depois de blocos vazios; sem cache de fatos entre consultas. A consulta mantém os limites de 1 milhão de linhas não vazias examinadas e 200 mil retornadas. Não há corte silencioso ou amostragem.
- Cabeçalhos conferidos antes e depois; metadados/origens e manifesto relidos no fechamento. Na conferência inicial, a trava continua verificada antes e depois. Chaves/tipos de BI_Itens são verificados também quando já houver `READY` e partes. As guardas históricas, de segmento e de estado permanecem vigentes.
- Cada chamada tem no máximo três tentativas para quota, timeout ou 5xx. Em quota, aguarda pelo menos 65 segundos para renovar a janela por minuto; em timeout/5xx, backoff de 2 e 4 segundos, mais pequeno jitter. Respeita `Retry-After` quando a exceção o disponibiliza. Permissão, origem ausente e requisição inválida não recebem repetição cega.
- Um único prazo de 4 minutos inclui chamadas, esperas, leituras vinculadas e preparação da resposta. Antes de dormir ou iniciar nova chamada, o orçamento é conferido. Resultado recebido depois do prazo também é recusado. O serviço avançado não oferece aqui um timeout cancelável por requisição: uma chamada bloqueada ou encerramento externo pelo Google pode terminar antes de o diagnóstico da aplicação ser apresentado.
- O Apps Script emite somente categorias, etapas, contagens e tempos controlados. Não registra exceção bruta, stack, URLs, IDs de planilhas, campos das linhas, tokens ou dados pessoais. O Data Studio recebe o diagnóstico sanitizado em `newUserError().setText(...)`, sem precisar abrir o Console Cloud.

Agrupar intervalos reduz requisições, não os dados que precisam ser lidos. Uma chamada pode conter até 384 mil células solicitadas; respostas preenchidas/longas, memória do Apps Script, consultas simultâneas e quotas diárias continuam sujeitos aos limites do Google. Não foram realizadas medições de latência, memória ou permissões na conta comercial. Não há promessa de tempo real com base no relógio virtual dos testes.

## Diagnósticos apresentados

| Código | Interpretação e próxima verificação |
| --- | --- |
| `NF_BI_COTA` | O serviço informou quota/rate limit. Aguardar e repetir somente a leitura; verificar outras consultas do mesmo usuário/projeto. Quota diária ou consumo concorrente não se resolve necessariamente com 65 segundos. |
| `NF_BI_PERMISSAO` | A conta não comprovou autorização/acesso. Conferir conta, autorização somente leitura e acesso a todas as partes. Não ampliar permissões indiscriminadamente. |
| `NF_BI_ORIGEM` | Arquivo não localizado ou não acessível. O erro não distingue exclusão de ocultação por falta de acesso. |
| `NF_BI_TIMEOUT` | Serviço informou timeout; recuperação limitada não concluiu. |
| `NF_BI_PRAZO` | Consulta excedeu o orçamento global de 4 minutos. Usar resumo ou detalhe mais adequado; não aceitar soma parcial. |
| `NF_BI_SERVICO` | Erro transitório do Google persistiu. |
| `NF_BI_REQUISICAO` | HTTP 400 na leitura; investigar contrato/intervalo, sem repetir cegamente. |
| `NF_BI_VALIDACAO` | Falhou uma guarda de manifesto, origem, trava, cabeçalho, chaves, tipos, limites ou resposta incompleta. Não editar a guarda para liberar. |
| `NF_BI_REFERENCIA`, `NF_BI_TIPO`, `NF_BI_LIMITE`, `NF_BI_INTERNO` | Erro de execução/estrutura do conector; conferir a implantação conjunta dos arquivos e devolver o diagnóstico. |

Etapas: `METADADOS`, `MANIFESTO`, `CABECALHO`, `BLOCOS_DADOS`, `CABECALHO_FINAL`, `MANIFESTO_FINAL` e `RESULTADO`. São nomes controlados; não incluem destino ou valores privados. Os leitores ABC usam o mesmo transporte e conferem também `RESULTADO_ABC`. Os JSONs de aviso incluem HTTP quando disponível, chamadas, retentativas, tempo decorrido e espera acumulada em milissegundos. A mensagem de falha mostra duração legível e declara que nenhum total parcial foi retornado.

## Testes reproduzíveis e resultados locais

```bash
node --test tests/test_continuation_connector.cjs tests/test_looker_abc_connector.cjs tests/test_history_connector.cjs tests/test_legacy_items_connector.cjs tests/test_connector_transport.cjs
```

O CI executa o mesmo conjunto. Métricas sintéticas, sem valores comerciais:

| Cenário | Resultado esperado e verificado |
| --- | --- |
| Grade de 500 mil linhas, cota 60 leituras/minuto, GET por bloco sem recuperação | 61ª tentativa recusada; nenhum resultado retornado. O leitor original do SHA `6738dff` também reproduziu essa recusa; sem cota, usou 130 chamadas totais. |
| Mesma grade com agrupamento e verificações finais | 125 intervalos em 16 chamadas de dados; **22 chamadas totais**, incluindo 2 leituras de cabeçalho, 2 de manifesto e 2 de metadados. Sem 429. |
| Grade densa, 499.999 linhas preenchidas e chaves únicas | Todas examinadas; recorte seleciona 500 itens, 1.000 unidades e 62.500 centavos, incluindo a última linha. |
| Três recortes sequenciais, mesma cota simulada | 67 tentativas totais; uma 429 recuperada após 65 segundos de relógio virtual; recorte vazio retorna zero linhas, sem truncamento. |
| 429/500/503/504 após o primeiro bloco | Retomada da mesma leitura, sem duplicar linhas. |
| 400/401/403/404, timeout, prazo e `Retry-After` | Classificação sanitizada; tentativas/espera limitadas e ausência de resultado parcial. |
| Mudança de cabeçalho, manifesto, origem, trava ou chave; batch incompleto/trocado | Consulta recusada integralmente. |

As 22 regressões novas acompanham as 45 anteriores. O caminho real de `getData`, `batchGet`, schemas, filtros e formatação é executado em VM com o serviço Google simulado. Também foi exercitado o `getData` real da Curva ABC com as duas tabelas `READY`, preservando a representação de datas usada por esse projeto e recusando acesso negado. A prova não substitui execução no Apps Script ou validação financeira comercial. O teste denso mede resultados e chamadas, sem aprovação dependente de tempo de máquina.

## Próximo passo para o Work — sem Terminal

1. Manter a fonte direta e o relatório comercial preservados, cargas FARMA pausadas e PET intacto. Não alterar manifesto, estados ou permissões para contornar erros.
2. Atualizar integralmente `Code.js`, `Tables.js` e `Schemas.js` de `connectors/continuacoes/` a partir do **mesmo commit corrigido**. Preservar o manifesto Apps Script somente leitura, o serviço Sheets v4 e a implantação anterior. Não basta salvar arquivos: criar uma versão privada e conferir qual implantação a fonte de validação utiliza.
3. Consultar primeiro um dia, depois alguns dias e um período vazio, um recorte por vez. Usar as referências privadas do mesmo corte; conferir produtos distintos, unidades, receita e cobertura. Nenhum total deste relatório é referência comercial.
4. Se falhar, devolver o texto completo **sanitizado** dos detalhes do erro (`NF_BI_*`, etapa, chamadas, retentativas e duração), recorte, horário/fuso e versão/SHA da implantação. Não enviar logs brutos, tokens, linhas ou dados pessoais. Os identificadores genéricos da interface podem acompanhar, mas não substituem o novo diagnóstico. Não é necessário acessar o Console Cloud bloqueado para esse procedimento.
5. Se passar, conferir os nove usos e mesclagens da fonte antes de qualquer troca comercial. Só depois da leitura efetiva, dos totais e das ligações comprovadas, informar ao operador que pode confirmar a tabela no fluxo oficial. A confirmação local continua pendente nesta entrega.
6. A Curva ABC permanece sujeita a confirmação das duas tabelas. Seu transporte recebeu a mesma recuperação/diagnóstico, mas a exceção inicial de BI_Itens não autoriza a consulta conjunta sem `READY`. Atualizar seus próprios três arquivos somente no fluxo privado específico, preservando a implantação anterior.

Consulte também [a conferência inicial](INICIALIZACAO%20BI%20ITENS.md) e [o contrato de continuações](CONTINUACOES.md). Os dez módulos de assinatura Windows, a versão 1.5.33 e seus pacotes permanecem byte a byte preservados. A correção deve ser implantada no Apps Script pelo Work; código no GitHub não atualiza a implantação Google automaticamente.

Verificações locais complementares: Ruff, Pyright (zero erros/avisos), auditoria de consistência, actionlint, sintaxe JavaScript, scanner Gitleaks dos arquivos alterados e 31 testes do fluxo de validação/distribuição aprovados. Os dez módulos de assinatura foram comparados em bytes à tag pública `v1.5.33`. A aprovação do CI e CodeQL deve ser consultada no SHA efetivamente enviado, sem inferir sucesso desta lista local.

## Cartões A/B da v6 e próximo ensaio

O Work confirmou o aviso em ambos os cartões, com contagens conciliadas. A causa interna permanece não comprovada. Foi implementada uma métrica virtual de distintos calculada no conector para um cartão separado, sem reagregação de dimensões no Google. Consulte [contrato, limites e roteiro de validação privada](CARTAO%20PRODUTOS%20DISTINTOS.md). A migração e a confirmação no Terminal continuam pendentes.
