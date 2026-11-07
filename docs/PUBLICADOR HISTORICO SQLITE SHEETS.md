# Histórico SQLite → Sheets → Data Studio: homologação FARMA

Esta implementação é código posterior à release 1.5.20. Não houve alteração de versão, release, relatório publicado, VPS ou planilha comercial. O Work deverá homologar o mesmo SHA em uma instalação isolada com três planilhas **de teste**. Não substituir manualmente módulos em `C:\NexoFlow` operacional. PET somente foi validado com fixtures; a réplica comercial depende da aprovação de FARMA.

## Diagnóstico e arquitetura

Na referência `c94158d35c40d5f9e424731d672de257a7d78ec4`, o publicador abria uma aba física e chamava `_upsert_records_detailed(..., _physical=True)`. O mapa de papéis reconhecia apenas `Historico_Alteracoes` como histórico. Habilitar continuações não corrigia esse caminho. O preparo não reservava a grade global; cada lote de 200 fazia snapshot completo e nova leitura integral. A main foi atualizada para `8c068f5` antes de implementar; sua documentação adicional foi preservada e atualizada.

O publicador agora compartilha `storage_role`, `ContinuationIndex`, `RolloverManager`, lease, criação por intenção durável e os comprovantes oficiais. `Publication` mantém índices de chaves/posições e lotes em SQLite privado, sem lista completa de fatos em memória. Cada tabela é lógica sobre todas as partes. Uma chave antiga continua na parte antiga. Não se copiam fatos para a parte ativa nem se exclui legado.

O preparo só faz GETs no Sheets/Drive. Cria uma cópia privada pelo backup SQLite, incluindo transações WAL confirmadas; abre a evidência em modo somente leitura, `query_only`, verifica integridade, perfil, schema e mistura de segmentos. Não migra o banco original. Confere os três destinos do mapa do perfil, marcadores de origem, edição, pastas, versão do Drive, cabeçalhos, chaves, partes e contagens do manifesto. Contagens de fatos, revisões, pendências, janelas, linhas de itens e compradores ficam na revisão. O snapshot tem SHA-256, tamanho e schema registrados.

A capacidade considera **todas as grades alocadas**, cabeçalhos, padding, expansão aprovada, índice de continuidade e reservas das cinco tabelas no mesmo arquivo. Padrão: margem de 18 milhões, teto configurado de 20 milhões, parte de 500 mil linhas **incluindo cabeçalho**. Um arquivo acima da margem pode usar padding existente sem ampliá-lo. Novas partes recebem arquivos privados pelo mecanismo oficial, na pasta e com acessos permitidos da origem. Ausência de OAuth para criar, origem pública/não comprovada, schema divergente ou falta de espaço bloqueia antes da primeira escrita de fatos. Não truncar, renomear ou apagar abas para liberar espaço.

`historico_publicacao_v2` vincula código do publicador, destinos, manifesto, snapshot, baseline, operações, coordenadas e hashes de lotes. Dados e coordenadas privados não entram no Git ou em artefatos. Revisões antigas são recusadas: não as converter à força. Um legado parcial requer análise dos comprovantes anteriores antes de novo preparo; pedidos remotos ativos ausentes localmente continuam bloqueando inativações.

## Tabelas, chaves e medidas

Os quatro schemas anteriores conservam cabeçalhos e tipos. Somente a quinta tabela é adicionada.

| Tabela lógica | Papel | Chave / grão | Uso |
|---|---|---|---|
| Historico_Pedidos | Histórico | segmento + pedido oficial | estados, emissão, produtos, frete oficial, faturamento observado |
| Historico_Itens | Histórico | segmento + pedido + item oficial | linhas e quantidades; mesmo SKU com IDs diferentes continua distinto |
| BI_LTV_Clientes | Dashboard | segmento + cliente oficial | compras válidas únicas e LTV acumulado, com ou sem Weni |
| BI_Cobertura_Historica | Dashboard | chave original da janela/cursor | recebimentos e estado de extração; não comprova cobertura civil |
| BI_Historico_Resumo | Dashboard | segmento + tipo_recorte + competência | MES, ANO, TOTAL e SEM_EMISSAO; visão rápida anual |

