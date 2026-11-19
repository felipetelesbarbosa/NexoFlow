# Implantação do leitor FARMA no Data Studio oficial

O [guia de operação Windows, VPS e Looker](OPERACAO_WINDOWS_VPS.md) registra o estado comercial a partir de 19/11/2026. As configurações da tabela inicial, as pendências descritas no ensaio e os comandos abaixo documentam a preparação de 18/11. Confira o guia vigente e os vínculos atuais antes de reaplicar qualquer etapa.

## Configuração conferida na VPS

| Item | Leitor oficial observado | Leitor de teste |
|---|---|---|
| SHA da imagem | `e5eaeade106b8fa36a0fbac8eaff07890370f6a7` | `c992b5dba57f5e84bfa9cf27cbe7a8b2423967ac` |
| Limite HTTP do Uvicorn | 8 | 48 |
| Conexões ao PostgreSQL | Conferir configuração e papel antes da transição | 4 no processo leitor. O papel aceita 6 no total. |
| Paralelismo SQL | Sem desativação pelo ambiente do leitor | `PGOPTIONS="-c max_parallel_workers_per_gather=0"` nas sessões do leitor |
| Portas publicadas | Nenhuma | Nenhuma |

O teste de abertura conjunta da ABC encontrou 14 rejeições de concorrência em uma janela com limite HTTP 16. Com 48, o dia e o período anual abriram na cópia. A revisão ativa era a FARMA READY v2, identificada no recibo operacional privado. A falha `53100` observada no ensaio anterior vinha da alocação de memória dinâmica em `/dev/shm` nas consultas paralelas, com espaço livre no disco do host. O ajuste em `PGOPTIONS` evita essa alocação paralela no processo leitor. O overlay conserva o dimensionamento de memória do contêiner, o PostgreSQL global, o limite do papel e a rede privada existentes.

O limite HTTP e o limite de conexões SQL controlam recursos diferentes. O Compose usa um processo Uvicorn, com quatro conexões ao banco no código. Evite carregar o leitor de teste e o oficial ao mesmo tempo. Os dois compartilham o papel FARMA. Antes de recriar o leitor, confirme a capacidade disponível desse papel, inclusive consultas administrativas e ensaios. Use a configuração real do túnel e as credenciais montadas de leitura.

## Sequência de implantação

1. Homologue a imagem e os quatro arquivos de `connectors/datastudio_api` do SHA escolhido. Integre também as alterações da `main` da release Windows 1.5.44, incluindo a publicação Weni Flows v2. Em 18/11, a integração de `028d93b` com `c992b5d` passou em 177 testes da suíte Data Studio com PostgreSQL descartável (dois cenários ignorados) e em 146 testes Node. Registre a versão do Apps Script e associe-a ao SHA. O ensaio do Work usou a implantação privada QA14. A versão oficial deve usar a rota padrão autenticada do código versionado. Não associe o relatório oficial a uma implantação de teste editável.
2. Confira as 37 fontes, cinco mesclagens, filtros e cálculos da cópia. Registre versão, revisão, destino, janela, resultado e IDs de origem e de destino. Preserve as ligações e a implantação anteriores para reversão. A validação da fonte `ds136` tem aceite próprio abaixo.
3. No diretório real `/opt/nexoflow/datastudio/producao`, use os dois arquivos Compose observados. Acrescente por último [o overlay do leitor FARMA](../integrations/datastudio/compose.farma-reader-tuning.yaml). Ele seleciona a imagem somente do serviço leitor. Confira a versão instalada do Compose, as configurações renderizadas e a imagem local antes de subir um contêiner.

   ```bash
   cd /opt/nexoflow/datastudio/producao
   base=(docker compose -p nexoflow-datastudio-farma-prod -f compose.yaml -f compose.tunnel.yaml)
   anterior="$("${base[@]}" ps -q datastudio-farma-read)"
   docker inspect --format '{{.Image}} {{index .Config.Labels "org.opencontainers.image.revision"}}' "$anterior"

   : "${NEXOFLOW_FARMA_READER_IMAGE:?Defina a tag local da imagem conferida}"
   : "${NEXOFLOW_FARMA_READER_OVERLAY:?Defina o caminho do overlay conferido}"
   docker image inspect --format '{{.Id}} {{index .Config.Labels "org.opencontainers.image.revision"}}' "$NEXOFLOW_FARMA_READER_IMAGE"
   candidato=("${base[@]}" -f "$NEXOFLOW_FARMA_READER_OVERLAY")
   "${candidato[@]}" config --quiet
   ```

   Compare os modelos efetivos em sessão privada. A renderização dos dois arquivos reais com e sem o overlay foi feita na VPS em 18/11. A comparação dos modelos confirmou alterações apenas na imagem, no comando e em `PGOPTIONS` de `datastudio-farma-read`. Nenhum contêiner foi recriado nessa simulação. Preserve opções adicionais existentes na configuração de leitura quando aplicável e repita o teste de carga. Registre os hashes dos arquivos base e do overlay sem copiar os valores de segredos.
