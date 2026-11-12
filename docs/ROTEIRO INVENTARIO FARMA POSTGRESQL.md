# Roteiro de migração do relatório FARMA — inventário de 12/11/2026

**Complemento posterior:** [contratos dos nove aliases](CONTRATOS%20NOVE%20ALIASES%20FARMA.md). As quatro projeções operacionais e o adaptador ABC foram implementados; as fórmulas/configurações reais e a origem/chave de ds136 continuam pendentes. As contagens de gaps abaixo descrevem a base 83692b6.

Complemento ao [guia de implantação e carga](MIGRACAO%20WINDOWS%20POSTGRESQL%20DATA%20STUDIO.md). A distribuição Windows continua 1.5.37. Esta entrega atualiza o **leitor na VPS, o conector privado e o roteiro**; não instala serviços nem troca fontes comerciais.

## Evidência e preservação

O [inventário fornecido pelo Work](inventarios/FARMA_DATA_STUDIO_2026-11-12.md) foi preservado como evidência, sem registros de clientes, pedidos ou segredos. Ele descreve **37 aliases, 5 mesclagens, 75 componentes com fonte, 8 controles de período, 14 filtros e 3 substituições de IDs**, em 14 páginas. Os nomes e campos observados não comprovam fórmulas, condições ocultas ou conexões físicas.

O inventário corrige a lista anterior de três mesclagens conhecidas. As cinco devem ser preservadas:

| Mesclagem | Usos observados | Fontes e junção observada |
|---|---:|---|
| Produtos de pedidos válidos | 0 | ds73 INNER ds72 por pedido_chave; filtro Venda elegível ainda precisa de fórmula |
| Público e compras identificadas | 0 | ds74 LEFT ds72 por contact_uuid |
| NexoFlow - Pedidos e produtos por cliente | 1 | ds80 LEFT ds83 por data e venda_chave |
| Anúncios - contatos e pedidos identificados | 2 | ds123 LEFT ds121 por Pedido após anúncio = pedido_id; cálculo temporal a conferir |
| FARMA · LTV por cliente | 2 | ds175 LEFT ds123 por cliente_id = farmalider_cliente_id |

Zero usos não autoriza exclusão. Preservar cada alias, incluindo ds74/ds103/ds123 (Base_Contatos) e ds141/ds175 (LTV), mesmo quando apontam à mesma tabela. Não fundir fontes por nome lógico. O inventário original conserva os nomes exatos, inclusive `FARMA | LTV por cliente`.

## Matriz reproduzível, sem acesso comercial

No checkout do SHA desta entrega, Linux ou PowerShell com Python:

```text
python scripts/audit_datastudio_inventory.py
python scripts/audit_datastudio_inventory.py --saida inventario-farma-conferencia.json
```

O segundo comando exige arquivo novo. A matriz guarda o hash do anexo, cada alias e seu nome, configuração candidata de tabela/grão, campos presentes no contrato versus rótulos a conferir, cinco mesclagens/junções, 83 componentes/controles e três substituições de IDs. Não lê Google, PostgreSQL ou SQLite; não declara homologação. `permits_cutover=false` é deliberado, mesmo com execução sem erro. Não é um novo comando `nexo` e não exige credenciais.

### Correspondências comprovadas no código

| Aliases (cada um deve continuar separado) | Tabela na API |
|---|---|
| ds2 | BI_Resumo_Diario |
| ds13, ds14, ds15, ds16, ds17 | BI_Canais, BI_Conversao, BI_Vendas, BI_Ads, BI_Status, respectivamente |
| ds74, ds103, ds123 | Base_Contatos |
| ds80, ds81, ds82, ds83, ds84 | BI_Clientes_Vendas, BI_Clientes, BI_Publico, BI_Itens, BI_Qualidade |
| ds86, ds88, ds90 | BI_Produtos_ABC, BI_KPIs_Periodo, BI_Produtos_Juntos (snapshots; não substituir os conjuntos ABC dinâmicos por eles) |
| ds121, ds133 | BI_Pedidos, BI_Meta_Resultados |
| ds139 | BI_Historico_Resumo, recorte_historico=TOTAL |
| ds140, ds142, ds143 | Historico_Itens, BI_Cobertura_Historica, Historico_Pedidos |
| ds141, ds175 | BI_LTV_Clientes |
| ds190, ds191, ds192 | BI_Historico_Resumo, recorte_historico=MES, ANO, SEM_EMISSAO, respectivamente |

São **28 aliases com tabela leitora disponível**, sujeitos à conferência dos campos calculados e da ligação física no Google. Isso não prova igualdade de todos os componentes.

### Nove aliases sem substituição direta comprovada