Novo schema: `chave, segmento, tipo_recorte, competencia, periodo_inicio, periodo_fim, pedidos, validos, cancelados, pendentes, outros, clientes, itens, unidades, produtos, frete, faturamento, cobertura, vigente`.

IDs são texto, inclusive zeros à esquerda. Datas usam America/Belem, com conversão do instante quando houver offset e interpretação local quando faltar. Medidas financeiras são calculadas em Decimal/centavos, enviadas como número ao Sheets e reconferidas em centavos. Sheets usa representação numérica própria: qualquer alteração de centavo na releitura impede fechamento. O indicador é faturamento **observado**, não liquidação comprovada.

Filtrar `vigente=Sim`. Receita, produtos e frete consideram estado `valido`. Cancelamento não apaga o pedido: atualiza sua linha e revisa LTV/itens vigentes. Frete técnico não vira produto ou unidade e não duplica o frete oficial. Não somar receita do pedido às linhas de itens, meses ao TOTAL, ou modelos de primeiro/último toque.

`clientes` é distinto por grão: comprador em dois meses conta uma vez no ANO/TOTAL. No Looker, usar um único ANO/TOTAL para um card de clientes, ou detalhar por competência. A agregação MAX não resolve uma soma arbitrária de competências; o conector bloqueia o card sem competência quando existem múltiplos recortes. LTV não é recalculado pelo filtro mensal de receita. No detalhe de produtos, filtrar também `estado=valido` e `frete=Não`; para auditar cancelamentos, manter os estados visíveis na tabela de pedidos. Clientes distintos em um período arbitrário podem exigir `COUNT_DISTINCT(cliente_id)` sobre pedidos válidos do período, dentro dos limites do detalhe, em vez de somar resumos mensais.

## Comandos reais para o Work

Usar o Terminal **da cópia de homologação no SHA validado**, selecionando FARMA antes dos imports e conferindo as três planilhas de teste no perfil privado. O comando `nexo historico` encaminha ao Python; não aciona Weni, Analytics, Recompra, Noturno ou nova coleta quando usados os argumentos abaixo. Não omitir `--planilhas` para publicar.

Os caminhos abaixo são exemplos locais privados, não arquivos do repositório. Não executar em PET comercial.

Como não há release nova nesta tarefa, o Work pode executar o código em um checkout **isolado de desenvolvimento/homologação**, com dependências do projeto já instaladas na sua própria `.venv`, configuração privada na raiz desse checkout apontando exclusivamente às três planilhas de teste e credenciais locais protegidas. Não usar a configuração comercial por engano. Em PowerShell aberto na raiz desse checkout, o encaminhamento equivalente é:

```powershell
$env:NEXOFLOW_PERFIL = 'FARMA'
function nexo { & .\.venv\Scripts\python.exe app\nexo_cli.py @args }
```

Definir o perfil antes de iniciar o Python. Essa função vale somente na sessão de homologação e não substitui executáveis ou módulos da instalação operacional. Também é possível substituir `nexo` por `.\.venv\Scripts\python.exe app\nexo_cli.py` em cada comando abaixo.

```text
nexo historico --auditar-banco C:\Homologacao\privado\farma.sqlite --resumo-mensal C:\Homologacao\privado\sqlite-mensal.json
nexo armazenamento status
```

A auditoria é somente leitura. O preparo faz a verificação completa de perfil e cria snapshot consistente, inclusive se a base de origem tiver WAL. Encerrar as outras cargas continua recomendado para um corte operacional fácil de registrar.

Atualizar primeiro o projeto privado do conector com `Code.js`, `Tables.js`, `Schemas.js` e seu manifesto em `connectors/continuacoes`. Habilitar Sheets API v4, manter permissões privadas e usuário com leitura de todas as origens/partes. Criar fontes no relatório **de teste** para as cinco tabelas, usando o ID do **Dashboard FARMA** e segmento FARMA; selecionar ANO/MES/TOTAL no resumo conforme o gráfico. Após confirmar essa ligação, autorizar as tabelas no manifesto:

```text
nexo armazenamento ativar-data-studio --abas Historico_Pedidos Historico_Itens BI_LTV_Clientes BI_Cobertura_Historica BI_Historico_Resumo --confirmar-fontes
nexo historico --planilhas capacidade --banco C:\Homologacao\privado\farma.sqlite --revisao C:\Homologacao\privado\plano-farma.json --resumo-mensal C:\Homologacao\privado\esperado.json
```

`capacidade` é o mesmo preparo **sem escrita remota** e grava uma revisão utilizável. A sintaxe antiga `--planilhas preparar --revisao ...` permanece; sem `--banco`, usa o SQLite privado do perfil. Não é necessário executar os dois preparos. A revisão descreve novas linhas, atualizações, inativações, inalteradas, partes de destino, grade projetada, reserva de índice e células livres por arquivo. A projeção do índice é uma reserva superior, não promessa de ocupação exata.

```text
nexo historico --planilhas aplicar --revisao C:\Homologacao\privado\plano-farma.json --max-lotes 1
nexo historico --planilhas conferir --revisao C:\Homologacao\privado\plano-farma.json --resumo-mensal C:\Homologacao\privado\piloto-observado.json
nexo historico --planilhas aplicar --revisao C:\Homologacao\privado\plano-farma.json
nexo historico --planilhas conferir --revisao C:\Homologacao\privado\plano-farma.json --resumo-mensal C:\Homologacao\privado\fechamento.json
```

Um lote contém **até 200 linhas e 1 MB**, de uma tabela/parte; o primeiro é selecionado por ordem estável de tabela, parte e posição/chave. O piloto não é uma amostra aleatória. Pode criar previamente as partes aprovadas, mas só confirma o número solicitado de lotes. Código 3 = pausa/pendência/divergência, não perda de toda a carga. O relatório parcial enumera exatamente os lotes, tabelas, partes e linhas confirmadas. Itens e LTV podem aguardar lotes posteriores; não chamar essa comparação parcial de fechamento financeiro. O leitor recusa a publicação WRITING, inclusive durante a pausa, em vez de apresentar total parcial como completo.

Retomar sempre a **mesma revisão, journal e cópia fonte**, no mesmo código validado. Não apagar travas ou refazer revisão para contornar falha. Há guarda do código: atualizar o publicador no meio de uma carga exige retomar com o código original ou reconciliar explicitamente. Um POST com resposta perdida fica SENDING; antes de novo POST a retomada relê as coordenadas: depois → confirmar sem POST; antes → repetir só nessas coordenadas; outro conteúdo → bloquear. Quota/autenticação não autoriza troca de destino ou escrita cega. A intenção do manifesto também é durável antes da alteração remota.

Rollback de um lote confirmado:

```text
nexo historico --planilhas rollback --revisao C:\Homologacao\privado\plano-farma.json --lote 1
```

Restaura somente as células anteriores se ainda corresponderem exatamente ao conteúdo escrito pelo lote. Uma edição posterior bloqueia. A restauração tem intenção RESTORING e recuperação de resposta perdida. Não remove arquivos, abas ou linhas; guarda prova das linhas/partes criadas. O lote volta a pendente e o manifesto permanece em publicação até retomar/fechar o plano. Não executar rollback de planilha inteira sobre edições de terceiros.

## Evidências privadas e reconciliação

A pasta privada `logs/privado/historico_publicacoes` do perfil contém snapshot, revisão, `plano.sqlite` com baseline de início referenciado por todos os lotes, `lote_NNNNNNNN.json` (somente intervalos afetados, estrutura, valores anteriores, hashes e prova de criação), conferências e recibos. Incluir tudo no backup **privado** da homologação. Não compartilhar essa pasta no Git/CI/release. Usar ACL Windows restrita ao usuário responsável; modo 0600/0700 também é solicitado pelo código, mas não substitui configuração de ACL no Windows.

