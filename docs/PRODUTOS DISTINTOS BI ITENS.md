# Produtos distintos de BI_Itens — validação privada

## Diagnóstico de 11/11/2026

Base: `a74319011e72422145db9236ce97d66b085b93f8`, implantação privada v3 relatada pelo Work. A comparação comercial linha a linha foi informada pelo Work; o Codex não acessou o relatório privado, o produtivo ou as chamadas efetivas dos cartões nesta tarefa. Nenhuma fonte comercial foi alterada.

**Comprovado no código e reproduzido em teste:** `sku_informado` era declarado `number`, logo `fields_` criava uma métrica com agregação Soma. O indicador representa uma condição de cada item, não uma quantidade somável. A regressão exige dimensão numérica sem Soma/Max e falhou na base anterior. O novo schema usa o tipo `number_dimension` já suportado pelo conector. Nome, valor 0/1, posição e cabeçalho físico permanecem iguais. A validação de tipos continua rejeitando texto no lugar de número, mesmo se o campo não estiver entre os solicitados.

**Ainda não comprovado:** que essa classificação explica precisamente a contagem divergente ou o aviso de reagregação do Google. O motor de otimização do Data Studio não foi reproduzido localmente. A hipótese precisa da comparação controlada no relatório privado. Não interpretar sucesso na tabela como sucesso no cartão.

`filtersApplied: false` não constitui defeito: o contrato oficial permite delegar os filtros ao Data Studio, devolvendo todos os campos pedidos, inclusive `forFilterOnly`. A resposta atual cumpre esse caminho. Não alterar para `true` sem implementar todos os filtros e retirar os campos exclusivamente de filtro.

Referências oficiais:
- https://developers.google.com/data-studio/connector/filters
- https://docs.cloud.google.com/data-studio/about-filter-properties

## Fluxo preservado

O planejador considera grade alocada e limite por parte. `app/sheets_partitions.py::_create_part` exige a tabela na lista `connector_tables` antes de criar continuação de Dashboard. A fonte direta lê uma aba; a confirmação depende de demonstrar a leitura lógica pelo conector. Essa guarda não foi alterada.

`getData` retorna uma linha por item, após o filtro de período e conferência de todas as partes. Não calcula COUNT_DISTINCT nem agrega por dia, SKU ou parte. O cartão solicita o código de produto; a tabela pede também quantidade/receita e dimensões configuradas. Os campos auxiliares solicitados pelo Google permanecem na resposta. A lista exata enviada pela interface comercial não foi capturada, portanto esses são os contratos demonstrados pelos testes, não um registro das chamadas reais.

A contagem correta é a cardinalidade do conjunto de `produto_codigo` no período, restrito a `sku_informado = 1`. Um código presente em dois dias ou partes pertence uma vez ao conjunto. Quantidade e receita somam os itens elegíveis, sem deduplicá-los por SKU. `produto_codigo` continua Texto, preservando zeros à esquerda. `atualizado_em` continua Texto. Nenhuma alteração no armazenamento, manifesto, estados, permissões ou rotina Windows.

## Testes locais

70 testes Node aprovados, incluindo três regressões novas no arquivo `tests/test_history_connector.cjs`:

- Schema de indicador/dimensões e preservação das métricas somáveis.
- Leitor real e `getData` com raiz e continuação sintéticas READY, um SKU repetido entre dias/partes, códigos sem SKU informado, recortes de vários dias, um dia e período vazio. A mesma resposta de itens permite contar dois SKUs elegíveis no período inteiro, mantendo 7 unidades e 3.700 centavos. Sem filtro, existem quatro códigos distintos no exemplo sintético. Os totais não são referências comerciais.
- Validação da dimensão numérica mesmo quando o campo não é solicitado para exibição.

As operações de filtro/conjunto no teste são um oráculo da regra comercial, não uma implementação do Data Studio. As regressões anteriores continuam cobrindo estado WRITING, origem, tipos, chaves, manifesto, cota e prazo. A cópia compartilhada do leitor ABC permanece sincronizada, sem liberar seu cruzamento independente.

## Roteiro exato para o Work

