# BI_Itens FARMA — cartão de produtos distintos calculado no conector

## Evidência recebida e limites

O pacote privado `NexoFlow_BI_Itens_v6_cartoes_AB.zip`, recebido em 12/11/2026 UTC, registra consultas feitas pelo Work em 11/11/2026, 22h00–22h14 UTC−3. Na v6 (`a6b291f`), os cartões com agregação nativa e `COUNT_DISTINCT(produto_codigo)` apresentaram a contagem correta e o mesmo aviso de reagregação. O manifesto estava liberado naquele corte. Isso não comprova seu estado atual.

As referências relatadas foram 216 produtos/331 unidades/R$ 17.675,89 para 01–03/11, 90/134/R$ 4.753,02 para 02/11 e ausência de dados para 30/11. Esses números não foram lidos nas planilhas pelo Codex. Os logs não identificam individualmente todos os cartões. Os 429 recuperados não comprovam a causa do aviso. O ZIP, suas capturas, IDs privados e registros não foram adicionados ao Git.

A causa interna do aviso do Google e dos 228 antigos permanece **não comprovada**. A documentação oficial informa que `semantics.isReaggregatable` se aplica às métricas; sua ausência na dimensão Texto não demonstra defeito. Não alterar esse atributo da dimensão ou desativar verificações para tentar esconder o aviso.

## Alternativa implementada

O schema virtual de **BI_Itens FARMA** oferece a métrica `produtos_distintos_periodo`, nome visível **Produtos distintos no período (SKU informado)**. É numérica, não reagregável (`setIsReaggregatable(false)`), com agregação Automático segundo o contrato do SDK. Não há coluna nova no Sheets, mudança do hash de schema físico ou transformação de `produto_codigo` em métrica. PET e os demais schemas permanecem com seus campos anteriores.

Quando solicitada, a métrica:

1. Exige o período válido já obrigatório no piloto FARMA.
2. Aceita apenas o cartão separado, sem dimensões exibidas nem outras métricas. Não serve para agrupamento diário, ranking ou mesclagem. Campos usados apenas para filtros seguem o contrato `forFilterOnly`.
3. Aplica integralmente o filtro SKU suportado; qualquer filtro não suportado bloqueia a consulta antes da leitura. Não devolve um escalar global para depois tentar aplicar no Data Studio um filtro sobre dimensões ausentes.
4. Executa a leitura e todas as conferências existentes: origem, segmento, manifesto, estado/trava, partes, cabeçalhos, tipos, chaves, contagens, limites e prazo, inclusive para linhas excluídas pelo filtro.
5. Calcula a união exata de `produto_codigo` não vazio com `sku_informado=1`, em todas as linhas elegíveis do período e de todas as partes. Mantém os códigos como Texto e seus zeros. Um SKU repetido em dias ou partes diferentes conta uma vez.
6. Devolve uma única linha numérica para um universo não vazio de produtos; quando nenhum SKU elegível existe, devolve zero linhas, preservando a apresentação sem dados. Não soma contagens diárias ou por parte.

A regra SKU informado é intrínseca à métrica, mesmo sem filtro externo. Não usar `EXCLUDE 1` para esperar contagem de produtos sem SKU: o universo continua sendo SKU informado. Para o piloto, usar `sku_informado = 1`.

As consultas detalhadas por `produto_codigo`, unidades e receita conservam o caminho anterior e seus resultados. O diagnóstico sanitizado `consulta_bi_itens_v1` passa a distinguir `resultado=DISTINTOS_CALCULADOS` de `ITENS_DETALHADOS`; registra estrutura/quantidades, sem valores comerciais individuais. Não se promete economia nas leituras: o cartão continua examinando as partes para produzir um total íntegro, mas devolve um escalar em vez das linhas detalhadas para a contagem no Google.

Isso é uma alternativa de execução da contagem, **não uma prova de correção do motor de reagregação do Google**. A ausência do aviso ainda depende de teste na implantação privada. Os cartões antigos podem continuar apresentando o aviso.

## Validação local reproduzível

```bash
node --test tests/test_continuation_connector.cjs tests/test_looker_abc_connector.cjs tests/test_history_connector.cjs tests/test_legacy_items_connector.cjs tests/test_connector_transport.cjs
```

