# Contratos dos nove aliases FARMA — complemento ao inventário

Continuação de `83692b6de1081c170ec15ad46f706d1168b8f331` e `162d696cf064124380691c7c4652090867edf82a`, com metadados complementares encaminhados pelo operador em 12/11/2026. Escopo: código, testes e documentação. Nenhuma troca de fonte oficial, carga comercial, alteração de manifesto ou implantação na VPS. As 37 fontes, cinco mesclagens (duas sem gráficos), 75 componentes, oito controles, 14 filtros e três substituições de IDs permanecem no inventário original.

## Implementado

`integrations/datastudio/read_catalog.py` define projeções restritas **somente no leitor autenticado**, sem mudar o hash/contrato de publicação Windows, os fatos ou o catálogo privado de armazenamento. As visões e grants são criados pelo admin já existente, de forma aditiva. Não há acesso anônimo, concessão PUBLIC ou acesso às tabelas brutas pelo papel leitor.

| Alias | Tabela / campos expostos |
|---|---|
| ds0 | Metricas_Diarias: data, tipo_atribuicao, anuncio_id, anuncio_titulo, contatos (numérico) |
| ds1 | Metricas_Vendas: data e os oito indicadores originais numéricos, incluindo pedidos, compradores, unidades, produtos, frete e faturamento |
| ds72 | Pedidos_FarmaLider: pedido_chave, pedido_id, contact_uuid, data, origem_pedido, status_confirmacao, status_validacao, farmalider_status_pedido, farmalider_forma_pagamento; campo derivado calc_gf73fvq57d (Venda elegível, Texto) |
| ds73 | Itens_Pedidos_FarmaLider: item_chave, pedido_chave, data, produto_codigo e produto_nome como texto; quantidade, valor_unitario e valor_total numéricos |

Sem CPF, telefone, dados brutos, mensagens de erro privadas ou IDs individuais de clique nessas projeções. Valores ausentes permanecem nulos; valor numérico malformado causa erro, não zero. Chaves e zeros à esquerda preservados. Os testes executam `ds73 INNER ds72` por pedido_chave e `ds74 LEFT ds72` por contact_uuid no PostgreSQL com a conta leitora real restrita. O filtro calculado Venda elegível foi comprovado pelo Work e implementado exclusivamente na projeção leitora; os testes aplicam o filtro antes das duas junções.

## ABC dinâmica via PostgreSQL

O conector definitivo ganha as seleções `ABC_abc`, `ABC_resumo` e `ABC_juntos`. Os IDs e tipos vêm de `fieldSpecs_` do conector `connectors/looker_abc`. `AbcCore.js` é uma cópia conferida byte a byte do cálculo oficial; `scripts/sync_datastudio_schema.py --check` verifica cálculo e schema. Não utiliza snapshots BI_Produtos_ABC/BI_KPIs_Periodo/BI_Produtos_Juntos como substitutos.

O adaptador lê BI_Itens e BI_Clientes_Vendas pela API, no período selecionado, com o mesmo destino/segmento/ambiente/hash e **a mesma versão READY positiva**. Divergência de versão, falha de rede, resposta incompleta ou falta de reconciliação entre itens e vendas aborta toda a resposta. O prazo é conferido antes de cada leitura e após o cálculo. O núcleo mantém classes, empates, SKU sem informação, resumo e pares únicos por pedido. Filtros de classe continuam aplicados no Data Studio após o cálculo, sem recalcular ABC só para a classe filtrada.

As consultas mantêm os limites de 50 mil linhas e 7 MB por resposta. Não há paginação silenciosa nem truncamento: intervalos grandes podem exigir futura agregação SQL especializada. Esta entrega não prova que uma consulta anual da base real caiba nesse limite. Cota/limite/erro não vira período vazio. No vazio válido, ABC/pares têm zero linhas e o resumo segue o contrato legado (zero produtos/receita, classes indisponíveis). O marcador READY é usado apenas internamente para provar a geração; `atualizado_em` permanece Texto e vazio na saída dinâmica quando não há um horário único comprovado. Não fabricar timestamp da carga.

## Metadados recebidos e contrato executável

A evidência complementar está em [JSON sem dados comerciais](inventarios/FARMA_METADADOS_COMPLEMENTARES_2026-11-12.json); o inventário original permanece intacto. A auditoria registra os dois hashes. Evidência encaminhada pelo operador não equivale a inspeção independente do editor nesta entrega.

**ds72 — Venda elegível:** ID `calc_gf73fvq57d`, Texto, sem agregação padrão. A visão acrescenta a coluna ao final, sem alterar os fatos ou o hash do publicador Windows. Expressão equivalente à fórmula recebida:

```text
CASE WHEN status_confirmacao = "CONFIRMADO_API"
  AND status_validacao IN ("OK", "ATENÇÃO_TOTAL_DIVERGENTE")
  AND farmalider_status_pedido IN ("4", "1", "2")
  AND farmalider_forma_pagamento != "0"
THEN "Sim" ELSE "Não" END
```

É uma seleção específica do relatório. **Não substitui a regra financeira global**, que também admite os estados -2, -1 e 0 nas condições oficiais. Não muda LTV, faturamento armazenado ou validação de pedidos. Mantém a comparação original de pagamento; não inventa uma lista adicional de pagamentos nesta fórmula.

O filtro **Pedidos confirmados e elegíveis**, valor **Sim**, pertence à entrada ds72 das duas mesclagens: `ds73 INNER ds72` por pedido_chave e `ds74 LEFT ds72` por contact_uuid. Na LEFT, filtrar ds72 antes da junção preserva contatos sem compra elegível; aplicar um WHERE ao resultado da junção pode removê-los e não é equivalente.

**Clientes que já compraram** é a métrica da mesclagem Público e compras identificadas: origem `contact_uuid`, ID observado `_1277959290_`, **Contar diferentes** sobre ds72 filtrada. Não somar contagens diárias nem contar linhas de itens. O ID próprio de saída dessa métrica permanece desconhecido; não gerar um ID substituto por aproximação.

| Alias | Modo antigo confirmado | Destino novo | Catálogo observado |
|---|---|---|---|
| ds106 | abc | ABC_abc | 16 campos técnicos |
| ds107 | abc | ABC_abc | Os 16 anteriores + periodo_rotulo, participacao_receita, participacao_acumulada |
| ds109 | resumo | ABC_resumo | 15 campos, incluindo participacao_top5_receita_pct e participacao_top5_receita |
| ds110 | juntos | ABC_juntos | 9 campos de período e pares de produtos |

Os IDs completos estão no JSON e são conferidos contra o schema gerado. Não fundir ds106/ds107 nem apagar campos antigos por terem catálogos visíveis diferentes. O parâmetro legado `spreadsheetId` aponta ao Dashboard FARMA, e datas são obrigatórias. Esse ID fica como evidência de origem: a conexão nova usa `tabela`, `segmento`, `ambiente` e a credencial privada da API; não depende de Sheets. Frações formatadas como percentual e indicadores com sufixo `_pct` preservam o contrato do núcleo ABC.

**ds136:** cabeçalho de oito campos preservado. Há evidência de uma publicação pontual de 01–06/11/2026, mas produtor, chave (incluindo participação de projeto), política de escrita/revisão e edições manuais continuam desconhecidos. Os **15 minutos** são atualização de leitura/cache da fonte Data Studio; não comprovam uma rotina de alimentação. Não foi criado mapeamento para `Conversas_Diarias`: projeto/data/conversas não conserva os oito campos nem comprova identidade. Não somar resolvidas/não resolvidas/transferidas presumindo grupos disjuntos, nem atribuir conversas a anúncios/pedidos por data.

## Pendências objetivas para o Work

Solicitar somente metadados, nunca linhas de clientes/pedidos ou segredos. Não repetir solicitações dos campos já recebidos.

| Alias | Ainda necessário antes da troca |
|---|---|
| ds0 / ds1 | Conferir IDs/tipos e conexão original, incluindo eventuais cálculos locais, mesmo com zero gráficos. |
| ds72 | Confirmar o ID próprio da métrica na saída da mesclagem, ou registrar que o editor não o disponibiliza; conferir vínculo do filtro e de contact_uuid após reconexão. Fórmula e ID de Venda elegível já recebidos. |
| ds73 | IDs/tipos efetivos e Record Count após reconexão; junção INNER e grão de item preservados. |
| ds106 / ds107 / ds109 / ds110 | ID e versão exatos da implantação antiga, para rastreabilidade/reversão; IDs sobrescritos localmente em gráficos. Modos, campos técnicos e spreadsheetId já recebidos. |
| ds136 | Produtor/responsável, chave única/projeto, política de escrita e revisão de dias, existência de preenchimento manual. Até isso ser comprovado, manter fonte atual. |

## Implantação e homologação na cópia (Work)