1. Preservar o relatório produtivo confirmado pelo operador, a fonte direta e as implantações anteriores. Trabalhar apenas no relatório e fonte privados v3. Fotografar configuração, filtros e corte atual; PET permanece fora desta rodada.
2. Para isolar a variável, duplicar o cartão de teste v3. Na fonte privada, editar `sku_informado`: **tipo Número, papel Dimensão, agregação Nenhuma** (se a interface disponibilizar essa edição). Não transformar em Texto, Soma ou Max. Registrar se o painel permite a alteração. Essa mudança de papel pode desativar filtros existentes: recriar o filtro do componente **Incluir → sku_informado → Igual a → 1** e conferir que está ativo. Comparar antes/depois mantendo período e demais opções iguais. Não fazer essa experiência na fonte produtiva.
3. Implantar uma nova versão privada com `Code.js`, `Tables.js` e `Schemas.js` completos do commit corrigido. Somente Schemas e Tables mudaram, mas o trio deve ser consistente. Preservar appsscript.json e autorização existente. Criar uma fonte de validação nova para evitar herdar o papel antigo; se reutilizar a fonte privada, usar **Atualizar campos/Reconectar**, revisar a alteração e verificar o papel efetivo. Não assumir que nova implantação atualizou o schema armazenado na fonte.
4. Conferir: `produto_codigo` como dimensão Texto; `sku_informado` como dimensão Número sem agregação; `quantidade` e `receita_item` como métricas Soma; `data` como Data; `atualizado_em` como Texto.
5. Criar uma tabela privada com dimensão `produto_codigo`, métricas Soma de quantidade e receita e filtro de dimensão `sku_informado = 1`. Criar um cartão privado **sem mesclagem**, métrica `produto_codigo` com agregação nativa **Contar diferentes**, mesmo filtro e intervalo. Evitar fórmulas condicionais, soma de distintos diários ou por parte. Garantir ausência de filtros ocultos, comparações ou controles diferentes.
6. Comparar cada componente com e sem o filtro, mudando uma variável por vez. O cartão sem filtro pode incluir códigos sem SKU informado e não é o KPI comercial aprovado. Conferir alguns dias, um dia e período vazio nas duas fontes no mesmo momento. Usar as referências privadas enviadas pelo operador; se a fonte direta mudou, registrar e reconciliar o corte. Preservar a diferença entre zero produtos e ausência de dados em receita/unidades.
7. Exigir cartão igual à tabela e sem aviso. Se persistir, devolver privadamente captura das configurações de campo/agregação/filtro, campos exibidos e auxiliares se observáveis, versão/implantação, corte, resultado com/sem filtro e texto sanitizado do erro. Não declarar que mudar para dimensão resolveu sem essa evidência. Não ampliar acesso ao Console Cloud.
8. Antes da migração, conferir os nove usos, mesclagens com BI_Clientes_Vendas e dependências de atualizado_em. Manter confirmação no Terminal pendente até a validação no Google e ligação efetiva da fonte correta. A primeira continuação comercial terá conferência posterior à retomada pelo operador. Curva ABC continua separada.

Não há autorização nesta tarefa para executar Analytics ou outra carga, editar manifesto, fabricar READY ou alterar PET. Os três arquivos são implantados no Apps Script; este roteiro não substitui módulos na instalação local.

## Seguimento após a versão privada v4

O Work confirmou que corrigir o papel de sku_informado não eliminou a divergência no cartão de vários dias. O recorte de um dia passou, a tabela de vários dias também; o cartão de vários dias continuou divergente com aviso de reagregação. O teste sem filtro ficou inconclusivo. Portanto, a alteração de schema foi necessária à semântica do indicador, mas **não comprovou a resolução do cartão**. Os números e referências comerciais permanecem na evidência privada do operador.

Não houve acesso autenticado pelo Codex às consultas do relatório. Uma soma de distintos diários/por partes poderia divergir do conjunto global, mas não foi demonstrado que o Google realizou essa soma. Não atribuir uma causa ao número mostrado sem comparar as consultas efetivas.

### Aplicação conservadora do filtro no conector

O conector passa a aplicar **somente em BI_Itens FARMA** filtros de sku_informado com EQUALS ou IN_LIST, INCLUDE/EXCLUDE e valores numéricos 0/1 (ou seus textos canônicos no pedido Google). Respeita AND entre grupos e OR dentro de cada grupo. Só aplica se **todos** os filtros forem suportados. Caso contrário, devolve todas as linhas do período e todos os campos solicitados, inclusive forFilterOnly, com filtersApplied=false. O fallback não aplica um subconjunto de condições.

Quando todos os filtros são suportados, eles são avaliados por item no leitor antes da projeção. A resposta usa filtersApplied=true e retira somente os campos que foram solicitados exclusivamente para filtrar. O indicador permanece na resposta quando também é um campo de exibição. Nenhum resultado é agregado ou deduplicado por produto, dia ou parte: isso preserva quantidades e receita. Ausência de filtro não exclui automaticamente itens sem SKU.

A varredura de todas as partes e as verificações de origem, tipos, chaves, contagens, trava e manifesto acontecem normalmente. Um item inválido fora da seleção também bloqueia a consulta. O código de leitura compartilhado, schema, publicação Windows, manifesto e PET não foram alterados nesta continuação. O histórico e as demais tabelas mantêm a delegação de filtros existente.