| Alias | Limite identificado e encaminhamento |
|---|---|
| ds0, ds1 | Metricas_Diarias/Metricas_Vendas estão no armazenamento, mas não na lista pública do leitor. Requerem projeção autorizada/tipada; não tornar público o catálogo inteiro. Preservar aliases sem uso. |
| ds72, ds73 | Pedidos_FarmaLider/Itens_Pedidos_FarmaLider estão privados. Integram as duas mesclagens de zero gráficos e não podem ser descartados. Capturar fórmula/IDs de Venda elegível e Clientes que já compraram para projetar os campos necessários, sem expor payload bruto, erros privados ou cliques. Não substituir pela BI só por semelhança de nomes/chaves. |
| ds106, ds107, ds109, ds110 | Conjuntos dinâmicos de ABC, resumo e compras juntas não equivalem aos snapshots BI_Produtos_ABC/BI_KPIs_Periodo/BI_Produtos_Juntos. Conferir implantação, parâmetros e IDs contra connectors/looker_abc; implementar/validar o adaptador PostgreSQL mantendo o cálculo por período. A falha anterior de leitura ABC é evidência de referência, não resultado esperado aceitável. |
| ds136 | BI_Weni_Conversas_Diarias não consta no catálogo. Existe Conversas_Diarias (projeto/data/conversas), mas nome parecido não prova schema, conteúdo, corte nem origem. Conferir cabeçalho, chave e eventual preenchimento manual antes de mapear/exportar. Não criar fonte zerada ou atribuir essas conversas a anúncios por data. |

**O corte integral das 37 fontes não está liberado por esta entrega.** Os limites acima são visíveis na matriz; não são tarefas para o Work contornar com SQL manual ou remoção de guardas. As projeções/adaptações de código restantes precisam ser concluídas após a comprovação dos contratos indicados. A carga histórica READY, sozinha, não resolve essas dependências do relatório. A enumeração de fontes pelo Work não confirmou ausência de células manuais.

## Correções comprovadas por regressão

O leitor definitivo podia incluir resumos `vigente=Não`. A nova regressão falhou no código anterior com uma competência antiga de receita 999; após a correção, somente as duas competências vigentes retornam. Nenhum fato é apagado.

O filtro anterior usava apenas periodo_inicio: podia incluir um mês inteiro num filtro de três dias ou omiti-lo quando o início solicitado era posterior. Agora a API seleciona sobreposições e recusa qualquer recorte agregado cortado, na mesma transação de leitura consistente. O erro `DS_FILTRO_CORTA_RECORTE_USE_DETALHE` chega sanitizado ao conector. Para dias, usar o detalhe financeiro; não repartir o mês proporcionalmente.

Compradores de múltiplas competências exigem a dimensão competencia ou um recorte único; MAX não transforma compradores mensais em compradores do período. SUM continua bloqueado. Teste: o mesmo cliente compra em outubro e novembro; ambos têm 1 comprador, ANO/TOTAL têm 1, receita 10,10 + 20,20 = 30,30. SEM_EMISSAO permanece separado, com pendência sem receita artificial.

O campo `faturamento` de BI_Clientes_Vendas e os campos financeiros explícitos do histórico/itens/LTV passam a ter tipo **CURRENCY_BRL** no conector. Os valores continuam numéricos, sem texto “R$” no transporte; atualizado_em continua Texto. Não presumir BRL para investimentos originais Meta quando a moeda da conta não foi conferida.

## Sequência do Work

1. Conferir SHA/CI desta entrega e os comandos do guia. Usar o novo leitor e os três arquivos do conector (`Code.js`, `Schemas.js`, `appsscript.json`) num projeto/implantação privada. Windows/publicador continuam com o contrato 1.5.37; hash do contrato de publicação, migração 002 e permissões atuais não foram alterados. Não atualizar o projeto piloto ou fonte direta por cima.
2. Preservar cópia do relatório oficial e suas fontes/implantações. Gerar a matriz offline. Para cada alias, registrar privadamente conexão original, nova conexão candidata, tabela, campo de período e campos/IDs, sem renomear/fundir/remover os aliases existentes. Se o Google emitir outro ID para a nova fonte, guardar a correspondência e manter a original para reversão; não prometer reuso do ID interno nem recriar todos os componentes.
3. Conferir as cinco mesclagens, inclusive as duas sem gráficos, seus lados LEFT/INNER, ordem, chaves, períodos e filtros. Capturar fórmulas dos rótulos como Novo campo, Pedido após anúncio, Venda elegível, CPA e ROAS, sem deduzi-las do nome. Preservar `nxf_canal`, `nxf_faixa` e a substituição de ID de contact_canal_principal registrada no anexo.
4. Resolver os nove aliases sinalizados antes do corte integral. Devolver apenas schema/configuração/fórmulas e contagens agregadas necessárias; nunca registros de clientes, tokens ou payload de compras. Ausência de uma fonte não pode virar zero silencioso.
5. Com dados READY no contrato definitivo, testar na cópia do relatório os casos abaixo. Comparar mesma versão/corte, SQL, API e Google. Registrar data/hora America/Belem, versão do leitor, implantação do conector, alias, filtro, universo e resultado. Testes sintéticos do Codex não preenchem essa conferência.
6. Somente após cobertura das 37 fontes, cinco mesclagens e todos os componentes, efetuar a troca no relatório oficial conforme autorização de corte do guia, preservando fontes antigas. Os 75 componentes possuem seu vínculo individual no anexo/matriz; conferir separadamente os oito controles de período. PET fica para etapa posterior.

