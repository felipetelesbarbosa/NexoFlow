# Relatório técnico: publicador histórico SQLite / Sheets

Entrega desenvolvida em `main` e incorporada à preparação da **1.5.21**, com publicação Windows posteriormente autorizada pelo usuário, condicionada aos checks e pacotes validados. A release 1.5.20 permanece preservada. Referência comparada: `c94158d35c40d5f9e424731d672de257a7d78ec4`; main atualizada para `8c068f5` antes da implementação. O SHA final e os resultados dos workflows são informados na entrega e podem ser conferidos no histórico Git. FARMA é o piloto; PET somente isolamento sintético. Não se executou carga comercial, nova consulta FarmaLíder, Weni, Noturno, Recompra, implantação VPS ou edição de relatório publicado.

## Causas confirmadas e mudanças

| Problema comprovado no código de referência | Correção |
|---|---|
| Leitura física e `_physical=True` contornavam o particionamento | Porta `SheetsTransport` usando manifesto, lease, intenções e criação oficial |
| Papéis diferentes para as novas tabelas do Histórico | `storage_role` compartilhado pelo roteador, manifesto e publicador |
| Sem reserva global de grade antes do primeiro lote | Planejador puro por arquivo, partes, padding e índice; OAuth e origem conferidos no preparo |
| Snapshot integral e releitura total a cada 200 linhas | Índices em disco na revisão, baseline compartilhado e backup somente de intervalos afetados; conferência integral no fechamento |
| Ausência de piloto e retomada local vinculada ao mesmo plano | `--max-lotes`, lotes determinísticos, estados pendente/SENDING/DONE/RESTORING e comprovantes |
| Risco de repetir POST após resposta perdida | Releitura de chaves/coordenadas/valores antes de decidir novo POST; intenção de manifesto também durável |
| Leitor não tinha schemas históricos/papel Histórico | Registro controlado e união das partes presentes/futuras com validação, limites e bloqueio WRITING |
| Sem resumo pequeno para leitura anual e confronto financeiro | `BI_Historico_Resumo` e relatório privado `historico_conferencia_v1` |

A revisão adicional encontrou e protegeu: linha removida fora do lote, mudança de pasta/permissão após preparo, parte criada antes da queda mas fora do snapshot inicial, alteração de coordenadas locais, diferença de um centavo e data-hora sem offset perto da meia-noite. A conferência identifica lote/parte por hashes privados; schema/segmento/duplicação não podem produzir um total aparentemente completo.

Não houve alteração do contrato financeiro, da identidade, do coletor histórico ou da atribuição comercial. O Hub não importa estes módulos de publicação; não foi necessário mudar sua persistência, API, worker ou migrações. Testes PostgreSQL específicos não foram executados para código Hub não afetado. A implantação permanece com o Work.

## Arquivos

Novos módulos: `app/history_capacity.py`, `history_publication.py`, `history_sheets_transport.py`, `history_snapshot.py`, `history_conference.py`, `history_publish_cli.py`.

Integração: `app/order_history_sheets.py`, `run_order_history.py`, `google_sheets.py`, `sheets_storage.py`, `sheets_partitions.py`, `sheets_continuation.py`, `pyproject.toml`.

Leitores: `connectors/continuacoes/{Code.js,Tables.js,Schemas.js,README.md}` e cópia compartilhada `connectors/looker_abc/Tables.js`. Fontes existentes continuam com seus IDs/campos; nenhum Apps Script foi implantado automaticamente.

Testes: `tests/test_history_{capacity,publication,sheets_transport,conference,publish_cli,attribution_boundary}.py`, `test_history_connector.cjs`, `benchmark_history_publication.py`; adaptação dos dois consumidores de `HistorySheets` em `test_order_history.py` para o protocolo revisado e inclusão do leitor novo em `test_sheets_setup.py` e no job de qualidade. Não se removeu a regressão dos consumidores legados.

Documentação: este relatório, `PUBLICADOR HISTORICO SQLITE SHEETS.md`, `HISTORICO PEDIDOS.md`, `CONTINUACOES.md` e README do conector.

## Ensaios medidos: sintéticos, sem latência Google

Benchmark reproduzível em `tests/benchmark_history_publication.py`, usando SQLite real temporário e o adaptador/RolloverManager reais sobre Sheets/Drive simulados. Parte reduzida a 250 linhas para atravessar fronteiras. A grade inicial do arquivo Histórico é 18.413.260; margem 18 milhões e teto configurado 20 milhões. OAuth, arquivos, pastas e permissões são fixtures, não acessos reais.

