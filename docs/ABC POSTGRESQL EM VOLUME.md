# ABC PostgreSQL em volume — leitor e conector

Entrega de 15/11/2026. Base `bba86d0c45968d429f5a6252da50498ca2923d39`; preserva o hotfix `SET LOCAL enable_nestloop=off` e o fechamento do publicador `4afd3c127ba27dd31075aa34e8eb1a508a9aebb9`. Escopo: código, regressão sintética e procedimento. Nenhuma implantação, consulta comercial, alteração do relatório ou reenvio de lotes pelo Codex.

## Causa e correção

O Work informou FARMA produção READY, versão 1, revisão `ca214c78-e590-4056-b58e-31877714facc`. No intervalo 01/01–15/11/2026, a consulta BI_Itens bruta com oito campos excedeu 50 mil linhas em 9,96 s. Isso é bloqueio de cardinalidade, não prova de timeout. O adaptador ABC antigo baixava BI_Itens e BI_Clientes_Vendas completos para calcular no Apps Script; assim o limite do detalhe também impedia o resumo.

A nova rota autenticada **POST /v1/abc** aceita exatamente `mode` (`abc`, `resumo`, `juntos`), `fields`, `start` e `end`. Usa somente as duas visões autorizadas, já reconciliadas, e a credencial leitora atual. Não cria tabelas, índices, grants ou revisões. Contrato/hash de publicação, schemas, IDs dos campos, alias e tipos permanecem. Não executar admin/fechamento para instalar esta correção.

- Um snapshot PostgreSQL `REPEATABLE READ READ ONLY` contém a versão READY, itens, vendas, validação e agregação. Nova publicação durante a consulta não mistura revisões: a resposta termina na versão que abriu. Durante WRITING continua disponível a versão READY anterior, conforme o contrato definitivo existente.
- PostgreSQL consolida produtos e pares. Itens e pedidos não são enviados ao Apps Script. ABC classifica os produtos consolidados no servidor Python; resumo é calculado integralmente no SQL e tem uma linha mesmo com mais de 50 mil SKUs. Pares contam cada combinação uma vez por venda, independentemente de itens repetidos do mesmo SKU.
- Quantidades e dinheiro usam numeric/Decimal; receitas são somadas em centavos. O núcleo `AbcCore.js` legado continua intacto como oráculo de paridade. Mantidos empates de ranking/classe, fronteiras 80/95, SKU ausente e tolerância de até um centavo **da conferência ABC legada**. Isso não relaxa a validação exata do fechamento financeiro.
- Nomes usam a ocorrência mais recente, com desempate pelo nome; empate de data/nome usa chave do item para escolha determinística da categoria. Não se inventa horário de carga: `atualizado_em` continua Texto vazio no conjunto dinâmico.
- Itens sem venda, data divergente, chave ausente/conflitante, quantidade inválida ou receita não reconciliada causam erro. Cancelamentos, vigência, exclusões, seleção do histórico por venda inteira e frete separado vêm das mesmas visões financeiras. Nenhum fato é editado.
- Datas são obrigatórias. Filtros de classe/produto do gráfico continuam posteriores ao cálculo do universo do período (`filtersApplied:false`), preservando a regra anterior; não recalcular ABC só sobre a classe escolhida.
- Permanecem 50 mil linhas e 7 MB **de saída**, 50 s por instrução SQL, 45 s de orçamento do adaptador ABC e limite de 500 SKUs por venda para pares. Se o próprio catálogo ABC ou os pares ultrapassarem o limite, a resposta inteira é recusada; resumo/período adequado são alternativas. Não há paginação silenciosa ou aumento de teto. Timeout leitor retorna `DS_CONSULTA_TEMPO_LIMITE`, sem SQL ou payload privado.

O conector faz uma chamada `/v1/abc` por consulta ABC, valida destino, segmento, ambiente, hash, versão positiva, campos e `complete`. Servidor antigo devolve erro explícito; não há fallback que volte a baixar todos os fatos.

## Outras fontes e períodos longos

Fontes existentes permanecem em **detalhe** por padrão. Não é seguro inferir a agregação escolhida no cartão a partir de `request.fields`: os metadados não comprovam SUM, média, contagem ou Record Count. A fonte detalhada continua recusando resultados acima do limite. Isso é uma guarda, não autorização para truncar.

Novo parâmetro opcional **modo_consulta=somas**, somente depois de conferir os componentes da fonte na cópia:

| Fonte | Métricas permitidas em SUM no SQL |
|---|---|
| BI_Itens | quantidade, receita_item |
| BI_Clientes_Vendas | pedidos, faturamento_produtos, frete, faturamento |
| Itens_Pedidos_FarmaLider | quantidade, valor_total |
| BI_Pedidos | pedido_valor, pedido_frete, pedido_faturamento_total, venda_valida |
| Historico_Pedidos | produtos, frete, faturamento |
| Historico_Itens | quantidade, valor |

As demais dimensões solicitadas formam o GROUP BY. Um pedido/item solicitado por chave pode continuar tendo cardinalidade alta. Não ligar `somas` automaticamente nos aliases ou mesclagens. **Usar somente nos componentes cuja métrica efetiva seja SUM desses campos**: média, MIN/MAX de fatos, Record Count e cálculos dependentes de linhas individuais precisam permanecer em detalhe ou ganhar contrato específico. Preços unitários, taxas, idade, compradores, LTV e indicadores Meta não são somados por inferência. Filtros não representáveis pela API (OR, exclusões, expressões etc.) bloqueiam o modo somas; no detalhe seguem delegados ao Google.

O cartão `produtos_distintos_periodo` continua COUNT DISTINCT SQL de SKU informado em todo o período. TOTAL/MES/ANO/SEM_EMISSAO conservam suas guardas; compradores não são soma de meses, LTV permanece acumulado e o filtro Meta FARMA e a formatação Receita gerada em R$ continuam intactos. `ds136` fica na fonte atual: produtor/chave/política de escrita ainda não comprovados.

## Evidências de teste

- Regressão antes da correção: consulta bruta de 60.003 itens recusada e caminho agregado inexistente. Depois: 60.003 itens → dois SKUs, 20.001 vendas, 60.003 unidades, R$ 6.000,30, um par contado 20.001 vezes. Frete sintético de R$ 99 por venda não entra na receita de produtos.
- Mesmo volume com 60.003 SKUs: resumo completo, uma linha; catálogo/pares com saída excessiva recusados sem linhas parciais.
- Paridade campo a campo com `connectors/looker_abc/AbcCore.js`: um dia, vários dias, vazio, SKU ausente, nomes recentes, empates e fronteiras. Verificação do caso histórico 149,90 operacional → 162,80 histórico com dois itens e frete separado, nos perfis sintéticos FARMA/PET.
- 50.004 linhas por fonte em BI_Clientes_Vendas, Itens_Pedidos_FarmaLider e Metricas_Diarias: somas e DISTINCT no SQL, com versão consistente. A suíte existente cobre as demais projeções, filtros, grãos históricos, contratos e isolamento. Não comprova desempenho anual de todas as 37 fontes reais.
- Falhas: origem incompleta, data/quantidade/chave divergente, timeout, resposta parcial, excesso de saída, conta sem autenticação, rota de escrita indisponível ao leitor. Conta leitora restrita executa ABC; publicação concorrente retorna snapshot anterior completo e a próxima consulta vê a versão nova.
- Local: 113 testes PostgreSQL aprovados em 28,09 s; um smoke de imagem Docker ignorado nesta rodada local (executado pelo CI em ambiente limpo). Mais 107 testes Node nos sete leitores; Ruff, Pyright global/módulos alterados e catálogo gerado aprovados. Os checks/CI devem ser conferidos no SHA final indicado na entrega. Tempos sintéticos são evidência local, não previsão de latência comercial.

## Implantação e reversão pelo Work

1. Conferir SHA final, CI e CodeQL. Guardar imagem/ID do leitor atual `bba86d0`, implantação Apps Script e configurações privadas para reversão. Conferir no ambiente o READY versão 1 informado pelo Work; se houve nova publicação, registrar o novo corte e não exigir artificialmente versão 1. Não reabrir a revisão nem tocar no publicador `4afd3c1`.
2. Obter checkout limpo do SHA validado na pasta de código existente. Construir somente a imagem e trocar **somente o serviço leitor FARMA** no Compose operacional. Não usar `up` sem nome do serviço; não recriar banco, publicador, PET ou outros serviços. A configuração Compose real deve ter a imagem do leitor separada da do publicador para preservar os SHAs distintos. O overlay de referência compartilha variável de imagem: não sobrescrever essa variável global como alteração permanente de ambos.