Esse caminho segue o [contrato oficial de filtros](https://developers.google.com/data-studio/connector/filters), evitando a necessidade de o Google reaplicar esse filtro específico antes de COUNT_DISTINCT. A eficácia sobre o aviso comercial ainda depende de homologação da nova implantação.

### Comparação estruturada e segura das consultas

As chamadas FARMA BI_Itens passam a registrar no console Apps Script um JSON `diagnostico: consulta_bi_itens_v1`, somente depois de concluídas as guardas da leitura. Campos: nomes autorizados solicitados, marca somente_filtro, início/fim, quantidade de grupos, formato dos filtros (campo autorizado/operador/tipo, nunca valores; até 25 grupos e condições), filtros_aplicados, tratamento e quantidade de linhas da resposta. Não inclui valores dos filtros, códigos de produto, dados pessoais, destino, token ou linhas da origem. Esse registro não aparece como linha de dados nem exige novas permissões.

O Work deverá comparar o registro do cartão de um dia com o de três dias e com o da tabela, se esses registros estiverem acessíveis nas superfícies já autorizadas. Verificar especialmente: campo data solicitado ou não, indicador como forFilterOnly, quantidade de chamadas e recortes efetivamente recebidos. `SKU_ANTES_AGREGACAO` significa que todos os filtros reconhecidos foram aplicados; `DELEGADO` significa que nenhum filtro de dimensão foi aplicado pelo conector. A captura é estrutural; não demonstra uma execução interna específica do otimizador Google. Se os logs não estiverem disponíveis, registrar essa pendência; não ampliar permissões nem contornar o bloqueio do Console Cloud.

### Nova validação privada pelo Work

1. Preservar a implantação v4 e criar uma nova versão privada com os três arquivos completos do mesmo commit corrigido. Nesta continuação, somente Code.js mudou em código operacional. Manter o schema corrigido da v4, a fonte direta em produção e o PET.
2. Em uma fonte privada ligada à nova implantação, conferir os tipos e repetir a tabela e o cartão equivalentes. Filtrar inicialmente apenas sku_informado = 1, sem filtros ocultos ou mesclagens, no recorte de um dia e de três dias, e depois no vazio. Forçar atualização e aguardar que os componentes terminem; não concluir com indicadores de atualização pendente.
3. Exigir tabela e cartão coerentes e sem aviso, além das quantidades e receitas corretas. Não usar uma soma dos cartões de cada dia como referência do período completo. A comparação sintética comprova que o mesmo SKU entre dias e partes conta uma única vez no conjunto global.
4. Fazer controle sem filtro na mesma fonte privada, um componente por vez. Esse controle retorna inclusive itens sem SKU informado e pode ter outra contagem. Não alterar produção para comparar.
5. Se persistir o erro, devolver privadamente o resultado e, quando acessíveis, os registros consulta_bi_itens_v1 correspondentes a cartão/dia, cartão/período e tabela/período, com horário e implantação. Não presumir que o campo corrigido ou o filtro aplicado já resolveram o aviso.
6. Manter migração e confirmação no Terminal pendentes até a leitura, os nove usos e a ligação efetiva serem validados. A primeira continuação real e a Curva ABC continuam com conferências separadas.

Novas regressões executam getData e o leitor reais com APIs sintéticas, incluindo aplicação prévia, retirada de forFilterOnly, preservação de campos exibidos, ausência/combinações de filtros, fallback integral, um dia/vários dias/vazio, SKU entre partes, valores financeiros, WRITING e chave duplicada em linha excluída. A base e5bbbef reprova a nova regressão de aplicação; o novo código passa. Esses testes não executam o Data Studio nem reproduzem sua mensagem interna de reagregação.

## Seguimento após a versão privada v5: período ausente

O Work relatou consultas sem dateRange e sem dimensionsFilters, com tratamento DELEGADO e devolução da base inteira, enquanto a tabela do relatório apresentava o recorte solicitado e o cartão continuava divergente. A fonte foi corrigida de BI_Clientes para BI_Itens antes dessa conferência, segundo o relato. O Codex não acessou as execuções autenticadas ou alterou a produção nesta etapa.

**Defeito confirmado no código:** getConfig declarava dateRangeRequired=false incondicionalmente. O [contrato oficial de período](https://developers.google.com/data-studio/connector/date-range) exige true para que o Google inclua dateRange nas solicitações getData. As correções anteriores cobriam o tratamento de filtros recebidos, mas não esse requisito de configuração. Isso explica a ausência de obrigação de envio das datas; não comprova como o Google chegou ao total divergente nem por que decidiu não enviar filtros de dimensão.

### Correção

- getConfig passa a usar a [configuração em etapas](https://developers.google.com/data-studio/connector/stepped-configuration). A primeira resposta recolhe as escolhas existentes; a resposta final declara dateRangeRequired=true somente para BI_Itens FARMA. Segmento e tabela são dinâmicos, todas as perguntas são preservadas nas respostas subsequentes e a etapa final encerra o fluxo. As demais tabelas e PET preservam a declaração anterior de período opcional; isso evita impor um período a LTV ou fontes cadastrais sem data.
- getData de BI_Itens FARMA exige início e fim válidos, ordenados, antes de abrir o transporte Sheets. Uma fonte antiga que ainda não enviar o intervalo recebe mensagem acionável para reconectar/configurar; não devolve toda a base silenciosamente e não inventa um período.
- Datas recebidas continuam sendo aplicadas antes da resposta. Ausência de dimensionsFilters não autoriza inventar sku_informado=1 nem declarar filtersApplied=true. A aplicação conservadora de filtros da v5 permanece vigente.
- O registro consulta_bi_itens_v1 inclui periodo_exigido e amostra, derivado de scriptParams.sampleExtraction. A documentação Google distingue extração para detectar tipos semânticos e consultas de gráficos. As amostras recebem um período próprio quando o recurso está habilitado; não comparar essa data de descoberta com a seleção do cartão.

Não existe, nas referências consultadas, uma opção de configuração que obrigue o envio de todos os filtros do relatório ao conector. O contrato permite que o Google filtre a resposta. Portanto, a ausência do filtro continua sendo uma investigação de vinculação/consulta efetiva, separada da correção comprovada de dateRangeRequired. Não trocar o indicador para true em uma resposta que não aplicou todos os filtros.

### Roteiro privado v6 para o Work

1. Preservar v5, fonte direta e relatório produtivo. Criar versão privada com os três arquivos completos do novo commit e uma **nova fonte privada BI_Itens FARMA**, concluindo as etapas de configuração. Não basta publicar Code.js: a fonte anterior pode conservar a configuração de período opcional. Registrar implantação, fonte e tabela efetivamente selecionada; não aceitar BI_Clientes como substituta.
2. Manter sku_informado como dimensão Número sem agregação, produto_codigo como Texto e atualizado_em como Texto. Na tabela e no cartão privados, conferir **Dimensão do período = data**. Usar o mesmo intervalo explícito para ambos durante o isolamento; depois testar o controle de período do relatório com os componentes em Automático e vinculados à mesma fonte. A configuração de período precisa ter sido concluída antes das consultas.
3. Forçar atualização e correlacionar horário, fonte/implantação e registros consulta_bi_itens_v1. Verificar chamadas **amostra=false**, periodo_exigido=true e datas exatas de cada recorte. Uma chamada de amostra ou uma consulta reaproveitada em cache não comprova que o gráfico solicitou o período atual. Não presumir qual chamada pertence a qual cartão apenas por proximidade na lista de execuções.
4. Testar um dia, três dias e período vazio, com tabela e cartão equivalentes. Conferir os totais privados contra a fonte direta no mesmo corte e a ausência de aviso de reagregação. A resposta de três dias deve estar limitada ao recorte; não usar uma contagem fixa de linhas como resultado esperado.
5. Recriar o filtro de dimensão sku_informado=1 especificamente no componente da nova fonte. Confirmar que está ativo e sem filtros herdados/mesclagens durante esse teste. Se o Google o enviar, o registro indicará SKU_ANTES_AGREGACAO; caso contrário, indicará DELEGADO, preservando os campos auxiliares para o Google filtrar. Não declarar esse segundo caminho incorreto apenas pela ausência de dimensionsFilters. Comparar também sem filtro, aguardando atualização completa.
6. Se persistir o aviso, devolver os registros sanitizados efetivamente correlacionados a cartão/dia, cartão/três dias e tabela/três dias, incluindo amostra, campos, datas e filtros estruturais, além da configuração de período/filtro dos componentes. Sem essa correlação, a origem interna do número continua pendente. Não ampliar permissões do Cloud Console.
7. Manter confirmação no Terminal e migração pendentes até os critérios passarem. Só então conferir os nove usos e ligações. A primeira continuação real e a Curva ABC permanecem validações separadas.

**Prova local:** três regressões novas verificam a sequência de getConfig e o escopo FARMA, a rejeição das chamadas sem datas/invertidas/inválidas antes de qualquer acesso e o recorte real de um dia/três dias/vazio, mesmo quando o Google não envia filtros. O marcador de amostra também é testado. A base 453379a reprova essas regressões. Esses testes usam SDK/Sheets simulados e não demonstram que a fonte privada no Google já foi reconectada ou que o cartão comercial foi corrigido.