`historico_conferencia_v1` é a saída compacta nova: segmento, instante, revisão, assinatura de manifesto e partes, cobertura, recortes por `AAAA-MM`, SEM_EMISSAO e TOTAL. Por recorte informa pedidos únicos, válidos/cancelados/pendentes/outros, compradores distintos, linhas de produto observadas/válidas, unidades válidas e produtos/frete/faturamento em centavos. Não contém IDs individuais, nome, CPF, telefone, endereço ou clique. Recebimentos brutos mensais não são reconstruídos artificialmente: ficam indisponíveis quando não preservados; a evidência traz contagens verificáveis por janela e, quando existentes, recibos por execução.

O esperado é calculado independentemente sobre a cópia SQLite e comparado à transformação antes de qualquer escrita. O observado vem da releitura de todas as partes em um fechamento consistente; não se relê a base inteira a cada lote. A soma de pedidos válidos e LTV deve fechar ao centavo. Divergências de intervalo geram `divergencia_intervalo.json` com parte/posição/lote e hashes, sem conteúdo de cliente; detalhes originais continuam só no journal privado. Uma divergência de schema/segmento/chave bloqueia imediatamente. Um centavo alterado é exibido pela conferência e impede aprovação.

## Fontes do Data Studio e limites

O registro de schemas autoriza explicitamente as cinco tabelas, além das BI existentes. A descoberta usa segmento, origem e manifesto, inclusive partes futuras; não expõe abas arbitrárias, auditorias ou cliques. A fonte nativa de uma aba física **não** passa a ler continuações por si só. O Work deve atualizar a implantação privada e as fontes no relatório de teste, preservando campos, filtros, estilos e fontes existentes. Não foi alterado relatório publicado nesta tarefa.

Cabeçalhos, tipos, chaves únicas, segmento, contagem e estado de todas as partes são conferidos. Parte ausente/ilegível, WRITING, índice modificado, conteúdo a mais ou limite excedido resulta em erro explícito. Não há corte silencioso. Limites: 1 milhão de linhas examinadas, 200 mil retornadas, 240 segundos, além das quotas Google. Detalhe de itens exige período e é selecionado pelos IDs oficiais dos pedidos desse período, com a mesma revisão entre as duas leituras. Pedidos sem data válida ficam na reconciliação SEM_EMISSAO, fora de filtro civil. Para visão anual usar `BI_Historico_Resumo`, não retornar 267 mil linhas ao Looker. Se um recorte agregado for cortado pelo filtro, o conector exige grão mais detalhado; não estima o restante. A infraestrutura Sheets não é uma garantia de atender detalhe ilimitado.

## Origem de anúncios: o que a tabela vazia significa

| Estágio | Meta | Google | Limite da evidência |
|---|---|---|---|
| Mensagem estruturada | referral em `ad_attribution` | gclid/gbraid/wbraid ou origem Google + meio pago | URL colada no texto não comprova origem; redirecionamento pode perder dados |
| Evento oficial | `meta_events` normaliza CTWA, liga URN exata | metadados disponíveis na mensagem | contato multicanal sem URN não comprova canal; evento sem identidade não cria vínculo |
| Contato | `weni_update._sync_ads_attribution` preserva primeiro/último e evidências | mesmo caminho | sem data/metadados disponíveis, não inventar |
| Analytics | `normalize_contact` → Base_Contatos → `build_bi_ads_rows` | mesmo caminho | dois modelos separados; toque posterior ao pedido não recebe venda |
| Eventos_Anuncios | `webhook_eventos.receive_event` → `append_event`, deduplicado | somente se o produtor receber evento suportado | Weni Update/Terminal não são esse produtor de webhook |
| Meta nativa | lê CTWA oficial e Marketing API por seus módulos | não substitui coleta Google autenticada | custos/conversas/CAC/ROAS requerem fontes e cobertura próprias |