```bash
set -euo pipefail
: "${sha:?Informe o SHA final aprovado desta entrega}"
test "$(git rev-parse HEAD)" = "$sha"
git diff --quiet
docker build --build-arg NEXOFLOW_SOURCE_SHA="$sha" \
  -f integrations/datastudio/Dockerfile -t "nexoflow-datastudio:$sha" .
# Depois de conferir o Compose real e apontar SOMENTE o leitor à nova imagem:
docker compose up -d --no-deps datastudio-farma-read
docker compose ps datastudio-farma-read
```

O comando deve ser executado com os mesmos arquivos/projeto Compose privados da implantação atual (nomes podem diferir; não presumir que o checkout de código seja o diretório do Compose). Confirmar healthcheck e label `org.opencontainers.image.revision` da imagem efetivamente em execução. Não imprimir o Compose resolvido ou variáveis de segredo.

3. Usar o segredo **leitor** existente para testar `/v1/abc` via canal privado/Cloudflare Access. Exemplo de **corpo**, sem credenciais; a resposta deve ter `complete:true`, versão positiva, contrato/destino FARMA e a mesma versão nas comparações:

```json
{"mode":"resumo","fields":["periodo_inicio","periodo_fim","skus_distintos","faturamento_produtos","abc_disponivel"],"start":"2026-01-01","end":"2026-11-15"}
```

Testar também `abc` (produto_codigo, unidades, receita_produtos, pedidos, classe_abc) e `juntos` (produto_a_codigo, produto_b_codigo, pedidos_juntos). Comparar resumo à soma de receita dos produtos da mesma revisão, unidades ao detalhe agregado, SKU distinto ao COUNT DISTINCT no período. Não somar pedidos por SKU para obter pedidos distintos: uma venda pode conter vários SKUs. Não somar pares como quantidade de pedidos.

4. Implantar **os quatro arquivos do mesmo SHA** em nova versão privada do Apps Script: `Code.js`, `Schemas.js`, `AbcCore.js`, `appsscript.json`. Só Code.js precisa mudar nesta entrega; os demais são entregues juntos e conservam bytes/contrato. Manter propriedades privadas atuais e implantação anterior. O endpoint continua o mesmo leitor; o conector escolhe a nova rota. Não substituir fontes oficiais.
5. Na cópia: ds106 e ds107 → ABC_abc, ds109 → ABC_resumo, ds110 → ABC_juntos. Preservar cada alias, os catálogos distintos observados, filtros e campos locais. Comparar 01–03/11, 02/11, 30/11 vazio, 01/01–15/11/2026 e período acumulado autorizado. Comparar com SQL no **corte definitivo atual**; 216/331/17.675,89 e 90/134/4.753,02 eram referências do piloto, não metas artificiais do histórico ampliado. Período vazio na ABC/pares tem zero linhas; resumo vazio mantém uma linha com zero produtos/receita e classes indisponíveis, conforme núcleo legado.
6. Conferir demais fontes e as cinco mesclagens (inclusive as duas sem gráficos), os 37 aliases, campos/substituições, 75 componentes, oito controles e 14 filtros. Para somas opcionais, começar numa fonte privada específica e comparar o mesmo gráfico em detalhe e somas com filtros idênticos; não aplicar em fontes com dependências de grão individual/Record Count. Não migrar ds136.
7. Registrar horários America/Belem, SHA do leitor e da implantação, versão READY, parâmetros, duração, número de linhas de saída, resultados e divergências sanitizadas. Somente os testes na cópia liberam a decisão posterior sobre o relatório oficial; esta tarefa não faz a troca.

**Reversão:** restaurar a imagem anterior apenas do leitor FARMA e a implantação anterior do conector na cópia. O leitor anterior não tem `/v1/abc`, portanto os dois componentes devem voltar juntos. Voltar `modo_consulta` a `detalhe` onde tiver sido testado. Não executar rollback de fatos, admin, reenvio, nova exportação, nova coleta ou novo fechamento: a revisão READY e os 2.775 recibos / 2.750.730 registros informados pelo Work são preservados.

## Complemento: vendas sem itens e Top de pares

Ver [diagnóstico privado, escopo explícito de volume e roteiro do Work](DIAGNOSTICO%20VENDAS%20SEM%20ITENS%20E%20TOP%20PARES.md). Preservados publicador, READY, contratos, aliases e ds136. A investigação dos 204 casos exige comparar o corte original confirmado com os fatos; o diagnóstico não aplica recuperação. O modo COMPLETO de compras juntas continua padrão, e Top exige escolha explícita na cópia.