4. Após o aceite da cópia, faça a troca do leitor na janela operacional. Use `"${candidato[@]}" up -d --no-deps --pull never datastudio-farma-read`. Confira o estado saudável, a imagem efetiva, a rota padrão pelo conector, FARMA/produção, revisão ativa, zero rejeições HTTP e ausência de `53100`. Acompanhe tempo de resposta, CPU e memória. Mantenha o publicador e o banco no projeto existente.
5. Troque as fontes no relatório oficial em grupos de páginas. Após cada grupo, valide os filtros, moeda, totais e mesclagens pelo endereço oficial. Pare e reverta o grupo se houver leitura incompleta, fonte inacessível, divergência de chaves ou erro de prazo.

## Controles de aceite

| Caso | Resultado esperado ou observado na cópia |
|---|---|
| Evolução histórica e financeira | As quatro exportações da cópia coincidiram com o PostgreSQL. Comparar novamente compras válidas e faturamento com o recibo privado. |
| ABC em 09/11/2026 | Conferir SKUs, unidades, receita de produtos e classes. O filtro B limita o ranking e preserva o total geral do período. |
| ABC de 01/01 a 15/11/2026 | Conferir SKUs, unidades e receita. A ordem e a frequência dos 25 primeiros pares coincidiram com a VPS. |
| ABC em 16 e 17/11/2026 | O primeiro ensaio exibiu `DS_PRAZO_CONSULTA` em parte dos gráficos. No reteste de 18/11, o resumo abriu com zero SKUs e R$ 0,00. O ranking e pares ficaram vazios e as classes exibiram “Não há dados”. Repetir a abertura conjunta pela rota oficial. |
| Produtos mais vendidos | Os sete componentes foram vinculados à fonte privada integrada. Os dois Top 5 coincidiram posição a posição em receita e unidades no dia e no anual. O filtro de um único produto preservou os totais filtrados e exibiu 100% de participação. No vazio, os cartões zeraram e os rankings ficaram vazios, sem erro. |
| Meus clientes | O ranking e os cartões de compradores, receita média e pedidos por comprador coincidiram com o controle privado de 09 a 12/11. Selecionar um comprador pelo nome reduziu o ranking a uma linha e conciliou os três cartões com os valores desse comprador. |
| Pedidos por cliente | O detalhe exibiu a mesclagem PostgreSQL com as dimensões originais e valores em BRL. O seletor de detalhe precisou usar a mesma mesclagem da tabela. Após o remapeamento, a busca por nome restringiu os produtos ao comprador selecionado de 09 a 12/11. |
| Resumo e Vendas | Entre 09 e 12/11, comparar pedidos, unidades e faturamento com frete com o recibo privado. Conferir moeda em BRL e preservar filtros. |
| Pedidos dos anúncios | Tabela e seletor na cópia usam a mesclagem QA14 por `pedido_apos_anuncio = pedido_id`, com coorte automática do primeiro anúncio à esquerda e o cabeçalho elegível à direita. Preserve `pedido_id` no resultado e exclua cabeçalhos nulos nos dois componentes. Os três pedidos da referência privada, o filtro de um pedido, a compra posterior ao primeiro anúncio e o intervalo vazio passaram. O período deve continuar selecionando a coorte. |
| Mesclagens, público e anúncios | Conferir chaves, cardinalidade, filtros, custos, atribuição FARMA e LTV por cliente. Comparar agregados no mesmo período e mesma revisão. |