1. Conferir SHA/CI desta entrega. Windows permanece 1.5.37; atualizar o servidor por checkout/imagem do SHA e executar o módulo admin do guia, que acrescenta as quatro visões restritas/grants. Usar o DSN administrativo privado existente, sem porta pública e sem reexecutar a 001. Preservar piloto e Metabase.
2. Implantar em versão privada nova os **quatro arquivos** de `connectors/datastudio_api`: Code.js, Schemas.js, AbcCore.js e appsscript.json. Não substituir fontes oficiais nem projetos antigos. Usar somente segredo leitor do segmento/ambiente correto.
3. Gerar a matriz com `python scripts/audit_datastudio_inventory.py --saida inventario-novo.json`. As quatro projeções passam a disponíveis; os quatro aliases ABC têm adaptador, com os modos antigos comprovados; implantação e sobrescritas locais ainda precisam de conferência. ds136 permanece sem mapeamento.
4. Na cópia, preservar cada alias e mesclagem. Conferir os metadados pendentes e três substituições existentes. Para ds72, conferir o campo Texto `calc_gf73fvq57d` (Venda elegível) e o filtro Sim nas duas entradas de mesclagem. Se a reconexão mantiver o campo calculado local, conservar sua fórmula idêntica; não criar dois campos homônimos nem apagar o original antes de mapear dependências. Caso o editor não permita preservar o ID, registrar a substituição explícita na cópia e validar cada dependência antes de qualquer corte. Contar diferentes de contact_uuid continua na métrica da mesclagem, sem nova fórmula de SUM.
5. Comparar ABC em um dia, vários dias com SKU repetido e período vazio, por SKU, classe, receita, unidades, ranking e pares; usar mesmo corte e conferir com o cálculo legado. Aumentar o recorte só até o limite explícito. Testar falha de leitura separadamente do vazio.
6. Repetir TOTAL/MES/ANO/SEM_EMISSAO, compradores distintos, filtros de anúncio FARMA, LTV acumulado e Receita gerada em R$ nos três componentes identificados. As guardas históricas e a moeda da entrega anterior permanecem. Conferir os nove usos BI_Itens e as cinco mesclagens, incluindo as duas sem gráficos.
7. Registrar versão READY/corte, SHA, implantação e resultados agregados. O corte das fontes oficiais depende dessa homologação e dos contratos pendentes; não é realizado por esta entrega.

Reversão técnica: conservar imagem e implantação anteriores. As projeções são aditivas e não modificam fatos. Não apagar visões/estados/dados para reverter o leitor; voltar à imagem/conector anteriores mantém as fontes originais disponíveis.

## Evidências locais desta entrega

- Rodada anterior: 34 testes aprovados em PostgreSQL 18.6 descartável, incluindo projeções com permissões mínimas, duas junções, snapshots e regras históricas. Um smoke de contêiner HTTP não executado localmente nesta rodada (exige imagem recompilada); o workflow inclui build e esse smoke.
- Rodada anterior: 103 testes Node aprovados nos sete leitores. Incluem o cálculo legado e o adaptador PostgreSQL: períodos diferentes, pares, vazio, base incompleta, mudança de versão, falha/limite, IDs e ordem dos campos SDK.
- Ruff, Pyright nos módulos Python envolvidos, geração/conferência do catálogo e identidade do núcleo ABC, HTML documental e diff aprovados.
- CI e CodeQL da base 83692b6 foram reconferidos como success. Os checks do novo commit são distintos e devem ser acompanhados no GitHub antes da implantação.
- Homologação no Google e informações faltantes da tabela de metadados continuam pendentes. Não houve consulta a dados comerciais nem avaliação de desempenho no volume anual real.

### Validação complementar dos metadados

A regressão de elegibilidade falhou antes da implementação (`DS_CAMPOS_NAO_AUTORIZADOS`) e passou depois. Cobre os três status elegíveis, os estados abertos preservados fora desse filtro, cancelamento, pagamento zero, confirmação/validação divergentes, DISTINCT de contato com três pedidos e as duas junções filtradas. Reaplica criação de visões/grants e compara os registros de armazenamento intactos. Testes do conector verificam ID/Texto/ausência de agregação e filtro anterior à resposta; a auditoria verifica os catálogos ABC distintos e mantém lacunas explícitas. Os checks da base 162d696 foram reconferidos como success; os checks da entrega complementar devem ser consultados no SHA final.

Resultado local da rodada complementar: **37 testes Python aprovados**, sem ignorados, em PostgreSQL 18.6 descartável, incluindo smoke HTTP da imagem recompilada; **104 testes Node aprovados** nos sete leitores. Ruff global, Pyright nos módulos Python modificados, consistência, catálogo gerado, HTML documental, diff e Gitleaks aprovados. O smoke usa imagem da árvore revisada, identificada como `metadata-working-tree`; o CI recompila a imagem com o SHA do commit. Não equivale a implantação, execução no Windows nem homologação no Google. Aviso de depreciação Starlette/httpx na suíte não reprovou testes.
