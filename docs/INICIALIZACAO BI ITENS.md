# Conferência inicial de BI_Itens sem fabricar READY

## Diagnóstico em 11/11/2026

O Work relatou uma fonte FARMA ligada diretamente ao Google Sheets, uma parte `BI_Itens#0` registrada no Dashboard e nenhuma entrada `estado` para a tabela. O conector carregava o schema, mas recusava os dados antes da comparação. A implantação observada pelo Work era anterior ao código atual. As planilhas e o Apps Script não foram acessados pelo Codex nesta investigação.

O código confirma uma dependência circular: `register_root` registra a raiz durante a preparação; o planejamento da expansão BI exige que o conector já tenha sido conferido; a carga para antes de `_begin/finish` e não gera `READY`. O leitor tratava a raiz legada registrada como uma publicação gerenciada incompleta. Uma aba principal sem registro já possuía caminho legado, mas o registro isolado de `#0` impedia a conferência.

## Correção exclusivamente de leitura

Os leitores compartilhados em `connectors/continuacoes/Tables.js` e `connectors/looker_abc/Tables.js` continuam idênticos. A conferência inicial passa a aceitar somente:

- Consulta de uma única tabela, exatamente `BI_Itens`, com schema explícito autorizado.
- Manifesto válido do mesmo segmento e Dashboard, com uma única parte, número zero, no arquivo principal.
- Ausência de estado da tabela e de qualquer intenção de criação para ela.
- Ausência de gravador ativo ou em recuperação, comprovada nos metadados antes e depois da leitura. Trava malformada também bloqueia; há margem conservadora de 60 segundos após a expiração.
- Origem, aba, cabeçalhos, hash de schema, chaves únicas, tipos e manifesto estáveis nas verificações existentes e adicionais.

O conector não grava fatos, metadados ou manifestos; não cria um estado `READY` e não confirma a fonte no Terminal. Estado `WRITING`, `READY` inconsistente, múltiplas partes sem contagens confirmadas, criação pendente e mistura FARMA/PET continuam bloqueantes. A exceção não se aplica às tabelas históricas nem a consultas conjuntas da Curva ABC. Após uma publicação normal, o caminho `READY` e a união das partes continuam exigindo as contagens confirmadas.

A leitura inicial representa apenas os dados legados atualmente publicados. Não comprova cobertura integral da API, conciliação financeira de todo o histórico ou atualização de todas as fontes. Os limites de linhas, prazo, filtros e resposta integral continuam vigentes; erros não autorizam devolver totais truncados.

Os dez módulos da assinatura Windows não foram alterados. A distribuição pública 1.5.33 permanece intacta. A alteração precisa ser implantada no Apps Script; o Setup não atualiza automaticamente o código hospedado no Google.

## Passagem para o Work, sem Terminal

1. Manter pausadas as cargas FARMA enquanto confere o legado. Preservar a fonte direta de produção, a cópia do relatório, o manifesto e o PET.
2. Buscar os três arquivos completos da entrega indicada no GitHub: `Code.js`, `Tables.js` e `Schemas.js` em `connectors/continuacoes/`. Conferir também o manifesto Apps Script e o serviço avançado Sheets, conforme `CONTINUACOES.md`.
3. Criar uma versão/implantação privada de teste, preservando a implantação anterior como retorno. Não presumir que editar o projeto atualiza uma implantação fixada em versão antiga. Registrar privadamente qual implantação atende a fonte de validação.
4. Configurar segmento FARMA, o Dashboard já conferido e a tabela lógica `BI_Itens`. Comparar os mesmos recortes privados anteriores: alguns dias, um dia e período vazio. Conferir todos os nove gráficos e eventuais mesclagens antes da troca da fonte de produção.
5. `atualizado_em` permanece Texto no schema oficial, preservando o conteúdo. A fonte nativa pode inferir Data e hora. Inspecionar filtros/cálculos dependentes e a representação efetiva antes de migrar; não converter ou renomear campos às cegas. O filtro operacional de período usa `data`.
6. Somente após validar e ligar a fonte correta, declarar ao operador que ela está apta para confirmação. O Work não executa nem afirma ter executado comandos locais.
7. O operador, no Terminal FARMA e sem outra carga ativa, confirma apenas a tabela validada:

```powershell
nexo armazenamento ativar-data-studio --abas BI_Itens --confirmar-fontes
nexo armazenamento status
nexo analytics
```

8. Após a retomada, o Work confere `READY`, as partes efetivamente criadas e os totais do mesmo período. A fonte deve descobrir a nova parte pelo manifesto, sem lista manual de arquivos. Não chamar a carga de concluída apenas pela leitura inicial.

A Curva ABC precisa de implantação e diagnóstico próprios. Atualizar seus três arquivos `AbcCore.js`, `Code.js` e `Tables.js` conforme a documentação, mas validar seus cruzamentos somente quando as duas tabelas necessárias estiverem confirmadas. O código de erro genérico informado pelo Work não comprova sua causa sem a execução/log correspondente.

## Testes e limites da prova

