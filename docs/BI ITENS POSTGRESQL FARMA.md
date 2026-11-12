# BI_Itens FARMA — Analytics Windows, API privada e PostgreSQL

## Escopo e estado

Implementação autorizada em 12/11/2026 (America/Fortaleza). Windows opt-in; FARMA/BI_Itens exclusivamente. Banco `nexoflow_datastudio_piloto`, tabela `farma.bi_itens`, chave `item_chave`. Leitura do Data Studio pela visão dedicada `farma.produtos_itens_datastudio`, usando outro serviço, outro login e outras credenciais Cloudflare Access. PostgreSQL permanece privado.

O usuário informou base conciliada de **68.273 linhas**, entre 20/04/2020 e 06/11/2026. É referência fornecida, não uma releitura comercial feita nesta entrega. O MCP Hostinger confirmou a VPS 2132956 em execução, mas não oferece terminal remoto; Docker Manager respondeu que o sistema não é suportado. Nenhum comando, migração ou carga foi executado na VPS pelo Codex. A auditoria posterior do Work confirmou que a visão Metabase `farma.produtos_itens` contém sete campos; os doze originais estão na tabela. A correção posterior à release cria uma visão exclusiva da API por migração aditiva 002. O Codex não reconsultou a VPS nesta correção. Ver [diagnóstico e retomada](CORRECAO%20VISAO%20API%20BI%20ITENS.md).

Não acessar bancos Métricas, Hub, n8n ou configuração do Metabase. Não recriar a infraestrutura, seus volumes ou o PostgreSQL. Não alterar o relatório Data Studio de produção durante a homologação. O Metabase é referência independente para conferir a visão.

## Origem e regras preservadas

`app/main.py` monta `looker_tables = build_looker_tables(...)`, de `app/looker_bi.py`, a partir do conjunto operacional conciliado. O envio usa **exatamente `looker_tables["BI_Itens"]`**, antes das substituições grandes do BI. Não precisa gravar BI_Itens no Sheets primeiro. As demais tabelas continuam em seu fluxo Sheets; PET mantém o destino anterior.

As leituras e gravações operacionais anteriores do Analytics continuam existindo. Esta entrega não transforma toda a rotina em uma operação independente do Sheets nem em transação distribuída. Não importa `Historico_Itens` automaticamente ou transforma 68.273 linhas da BI_Itens em todo o histórico oficial/LTV. Reutiliza o mesmo universo e regras comerciais do Analytics.

O parser gera a chave interna por `sha256(pedido_chave|posição)[:32]`; a BI aplica `opaque_key("item", chave_interna)`. `venda_chave` é `opaque_key("venda", pedido_chave)`. Portanto, reordenar pode manter chaves e mudar SKU/valores, e reduzir itens pode deixar posições antigas. O publicador envia o snapshot completo de cada venda no mesmo lote. Nunca divide uma venda para respeitar o tamanho desejado do lote.

As linhas da BI já excluem pedidos não elegíveis/cancelados e produtos fora das regras FARMA. O escopo de reconciliação vem dos pedidos válidos ou oficialmente cancelados com identidade verificada, usando os validadores existentes. Nenhuma ausência genérica de linha autoriza apagar uma venda remota.

Em extração parcial, falha de consulta, pendência de itens ou erro de parsing, **não há remoções**, mesmo quando uma chave antiga não aparece. Partes 1–3 da carga de contatos também não autorizam remoções. A Parte 4 exige as anteriores concluídas pelo contrato existente e ausência de falhas. O Analytics envia a base acumulada e limita reconciliações às vendas explícitas. Clientes sem Weni continuam seguindo a identidade financeira já implementada. Frete técnico não vira produto; receita/quantidade vêm da mesma BI.

## Configuração Windows

Somente `PERFIS["FARMA"]` recebe as opções:

```python
"BI_ITENS_DESTINO": "sheets",  # padrão; mudar para postgres somente na homologação
"BI_ITENS_POSTGRES_MODO": "simular",  # aplicar apenas após conferir
"BI_ITENS_POSTGRES_CREDENTIALS_FILE": "credentials/bi_itens_farma_publicador.json",
```

