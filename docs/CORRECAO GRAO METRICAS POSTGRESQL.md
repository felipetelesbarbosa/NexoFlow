# Exportação PostgreSQL — grão das métricas de anúncios

## Evidência e causa

A evidência sanitizada fornecida pelo operador na 1.5.39 aponta `Metricas_Diarias`, parte 0, linhas 2 e 3, com a mesma chave antiga e divergências em `anuncio_titulo` e `contatos`. A consistência final da tentativa não foi concluída; o corte não é READY. Nenhum valor comercial foi acessado nesta correção.

A causa no contrato foi reproduzida com os geradores oficiais e dados sintéticos: `analytics.build_daily_metrics()` agrupa por `(data, tipo_atribuicao, anuncio_id, anuncio_titulo)`, enquanto o registro PostgreSQL omitia o título. `build_bi_ads_rows()` também agrupa por título e o contrato BI_Ads tinha a mesma omissão. As duas chaves agora incluem `anuncio_titulo`. Títulos diferentes continuam em grupos separados, inclusive com ID ausente; não se soma primeiro e último toque nem se escolhe a última linha. Mesma chave completa com conteúdo diferente continua bloqueada.

O formato físico das abas, seus cabeçalhos e hashes permanecem válidos. Não ordenar ou editar as planilhas, nem alterar o manifesto ou as exclusões. O catálogo Apps Script é regenerado com o novo hash do contrato; os campos/IDs públicos permanecem os mesmos.

## Verificação ampliada das chaves

Revisão por inspeção dos produtores/gravadores (não é auditoria das linhas comerciais):

| Conjuntos | Identidade conferida | Resultado e limite |
| --- | --- | --- |
| Metricas_Diarias; BI_Ads | Dimensões dos dois geradores em analytics.py | Duas omissões de título reproduzidas e corrigidas. |
| Base_Contatos; Pedidos_FarmaLider; Itens_Pedidos_FarmaLider; BI_Pedidos | UUID/ID oficial de contato, pedido e item nos upserts | Chaves explícitas preservadas; duplicata divergente permanece erro. |
| Historico_Alteracoes | Contato + instante sincronizado + ação | Histórico append-only; coincidência completa divergente exige evidência, não descarte. |
| Eventos_Anuncios; Campanhas_Meta | event_id; anuncio_id | Contratos explícitos dos gravadores preservados. |
| Metricas_Vendas; BI_Resumo_Diario; BI_Vendas | Dia | Geradores consolidam um registro por dia. |
| BI_Canais; BI_Conversao | chave construída com dia/dimensão | Não omitir dimensões da chave já produzida. |
| BI_Status; BI_Qualidade; Controle | Snapshot/status, singleton de qualidade e chave de controle | Substituição/upsert dos conjuntos conforme gravadores; não ampliar chave usando contagens. |
| BI_Publico; BI_Clientes; BI_Clientes_Vendas; BI_Itens | Chaves opacas de contato, cliente, venda e item | Grãos separados e _unique() do gerador preservados. |
| BI_Produtos_ABC | Período + código + nome | Snapshot legado sem chave de produto opaca. Sem SKU, nomes iguais não comprovam identidade; colisão divergente permanece bloqueante. Não inventar SKU ou colapsar produtos para exportar. Não há evidência dessa colisão no corte comercial. |
| BI_Produtos_Juntos; BI_KPIs_Periodo | Período + par ordenado; período | Pares agregados e snapshot único por período. |
| Historico_Pedidos; Historico_Itens; BI_LTV_Clientes; BI_Cobertura_Historica; BI_Historico_Resumo | chave oficial/composta emitida pelo histórico | Regras financeiras, período, janela/limite e grãos dos resumos preservados. |
| Meta_Ads_Diario; Meta_Ads_Campanhas; Meta_Ads_Anuncios; BI_Meta_Resultados; BI_Meta_Conversoes | chave explícita de meta_ads_model.py | Gerador já recusa fatos divergentes; hash não é substituído por título. |
| Tickets_Delivery_Weni; BI_Delivery_Pedidos | ticket_uuid; pedido_chave | Vínculos explícitos preservados. |
| Conversas_Diarias | projeto + data | Não mapear automaticamente ds136, cujo produtor/chave seguem pendentes. |
| Cache_profile; Cache_orders; Cache_creations; Cache_history_run_receipts; Cache_history_windows; Cache_history_seen; Cache_history_orders; Cache_history_issues; Cache_history_revisions | Chaves primárias/únicas dos schemas SQLite em cache_schema.json | Contrato preservado; não exportados como fatos Sheets. |
| Exclusoes_Publicacao | segmento + pedido_id | Evidência da revisão original preservada. |

Essa inspeção não comprova ausência de conflitos em todos os dados reais; a guarda e o diagnóstico permanecem ativos em todas as tabelas.

## Cota de leitura

`exportar-sheets` abria diretamente GoogleSheetsStore, sem o limitador HTTP preventivo compartilhado usado pelo histórico. Isso explica por que esta via podia exceder cotas mesmo tendo retry exponencial. A entrada passa a usar o mesmo QuotaGate/QuotaAdapter, com a classe geral de Sheets, sem trocar validadores por validadores exclusivos das cinco tabelas históricas. O limitador instala-se antes da primeira leitura, compartilha o ledger local existente e conserva TLS, proxy, timeout e retentativas. Não garante ausência de 429 quando outras aplicações/PCs consomem a cota. A regressão usa gspread/requests e relógio virtual, sem credenciais.