No código atual, `Eventos_Anuncios` é alimentada pelo webhook opcional, não pelo publicador nem pela simples importação do Terminal. Ter Meta em primeiro/último e só cabeçalho nessa aba é compatível com esse fluxo. Não comprova perda isoladamente. Não se comprovou nesta tarefa se o operador executou/configurou o webhook, se Google forneceu metadados, nem se os três arquivos comerciais têm o mesmo corte. Não generalizar da amostra negativa.

O fallback legado `*_anuncio_id` pode ser **ID de clique**; conferir origem/evidência e `*_anuncio_clique_id` antes de relacionar ao ad_id oficial. Histórico não contém toda essa cadeia e não passa a atribuir vendas pelo simples contato. Compra intermediária é preservada, toque posterior não recebe crédito. Sem gasto comprovado, CAC/ROAS ficam indisponíveis, não zero. Não somar primeiro+último nem ligar conversas diárias a anúncio/pedido apenas pela data.

Registrar no fechamento: SHA/código, perfil e projeto, revisão e hash do snapshot, instante por fonte, períodos, último evento Weni coberto, atualização de custos Meta, fuso da conta e America/Belem, cobertura de pedidos e partes/revisão de cada tabela. A aba de conversas do Work mantém sua chave projeto/data e seu ID; não foi alterada. Fuso Meta diferente deve ser anotado; não redistribuir totais sem base horária.

## Critérios de homologação FARMA e futura réplica PET

1. Três planilhas de teste na pasta privada FARMA, IDs e permissões conferidos. Não copiar token/SQLite comercial para Git ou CI. Guardar original e backup consistente privados.
2. Auditar a cópia e guardar totais de controle: pedidos/itens, estados, compradores, produtos/frete/faturamento e LTV em centavos, janelas/revisões/pendências; verificar SEM_EMISSAO. Totais reais vêm da cópia atual, não da estimativa histórica de 267.672/207.582.
3. Preparo sem POST de fatos; conferir delta de chaves, cinco tabelas, grades e reservas, arquivos/partes planejados, OAuth e pasta. Histórico original não é apagado ou movido.
4. Piloto de um lote; comparar as posições e cobertura indicadas. Forçar falha simulada somente na homologação e testar retomada/rollback sem edição concorrente. Não declarar itens/LTV ausentes fora do piloto.
5. Retomar até zero lotes; conferir integralmente. Exigir zero diferença em cada indicador e entre pedidos/LTV. Repetir e comprovar zero novas escritas idênticas.
6. No relatório de teste: resumo anual, mensal, um dia, período vazio, itens por pedido, cliente que compra em dois meses, cancelamento e SEM_EMISSAO. Testar parte nova após vínculo, parte indisponível e estado WRITING: erro, nunca total parcial. Não juntar receita de pedido com item ou somar modelos de anúncio.
7. Antes de liberar o painel, registrar fontes/cortes/fusos e evidências do mesmo manifesto, com aprovação operacional separada para publicação comercial FARMA. Esta tarefa não concede homologação financeira/comercial nem troca fontes do relatório publicado.
8. Só depois replicar para PET com mapa/pastas/credenciais/cópia/revisão próprios, D+30 e regras PET preservadas. Nenhuma revisão FARMA pode ser reutilizada em PET. Publicação comercial PET continua pendente.

## Reproduzir os ensaios sem Google

```text
python -m unittest tests.test_history_capacity tests.test_history_publication tests.test_history_sheets_transport tests.test_history_conference tests.test_history_publish_cli tests.test_history_attribution_boundary -v
node --test tests/test_history_connector.cjs tests/test_continuation_connector.cjs tests/test_looker_abc_connector.cjs
```

No Linux, benchmark sintético: `PYTHONPATH=app:. python tests/benchmark_history_publication.py`. No PowerShell de desenvolvimento: `$env:PYTHONPATH='app;.'; python tests/benchmark_history_publication.py`. Nenhum cliente comercial é usado; os testes bloqueiam sockets reais. Consulte o [relatório técnico](RELATORIO%20PUBLICADOR%20HISTORICO.md) para medidas e limites das evidências.
