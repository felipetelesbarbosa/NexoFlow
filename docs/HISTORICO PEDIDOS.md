# Histórico paginado de pedidos e LTV observado

Contrato recebido: `GET /api/Delivery/pedidos/{segmento}`, parâmetros `dataInicio`, `dataFim`, `pagina`, `limite` e token privado em query. O cliente utiliza a rota direta/proxy já selecionada e recusa redirecionamentos. FARMA e PET possuem estado, cadastros, contatos e destinos separados.

## Executar no Windows

Abra o NexoFlow Terminal, selecione o segmento e use a opção **10** ou os comandos abaixo. A identidade de segmento é fixada antes dos imports. Não trocar perfil dentro do processo.

```text
nexo historico --inicio 2026-11-01 --fim 2026-11-06 --limite 500 --max-paginas 2
nexo historico --inicio 2026-11-01 --fim 2026-11-06 --limite 500
nexo historico --modo incremental --limite 1000
nexo historico --inicio 2026-10-01 --fim 2026-10-31 --modo reconciliacao --reiniciar-janela
nexo historico --somente-resumo
```

O segundo comando retoma o primeiro. Uma página: `--max-paginas 1`. Todas: omitir esse parâmetro (orçamento operacional de 10.000 páginas por execução, não máximo da API). Trocar o limite cria um cursor novo pela página 1, mantendo a deduplicação dos fatos existentes. Não há teto arbitrário de 100 ou 1.000 pedidos na API; o parâmetro respeita int32 positivo.

Faixas longas são divididas em janelas de até 31 dias entre extremos, compartilhando a fronteira. A amostra não prova inclusividade de `dataFim`: não se soma um dia automaticamente ao pedido do operador. Datas sem offset são interpretadas em America/Belem pela convenção operacional, nunca UTC. A extração pode concluir todos os IDs declarados e ainda apresentar `LIMITES_DA_API_NAO_HOMOLOGADOS`. Isso não equivale a cobertura temporal completa.

A coleta incremental consulta hoje até D−20, inclusive no calendário solicitado, e retoma primeiro janelas incompletas. A importação histórica não ativa Recompra nem atualiza contatos, campos ou grupos Weni. O vínculo Weni é uma leitura, não criação/fusão de contato. A consulta geral cadastral e a listagem Weni são indexadas uma vez nessa fase; não há GET individual por pedido/CPF.

Analytics incorpora os fatos locais já importados, deduplicando pela chave oficial existente. Uma confirmação mais recente da API tem precedência sobre o cache histórico antigo. Para habilitar também a **coleta automática recente**, configure no perfil privado:

```python
FARMALIDER_HISTORY_ENABLED = True
FARMALIDER_HISTORY_PAGE_LIMIT = 500
FARMALIDER_HISTORY_MAX_PAGES = 100
```

No PET, as opções pertencem a `PERFIS["PET"]`. O padrão é desativado, até homologar acesso à nova rota. O Noturno herda a opção pelo Analytics; não executa backfill completo. Não há alteração nos mecanismos de revisão/aplicação da Recompra.

## Identidade e valores

A chave financeira é segmento + pedido oficial; o cliente é `capa.codCliente`. Compra oficial sem Weni continua no histórico e no LTV. O cadastro geral fornece CPF/nome/telefone/e-mail pelo mesmo ID oficial. CPF válido exige contato único e cliente oficial não ambíguo. CPF inválido preenchido exige **nome completo normalizado e telefone, ou nome completo e e-mail**, além de CPF concordante. Não se corrige CPF, não se acrescenta nono dígito e não se escolhe um contato ambíguo. CPF vazio/zerado/malformado não autoriza vínculo.

Pedidos status 3 ou pagamento 0 são cancelados mesmo se houver pagamento de outro código. Estados documentados não cancelados seguem as regras existentes. Itens ausentes/malformados são pendência; lista explicitamente vazia, com cabeçalho comprovado, exclui venda. Itens com mesmo SKU e IDs distintos permanecem distintos.

Base financeira: soma de totais de itens conciliados + frete oficial, contado uma vez. Lançamento código zero/descrição vazia é frete apenas com soma igual ao cabeçalho. Dinheiro usa Decimal e centavos. Desconto não zero, total de item incompatível com quantidade×unitário, precisão não sustentada ou total explícito divergente ficam pendentes. Nenhum desconto é aplicado duas vezes. A amostra não comprova liquidação, estorno ou devolução; o indicador chama-se **faturamento observado**, não valor pago.

