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