As novas regressões falharam antes da implementação porque a métrica não existia. A suíte passa com a nova resposta. Os cenários incluem SKU repetido na raiz e continuação em três dias, um dia, vazio, preservação de unidades e centavos no detalhe, métricas/dimensões misturadas recusadas, filtros delegados recusados, isolamento PET, WRITING, chave duplicada, tipo inválido numa linha excluída e parte ausente.

Na grade simulada de 500 mil linhas, o cartão percorre os mesmos 125 intervalos em 16 chamadas de dados e **22 chamadas totais**, sem chamada adicional para contar SKUs e sem 429 com a quota simulada. Falha 503 persistente depois do primeiro bloco recusa o total inteiro. Os relógios, quotas e serviços são simulados; não demonstram latência ou homologação comercial.

## Roteiro do Work — nova versão privada, sem Terminal

1. Manter fonte direta de produção, implantação v6 e cartões A/B preservados; FARMA pausada e PET intacto. Conferir o manifesto somente em leitura; trava/WRITING/recuperação pendente continua bloqueando. Não criar READY, editar manifesto ou ampliar permissões.
2. Atualizar integralmente `Code.js`, `Tables.js` e `Schemas.js` de `connectors/continuacoes/` a partir do mesmo commit aprovado no GitHub. Somente `Code.js` recebeu lógica nova nesta entrega; os outros dois precisam corresponder à mesma referência. Preservar o manifesto Apps Script somente leitura e o serviço Sheets v4. Criar **nova versão privada**, sem sobrescrever a anterior.
3. Criar uma fonte privada nova, FARMA/BI_Itens, apontando ao Dashboard já autorizado. Isso evita presumir que o cache de schema da v6 conhece o novo campo. Conferir `produtos_distintos_periodo` como Número/Automático e `atualizado_em` como Texto.
4. No relatório privado, criar um terceiro cartão **C**, usando diretamente **Produtos distintos no período (SKU informado)**. Não usar COUNT_DISTINCT, SUM, fórmula adicional, dimensão exibida ou mesclagem nesse cartão. Manter período automático do controle e filtro `sku_informado = 1`. Não usar busca de produto ou outros filtros no cartão C nesta entrega.
5. Comparar a tabela detalhada, fonte direta e cartão C nos três recortes. Repetir após reabertura para os três períodos. Conferir referências no mesmo corte; se a fonte mudou, reconciliar a diferença. O cartão C deve mostrar 216/90/sem dados apenas se o corte ainda corresponder à referência e abrir **sem aviso**. Registrar a versão/SHA, horário, campo/agrupamento e diagnóstico `DISTINTOS_CALCULADOS`, sem linhas comerciais.
6. Se persistir aviso, não migrar nem confirmar: devolver texto e metadados sanitizados do novo cartão e a execução correspondente. Não afirmar que o novo caminho resolveu o Google só porque o valor bateu.
7. Se C passar, conferir individualmente os nove usos e as mesclagens. A nova métrica substitui somente o indicador de distintos; tabelas/rankings/unidades/receita continuam nos campos detalhados anteriores. Fazer backup atualizado antes da troca comercial autorizada, preservar a fonte direta para reversão e reler os resultados após a migração. Não substituir todos os campos pelo escalar.
8. Só após validação e ligação real da fonte em produção, informar ao Codex/Felipe que os pré-requisitos para confirmação local estão atendidos. Não executar ou alegar comandos do Terminal. A primeira continuação real terá conferência própria após a retomada pelo operador. Curva ABC permanece separada.

## Distribuição

Não exige novo release Windows: é uma mudança hospedada no Apps Script. Windows 1.5.35 permanece intacto. Atualizar GitHub ou instalar Setup não atualiza a implantação Google. Não houve acesso/gravação comercial, edição de relatório, coleta API, Weni, Noturno, Recompra ou implantação VPS nesta entrega.

Referências oficiais consultadas em 12/11/2026 UTC:

- [Semântica e agregação](https://developers.google.com/looker-studio/connector/semantics).
- [SDK Field: setIsReaggregatable](https://developers.google.com/apps-script/reference/data-studio/field#setIsReaggregatable(Boolean)).
- [Contrato de getData e forFilterOnly](https://developers.google.com/looker-studio/connector/reference#getdata).