| Medida | 100 pedidos | 1.200 pedidos |
|---|---:|---:|
| Linhas planejadas nas cinco tabelas | 205 | 2.405 |
| Lotes | 5 | 23 |
| Novos arquivos de partes | 2 | 10 |
| Preparo | 0,014 s | 0,092 s |
| Aplicação | 0,090 s | 2,400 s |
| Conferência | 0,047 s | 2,298 s |
| Tentativas de leitura instrumentadas, incluindo conferência/repetição | 169 | 511 |
| Tentativas de escrita instrumentadas, inclusive controle/criação | 39 | 147 |
| Chamadas de escrita de células no modelo, inclusive manifesto/cabeçalho | 18 | 68 |
| Backup por lotes, acumulado | 72.456 bytes | 829.736 bytes |
| Maior backup individual | 41.087 bytes | 82.353 bytes |
| Escritas de dados na repetição da mesma revisão | 0 | 0 |
| Diferença pedidos × LTV | 0 centavos | 0 centavos |

Esses contadores são operações do modelo e das tentativas instrumentadas, **não HTTPs comerciais nem previsão de duração em produção**. Criação de partes e confirmação têm custo adicional; não se eliminaram leituras de segurança. O custo de backup cresce com os intervalos escritos, em vez de um snapshot integral novo por lote. O baseline fica uma vez no journal privado. A repetição confirma sem reaplicar.

Projeção versus observação: na carga de 1.200, Histórico original permanece exatamente em 18.413.260 células; Dashboard em 424; Operação em zero na fixture. Cinco partes de pedidos: quatro grades de 3.750 e uma de 3.075; cinco de itens: quatro de 2.750 e uma de 2.255. Os valores físicos observados coincidiram com o plano. A reserva de crescimento do índice é tratada como limite superior, não espaço a ser obrigatoriamente alocado.

Ensaio puramente de capacidade com **1.100.000 pedidos + 207.582 linhas de itens**: reserva global respeitou 20 milhões e atravessou duas fronteiras de pedidos (três partes com limite de 500 mil linhas incluindo cabeçalho). O caminho físico antigo não comportaria a estimativa de 6.298.508 células adicionais frente a 1.586.740 livres; essa aritmética e a grade são sintéticas/configuradas, não reconciliação dos dados atuais do cliente. Delta real e número de itens são obtidos no preparo a partir da cópia e dos destinos.

## Cobertura de testes

Implementação inicial em `01260749c17c736f4d3e98f4c45d47f5f0e54a36`, complementada pela guarda de tipos em `eb73b575791f07529bb022f00e759b2e34c2c3ba`. Validação local final: **1.852 testes Python, sem falhas, 73 ignorados por condições de plataforma/ambiente**; **30 testes Node aprovados**; Ruff e Pyright sem erros; auditoria de consistência e documentação HTML aprovadas; pip-audit sem vulnerabilidades conhecidas nas dependências principais/webhook. Gitleaks aprovou o histórico Git e a exportação dos arquivos destinados ao commit. Credenciais locais ignoradas não foram incluídas nessa exportação. Testes ignorados não contam como validação real Windows/Google.

Os workflows Windows/qualidade/segredos e CodeQL do commit final devem ser conferidos no GitHub; o resultado efetivo e o SHA final acompanham a entrega. Os commits de desenvolvimento/preparação usam `[skip release]`; a publicação autorizada é executada pelo workflow manual no mesmo SHA, após CodeQL e checks aprovados.

- Preparo sem escrita; perfil, schema, permissões, capacidade e ausência de OAuth; SQLite com WAL, query_only e hash original preservado.
- Comando real `nexo_cli.run` em processo de testes com factories Weni/Farma que falham se acionadas: preparar, piloto, conferir, retomar, conferir mensal e rollback, com códigos 0/3.
- Fronteiras reduzidas com comparação de cada chave/valor, atualização na parte anterior, cancelamento, revisão LTV, fonte vazia e dois itens do mesmo SKU com IDs diferentes.
- Falha antes do POST, resposta perdida após POST, queda entre manifesto remoto e recibo local, edição posterior, mudança de manifesto, coordenadas de journal alteradas e rollback interrompido.
- Conferência por mês/TOTAL: cliente em dois meses contado uma vez no total, pedido duplicado em duas janelas, cancelado, pendência sem emissão, bases em centavos e discrepância sintética de um centavo localizada.
- Data Studio: partes futuras, parte ausente, schema/tipo/chave/segmento divergente, WRITING, linha além da contagem confirmada, filtro de um dia/vazio, resumo anual, corte incompatível de resumo, detalhe de itens com revisão coerente e limite de 200 mil sem truncamento.
- Meta/Google: mensagem estruturada → plano de campos → contato normalizado → BI_Ads, evento duplicado, clique sem ID oficial de criativo, URL colada, identificação perdida, canal multicanal não inferido e compra entre toque anterior/posterior. Preservação do pedido; CAC/ROAS não fabricados. A regressão existente também cobre CTWA, custos desconhecidos, duplicação e separação FARMA/PET.
- Regressão geral Windows Python, lint, tipos, consistência, documentação HTML, dependências e varredura de segredos integram a validação; resultados finais e CI do mesmo SHA são fornecidos na entrega.

