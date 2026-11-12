# Contratos dos nove aliases FARMA — complemento ao inventário

Continuação de `83692b6de1081c170ec15ad46f706d1168b8f331`, em 12/11/2026. Escopo: código, testes e documentação. Nenhuma troca de fonte oficial, carga comercial, alteração de manifesto ou implantação na VPS. As 37 fontes, cinco mesclagens (duas sem gráficos), 75 componentes, oito controles, 14 filtros e três substituições de IDs permanecem no inventário original.

## Implementado

`integrations/datastudio/read_catalog.py` define projeções restritas **somente no leitor autenticado**, sem mudar o hash/contrato de publicação Windows, os fatos ou o catálogo privado de armazenamento. As visões e grants são criados pelo admin já existente, de forma aditiva. Não há acesso anônimo, concessão PUBLIC ou acesso às tabelas brutas pelo papel leitor.

| Alias | Tabela / campos expostos |
|---|---|
| ds0 | Metricas_Diarias: data, tipo_atribuicao, anuncio_id, anuncio_titulo, contatos (numérico) |
| ds1 | Metricas_Vendas: data e os oito indicadores originais numéricos, incluindo pedidos, compradores, unidades, produtos, frete e faturamento |
| ds72 | Pedidos_FarmaLider: pedido_chave, pedido_id, contact_uuid, data, origem_pedido, status_confirmacao, status_validacao, farmalider_status_pedido, farmalider_forma_pagamento |
| ds73 | Itens_Pedidos_FarmaLider: item_chave, pedido_chave, data, produto_codigo e produto_nome como texto; quantidade, valor_unitario e valor_total numéricos |

Sem CPF, telefone, dados brutos, mensagens de erro privadas ou IDs individuais de clique nessas projeções. Valores ausentes permanecem nulos; valor numérico malformado causa erro, não zero. Chaves e zeros à esquerda preservados. Os testes executam `ds73 INNER ds72` por pedido_chave e `ds74 LEFT ds72` por contact_uuid no PostgreSQL com a conta leitora real restrita. O filtro calculado Venda elegível **ainda não está comprovado**; não inferir sua fórmula a partir do rótulo, nem aplicar a mesclagem sem o filtro original.

## ABC dinâmica via PostgreSQL

O conector definitivo ganha as seleções `ABC_abc`, `ABC_resumo` e `ABC_juntos`. Os IDs e tipos vêm de `fieldSpecs_` do conector `connectors/looker_abc`. `AbcCore.js` é uma cópia conferida byte a byte do cálculo oficial; `scripts/sync_datastudio_schema.py --check` verifica cálculo e schema. Não utiliza snapshots BI_Produtos_ABC/BI_KPIs_Periodo/BI_Produtos_Juntos como substitutos.

O adaptador lê BI_Itens e BI_Clientes_Vendas pela API, no período selecionado, com o mesmo destino/segmento/ambiente/hash e **a mesma versão READY positiva**. Divergência de versão, falha de rede, resposta incompleta ou falta de reconciliação entre itens e vendas aborta toda a resposta. O prazo é conferido antes de cada leitura e após o cálculo. O núcleo mantém classes, empates, SKU sem informação, resumo e pares únicos por pedido. Filtros de classe continuam aplicados no Data Studio após o cálculo, sem recalcular ABC só para a classe filtrada.

As consultas mantêm os limites de 50 mil linhas e 7 MB por resposta. Não há paginação silenciosa nem truncamento: intervalos grandes podem exigir futura agregação SQL especializada. Esta entrega não prova que uma consulta anual da base real caiba nesse limite. Cota/limite/erro não vira período vazio. No vazio válido, ABC/pares têm zero linhas e o resumo segue o contrato legado (zero produtos/receita, classes indisponíveis). O marcador READY é usado apenas internamente para provar a geração; `atualizado_em` permanece Texto e vazio na saída dinâmica quando não há um horário único comprovado. Não fabricar timestamp da carga.

## Metadados que o Work precisa extrair

Solicitar somente metadados, nunca linhas de clientes/pedidos, credenciais ou payload comercial.