## Recortes e critérios no Google

| Caso | Verificação obrigatória |
|---|---|
| ds139 TOTAL | Um recorte acumulado vigente; não somar MES/ANO/SEM_EMISSAO ao TOTAL. A configuração TOTAL não recebe filtro de calendário; rotular como acumulado. Total inclui pendências sem data conservadas. |
| ds190 MES | Uma linha por competência; soma de receita/estados fecha com TOTAL incluindo SEM_EMISSAO. Compradores por mês não somáveis. Usar meses inteiros; dias exigem detalhe. |
| ds191 ANO | Uma linha por ano; compradores calculados diretamente nesse ano. Não MAX/SUM de compradores mensais para fabricar anual. Intervalo parcial de ano deve falhar, não exibir o ano completo. |
| ds192 SEM_EMISSAO | Preservar alias, mesmo sem uso. Conferir contagens/pendências; não atribuir data ou receita artificial. |
| ds133 anúncios | Recriar/conferir filtro classificacao=FARMA e os filtros herdados/página. Dados sintéticos INDEFINIDO não entram. Conferir a condição composta Delivery FarmaLíder e origem/metodologia de Primeiro anúncio. Custo desconhecido permanece indisponível, não zero; CPA/ROAS exigem denominadores e moeda comprovados. |
| ds80 Receita gerada | Conferir os componentes cd-qiedv2y67d, cd-mwlhg9v97d e cd-ze1p6l2r8d: fórmula efetiva, SUM no grão correto, tipo moeda BRL, duas casas, separadores brasileiros. Renovar campos da fonte privada e rever sobreposições de formato do gráfico. |
| BI_Itens | SKU distinto no período inteiro, quantidade, receita e detalhe; SKU repetido em dias diferentes conta uma vez. 01–03/11, 02/11 e 30/11; somente usar as referências 216/331/17.675,89 e 90/134/4.753,02 quando o corte/universo for o mesmo piloto. O histórico definitivo ampliado pode mudar esses números legitimamente. |
| LTV e mesclagens | LTV acumulado não se recalcula pelo mês de receita. Não multiplicar receita por itens/contatos, nem somar primeiro e último toque. Conferir cardinalidade real antes de aceitar o total da mesclagem. |
| Vazio/erro | Sem linhas: receita/unidades sem dados, distintos conforme métrica. Erro/limite/permissão não pode ser tratado como período vazio. Nunca aceitar total parcial com aviso. |

Se um recorte cruza a cobertura observada de uma competência, registrar essa limitação. Preservar LIMITES_DA_API_NAO_HOMOLOGADOS e as pendências. Recorte civil não comprovado não vira completo pela migração de armazenamento.

## Estado da comprovação

Inventário real: fornecido pelo Work, não nova inspeção Google do Codex. Código: regressões locais PostgreSQL descartável, Node e auditoria offline. Implantação, equivalência de fórmulas/IDs, nove aliases sem substituição direta, resultados na cópia Google e corte comercial: pendentes. Nenhum manifesto comercial, estado READY, planilha, VPS, relatório oficial ou PET foi editado nesta entrega.


## Validação executada no Codex

- PostgreSQL 18.6 descartável e contêiner HTTP privado: **33 testes aprovados**, incluindo repetição, rollback, isolamento, snapshot consistente, inventário e as novas guardas de resumo. Sem portas publicadas ou dados comerciais.
- Sete suítes Node de conectores: **99 testes aprovados**. As novas regressões cobrem BRL, TOTAL/MES/ANO/SEM_EMISSAO, filtro FARMA, valores indisponíveis e erros sanitizados.
- Histórico, Analytics, CLI/configuração Windows e documentação: **69 testes + 18 subtestes aprovados** no Linux. A matriz Windows executa no CI do commit; execução local Linux não é teste no Windows do operador.
- Ruff, Pyright (app e os dois módulos Python alterados), catálogo do conector, consistência e HTML documental aprovados. Dependências do serviço: nenhuma vulnerabilidade conhecida no pip-audit.
- Regressão antes da correção: resumo não vigente retornava indevidamente; teste BRL retornava tipo Number. Ambos falharam antes e passaram depois.
- A primeira tentativa de smoke Docker não iniciou o contêiner em um workspace quase cheio. Removidas somente imagens de teste antigas desta sessão; reconstrução e repetição completas aprovadas. Nenhum volume/backup da VPS foi acessado ou removido.

CI/CodeQL devem ser conferidos no SHA informado na entrega. Nenhum pacote Windows novo foi gerado, e a release 1.5.37 permanece intacta.
