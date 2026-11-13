# NexoFlow 1.5.38 em preparação

Release corretiva autorizada: exportação Sheets para PostgreSQL aceita campos canônicos reordenados, valida hash físico e mantém guardas de origem. Publicação depende dos checks e pacotes do mesmo SHA. A 1.5.37 abaixo permanece como última distribuição comprovada até a publicação.

# NexoFlow 1.5.37 publicada

Publicada em **12/11/2026, 19:18:38 (America/Fortaleza)**, SHA `2683717431b1c4313efaaaef35cfaaf20236958a`. [Release](https://github.com/felipetelesbarbosa/NexoFlow/releases/tag/v1.5.37), [CI e pacotes](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/43314024652), [CodeQL](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/43314024795), [Meta](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/43314026009) e [publicação reutilizando os artefatos](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/43318519275). Downloads públicos conferidos: hashes, CRC, 571 entradas do manifesto, 123 módulos e versões dos executáveis. Sem implantação ou migração comercial.

Contrato definitivo Data Studio opt-in: `app/ds_backend`, `integrations/datastudio`, `connectors/datastudio_api`. Preservar o piloto e a migração 001 já aplicada; usar a 002 aditiva. Sheets continua padrão. Publicação de código não autoriza afirmar migração comercial. Ver docs/MIGRACAO WINDOWS POSTGRESQL DATA STUDIO.md.

# NexoFlow 1.5.36

A correção de leitura posterior à 1.5.36 usa a visão dedicada `farma.produtos_itens_datastudio` (migração aditiva 002). A visão de sete campos `farma.produtos_itens` e suas permissões Metabase são preservadas. Checkout Linux e Apps Script exigem o SHA validado da correção; Windows/publicador continuam 1.5.36. Ver docs/CORRECAO VISAO API BI ITENS.md. Não executar migração/carga comercial no trabalho Codex nem desbloquear estados à mão.

A distribuição 1.5.36 foi publicada em 12/11/2026, 03:06:30 (America/Fortaleza), no SHA `2cc09b864efedbb0ca2d2dc10c62c6bc23091e61`. CI, PostgreSQL/Docker, matriz Windows, Setup Preserve/Clean/rollback e pacotes aprovados; downloads públicos conferidos. O envio BI_Itens FARMA e a leitura Data Studio pelo piloto PostgreSQL continuam opt-in e dependem da implantação/homologação do Work. Não houve carga comercial, mudança na VPS ou migração da fonte de produção nesta entrega. Ver docs/BI ITENS POSTGRESQL FARMA.md.

A 1.5.35 foi publicada em 11/11/2026, 21:23:49 (America/Fortaleza), no SHA `c6204f0535914c48fec71ce5c009f0e8f9a1884a`. Checks, pacotes e downloads públicos conferidos. A 1.5.34 e anteriores permanecem intactas. A validação comercial da BI_Itens no Data Studio continua pendente.

A distribuição 1.5.34 foi publicada em 11/11/2026, 19:12:49 (America/Fortaleza), no SHA a25ae828b6dc732ecfcafa60db145e8cf27c84f5. A recuperação de resposta incerta da trava Sheets foi validada nos pacotes Windows; downloads públicos conferidos. A 1.5.33 e anteriores permanecem intactas. Isso não comprova recuperação da carga comercial nem resolve o aviso de reagregação do Data Studio.

A distribuição 1.5.33 foi publicada em 10/11/2026, 23:28:34 (America/Fortaleza), no SHA 7884d7007fd0c65cbf90bfc30c5c35dc6c9056fb, com recuperação da leitura da trava Sheets após 429/5xx. A 1.5.32 e as anteriores permanecem intactas. Os downloads públicos foram conferidos. Não executar cargas comerciais por causa de uma publicação de código.

Antes de qualquer nova tarefa, consultar a [Base Mestre permanente](docs/planejamento/DIRETRIZES_E_CONHECIMENTO_NEXOFLOW.md), os contratos especializados e o estado atual da main/release. Distinguir código, testes, distribuição, instalação, implantação e homologação comercial.

Reutilizar os planos, journals, capacidade e guardas existentes. Preservar byte a byte os dez módulos de assinatura 1.5.29/30. O workflow deve conferir os dois pacotes. Revisão manual WRITING não pode ser assumida automaticamente. Exclusões autorizadas só são reaplicadas no novo snapshot se o fato continuar idêntico; nunca apagar do SQLite original. Falhas da etapa histórica não podem avançar o checkpoint de sucesso nem declarar todas as fontes atualizadas. Publicação requer CI/CodeQL e Windows/Setup/artefatos aprovados no mesmo SHA.

## Conferência antes da entrega

- Reproduza a falha relatada com dados sintéticos e registre uma regressão que falhe antes da correção, quando houver comportamento executável alterado.
- Valide a integração da rotina afetada: argumentos da CLI, simulação, revisão, aplicação, estado persistido, códigos de saída e continuidade das etapas. Simule APIs e recursos externos; execute a lógica real de decisão e validação.
- Cubra sucesso, falha isolada, falha crítica, alteração após a revisão e retomada sem duplicidade, conforme o risco da mudança. Launchers exigem testes Windows do console e do executável distribuído.
- Confira o diff e execute lint, tipos, testes pertinentes, consistência e os checks exigidos pelo workflow. Valide o pacote instalado quando houver impacto operacional; não use apenas a contagem de testes como evidência de correção.
- Antes de anunciar publicação, confirme o sucesso do workflow do mesmo commit, a tag e os arquivos efetivamente disponibilizados no release. Preserve versões e nomes estáveis.
- Informe o que foi validado e seus limites: teste local, compilação para Windows, execução no Windows e teste do pacote são evidências diferentes. Não prometa ausência de erros nem apresente hipótese como causa confirmada.

## Regras do projeto

- Sempre informar quando uma alteração exigir nova release/Setup para chegar à instalação Windows/Local. Para mudanças exclusivamente documentais ou outras que não precisem de distribuição, não emitir esse aviso. Código na main não atualiza automaticamente C:\NexoFlow.


**Referência para trabalhos futuros com IA Manager, agentes personalizados, Weni CLI, ferramentas Python e disparos por Flows:** consulte [a base de conhecimento Weni CLI e agentes](docs/WENI%20CLI%20AGENTES%20E%20FLUXOS.md). É documentação de pesquisa, não autorização para alterar agentes, fluxos ou campanhas em produção.


- Use mensagens de commit curtas em português que descrevam a área ou a alteração, como `Automação`, `Documentação`, `Instalador` ou `Corrigir revisão da Recompra`. `NexoFlow 1.5.28` identifica a versão, não é uma mensagem obrigatória de commit. Separe alterações por área quando isso tornar a navegação do GitHub mais clara; não reescreva o histórico apenas para mudar os textos exibidos.
- A `main` é a única branch de trabalho do repositório. Atualize diretamente a `main`; não crie nem mantenha branches adicionais.
- A distribuição publicada usa NexoFlow 1.5.37, tag v1.5.37 e pacotes com sufixo 1.5.37. Novas publicações exigem autorização e validação. Para cada próxima publicação de atualização/hotfix/patch, incremente uma única vez: 1.5.38, ... 1.5.99; depois 1.6, 1.6.1, ... 1.6.99. Não incremente por commit ou tentativa de CI da mesma entrega. Preserve tags e releases anteriores; nunca sobrescreva uma versão anterior com um novo patch. Confira `VERSION` e `docs/VERSIONAMENTO.md`.
- Cada release deve mostrar a data da sua publicação. Não reutilize uma versão já publicada para código novo.
- O NexoFlow Windows é operacional e autônomo; Analytics e Noturno usam a integração Meta nativa, sem exigir Codex ou MCP. MCP é opcional. O **NexoFlow Hub** tem desenvolvimento e homologação Linux expressamente autorizados na Etapa 2, isolados em `hub/`, com dados sintéticos, PostgreSQL temporário e escrita real bloqueada. Consulte [o núcleo](hub/README.md) e o [planejamento](docs/planejamento/README.md). Não transformar o Windows em cliente dependente do Hub, não alterar serviços/volumes da VPS nem abrir portas públicas nesta fase. Commits Hub usam `[skip release]`, sem incrementar a versão ou publicar releases Windows. Alterações compartilhadas exigem regressão Windows.
- Preserve as credenciais e os diagnósticos privados fora do Git e dos pacotes públicos.
- Use os nomes de pagamento: 0 Cancelado, 1 Dinheiro, 2 Débito, 3 Crédito, 4 Ticket, 5 Pix por Link de Pagamento, 6 Pix no POS.
- Horários operacionais usam `America/Belem` (UTC-3).
- Status de pedido: EmAberto=-2, PendenteDePagamento=-1, EmProcessamento=0, ProntoParaRota=4, EmTransito=1, Concluido=2, Cancelado=3. Estados abertos permanecem em rechecagem. Todos os estados documentados não cancelados (-2, -1, 0, 4, 1, 2) contam como venda validada; status 3 ou pagamento 0 exclui a venda. Weni, Analytics e Recompra usam a mesma regra. No Analytics, reconsultar status dos pedidos já registrados somente quando a data do pedido estiver entre hoje e 20 dias atrás (inclusive), em America/Belem. Preservar pedidos mais antigos sem reconsulta automática, mantendo a consulta por CPF para descobrir novas compras e a validação inicial de pedidos ainda não registrados.

- Pedidos cuja resposta oficial, com identidade, proprietário e data verificados, não contém itens são tratados como cancelados e ignorados em vendas, produtos do dashboard e Recompra, sem bloquear a carga. Falhas de consulta e respostas malformadas continuam sendo erros.

- Textos apresentados ao usuário devem usar português brasileiro (pt-BR), com acentos e cedilha. Preserve identificadores técnicos. BAT/CMD em UTF-8 sem BOM com `chcp 65001`; PowerShell em UTF-8 com BOM; HTML com `lang="pt-BR"`; metadados dos executáveis em pt-BR.

- Consultar primeiro CPFs válidos; depois inválidos preenchidos não zerados. Valores ausentes, inteiramente zerados ou malformados são pendências cadastrais e não autorizam consulta por CPF. Repor zeros à esquerda até 11 dígitos somente se os dígitos verificadores forem válidos. Não alterar dígitos existentes nem confundir presença na API com validade matemática.

- CPF inválido exige primeiro nome correspondente (normalizando acentos, maiúsculas e símbolos) ou número local do telefone correspondente, ignorando +55 e DDD, do mesmo cliente da Weni. Bloqueie ausência, divergência e ambiguidade; cache compartilhado de CPF não compartilha identidade/pedidos.

- Recompra mantém a política de bloqueio por recusa/Opt-Out, inclusive quando marketing_opt_in está afirmativo; campo vazio não é tratado como consentimento registrado. Novas inclusões e trocas de referência exigem evento D+25 ainda futuro, reconferido antes do POST. A passagem do horário, sozinha, não remove contatos já admitidos com a mesma referência.

- No histórico paginado, a regra autorizada na 1.5.18 mantém pedidos com divergência isolada entre lançamentos de frete (codProduto=0/descrição vazia) e frete oficial do cabeçalho. O valor financeiro vem do cabeçalho; preservar os dois valores e a diferença como aviso, sem duplicar frete ou incluir esses lançamentos em produtos/quantidades. Cancelamento, identidade, itens malformados, descontos e total explícito incompatível continuam protegidos. A política não altera automaticamente registros antigos que perderam itens/valores; exigir resposta oficial/reconciliação. Fora do histórico, preservar os validadores legados não alterados nesta entrega.

- `clientes/FARMA` pode retornar `cliente`, `ultimoPedido` e `itens`. Guardar snapshots completos e verificados em memória por CPF/ID durante a execução. Pedido/cliente/itens precisam pertencer à mesma identidade; respostas ausentes, incompletas ou ambíguas usam consulta individual, sem concluir ausência de compra, exceto na Recompra FARMA: essa rotina usa exclusivamente a consulta geral por fase e deixa evidências insuficientes pendentes, sem HTTP individual. O histórico é observado uma vez por índice carregado, inclusive fora da Recompra; falha de gravação não marca a observação como concluída. `CPF_NAO_CONFIRMADO_BASE_GERAL` e `PEDIDO_NAO_CONFIRMADO_BASE_GERAL` são pendências explícitas, nunca ausência de compra comprovada. Regra autorizada: contato no grupo com consulta incompleta é removido preventivamente quando `pedido_data` físico da Weni completa sete dias (168 horas, America/Belem); vale para FARMA e PET. Data ausente, inválida ou futura não permite inferir o prazo. Manter cadastro, campos, estado de admissões e auditoria; revalidar nas próximas cargas. Antes de remover, consultar novamente a fonte e reler o contato, bloqueando alterações posteriores à revisão. Remoção confirmada não encerra a pendência de validação. Cancelamento, pagamento inválido e recusa já comprovados na Weni continuam autorizando a remoção prevista, sem depender de consulta de pedido. Cadastro só preenche campos vazios e mantém evidência na revisão. Endereço exige correspondência única com o último pedido (CEP, cidade/UF, logradouro, número e complemento), inclusive quando o endereço correspondente não é o principal. Leituras de preparação não podem autorizar uma aplicação posterior: Recompra e deduplicação reiniciam as leituras antes do apply. O arquivo PET usado como referência de formato não alimenta a operação FARMA.

## Perfis de segmento

- Os mesmos executáveis operacionais perguntam o segmento antes de executar; o menu propaga `NEXOFLOW_PERFIL` antes dos imports. Agendamentos podem definir --perfil explicitamente. Nunca trocar perfil em um processo que já carregou configurações ou clientes.
- Preservar os mesmos contratos de auditoria, rota direta/proxy, retentativas e aplicação nos dois perfis. Credenciais Weni, três destinos Sheets, logs, importações, revisões e estado devem permanecer separados. Revisões e manifestos copiados entre segmentos devem ser recusados.
- FARMA mantém filtro de produtos humanos e D+25. PET exige vínculo oficial PET, preserva seus itens e usa D+30, pedido_data, compra_recente e opt_in_marketing Sim/Não, sem exigência de maioridade. Pagamento da Recompra exige código documentado de 1 a 6; falhas de consulta permanecem pendentes em ambos os perfis.

- Cargas FARMA e PET podem coexistir; duas cargas do mesmo segmento continuam bloqueadas. Launchers nativos e BAT do Noturno usam o mesmo contrato Win32. Instalação/desinstalação precisam das travas global e dos dois segmentos antes de modificar arquivos. Estado, logs e destinos permanecem isolados.

- O check-up precisa passar enquanto o próprio Noturno mantém a trava do segmento, inclusive com FARMA e PET ativos. Fixtures usam nomes de trava exclusivos e somente diretórios temporários. Inspeção de PE não inicia outra carga; nenhum modo de teste pode desativar as travas operacionais. Validar essa combinação no pacote instalado.
- O check-up operacional verifica componentes Python, dependências e consistência sem executar a suíte de desenvolvimento ou scripts opcionais do instalador/Codex/MCP. Preserve perfil e rede da sessão. A suíte completa continua obrigatória no CI; `app/run_checkup_tests.py --development-tests` é explícito e mantém suas falhas visíveis. Diagnósticos de credenciais e conexões continuam nas etapas das integrações; aprovação local não comprova acesso às APIs. Não adicionar bypass de PowerShell nem remover marca de origem para aprovar o check-up.

- Percentual de falhas individuais de consulta gera aviso por lote, sem descartar contatos/pedidos válidos nem avançar o cursor parcial do Analytics. Autenticação inválida, circuito aberto e falha estrutural de armazenamento continuam bloqueantes. Guardas da Recompra comparam campos físicos da Weni; aliases analíticos de PET não representam mudanças externas.

- Uma resposta válida do cliente com `ultimoPedido: null` representa ausência de pedido, não falha de API ou de segmento. Não buscar pedido antigo da Weni para substituir esse null, criar venda, cancelamento ou admissão na Recompra. Campo omitido não comprova ausência. A identidade do CPF continua verificada; ausência de pedido não comprova vínculo cadastral com o segmento nem autoriza deduplicação/enriquecimento sem evidência própria.

- Anúncios Meta usam eventos CTWA oficiais por período, com vínculo exato à URN nativa. Texto de anúncio e simples resposta HTTP 200 não confirmam atribuição ou venda. Corrigir campos existentes somente com evento correspondente comprovado; preservar campos corretos e atribuições fora da cobertura. Pendências de evento ou gravação conservam cursor próprio para reconsulta. Título/URL não são inventados a partir de eventos que não os retornam.

- FARMA usa pedido_data (Data e hora) e ultimo_pedido (Texto com ID oficial, compatível com localizadores legados), sem exigir/escrever ultima_compra. PET mantém compra_recente. Pedidos sem segmento comprovado ou explicitamente nulos não autorizam venda/admissão/enriquecimento e não geram pendência de consulta; rede, autenticação e respostas malformadas preservam suas classificações.

- Variantes brasileiras de celular com/sem nono dígito servem somente para impedir criação duplicada. Não comprovam identidade/CPF nem autorizam fusão, exclusão ou alteração do telefone. CPF ausente/divergente e múltiplos contatos exigem reconciliação; a busca é repetida antes do POST.

- Atualização Preserve mantém secrets_config.py, credentials, logs e importacoes no lugar, inclusive no rollback. Não renomear/apagar esses dados para contornar handles de diretório; cópias do payload não os sobrescrevem. Validar no Windows com raiz/logs/credenciais/importações abertos, rollback e hashes de programa. Clean preserva suas regras próprias e aborta com dados anteriores intactos se houver bloqueio.

- PET não calcula, exige nem grava maior_de_18_anos. Idade continua informativa; o endereço cadastral usa o mesmo segmento do pedido na conferência. Não aceitar evidência de campo que não foi produzido pela política do perfil.
- Recompra incremental mantém cache e índice por segmento no estado existente. Após uma coleta completa confirmada, consultar contatos Weni modificados desde o cursor com 15 minutos de sobreposição, comparar hashes da base geral atual, reavaliar novos/alterados, prazos e pendências. O modified_on da Weni não representa atualização de pedido na API. Primeira execução, índice incompatível e --full cobrem toda a base. Dry-run não avança checkpoint; estado/recusas/guardas e resultados incertos continuam protegidos.
- Persistência de compra somente local não é POST Weni: contabilizar separadamente, acumular e salvar com checkpoint atômico. Intenção de inclusão no grupo permanece durável antes do POST. Nenhuma aceleração autoriza reaplicar admissão incerta. A janela de preparação 0..25/30 dias permanece distinta do envio D+25/30; não admitir retroativamente.
- Deduplicação por CPF válido e cliente oficial único considera conjuntos de pedidos comprovados, incluindo histórico. Preservar o contato com pedido, consolidar conjuntos iguais e manter conjuntos diferentes com nomes numerados estáveis após revisão. Sem pedido, conservar a identificação por telefone nativo único. Não apagar apenas por coincidência de nome/telefone, não transferir Opt-In e não reutilizar revisões destrutivas anteriores à nova política.

## Histórico paginado autorizado

- Contrato `GET /api/Delivery/pedidos/{segmento}` recebido; implementar Windows primeiro e Hub depois da regressão. Token privado em query, sem redirecionamentos/logs sensíveis; limite ajustável, cursor inclui limite, completude por IDs antes de filtros.
- Histórico oficial usa cliente/pedido por ID, mesmo sem Weni. No novo vínculo histórico, CPF inválido exige nome e telefone ou nome e e-mail concordantes, sem ambiguidade; regra mais restritiva explicitamente autorizada. Não alterar silenciosamente validadores legados.
- Release Windows autorizado após checks; Hub somente código/homologação sem release ou escrita comercial. Datas finais/descontos não demonstrados permanecem pendentes, nunca inventar pagamento ou cobertura completa.

## Eficiência da publicação

- Para releases autorizadas, preferir uma única geração no commit final com `[skip release] [preparar pacotes]`, seguida de publicação com `validated_run_id` da execução aprovada do MESMO SHA. Não repetir preparação completa e publicação completa no mesmo commit. Conservar os checks obrigatórios e as quatro combinações da matriz Windows; não repetir a quinta suíte no build. Usar o monitor determinístico e reler logs somente diante de falha ou mudança relevante. Isso reduz trabalho redundante de CI e do modelo. Ver [rotina eficiente](docs/RELEASE%20EFICIENTE.md). O novo caminho é posterior à 1.5.33 e não modifica seus pacotes.