## Compatibilidade do contrato e VPS

O hash do contrato muda; Windows, publicador/leitor definitivo e `connectors/datastudio_api/Schemas.js` precisam da mesma revisão de código. Não atualizar somente o Windows e tentar publicar contra uma API antiga. O piloto BI_Itens e Metabase não mudam.

A migração administrativa existente admite o hash anterior exato somente se **Metricas_Diarias e BI_Ads estiverem vazias em nf_registros/nf_stage/nf_atuais nos dois segmentos**, sem execução WRITING. Outros dados/recibos ficam intactos. Hash desconhecido, escrita incompleta ou métrica já armazenada bloqueiam com código específico. Não reescrever chaves de revisões publicadas ou hashes de planos para forçar compatibilidade.

Work: pausar os serviços definitivos antes da migração, fazer backup privado consistente, conferir o novo SHA e executar a administração existente com os arquivos DSN privados já provisionados. Sintaxe real: `python -m integrations.datastudio.admin --dsn-file CAMINHO_PRIVADO_EXISTENTE --ambiente homologacao --segmento FARMA` (ou producao somente no banco correspondente). Não inventar caminho/DSN nem repetir aprovar-origem com um manifesto antigo. Atualizar publicador/leitor/conector em conjunto, conferir contrato e refazer o manifesto do corte novo. Se houver métricas anteriores, preservar a base e analisar uma migração versionada específica; não apagar dados.

## Windows e próxima evidência

Esta mudança está distribuída na **1.5.40**; instalar o Setup em Preserve. A 1.5.39 não contém a correção de grão ou de cota. Não substituir módulos avulsos. Após distribuir o Setup validado, instalar em Preserve, confirmar a versão e repetir exportação e auditoria em pasta nova com o mesmo exclusoes.json confirmado. Preservar tentativas anteriores. Não executar API comercial, Weni, Noturno ou carga PostgreSQL para investigar.

## Resultados desta correção

- Regressão com geradores oficiais falhou antes da correção: duas linhas de título distinto geravam uma única chave PostgreSQL.
- 17 casos de grão/cache aprovados: FARMA/PET, primeiro/último anúncio, ID presente/ausente, contagens, replay e bloqueio de conteúdo divergente na chave completa; comparação de todas as chaves de cache ao schema SQLite.
- PostgreSQL Docker descartável: 58 testes aprovados, um smoke de imagem HTTP ignorado. Inclui roundtrip das duas métricas, atualização idempotente do contrato com outros dados preservados e bloqueios por WRITING, métricas armazenadas e hash desconhecido.
- Regressão combinada Data Studio, cota, Analytics e BI: 88 testes e 34 subtestes aprovados na rodada anterior à expansão dos casos de prefixo/ID; 23 ignorados por dependência de infraestrutura nessa rodada. Os testes PostgreSQL foram executados separadamente acima.
- 104 testes Node dos conectores aprovados. Ruff, sincronização do catálogo, documentação e consistência aprovados. Tipos dos arquivos operacionais e do módulo novo aprovados.

Não houve acesso às planilhas comerciais, atualização da VPS nem nova coleta. A inspeção do JSON confirma a localização do conflito; a nova exportação comercial após distribuição continua pendente. A 1.5.39 permanece intacta.

## Distribuição corretiva em preparação

Windows 1.5.40 em validação: inclui as correções de grão, o controle de cota na exportação e os pacotes sem o instalador Python. O Setup reutiliza Python existente ou oferece download do site oficial com hash fixado. Testes Windows novos cobrem reaproveitamento, download simulado, hash divergente e falha de rede; aprovação e downloads devem ser conferidos antes de anunciar a publicação. A mudança de contrato exige atualização coordenada dos serviços/conector pelo Work, sem executar cargas automaticamente.

## Publicação comprovada 1.5.40

Publicado em 13/11/2026, 00:41:51 (America/Fortaleza), SHA `c5da21c05c9a8c220bb55538b74957e8052e8624`. [CI](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/43357598802), [CodeQL](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/43357599045) e [publicação sem recompilar](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/43360624111) aprovados. Windows 3.11/3.14 nas duas codificações, PostgreSQL/Docker, executáveis, Setup Preserve/Clean/rollback e testes simulados do download Python aprovados. Downloads públicos iguais aos preparados: hashes, CRC, módulos, manifesto e versões conferidos. Os dois ZIPs não contêm instalador Python.

- Setup: `1c9d41b6d9d184a4530f35fe7971d2b79a68e16840460359e8defd586d9dc877` (13.526.371 bytes).
- Projeto: `cefcf3976eb0758970ce15954a47524c5797a4c26375f1a6edb98c47890183d1` (12.424.393 bytes).

Operador: instalar Preserve, confirmar `nexo versao` = 1.5.40, selecionar FARMA e executar exportação/auditoria em pasta nova com o mesmo exclusoes.json. Preservar todas as tentativas anteriores. A exportação Sheets não exige implantação da API, mas o envio posterior ao PostgreSQL exige a atualização coordenada deste contrato pelo Work conforme a seção acima. Nenhuma publicação real ou homologação financeira comercial foi executada pelo Codex.