| Alias | Evidência necessária antes de homologar a ligação |
|---|---|
| ds0 / ds1 | IDs/tipos efetivos do schema e conexão original; confirmar que não há cálculo adicional mesmo com zero gráficos. |
| ds72 | Fórmula integral, ID original/substituto, tipo e agregação de **Venda elegível** e **Clientes que já compraram**; informar dependências de campos. Confirmar o filtro Pedidos confirmados e elegíveis nas duas mesclagens. |
| ds73 | IDs/tipos de pedido_chave, produto_codigo, quantidade, valor_total e Record Count. Confirmar a junção INNER e o grão de item antes da migração. |
| ds106 | Implantação/versão, parâmetro `tabela` efetivo (abc/resumo/juntos), demais parâmetros, campos/IDs. O nome ABC por período sozinho não determina o modo. Preservar mesmo com zero usos. |
| ds107 | Mesmos metadados; candidato `ABC_abc`, condicionado à confirmação do modo `abc` e IDs/cálculos locais. |
| ds109 | Mesmos metadados; candidato `ABC_resumo`, condicionado ao modo `resumo`. Confirmar fração versus percentual nos campos de participação. |
| ds110 | Mesmos metadados; candidato `ABC_juntos`, condicionado ao modo `juntos`; conferir SKU A/B e pedidos_juntos. |
| ds136 | Produtor/rotina (ou responsável manual), chave única, eventual projeto adicional, política de atualização/revisão dos dias, origem/fuso e preenchimentos manuais. Cabeçalho confirmado: data, segmento, conversas_weni, resolvidas, nao_resolvidas, transferidas, origem, fuso. |

Para ds136, **não foi criado mapeamento para Conversas_Diarias**: seu contrato projeto/data/conversas não conserva os oito campos nem comprova a identidade dos registros. Não somar resolvidas/não resolvidas/transferidas presumindo grupos disjuntos; não atribuir conversas a anúncio ou pedido apenas por data. O cabeçalho confirmado fica na matriz offline, com as quatro evidências pendentes.

## Implantação e homologação na cópia (Work)

1. Conferir SHA/CI desta entrega. Windows permanece 1.5.37; atualizar o servidor por checkout/imagem do SHA e executar o módulo admin do guia, que acrescenta as quatro visões restritas/grants. Usar o DSN administrativo privado existente, sem porta pública e sem reexecutar a 001. Preservar piloto e Metabase.
2. Implantar em versão privada nova os **quatro arquivos** de `connectors/datastudio_api`: Code.js, Schemas.js, AbcCore.js e appsscript.json. Não substituir fontes oficiais nem projetos antigos. Usar somente segredo leitor do segmento/ambiente correto.
3. Gerar a matriz com `python scripts/audit_datastudio_inventory.py --saida inventario-novo.json`. As quatro projeções passam a disponíveis; os quatro aliases ABC têm adaptador, mas a configuração efetiva permanece a conferir. ds136 permanece sem mapeamento.
4. Na cópia, preservar cada alias e mesclagem. Confirmar os metadados acima, fórmulas, IDs e três substituições existentes. Não completar fórmula desconhecida por aproximação.
5. Comparar ABC em um dia, vários dias com SKU repetido e período vazio, por SKU, classe, receita, unidades, ranking e pares; usar mesmo corte e conferir com o cálculo legado. Aumentar o recorte só até o limite explícito. Testar falha de leitura separadamente do vazio.
6. Repetir TOTAL/MES/ANO/SEM_EMISSAO, compradores distintos, filtros de anúncio FARMA, LTV acumulado e Receita gerada em R$ nos três componentes identificados. As guardas históricas e a moeda da entrega anterior permanecem. Conferir os nove usos BI_Itens e as cinco mesclagens, incluindo as duas sem gráficos.
7. Registrar versão READY/corte, SHA, implantação e resultados agregados. O corte das fontes oficiais depende dessa homologação e dos contratos pendentes; não é realizado por esta entrega.

Reversão técnica: conservar imagem e implantação anteriores. As projeções são aditivas e não modificam fatos. Não apagar visões/estados/dados para reverter o leitor; voltar à imagem/conector anteriores mantém as fontes originais disponíveis.

## Evidências locais desta entrega

- 34 testes aprovados em PostgreSQL 18.6 descartável, incluindo projeções com permissões mínimas, duas junções, snapshots e regras históricas. Um smoke de contêiner HTTP não executado localmente nesta rodada (exige imagem recompilada); o workflow inclui build e esse smoke.
- 103 testes Node aprovados nos sete leitores. Incluem o cálculo legado e o adaptador PostgreSQL: períodos diferentes, pares, vazio, base incompleta, mudança de versão, falha/limite, IDs e ordem dos campos SDK.
- Ruff, Pyright nos módulos Python envolvidos, geração/conferência do catálogo e identidade do núcleo ABC, HTML documental e diff aprovados.
- CI e CodeQL da base 83692b6 foram reconferidos como success. Os checks do novo commit são distintos e devem ser acompanhados no GitHub antes da implantação.
- Homologação no Google e informações faltantes da tabela de metadados continuam pendentes. Não houve consulta a dados comerciais nem avaliação de desempenho no volume anual real.