Para um 503, registre a janela, o gráfico e o erro sanitizado. Compare os logs do leitor, do proxy e do PostgreSQL no mesmo horário. Conte recusas de conexão do papel, `Exceeded concurrency limit` e `53100` separadamente. Ao ver `DS_PRAZO_CONSULTA`, compare o tempo na API com o tempo do conector e refaça o cenário com a página inteira. O teste de 18/11 mediu o `jit` no resumo vazio em sessões de diagnóstico. O resultado com `jit=off` foi de 6,4–7,1 s e com `jit=on` de 8,5–8,7 s. O overlay leva apenas a configuração homologada de paralelismo e limites. Preserve o prazo e as guardas do conector.

## Pendências de Público e do painel Anúncios

- **Público.** Na cópia, o Looker exibiu erro de sistema nos gráficos após a troca, inclusive no ensaio do leitor ajustado. Os 12 componentes de `BI_Publico` voltaram às ligações anteriores. A consulta direta à API retornou HTTP 200 para as duas projeções integrais da READY v2. A métrica de compra identificada de `BI_Publico` soma marcações dos contatos. A mesclagem de compradores operacionais conta contatos com pedido elegível. Reconcilie os dois critérios separadamente antes de validar uma nova projeção dos cartões e filtros.
- **Painel principal de Anúncios.** No período de 01 a 18/11, a cópia e a consulta de `BI_Meta_Resultados` classificada como FARMA em BRL divergiram em anúncios, investimento e conversas. O painel segue na fonte anterior. Confira a população e os filtros herdados antes de promover as métricas do painel. A página Pedidos dos anúncios tem validação própria por coorte.

## Fonte Weni ds136

A instalação de homologação confirmou seis recibos e zero recibos novos no reenvio. Em 18/11, os quatro totais da cópia coincidiram com as seis datas consultadas pelo papel leitor de homologação. Na mesma inspeção, a visão `farma.ds_bi_weni_conversas_diarias` ainda estava ausente no banco comercial. O aceite de produção exige a visão e o papel leitor conferidos no banco correspondente, projeto FARMA e fuso `America/Belem`, e cobertura diária comprovada. Confira o período editável do relatório antes de trocar a fonte. A janela de 01 a 06/11 é o controle inicial de conversas, resolvidas, não resolvidas e transferidas. O roteiro comercial existente descreve a instalação de homologação e as guardas de cobertura. [Guia Weni](CONVERSAS%20DIARIAS%20WENI.md)

## Reversão

Reassocie os componentes do grupo ao mapeamento anterior. Para reverter o leitor, confira que os dois arquivos Compose base ainda apontam à imagem registrada antes da troca e execute `"${base[@]}" up -d --no-deps --pull never datastudio-farma-read`. Reconfira o SHA, a rota de leitura e a revisão ativa. Preserve a definição anterior do conector, os recibos, os fatos e os backups. Evite recriar o projeto inteiro, reiniciar o PostgreSQL ou usar comandos de limpeza de volumes para reverter esta mudança.

## Reteste das três pendências na cópia

A integração parte do roteiro `6b19dd8` e da main da distribuição 1.5.44. Use o SHA desta revisão para a imagem de teste e os quatro arquivos de `connectors/datastudio_api`. Mantenha o overlay e a capacidade de conexão conferidos acima, assim como a versão vigente do publicador, exceto se o publicador do ambiente de teste ainda precisar do suporte a `WENI_FLOWS_V2`. Os testes de uma fonte usam o mesmo ambiente, revisão, período e filtros nas duas leituras.

### Público · ds82 e compradores operacionais

A consulta de detalhe retorna um registro por contato. O ensaio de `BI_Publico_Resumo` devolve agrupamentos conjuntos por `cidade`, `canal`, `idade` e `idade_informada`. Cada linha traz contagens aditivas para população, compra identificada, ausência de compra identificada, idade informada e cidade ausente. O conector preserva as dimensões necessárias aos filtros locais. A diferença de volume pode ser comparada com a contagem e os tempos registrados pelo diagnóstico `publico_farma` nas execuções do Apps Script. O log contém somente contagens de campos/linhas/filtros e tempos. Registre também o código do gráfico e a hora de execução no Looker. A causa interna do erro de sistema depende dessa comparação na cópia.