## Limites e homologação pendente

Não foi fornecido um destino privado de homologação separado e comprovado nesta tarefa. Portanto **nenhuma planilha, dashboard ou SQLite comercial foi lido/alterado para validar esta implementação**. Não se alegou equivalência de snapshots comerciais ou ausência de Google no projeto inteiro a partir da amostra do Work.

A configuração efetiva de OAuth, pastas e compartilhamentos, quotas, ACL Windows, latência, execução no executável distribuído e implantação privada do conector exigem homologação do Work. A publicação da 1.5.21 executou a suíte Windows, os launchers e os testes de instalação Preserve/Clean/rollback no pacote efetivamente gerado (workflow 42405811308, commit 29bba747a6cc5dcc57e1c547f94dc3a6af3fb6f1). O smoke test instalado inclui os novos testes do publicador. Não substituir arquivos avulsos na operação. Os resultados efetivos dos workflows e os hashes dos pacotes acompanham a entrega; não confundir aprovação do pacote com homologação comercial em Sheets.

O lease coordena escritores que obedecem ao contrato. Sheets não oferece transação ACID abrangendo três arquivos nem compare-and-swap para edições manuais arbitrárias de células. Não editar/ordenar as tabelas durante a carga. As guardas detectam edições nos cortes conferidos e bloqueiam conflitos observados, sem prometer eliminar corridas com terceiros que ignorem a trava. Uma publicação parcial fica indisponível ao leitor até fechar ou reconciliar.

Permanece o alerta de cobertura civil da API; não se refaz carga anual para publicar. Recebimentos brutos antigos por mês não são inventados. Detalhe acima dos limites do conector exige recorte ou outra capacidade analítica; a visão anual deve usar resumo.

O [roteiro operacional para o Work](PUBLICADOR%20HISTORICO%20SQLITE%20SHEETS.md) inclui comandos, totais por tabela, ligação de fontes, backups, retomada, rollback e critérios de liberação FARMA antes da futura réplica PET. A execução comercial permanece uma etapa separada.

## Correção durante a validação Windows

O CI de `9f5f03c` comprovou WinError 32 somente no encerramento do teste que altera coordenadas do journal: o contexto SQLite do teste não fechava a conexão. Corrigido com `contextlib.closing` e commit explícito, sem ignorar a falha ou forçar remoção. As conexões do publicador já usavam fechamento explícito. A suíte Windows foi repetida e aprovada no commit 29bba747a6cc5dcc57e1c547f94dc3a6af3fb6f1, publicado na release 1.5.21 em 07/11/2026.

O orçamento de 240 segundos é compartilhado entre as leituras de pedidos e itens no mesmo getData, evitando reiniciar o prazo ao passar à segunda tabela. Regressão sintética recusa uma segunda leitura que já consumiu o prazo global.

A regressão de aba legada no arquivo Operação (quando o papel autorizado é Histórico) falhou antes da guarda adicional e passou depois. O preparo agora verifica essas abas órfãs em todos os arquivos inventariados, bloqueando antes de criar cópia ou gravar fatos; o legado não é movido nem apagado.


## Correção das três origens — entrega 1.5.22

Causa comprovada: `StorageSetup._stamp()` da 1.5.21 só marcava Dashboard. O
transporte exigia os três marcadores corretamente. A fixture de transporte
pré-marcava origens e ocultava a falha de inicialização. Regressão sem marcadores
falhou em Operação antes da correção. O fluxo agora valida todos os marcadores,
pré-verifica permissões/pastas nos três destinos, confere o índice existente e
executa `stamp_book` para cada papel sob lease. Edição pela conta de serviço
passou a ser condição explícita da comprovação Drive. Sem fatos comerciais novos.

Arquivos operacionais: `run_sheets_continuation.py`, `sheets_continuation.py`,
`sheets_provisioning.py`. Regressões em `test_sheets_setup.py` e
`test_history_sheets_transport.py`: configuração realmente nova, três origens,
idempotência, inicialização parcial, resposta perdida/lease expirado, conflito de
papel/segmento/hub/localização/duplicação, IDs repetidos, falhas Drive e permissão,
mais caminho configurar → ativar → capacidade → piloto → conferir → rollback →
retomar → conferir → repetição sem deltas. O smoke do pacote instalado inclui os
novos testes de origem e rede, além das suítes do publicador. O código do conector
não mudou: cinco schemas e verificações de WRITING/partes/segmento permanecem.

A release reúne `aed1ac1` (rede e Setup) e preserva todas as releases anteriores.
A coleta anual, Weni, Recompra, planilhas comerciais, relatórios e VPS não foram
executados/alterados. A análise do anexo agregado fecha em centavos; anomalias
individuais dependem da inspeção pontual privada do SQLite pelo Work.
Os resultados do CI/CodeQL e os hashes efetivos acompanham a entrega publicada;
não presumir homologação comercial a partir de testes simulados.