Arquivo privado referenciado, fora do Git e do pacote público:

```json
{
  "endpoint": "",
  "publish_token": "",
  "access_client_id": "",
  "access_client_secret": ""
}
```

Preencher com o hostname HTTPS efetivamente implantado, segredo da API publicadora e **Service Token Cloudflare exclusivo do Windows/publicação**. Não usar DSN, senha PostgreSQL, token Weni, chave de leitura ou chave da Hostinger. O endpoint é só a origem HTTPS, sem query, usuário, senha ou caminho. Redirects são recusados; TLS permanece verificado e a sessão requests herda o proxy autorizado da instalação. Falhas não enviam credenciais para outra rota/destino.

Caminhos relativos das credenciais são resolvidos pela raiz instalada. A outbox é `logs/privado/bi_postgres/outbox.json`; arquivos completos/encerrados são preservados ao lado. Windows Preserve conserva configuração, credentials e logs. Não sobrescrever a configuração existente com o exemplo público.

`simular` calcula inserções, atualizações, mantidos e remoções previstas contra o banco, revertendo staging/TEMP; não cria fatos, planos ou recibos duráveis e não avança checkpoint. É simulação **do destino PostgreSQL**: as demais etapas normais do Analytics ainda podem escrever no Sheets. Não é dry-run global de Weni/Sheets. `sheets` mantém todo o comportamento anterior e não abre conexão com a API.

## Protocolo e idempotência

1. Antes da coleta, o Windows verifica protocolo/destino e reserva sessão idempotente, com revisão monotônica atribuída pelo servidor. Requisições não dependem do relógio do PC para ordenar lotes.
2. Linhas, escopos e lotes são validados integralmente e congelados na outbox privada com hash antes do primeiro envio. Alvo usual: 1.000 linhas por lote, até 20.000 quando uma venda indivisível exigir, no máximo 7,5 MB. Venda maior bloqueia explicitamente, sem truncamento.
3. O servidor registra o plano imutável de IDs/digests dos lotes e estado `WRITING`. Uma segunda publicação não assume um plano incompleto de outro gravador.
4. Cada lote cria staging temporário tipado, usa COPY parametrizado, valida duplicidades/escopo/proprietário/precisão, calcula delta, guarda imagens anteriores/novas privadas, faz upsert e reconcilia apenas as vendas autorizadas na **mesma transação**.
5. O upsert compara todos os campos comerciais e ignora apenas `atualizado_em`. Linhas idênticas não recebem UPDATE, inclusive em nova execução; timestamp não é usado como prova de mudança comercial. Valores monetários trafegam como strings decimais; códigos continuam Texto. O staging é relido para recusar arredondamento silencioso pelo tipo do destino.
6. Recibo e alterações confirmam juntos no COMMIT. Resposta perdida pode repetir o mesmo UUID/digest; o servidor retorna o recibo persistido. UUID reutilizado com conteúdo diferente é recusado. O Windows consulta o recibo antes de reenviar ao retomar.
7. Só após conferir recibo, alvo, sessão, digest e contagens, o Windows persiste o checkpoint do lote. Depois de todos os recibos, reconfirma o plano no servidor antes do checkpoint global. `READY` exige todos os lotes completos; publicação parcial fica `PARCIAL`. Uma resposta HTTP 200 isolada não basta.
8. Revisões anteriores à última aplicada não sobrescrevem correções novas nem ressuscitam cancelados. Na mesma sessão, uma venda não pode ser reatribuída a outro lote. Essas revisões ordenam **extrações do publicador**; não inventam uma versão oficial do pedido que a API do delivery não forneceu. Manter um único Windows publicador autorizado e não clonar sua credencial/outbox para máquinas concorrentes.

Não há exclusão global de chaves remotas ausentes da extração. Itens antigos da mesma venda só são removidos quando o lote é completo e essa venda está explicitamente coberta. Ausência de cliente, falha de API ou recorte parcial não comprovam cancelamento.

## API publicadora — somente rede interna