LTV = soma de compras válidas únicas por segmento/cliente oficial em toda a base observada; ticket = LTV / compras. O filtro mensal de receita não limita LTV. Histórico parcial não comprova aquisição de cliente novo. Atualização inválida/omissão preserva o fato anterior e registra pendência. Um fechamento com mais de 20 dias só muda via `--modo reconciliacao`; uma compra antiga inédita pode ser importada.

O modelo Meta anterior informa último toque observado sem janela causal. Pedidos desta fonte ficam fora dessa atribuição automática. A função pura `attribute_history` aceita somente vínculo/segmento/evento oficial anterior e janela explicitamente homologada; ainda não há janela comercial configurada. Não inventar anúncio nem atribuir a uma interação posterior.

## Planilhas e Data Studio

A preparação só lê os três destinos autorizados pelo mapa/configuração de cada perfil; não cria arquivos nem muda suas pastas.

```text
nexo historico --planilhas preparar --revisao logs\privado\historico_revisao.json
nexo historico --planilhas aplicar --revisao logs\privado\historico_revisao.json
```

Homologue primeiro com três planilhas **de teste** configuradas em uma instalação de teste, não nas planilhas comerciais. Nenhuma escrita real foi executada durante o desenvolvimento. A aplicação exige revisão com os mesmos dados, IDs, schemas e snapshots. Pedido ativo remoto ausente da base local bloqueia a aplicação para reconciliação. Backup privado antecede cada lote; respostas são relidas. Falha parcial exige preparar novamente e aplicar o restante, sem duplicação. Linhas substituídas permanecem com `vigente=Não`; filtros usam `vigente=Sim`.

| Arquivo | Abas novas | Grão |
|---|---|---|
| Histórico | `Historico_Pedidos`, `Historico_Itens` | pedido; item oficial por pedido |
| Dashboard | `BI_LTV_Clientes`, `BI_Cobertura_Historica` | cliente oficial; janela de extração |

IDs de pedido/cliente/contato são texto. A tabela de pedidos informa estado, motivo, origem, política financeira, vínculo Weni, produtos, frete e faturamento. LTV informa compras, primeira/última compra e cobertura observada. As abas preexistentes não mudam de cabeçalho. A fonte do Data Studio deve usar data do pedido para receita mensal e a tabela LTV independente do filtro mensal. Nenhum dashboard foi editado neste desenvolvimento.

## Persistência, falhas e rollback

São tabelas aditivas no `clientes_observados.sqlite` privado de cada segmento: `history_orders`, `history_windows`, `history_seen`, `history_issues`, `history_revisions`. Fatos, itens normalizados (JSON mínimo) e cursor da página fazem commit juntos. O banco não recebe endereço, observações ou rastreio. O histórico recebido comercial nunca entra no Git, CI ou pacote.

Página repetida, vazia prematuramente, total instável, IDs faltantes, falha de rede ou orçamento esgotado conservam cobertura incompleta. Para totais instáveis, repetir com `--reiniciar-janela` em período estabilizado. A contagem de completude usa IDs recebidos **antes** das exclusões comerciais.

Rollback Windows: fechar as rotinas, fazer backup privado do SQLite e dos arquivos de revisão, desativar a coleta automática e retornar ao pacote anterior preservando dados. A versão anterior ignora as tabelas novas; não executar DROP. Para Sheets, restaurar somente as linhas do lote a partir do backup privado, após conferir IDs/segmento e alterações posteriores. Não restaurar uma planilha inteira sobre mudanças alheias.

## Evidência e limites

A análise local da amostra PET classificou 40 pedidos válidos e 12 cancelados, sem pendências financeiras. Confirmou 52 IDs, 73 itens, status 2/1/3 em 33/7/12 pedidos; todos os cancelados tinham pagamento diferente de zero. Dados não foram copiados para fixtures. Múltiplas páginas, identidade, valores, falhas e retomada são testados com dados sintéticos. Rotas reais em ambas as redes, dados FARMA, inclusividade da data final e semântica de descontos permanecem para homologação autorizada.
