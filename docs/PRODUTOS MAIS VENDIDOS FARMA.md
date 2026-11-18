# Produtos mais vendidos no Looker Studio

A fonte privada `Produtos_Mais_Vendidos` lê os itens das vendas FARMA pela visão `farma.ds_bi_itens`. O leitor e o conector devem conter a rota `POST /v1/produtos` e o respectivo esquema. O controle de período existente fornece as duas datas. Configure uma única instância da fonte nos sete componentes de dados da cópia para que o mesmo seletor de nome atue em todos.

| Componente | Campos e configuração |
|---|---|
| Top 5 por receita · `cd-zbyb8f427d` | Use o código do produto como chave de agrupamento e o nome como rótulo. Exiba receita, unidades e `participacao_acumulada` como percentual com duas casas e agregação MAX. Remova as operações de comparação e soma em execução do gráfico. Ordene por `posicao_receita_top5` crescente. |
| Top 5 por unidades · `cd-dh5fz9k67d` | Use a mesma chave e rótulo, com unidades, receita e ordenação crescente por `posicao_unidades_top5`. |
| Ranking paginado · `cd-mli8wgga8d` | Mantenha 10 linhas por página. Agrupe por `produto_codigo`, exiba `produto_nome`, `receita_item` e `quantidade`. Ordene por receita decrescente e depois pelo código crescente. |
| Cartão de produtos · `cd-uqdlxzma8d` | `produtos_distintos_periodo` com MAX. O leitor conta códigos diferentes com SKU informado no período e na seleção. |
| Cartão de receita · `cd-tyy2h1ma8d` | `receita_item` com SUM e formato BRL. |
| Cartão de unidades · `cd-36qnu1ma8d` | `quantidade` com SUM. |
| Seletor de nome · `cd-2zpk2p3b8d` | Dimensão `produto_nome`, métrica `registros` com SUM. A lista conta linhas de itens de cada grafia. Pesquise na lista e marque uma ou mais opções. |

Preserve os rótulos, a paginação e o período padrão já configurados na cópia. O campo `periodo_inicio` identifica o início do intervalo usado na agregação. O controle de datas `cd-5jxb8f427d` atua pelo intervalo da requisição. O conector escolhe a consulta pelos campos pedidos. A posição ou o percentual identifica o Top 5 de receita, a posição por unidades identifica o outro Top 5, e o código sem esses campos identifica o ranking completo.

## Cálculo e limites

A seleção por nome compara a grafia exata nos itens físicos antes de agrupá-los por código. Um SKU com vários nomes exibe o maior nome dentro da seleção, sob ordenação binária. Dois SKUs com o mesmo nome continuam distintos. O Top de receita desempata por código crescente. O Top de unidades desempata por receita decrescente e depois por código crescente. A participação de cada posição divide a receita acumulada até essa linha pela receita de todos os SKUs selecionados. Se o total for zero, a participação fica nula.

Cada resposta usa a READY da sua própria transação de leitura. No mesmo processo, componentes com a mesma publicação, visibilidade PostgreSQL, intervalo e filtro podem reutilizar uma agregação completa. Com nomes ou revisão diferentes, o leitor recalcula. A lista completa obedece a 50 mil registros e 7 MB por resposta. Um Top 5 ou um cartão pode caber mesmo que o ranking completo exceda esses limites. O leitor devolve erro para chaves de item repetidas, valores inválidos, tempo excedido e respostas grandes demais.

## Conferência na cópia

1. Em 09/11/2026, compare os três cartões com o recibo privado da READY. Confira a ordem, as unidades, os valores e o percentual nas cinco linhas. Calcule a participação na posição cinco dividindo a soma dessas cinco receitas pela receita do cartão. Use o denominador integral antes de arredondar a exibição.
2. Marque apenas o primeiro produto no seletor. Compare receita e unidades filtradas com seus itens. Se o nome corresponder a apenas um SKU com receita positiva, a tabela deve mostrar uma linha e 100%. Limpe o filtro e confira os totais originais.
3. De 01/01 a 15/11/2026, compare também a contagem dos SKUs e os dois rankings com a leitura da mesma READY. Em um intervalo vazio, os cartões devem exibir zero e as tabelas e a lista devem voltar vazias.
4. Registre na homologação privada da cópia a revisão, o intervalo, os filtros e os controles agregados. A troca no relatório oficial é uma etapa posterior.