- `GET /publicacao/destino`: contrato do alvo.
- `POST /publicacao/farma/bi-itens/sessoes`: reserva/reconsulta por UUID.
- `POST /publicacao/farma/bi-itens/planos`: fixa/reconfirma o plano.
- `POST /publicacao/farma/bi-itens/simular`: delta sem commit de fatos/metadados.
- `POST /publicacao/farma/bi-itens/lotes`: transação de publicação.
- `GET /publicacao/farma/bi-itens/lotes/{uuid}`: recibo persistido.
- `GET /publicacao/farma/bi-itens/sessoes/{uuid}`: estado para recuperação.

Sem Swagger, rotas administrativas ou SQL arbitrário. Corpo limitado a 8 MB; credencial Bearer dedicada adicional ao Cloudflare Access. Logs de acesso do Uvicorn desabilitados para evitar exposição acidental; erros públicos controlados, sem DSN, senha, headers, URLs autenticadas ou linhas. O recebedor recusa banco errado, schema/chave divergentes, usuário de serviço com privilégios excessivos, RLS, triggers de usuário ou FKs que precisem de revisão de efeitos colaterais. Não desativar essas proteções para aprovar um destino incompatível.

## API e conector de leitura

O segundo processo usa `READ_DSN_FILE`, `READ_TOKEN_FILE`, login **nf_bi_itens_reader** e apenas `SELECT` em `farma.produtos_itens_datastudio` e na visão de estado. Não recebe o DSN/token do publicador e não oferece suas rotas.

- `GET /consulta/destino`: contrato/schema/autenticação; informa estado, inclusive enquanto não estiver pronto, sem devolver fatos.
- `POST /consulta/farma/bi-itens`: período obrigatório, campos e filtros autorizados. Segmento e visão fixos. Não aceita tabela/database configurável pelo relatório.

A visão precisa oferecer os 12 campos originais de BI_Itens: `item_chave`, `venda_chave`, `cliente_chave`, `data`, `produto_codigo`, `produto_nome`, `categoria`, `quantidade`, `valor_unitario`, `receita_item`, `sku_informado`, `atualizado_em`. Códigos/chaves são Texto, data é DATE, quantidade e valores são NUMERIC. A migração projeta diretamente os doze campos, sem casts, filtro, join ou agregação, preservando tipos, precisão/escala, collation e uma linha por item. Uma visão agregada sem essas identidades não pode ser usada silenciosamente no lugar do detalhe: devolver o schema ao Codex para adaptar o contrato, sem alterar a visão comercial às cegas.

Consultas usam transação REPEATABLE READ/READ ONLY, validam grão único por item e números antes do filtro, e consultam o estado confirmado na mesma fotografia do banco. `WRITING`, `PARCIAL` e `REVERTIDO` recusam os totais. Sem plano novo, `LEGADO` representa a base existente, cuja conciliação inicial precisa ser confirmada pelo Work. Isso não fabrica `READY` no manifesto Sheets.

O SQL agrupa pelos campos dimensionais realmente solicitados e soma quantidade/valores no banco, com Decimal/NUMERIC. A métrica virtual `produtos_distintos_periodo` calcula COUNT DISTINCT global com SKU informado e não é reagregável. Não somar contagens diárias/por parte. Detalhes maiores que 200 mil linhas ou respostas acima de 12 MB são recusados integralmente; resumo anual continua disponível porque agrega no PostgreSQL. Timeout por consulta e concorrência limitada protegem o servidor. Não há paginação/truncamento apresentado como resposta completa.

Filtros suportados: INCLUDE/EXCLUDE, AND/OR, EQUALS/IN_LIST nas dimensões e CONTAINS literal sensível a maiúsculas nos textos. Filtros de data adicionais são tipados. Outros operadores são recusados, inclusive regex; não ignorados. Conferir os filtros/controles reais dos nove usos. Quantidade, receita e valor unitário mantêm a agregação declarada no schema existente; não reinterpretar SUM de valor unitário como preço médio.

O conector privado está em `connectors/bi_itens_api/`. Preserva IDs dos 12 campos e `atualizado_em` Texto. A fonte usa autenticação **Chave** com o segredo exclusivo da API leitora armazenado em UserProperties; Cloudflare Access da leitura fica nas propriedades privadas do script:

```text
NF_READ_ENDPOINT
NF_ACCESS_CLIENT_ID
NF_ACCESS_CLIENT_SECRET
```

São credenciais distintas das do Windows. Nunca colar no código ou no Git. O manifesto pede apenas external_request; não lê Drive/Sheets nem abre PostgreSQL público. Retentativas HTTP transitórias são limitadas; publicação pendente ou autenticação não é contornada. O diagnóstico `NF_PG_CONSULTA` informa campos, datas, contagem, revisão e corte, sem valores de filtros/chaves.

## Preparação da VPS pelo Work

1. Manter as cargas Windows encerradas e produção Data Studio na fonte atual. Consultar os Compose/containers/redes reais e o helper de seis arquivos. Não substituir os serviços existentes. Localizar o PostgreSQL do projeto **nexoflow-datastudio-piloto**, a visão, o usuário Metabase somente leitura e os backups existentes.
2. Fazer backup consistente do **banco piloto**, com pg_dump custom pela rotina já autorizada e SHA-256 privado. Não apagar volumes/backups. Executar `integrations/bi_itens_publisher/audit.sql` em leitura: conferir schema/chave, números, datas, visão, permissões, RLS e triggers. Confirmar os 68.273 itens no corte inicial ou explicar a atualização efetiva. Registrar mês/TOTAL e os mesmos recortes do Metabase. Não enviar DSNs, senhas ou linhas comerciais ao Git/CI.
3. Compilar a imagem do commit aprovado. Dockerfile fixa a imagem base por digest e as dependências transitivas; não atualiza pip automaticamente. Em ambiente com CA corporativa, usar o secret opcional `build_ca_bundle` com a cadeia confiável autorizada, sem desativar TLS. Código/segredos privados não entram na imagem.
4. `admin --migrar` valida a tabela/PK e aplica `migration.sql` e `migration_002_read_view.sql` na mesma transação. Além dos metadados/índices existentes, cria **somente a nova visão** `farma.produtos_itens_datastudio`. Não altera fatos, a definição/OID/owner/ACL de `farma.produtos_itens` ou permissões Metabase. Repetir preserva a visão API correta; objeto/definição conflitante bloqueia e reverte toda a transação, sem `CREATE OR REPLACE` desse objeto.
5. Rodar `audit_read_view.sql` após a migração, por conexão administrativa somente leitura: exigir 12 tipos preservados, zero linhas divergentes e igualdade por mês/TOTAL entre tabela, visão API e visão Metabase nos campos comuns. Comparar OID/owner/ACL legados ao préflight. Criar logins dedicados sem privilégios administrativos, com senhas novas geradas no servidor. Aplicar `grants.sql` ao publicador e `reader-grants.sql` ao leitor. Não usar postgres, dono do banco, usuário Hub/n8n/Métricas ou do Metabase. O login de publicação recebe apenas DML da tabela alvo, metadados necessários, sequência e TEMP; leitor recebe SELECT nas duas visões, sem DML/DDL da tabela-base.
6. Guardar DSNs/segredos em arquivos privados fora do checkout, adequados ao UID 10001 dos serviços. O admin DSN não é segredo de runtime. Os arquivos montados no runtime devem ser legíveis pelo UID 10001, com 0400 e proprietário apropriado; não tornar credenciais de produção legíveis por todos.
7. Usar `compose.overlay.example.yaml` como referência adicional, apontando à rede existente validada e **sem ports**. Se o Tunnel não compartilhar essa rede, adaptar somente a extensão autorizada após inspecionar a configuração real. Não expor 5432/8080, não recriar PG/n8n/Hub/Metabase e não substituir seus Compose. Ambos os serviços usam filesystem somente leitura, UID sem root, capabilities removidas, healthchecks e rotação de logs.
8. Criar duas aplicações Cloudflare Access do tipo Service Auth, com dois Service Tokens distintos, políticas sem bypass público. Sugestões de hostname (não afirmadas como existentes): `bi-publicacao.nexoflowhub.com.br` e `bi-consulta.nexoflowhub.com.br`. Ativar a proteção antes de ligar DNS/ingress ao Tunnel. O primeiro ingress aponta somente ao publicador, o segundo ao leitor. Não reutilizar o token administrativo da Cloudflare/Hostinger como credencial do Windows.
9. Confirmar que sem Service Token ou com token trocado entre aplicações não se acessa a origem; com Access válido e Bearer errado a API retorna 401. Chave de leitura não publica, chave do publicador não lê. Testar TLS na rota autorizada do PC (direta/proxy), sem mudar proteções de rede.
10. Preencher privadamente o arquivo Windows e as propriedades/autenticação do conector. Tokens Cloudflare só existem após serem emitidos pelo provedor; os campos pendentes não podem ser preenchidos com valores inventados.