No banco usado pelo leitor de homologação, com o DSN administrativo vinculado ao ambiente e os papéis FARMA já provisionados, instale a visão com a revisão READY ativa.

```bash
: "${REDE_PG:?Rede privada do ambiente de teste}"
: "${DSN_ADMIN:?Arquivo privado de DSN do banco de teste}"
: "${IMAGEM_FARMA_TESTE:?Imagem do SHA validado}"
: "${READY_TESTE:?UUID da READY ativa no banco de teste}"
docker run --rm --network "$REDE_PG" -v "$DSN_ADMIN:/run/secrets/admin-dsn:ro" \
  "$IMAGEM_FARMA_TESTE" python -m integrations.datastudio.admin \
  --dsn-file /run/secrets/admin-dsn --ambiente homologacao --segmento FARMA \
  --instalar-publico-farma "$READY_TESTE"
```

Na cópia, duplique a página e configure a tabela lógica `BI_Publico_Resumo`. Cada contato da publicação corresponde a uma chave única na origem. Os campos de contagem da visão são somáveis. Preserve o rótulo `Não informado` no controle de cidade e conte esse rótulo no cartão de cidade ausente, junto com valores nulos ou vazios após `TRIM`. A coluna de contatos sem compra é o total menos a soma das marcações, como no relatório anterior, inclusive para uma marcação vazia.

| Componente | ID na cópia | Campo ou expressão na fonte resumida |
| --- | --- | --- |
| Contatos na base | `cd-q2trpqu27d` | `SUM(contatos)` |
| Contatos com compra identificada | `cd-tefmjqea8d` | `SUM(compra_identificada)` |
| Sem compra identificada | `cd-jw98usea8d` | `SUM(sem_compra_identificada)` |
| Contatos que já compraram (%) | `cd-4nddr8ea8d` | `SUM(compra_identificada) / SUM(contatos)`, com denominador zero retornando nulo |
| Contatos com idade informada | `cd-8qltwe6d8d` | `SUM(contatos_idade_informada)`, com `idade_informada = 1` |
| Contatos sem cidade | `cd-2g1cap6d8d` | `SUM(contatos_sem_cidade)` |
| Tabela por canal | `cd-0vau7zw67d` | `canal`, contatos, compra identificada, razão entre somas por canal e percentual de contatos no total filtrado |
| Tabela por faixa etária | `cd-57m5b7w67d` | Faixa etária, `SUM(contatos_idade_informada)`, com `idade_informada = 1` |
| Tabela por cidade | `cd-cj7ofn6d8d` | `cidade`, `SUM(contatos)` e **Porcentagem do total** sobre essa soma |
| Controle Cidade | `cd-golewrna8d` | `cidade` com `SUM(contatos)` |
| Controle Canal de contato | `cd-1108funa8d` | `canal` com `SUM(contatos)` |
| Controle Faixa etária | `cd-61m1qioa8d` | Faixa etária com `SUM(contatos)` |