A regressão sintética reproduziu a recusa da raiz registrada sem estado no código anterior. Com a correção, 45 testes Node passaram, incluindo os leitores geral e ABC, FARMA/PET, manifesto imutável, escritor ativo/iniciado durante a consulta, schema/origem, intenção pendente, chaves duplicadas, medidas com tipo inválido e a permanência do bloqueio de cruzamentos sem `READY`. Ruff, validação do workflow e diff também foram conferidos. O CI executa a nova regressão junto às existentes.

Esses testes não substituem a atualização real da implantação e a comparação dos dados pelo Work. Nenhum registro comercial, credencial, manifesto ou relatório publicado foi alterado nesta implementação.

## Seguimento de getData após a implantação versão 2

O Work informou que a implantação privada do SHA `6738dff` carregou o schema, mas falhou ao consultar os dados. Isso não invalida a guarda inicial nem comprova a causa de transporte. A investigação seguinte reproduziu excesso de chamadas em uma grade de 500 mil linhas e adicionou leitura agrupada, recuperação limitada e diagnóstico no próprio Data Studio. Consultar [diagnóstico, testes e roteiro atualizado](DIAGNOSTICO%20GETDATA%20BI%20ITENS.md). A comparação comercial e a confirmação local continuam pendentes.

## Bloqueio observado após instalar 1.5.34

Em 11/11/2026, o log fornecido pelo operador mostrou atualização de BI_Pedidos e BI_Clientes_Vendas, seguida da recusa de criar uma continuação de BI_Itens porque sua fonte ainda não estava confirmada. Não houve repetição do erro de renovação da trava nesse trecho. Isso não comprova o estado atual do manifesto nem a homologação do painel.

A recusa é necessária enquanto a produção usa uma aba direta. O defeito corrigido foi a detecção tardia: o Analytics já havia substituído tabelas grandes antes de descobrir a pendência. O novo `app/bi_preflight.py` verifica o grupo BI_Vendas, BI_Ads, BI_Pedidos e as oito tabelas comerciais antes de iniciar essas substituições. O comando `nexo looker` verifica as oito tabelas antes de sua migração numérica/substituição. A publicação nativa continua conferindo tudo novamente; a prévia não autoriza escrita nem cria READY, partes, confirmação, trava ou revisão.

A prévia conta a grade de cada arquivo uma vez, projeta a expansão na ordem do gravador e não libera capacidade por redução de dados. Acima da margem operacional, a reserva vazia da raiz não é tratada como espaço para novos fatos. Quando necessário para uma fonte não confirmada, lê somente sua coluna de chave, em blocos de até 10 mil células; não refaz um download de todos os valores da tabela. Fontes confirmadas continuam sujeitas às guardas reais, sem essa contagem adicional. Mudanças de manifesto/cabeçalho e falhas de acesso permanecem bloqueantes.

**Limites:** a prévia ocorre depois da coleta e das gravações operacionais e das primeiras três tabelas BI. Não transforma toda a rotina em uma transação, não elimina todas as consultas do Analytics, não garante capacidade diante de edições posteriores e não valida permissões de uma continuação ainda não criada. A pendência conhecida retorna 3, mantém o cursor de sucesso e impede as etapas posteriores; falhas estruturais continuam retornando 1. A distribuição 1.5.34 não contém esta melhoria; será necessária uma nova release validada.

### Próximo passo operacional

Não repetir Analytics/Noturno para tentar resolver a ausência de confirmação. Com as cargas FARMA encerradas, o Work deve retomar a comparação no relatório privado v6, incluindo o cartão original versus `COUNT_DISTINCT(produto_codigo)`, os nove usos/mesclagens e o período vazio. A tabela conciliada isoladamente não resolve o aviso no cartão. Conferir também manifesto e ausência de gravador ativo; nenhum READY ou desbloqueio manual.

Somente depois da validação e ligação real da fonte, o operador usa os comandos do roteiro acima. Para recalcular apenas as oito tabelas comerciais a partir dos fatos já armazenados no Sheets, existe `nexo looker --inicio AAAA-MM-DD --fim AAAA-MM-DD`; o intervalo define o período ABC/KPIs. Esse comando grava BI, não coleta FarmaLíder/Weni, não atualiza todas as etapas do Analytics e não retoma uma revisão física anterior por número de linha. Não executá-lo enquanto a fonte continuar pendente. Após a migração, conferir a continuação e os totais; só então retomar a rotina completa.

Testes sintéticos novos cobrem FARMA/PET, crescimento conjunto, grade de 500 mil linhas, fonte já confirmada com duas continuações, cabeçalho/manifesto alterados, nenhuma escrita no bloqueio e preservação do checkpoint. As regressões dos comandos Analytics e looker falham contra os respectivos pontos de entrada anteriores. Os dez módulos de assinatura foram preservados. Evidências comerciais permanecem exclusivamente nos anexos privados do operador.

Validação local desta correção: 2.009 testes Python, 95 ignorados por dependências/plataforma; 78 testes Node; Ruff, Pyright (zero erros/avisos), auditoria de consistência, documentação gerada e pip-audit aprovados. São testes sintéticos em Linux; os checks Windows/CodeQL devem ser consultados no commit enviado. Não houve nova publicação, instalação Windows ou homologação comercial.