Ferramenta administrativa local (no ambiente Linux com dependências da imagem), sempre com DSN de admin **do piloto** em arquivo privado:

```bash
PYTHONPATH=app:. python -m integrations.bi_itens_publisher.admin --dsn-file /caminho/privado/admin-dsn --migrar
PYTHONPATH=app:. python -m integrations.bi_itens_publisher.admin --dsn-file /caminho/privado/admin-dsn
```

Não colocar DSN/senha no comando. Se executado dentro de contêiner, montar somente esse arquivo administrativo e a rede piloto durante a operação, sem entregá-lo aos serviços permanentes.

## Homologação e ativação Windows

Primeiro aprovar os testes locais/CI e o pacote instalado. Depois homologar o canal e o schema reais, inicialmente sem fatos comerciais novos. O usuário autorizou preparar a integração; esta entrega não executa a carga comercial automaticamente.

1. Atualizar pelo Setup **Preserve**, com rotinas encerradas; conferir `nexo versao`. Copiar o secrets atualizado mantendo os tokens existentes. O exemplo público não contém suas credenciais. Manter `BI_ITENS_DESTINO="sheets"` até os serviços estarem prontos.
2. Nesta etapa, manter FARMA em `sheets` e Analytics/Noturno pausados. Com a API leitora, conferir a base conciliada no relatório privado antes de mudar produção. Não precisa repetir coleta histórica anual nem enviar SQLite à VPS.
3. Quando o canal estiver validado, selecionar FARMA e configurar `BI_ITENS_DESTINO="postgres"`, modo `simular`, credenciais dedicadas preenchidas. Executar uma atualização Analytics normal; o resultado informa o delta PostgreSQL, sem checkpoint de publicação, e mantém BI_Itens Sheets intacta. As demais etapas normais permanecem operacionais.
4. Conferir os números esperados, incluindo as diferenças justificadas desde a base inicial, e somente então mudar para `aplicar`. Executar Analytics na rotina autorizada. Ele valida as mesmas linhas, publica em lotes e recebe os recibos antes de avançar. Não executar Weni/Recompra/Noturno só para retomar a outbox.

Comandos reais, depois da configuração/ativação no perfil FARMA:

```powershell
nexo versao
nexo analytics
nexo bi-itens-postgres status
nexo bi-itens-postgres retomar
```

`retomar` envia somente os lotes congelados pendentes, sem nova coleta Weni/API e sem regravar Sheets. `status` não aplica. Se já estiver confirmado, não reenvia fatos. O Analytics também retoma a outbox pendente antes de coletar novamente.

## Reversão e reconciliação administrativa

- Para interromper novas publicações, encerrar as rotinas e retornar `BI_ITENS_DESTINO="sheets"`; preservar a outbox e os recibos. A retomada do destino Sheets pode voltar a exigir continuações e fonte confirmada, conforme o estado anterior. Não confirmar BI_Itens no Terminal para contornar o novo/antigo caminho.
- Manter fonte direta/implantação anterior do Data Studio para reversão das ligações; não apagá-las.
- Reverter lote exige admin local e conferência das imagens armazenadas. O código compara as linhas atuais às imagens aplicadas e **recusa edição posterior**. Restaura apenas o lote, em transação, e avança a cerca de revisão. A conta Windows não possui rota administrativa.

```bash
PYTHONPATH=app:. python -m integrations.bi_itens_publisher.admin --dsn-file /caminho/privado/admin-dsn --reverter-lote UUID_DO_LOTE
```