Copie do editor a expressão e os rótulos de **Faixa etária** usando a dimensão `idade`. Confirme a ordenação anterior dos controles. Compare sem filtro, cada controle isolado e os três combinados, inclusive faixa sem resultado. A visão é um resumo atual da READY, sem dimensão de período. [Inventário da página Público](inventarios/FARMA_DATA_STUDIO_2026-11-12.md#9-base-de-clientes)

- **BI_Publico.** No corte conferido na cópia, os seis cartões mostraram **48.843 contatos**, **30.939 com compra identificada**, **17.904 sem a marcação**, **63,34% com compra**, **2.184 com idade informada** e **6.174 sem cidade**. Compare esses controles com a visão PostgreSQL e a fonte anterior. Registre número de grupos e latência.
- **Compras elegíveis.** Em inspeção SQL privada, conte `DISTINCT p.contact_uuid` de `farma.ds_pedidos_farmalider p` com `p.calc_gf73fvq57d='Sim'` e com correspondência em `farma.nf_atuais` na tabela `Base_Contatos` por `registro->>'contact_uuid'`. Compare **28.868 contatos** no corte da READY v2, deduplicando vários pedidos do mesmo contato. Preserve a mesclagem `ds74 LEFT ds72`, seus filtros e a presença dos contatos sem pedido. Compare o seu valor separadamente da soma de marcações de `BI_Publico`.

### Painel principal de Anúncios · ds133

No recorte inclusivo **01 a 18/11/2026**, o Work isolou toda a diferença em um único ID. Os outros dois coincidiram por anúncio, em investimento e conversas. O ID que falta na tabela da cópia está em ambas as bases, Google Planilhas e PostgreSQL, classificado como FARMA e vinculado ao Delivery FarmaLíder. O controle PostgreSQL delimita `segmento='FARMA'`, `classificacao='FARMA'` e `moeda='BRL'`. O detalhe por ID foi conferido pelo Work e fica na evidência privada.

O relatório está sem filtro global. O filtro de página **Delivery FarmaLíder | Campanhas verificadas** pertence à fonte de validação PostgreSQL. No editor, as duas condições INCLUDE unidas por AND aparecem com campos ausentes e valores em branco. Investimento, Pedidos, Receita, CPA e a tabela ainda usam Google Planilhas, com **Herdar filtros** desligado e sem filtros locais. A tabela indica **Filtro inválido**. Conversas e ROAS herdam filtros e também têm o filtro local `classificacao = FARMA`. O aviso de filtro inválido precisa ser resolvido, mas ainda falta evidência de que ele exclui esse ID.

A coluna `conversas_iniciadas_meta` vem da Meta. A coluna `conversas` mede conversas Weni com evidência própria. O controle por ID soma `conversas_iniciadas_meta`. Compare o grão e os filtros efetivos de cada cartão antes de interpretar a diferença.

Exporte da cópia as duas linhas agregadas, com ID textual e centavos inteiros, num JSON privado com uma linha por anúncio. Use `null` para valor indisponível. Confirme se custo e conversas usam filtros equivalentes. Se os filtros diferirem, faça os controles em duas tabelas de ensaio, uma com o filtro efetivo de cada cartão. Estrutura da entrada `copia.json` com valores fictícios:

```json
[
  {"anuncio_id": "001", "investimento_centavos": 250, "conversas_meta": 3}
]
```

No leitor FARMA com acesso administrativo privado somente para esta inspeção, compare a mesma janela do recorte observado. O processo inicia uma transação de leitura, confere a READY e lista grupos por anúncio, conta, classificação, moeda, fuso e política. O resumo indica presença em cada lado e a diferença por ID. Ele preserva ausência de custo e recusa grão ambíguo. O catálogo de campanhas é cruzado pela chave diária. A saída é privada e não inclui registros de contatos.

```bash
: "${READY_FARMA:?UUID da READY comercial observada na cópia}"
: "${CORTE_ADS_PRIVADO:?Caminho absoluto do JSON privado da cópia}"
: "${DSN_ADMIN_PROD:?Arquivo privado do DSN do banco comercial}"
docker run --rm --network "$REDE_PG" \
  -v "$DSN_ADMIN_PROD:/run/secrets/admin-dsn:ro" \
  -v "$CORTE_ADS_PRIVADO:/run/evidence/copia.json:ro" \
  "$IMAGEM_FARMA_TESTE" python -m integrations.datastudio.ads_panel_audit \
  --dsn-file /run/secrets/admin-dsn --ambiente producao --revisao "$READY_FARMA" \
  --inicio 2026-11-01 --fim 2026-11-18 --copia /run/evidence/copia.json
```

Na cópia, isole a exclusão com uma variável por vez.

1. Em uma página só de teste, coloque uma tabela com a **mesma fonte Google Planilhas**, período fixo inclusivo de **01 a 18/11/2026**, dimensão de período `data`, ID textual e data como dimensões. Use as somas de `investimento_atribuivel` e `conversas_iniciadas_meta`. Comece sem filtros herdados e separe o anúncio com um filtro local pelo ID exato. Abra a tabela antes e depois de atualizar os dados. Compare o resultado com as linhas da aba para as mesmas datas.
2. Se o ID continuar ausente, confira o arquivo, a aba, o intervalo efetivo de células, a atualização dos dados, o tipo do ID e as datas dessas linhas. Teste uma nova conexão de validação com toda a aba, preservando a conexão anterior. Registre qual ajuste faz aparecer **R$ 22,35 e 8 conversas**.
3. Se o ID aparecer na tabela neutra, reintroduza separadamente a dimensão **Campanha**, a ordenação, a paginação e os filtros efetivos. Antes de reconstruir o filtro de página, obtenha os IDs dos campos e valores das duas cláusulas de uma fonte funcional. Aplique as condições comprovadas em uma tabela de teste e valide o efeito também nos cartões que herdam filtros.
4. Refaça a comparação por ID e por componente. O universo FARMA/BRL do PostgreSQL tem **3 anúncios, R$ 251,02 e 70 conversas**. A cópia apresentou **2 anúncios, R$ 228,67 e 62 conversas**. A fonte candidata deve reproduzir o universo pretendido com filtros válidos e a exclusão explicada antes da troca de `ds133`.

### Weni · instalação idempotente e cobertura

Na inspeção do relatório oficial, a `ds136` tinha **zero gráficos e zero variáveis vinculados**. Nenhum componente vinculado exige uma data mínima. A primeira data disponível na aba é **01/11/2026**. Os seis dias usados como referência vieram de uma extração do **Weni Insights**. O produtor histórico da aba segue sem confirmação.

A origem para novos dias é **Flows v2 do Delivery FarmaLíder**, com o UUID do projeto Insights e a identificação separada do workspace Flows. O operador validou a leitura de 01/11 no Windows. Homologue a fonte num componente temporário da cópia a partir de 01/11. Se houver um novo uso no relatório, confira a cobertura do recorte desse componente antes de vinculá-lo. Preserve a aba original como evidência.

Execute o mesmo instalador de visão **duas vezes** com o UUID privado já conferido. Primeiro, faça isso no banco de homologação. Para produção, use exclusivamente o DSN e o argumento `--ambiente producao` correspondentes ao banco comercial e registre a autorização da janela. O comando vincula o projeto e instala a visão com oito campos. As métricas são publicadas separadamente pelo Windows com credencial do destino correspondente.

```bash
: "${PROJETO_FARMA:?UUID do projeto Weni já conferido}"
docker run --rm --network "$REDE_PG" -v "$DSN_ADMIN:/run/secrets/admin-dsn:ro" \
  "$IMAGEM_FARMA_TESTE" python -m integrations.datastudio.admin \
  --dsn-file /run/secrets/admin-dsn --ambiente homologacao --segmento FARMA \
  --instalar-conversas-projeto "$PROJETO_FARMA"
```

No Windows de homologação, siga os comandos de coleta e publicação do [guia Weni](CONVERSAS%20DIARIAS%20WENI.md). Confira os dias pendentes do cache para o destino antes de publicar. O comando `publicar` envia todos os dias ainda sem recibo desse projeto nesse destino. Após os seis dias, repita o comando e confirme zero recibos novos. Na API leitora, solicite `data`, `segmento`, as quatro métricas, `origem` e `fuso` de 01 a 06/11. Confira as seis datas uma vez cada, FARMA, `WENI_FLOWS_V2` para o coletor atual, `America/Belem` e **2.002 / 465 / 316 / 1.221**. A ausência da visão retorna `DS_INSIGHTS_VISAO_AUSENTE`. Uma lacuna ou duplicidade de datas no recorte retorna `DS_INSIGHTS_COBERTURA_INCOMPLETA`. Confira a ausência de lacunas em todo o período efetivo do relatório antes de trocar a fonte.

Para reverter o ensaio, volte as fontes dos componentes na cópia e restaure a implantação/conector anteriores. O leitor pode voltar à imagem registrada com o Compose base da seção Reversão. As duas visões aditivas e os recibos ficam disponíveis para conferência futura.