- Plano que não chegou a aplicar fatos ou cujos lotes foram todos revertidos pode ser encerrado pelo fluxo oficial, sem criar READY:

```bash
PYTHONPATH=app:. python -m integrations.bi_itens_publisher.admin --dsn-file /caminho/privado/admin-dsn --encerrar-plano UUID_DA_SESSAO
```

- Após prova de encerramento/reversão no servidor, arquivar a tentativa local preservando todos os bytes do plano/recibos. A operação não confirma lotes nem avança checkpoint:

```powershell
nexo bi-itens-postgres arquivar-encerrada
```

O servidor precisa comprovar REVERTIDO ou revisão superada sem WRITING. O próximo Analytics cria sessão nova e reconcilia dados atuais. Não editar assinaturas, hashes, UUIDs ou estados à mão. Após rollback, o leitor recusa a fotografia incompleta até nova publicação íntegra; não marcar READY manualmente.

Backups devem incluir o banco piloto completo (tabela, visão, índices, metadados e imagens de rollback), arquivos de segredos/configuração privados da VPS e Windows, logs/outbox e referências às versões implantadas. Não exportar isso a artefatos públicos. A migração não possui down destrutivo automático; rollback operacional conserva metadados e retorna serviços/fonte à versão anterior, com outboxes preservadas. Restauração integral de dump exige procedimento específico fora de qualquer carga concorrente, não é substituto do rollback por lote.

## Roteiro Data Studio do Work

1. Criar/atualizar cópia de segurança do relatório de produção e trabalhar numa **cópia privada**. Preservar a fonte direta, as fontes v6/v7 e implantações anteriores.
2. Criar projeto Apps Script privado separado. Implantar **Code.js, Schema.js e appsscript.json** de `connectors/bi_itens_api/` do mesmo SHA aprovado. Não misturar com os três arquivos do conector de continuações.
3. Configurar propriedades privadas da leitura e usar a Chave da API leitora na autorização do conector. Registrar versão/SHA. O conector está fechado em FARMA e nessa visão; não adicionar PET por nome de campanha/arquivo.
4. Conferir os 12 IDs, dimensões e agregações, `data` como Data, `sku_informado` Número sem agregação e `atualizado_em` Texto. Para cartão de distintos, usar diretamente **Produtos distintos no período (SKU informado)** sem COUNT_DISTINCT/SUM adicional. Também conferir tabela por produto, rankings/Top 5, unidades e receita.
5. Comparar com Metabase/SQL da mesma visão e corte: 01–03/11/2026, 02/11/2026, 30/11/2026 vazio, um intervalo mensal, anual e toda a cobertura disponível. As referências antigas 216/331/R$17.675,89 e 90/134/R$4.753,02 só valem se o corte ainda corresponder; registrar diferenças legítimas, sem forçar números.
6. Testar produto repetido em dois dias, códigos com zeros, filtro SKU, busca/seleção por produto, controles de data, totais e mesclagens BI_Clientes_Vendas. Mapear **os nove usos individualmente**, inclusive produtos em destaque e Pedidos por cliente. Não multiplicar receita por join de item/pedido ou comparar fontes com recortes diferentes. Validar filtro não suportado como bloqueio explícito, sem soma parcial.
7. Reabrir e repetir os três recortes. Conferir ausência de aviso de reagregação, cálculos e períodos vazios. A aprovação do código/SQL não substitui esses testes no Google.
8. Somente após envio homologado, plano READY, totais ao centavo, rankings, filtros, chaves e os nove usos aprovados, trocar as ligações necessárias da cópia para produção conforme autorização do usuário. Preservar fontes anteriores e reversão imediata. Não migrar campos sem verificar suas dependências e IDs.
9. Não executar `armazenamento ativar-data-studio --abas BI_Itens --confirmar-fontes` por causa desta API: essa confirmação é do leitor **Sheets/continuações**, não do destino PostgreSQL. A nova rota não precisa liberar continuações de BI_Itens, pois não escreve essa tabela no Sheets. O manifesto antigo fica preservado.

## Evidências e limitações

O CI inclui PostgreSQL 18.6 descartável, Docker/API reais sem portas publicadas, logins mínimos, staging/upsert, recibos, idempotência, queda antes/depois do commit, correção/chave/cancelamento, parcial sem exclusões, ordenação, concorrência, rollback com edição posterior recusada, planos incompletos, schema/segmento, leitura READ ONLY, grão, ranking, filtros, períodos vazios e 200.001 linhas sem truncamento. O SDK/UrlFetch do conector é simulado em Node; os SQLs são executados no PostgreSQL real temporário.

Windows continua autônomo quando a opção fica desabilitada. O Setup não implanta serviços na VPS, não emite Service Tokens Cloudflare nem atualiza o Apps Script. Não houve leitura/atualização de dados comerciais nesta validação, migração Data Studio ou deploy Hub. `LIMITES_DA_API_NAO_HOMOLOGADOS`, pendências e contratos financeiros anteriores permanecem preservados. Consultas de fontes diferentes não formam uma transação distribuída: validar revisões/cortes, o término do Analytics e suas outras tabelas antes de afirmar todos os KPIs atualizados.

Passagem resumida: [prompt operacional para o Work](PROMPT%20WORK%20BI%20ITENS%20POSTGRESQL.md).

A outbox local é protegida pelo lock de arquivo do sistema operacional, compartilhado entre Analytics e os comandos de retomada. Uma segunda rotina não pode regravar seu estado; caminhos dos perfis são separados. A trava PostgreSQL continua necessária para coordenação entre instalações. Não remover arquivos de lock para forçar retomada.

Revisão adicional: ausência no builder BI (inclusive pedido com data futura) não autoriza remover fatos anteriores. O escopo de reconciliação é a união das vendas nas linhas validadas e dos cancelamentos oficiais explícitos. Regressão reproduzida antes do ajuste e conferida também no PostgreSQL com plano completo, preservando os fatos anteriores.


## Retomada da implantação após a auditoria das sete colunas

Windows permanece 1.5.36; o protocolo de publicação e `farma.bi_itens` não mudaram. Usar o **SHA validado da correção** para o checkout Linux, imagem e arquivos do conector. Não usar o servidor/conector contidos na tag 1.5.36 para essa retomada, pois ainda apontam à visão antiga. Atualizar os dois lados da leitura juntos; uma combinação antiga/nova é recusada por alvo divergente.

1. Preservar o backup e as evidências já conferidas pelo Work; revalidar hash/catálogo/corte antes da migração. Rodar `audit.sql` em leitura e guardar OID/owner/ACL de `farma.produtos_itens`.
2. Com DSN administrativo do piloto em arquivo privado, executar no checkout do SHA validado:

```bash
PYTHONPATH=app:. python -m integrations.bi_itens_publisher.admin --dsn-file /caminho/privado/admin-dsn --migrar
```

3. Aplicar `reader-grants.sql` após criar o login exclusivo. O SELECT novo aponta somente à visão API e à visão de estado. Não conceder dados extras ao Metabase nem usar seu login na API. O script não revoga nem concede privilégios na visão antiga; conferir separadamente qualquer grant preexistente inesperado da conta leitora.
4. Rodar `audit_read_view.sql` por conexão administrativa em leitura. A conta runtime não precisa de SELECT na tabela-base ou na visão Metabase para essa auditoria. Exigir zero divergências dos doze campos e grão; os agregados incluem todos os meses e TOTAL, sem IDs individuais.
5. Repetir a migração e conferir ausência de mudanças de OID/owner/ACL/dados. Não fabricar READY: WRITING/PARCIAL/REVERTIDO continuam bloqueantes; LEGADO identifica a base conciliada anterior à primeira publicação automática.
6. Implantar as APIs/Cloudflare e o conector do mesmo SHA em cópia privada; comparar com Metabase nos mesmos cortes. Retomar o envio Windows somente na etapa posterior aprovada. Nesta correção não executar Analytics/Noturno nem publicação comercial.

Reversão desta migração: parar a API leitora e manter a fonte de produção anterior; deixar a nova visão e metadados preservados e sem consumo até investigar. Não alterar a visão Metabase, apagar fatos ou executar down destrutivo.
