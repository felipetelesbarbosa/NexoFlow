# Meta Ads no NexoFlow Analytics

O Analytics e o Noturno consultam a Marketing API da Meta pelo cliente HTTP nativo `app/meta_ads_client.py`. O Setup 1.5.42 retira a oferta de servidor MCP local e os instaladores de Codex CLI.

Use a instalação em `C:\NexoFlow`, com o Python e as dependências preparados pelo Setup. O pacote Python inclui o cliente e o módulo de configuração `app/meta_ads_settings.py`.

## Credencial local e contas permitidas

O coletor nativo lê a credencial privada no caminho usado nas versões anteriores. Em uma atualização, mantenha o JSON existente neste local.

```text
C:\NexoFlow\credentials\mcp\meta_ads_credentials.json
```

Se o arquivo não existir, copie **localmente** o modelo `configuracao/meta_ads_credentials.example.json` para esse caminho e configure:

- `access_token`: credencial autorizada para leitura de anúncios; não inserir no código, nos logs, no Git ou no chat.
- `api_version`: versão da Marketing API compatível com o cliente.
- `allowed_ad_account_ids`: lista explícita de contas autorizadas. A lista limita a consulta; não concede uma permissão nova na Meta.

Não remova a allowlist nem amplie as contas automaticamente. O aplicativo não altera campanhas, orçamento, anúncios, públicos ou permissões. Consultas Graph são somente GET; a gravação analítica autorizada ocorre no Google Sheets do NexoFlow.

O arquivo real de credencial é ignorado pelo Git e proibido nos pacotes públicos. O Setup pode copiar os bytes para recuperação, mas não interpreta ou imprime o token. A instalação/atualização mantém token e allowlist locais, inclusive na opção **Clean**. Nessa opção, as demais configurações, credenciais Google e estados seguem as regras existentes de instalação limpa; a exceção é somente a credencial Meta. Arquivo Meta já presente no destino não é sobrescrito pela cópia de backup.

## Ativação

A configuração fica no `secrets_config.py` local e usa:

| Chave | Regra |
| --- | --- |
| `META_ADS_ENABLED` | Padrão `False`; habilitar com `True` após conferir credencial, contas e destino. No PostgreSQL, usa as tabelas Meta do contrato. Em perfis legados Sheets, prepara as cinco abas Meta ausentes ou vazias. |
| `META_ADS_START_DATE` | Data inicial histórica desejada, no formato ISO `AAAA-MM-DD`. |
| `META_ADS_OVERLAP_DAYS` | Sobreposição da incremental; padrão **7 dias**, para reconciliar indicadores que a Meta pode atualizar após a primeira coleta. |

Configure a credencial Meta, os tokens Weni e a credencial do destino escolhido no perfil. Para o modo PostgreSQL FARMA, siga o [guia de operação Windows e VPS](OPERACAO_WINDOWS_VPS.md). Sheets usa os arquivos e as permissões Google dos perfis legados.

Execute o **NexoFlow Analytics** pelo aplicativo normal, selecionando o segmento. O **Noturno** utiliza a mesma integração ao executar Analytics. Para consultar as opções do comando dedicado instalado:

```powershell
cd C:\NexoFlow
.\.venv\Scripts\python.exe app\run_meta_ads.py --help
```

A primeira coleta usa a data inicial configurada; incrementais reaproveitam o estado e reconsultam a sobreposição. Um token ausente, acesso negado ou consulta incompleta precisa aparecer como diagnóstico da etapa, sem ser confundido com investimento zero ou apagamento dos dados anteriores. Preserve o estado e os relatórios privados para revalidar a etapa.

## Estrutura aditiva e revisão

A partir da 1.5.14, o Analytics habilitado prepara ou retoma automaticamente as cinco abas Meta nos arquivos já configurados do segmento:

| Arquivo | Abas |
| --- | --- |
| Operação | `Meta_Ads_Diario`, `Meta_Ads_Campanhas`, `Meta_Ads_Anuncios` |
| Dashboard | `BI_Meta_Resultados`, `BI_Meta_Conversoes` |

Na preparação desta entrega, foram conferidas **dez abas Meta**, cinco em FARMA e cinco em PET, nos arquivos existentes e nas pastas de cada segmento. Os IDs dos arquivos permanecem os mesmos e as 54 abas previamente existentes foram preservadas. Essa conferência comprova a estrutura preparada; não comprova que métricas reais já tenham sido carregadas nem que páginas do Data Studio tenham sido editadas.

O bootstrap cria uma aba ausente ou inicializa uma aba realmente vazia com o cabeçalho canônico. Uma aba existente com schema correto é reutilizada; os dados, históricos, IDs dos arquivos e as demais abas são preservados. Cabeçalho divergente, conteúdo inesperado ou mudança após a leitura bloqueiam a gravação e exigem revisão manual. Uma retomada reconfere a estrutura antes de continuar e não transforma falha em investimento zero.

O comando dedicado mantém a simulação por padrão e exige revisão e `--confirm-schema` para aplicar no mesmo perfil/período, por exemplo:

```powershell
.\.venv\Scripts\python.exe app\run_meta_ads.py --perfil PET --start 2026-10-01 --end 2026-10-31 --dry-run --review logs\PET\privado\meta_ads_review.json
.\.venv\Scripts\python.exe app\run_meta_ads.py --perfil PET --start 2026-10-01 --end 2026-10-31 --apply --confirm-schema --review logs\PET\privado\meta_ads_review.json
```

Revise o resultado da simulação antes do segundo comando. Confirmação de schema não autoriza apagar dados, migrar uma aba divergente nem trocar o destino de outra marca. Arquivos fornecidos por `--input` são fixtures de simulação offline e nunca autorizam aplicação em produção. Confira as tabelas e os destinos do perfil antes de habilitar a carga. O bootstrap aditivo do Analytics não autoriza migração destrutiva nem correção automática de schemas divergentes.

## Conciliação de pedidos da Weni no Windows

Com Meta Ads ativo no perfil FARMA, o Analytics e a etapa Analytics do Noturno cruzam os contatos e eventos oficiais CTWA da Weni com os pedidos da FarmaLíder. O resumo fica no log da execução. A seção `reconciliacao_pedidos_weni` do arquivo `logs/privado/meta_ads_ultima_execucao.json` registra os totais e o motivo por pedido, com os IDs de anúncio e evento disponíveis. Guarde esse arquivo no ambiente privado.

A revisão por pedido parte dos contatos com origem Meta cuja chegada caiu no período de Belém. Ela verifica o último pedido informado pela Weni e aplica os mesmos critérios usados na publicação. A venda exige pedido elegível, evento oficial vinculado ao mesmo contato por UUID, último toque anterior ou simultâneo ao pedido e uma linha diária do anúncio na janela e no fuso da conta Meta. O diagnóstico distingue falta de evento, último toque ambíguo, pedido sem vínculo elegível e ausência da linha de veiculação. A data da chegada do contato e a data do anúncio atribuído podem cair em dias diferentes.

O recorte de hoje até D−20 vale para a reconsulta de pedidos da FarmaLíder, inclusive o histórico incremental quando habilitado. A atualização incremental da Meta tem uma sobreposição própria de sete dias por padrão, configurável em `META_ADS_OVERLAP_DAYS`. O vínculo com a venda segue a política de último toque observado descrita acima. [Guia do histórico automático](ANALYTICS%20HISTORICO%20AUTOMATICO.md)

Para pedidos do histórico paginado, a auditoria mostra em `evidencias_ctwa_paginados` quantos têm evento CTWA anterior do mesmo contato, quantos têm eventos ambíguos ou posteriores e quantos carecem de vínculo. Se houver evento anterior inequívoco, o arquivo privado registra o anúncio, o evento e o intervalo em segundos até o pedido. Essa versão registra os resultados em auditoria. [Regra do histórico de pedidos](HISTORICO%20PEDIDOS.md)

#### Homologação do atendimento humano FARMA

Na FarmaLíder, a Lili fornece orçamentos e encaminha o cliente. A venda é realizada pelo agente humano. A tag `Pedido Finalizado` registra que houve um pedido no atendimento em que foi aplicada. `Orçamento` indica orçamento registrado. O evento de transferência indica encaminhamento e pode ser usado para medir oportunidades.

Verifique a sequência no mesmo projeto FARMA: metadados CTWA do anúncio na Weni, identidade da conversa, atendimento humano e tag do próprio ticket. O evento CTWA fornece o ID do anúncio, do clique e da mensagem externa. Use o ID da conversa quando disponível e confirme a identidade do atendimento na origem. A `ds136` publica totais por dia. A validação individual usa o detalhe da Weni Flows e do Weni Chats.

Conte a tag `Pedido Finalizado` uma vez por atendimento comprovadamente ligado ao anúncio. Para o CPA e o ROAS, concilie o atendimento com um pedido oficial único e válido da FarmaLíder, com valor, status e pagamento conferidos na API. Um identificador do pedido gravado no próprio ticket resolve o vínculo. Vários pedidos candidatos para o mesmo atendimento deixam a receita pendente de conciliação. Os rótulos de orçamento ou transferência medem etapas distintas da venda.

Para conferir no Analytics da Weni, abra **Live Desk → Dados históricos**, selecione o período e aplique **Pedido Finalizado** no setor **Delivery FarmaLíder**. Busque o nome em **Contato**. Identifique o ticket pelo encerramento e pela duração. O mesmo contato pode ter vários atendimentos ou pedidos no período. Compare a emissão de cada pedido com o ticket correspondente e use o ID oficial do pedido na deduplicação. A confirmação manual pelo Analytics pode ser feita enquanto a coleta automática das tags por ticket aguarda acesso à API do Weni Chats.

#### Métricas da página Anúncios em produção

| Nome no Data Studio | Regra |
| --- | --- |
| **Pedidos na conversa do anúncio** | Pedidos válidos fechados no atendimento humano iniciado pela conversa do anúncio, com a tag `Pedido Finalizado` vinculada ao ticket. A receita dessa categoria entra no ROAS principal. O CPA principal divide o investimento da Meta da FarmaLíder pela quantidade desses pedidos. |
| **Pedidos após a conversa do anúncio (até 7 dias)** | Pedidos válidos do mesmo contato em outro atendimento, emitidos em até 168 horas após a abertura da conversa do anúncio. Exibir quantidade e receita próprias. |

O **CAC de novos clientes** divide o investimento da FarmaLíder no Meta pelos clientes distintos cuja primeira compra válida registrada no histórico FARMA desde 2020 foi classificada em **Pedidos na conversa do anúncio**. Use a identidade oficial do cliente e compare o ID da compra atribuída com o primeiro pedido elegível no histórico integral da revisão READY. Compras anteriores ao período do painel identificam clientes recorrentes. Com histórico incompleto ou sem novos clientes atribuídos, o CAC fica indisponível.

Classifique cada ID oficial de pedido uma única vez no segmento FARMA antes de agregar por anúncio e período. Um vínculo comprovado com a conversa original tem prioridade. Se houver vários eventos de anúncio para uma compra posterior, use o último evento elegível anterior ao pedido no mesmo contato; trate toques conflitantes como pendência. Conte pedidos diferentes do mesmo cliente pelos respectivos IDs. Preserve as datas da conversa e da compra. Filtre a veiculação e a coorte de pedidos pela data da conversa do anúncio no fuso da conta Meta e informe cobertura parcial enquanto o ciclo ainda estiver aberto ou o vínculo estiver pendente.

A publicação tem como destino o Data Studio oficial, pelo PostgreSQL na VPS e pelo conector comercial. A exportação XLSX de **Salas** no Analytics da Weni, para chats encerrados do setor Delivery FarmaLíder e com a tag **Pedido Finalizado**, é a alternativa ao acesso à API do Weni Chats. O leitor de exportações do Windows preserva o vínculo por UUID ou URN, as tags e as datas do ticket. A configuração PostgreSQL do perfil direciona o importador para o publicador da VPS, onde a tabela interna `Tickets_Delivery_Weni` registra os tickets. O histórico completo de pedidos vem da FarmaLíder. O cruzamento por conversa e pedido e os campos de Anúncios e CAC precisam de integração ao Analytics e ao leitor comercial. A auditoria de último pedido por contato valida casos, mas não comprova a cobertura de todos os pedidos. [Detalhe e validação dos tickets](README%20DELIVERY.md) · [Operação Windows e VPS](OPERACAO_WINDOWS_VPS.md)

Para conferir um período na revisão READY do ambiente configurado no perfil FARMA, execute no Terminal NexoFlow com o pacote que contém a rotina e `ARMAZENAMENTO_BACKEND = "postgres"`:

```powershell
Set-Location C:\NexoFlow
.\.venv\Scripts\python.exe -B app\run_meta_ads.py --perfil FARMA --start 2026-11-01 --end 2026-11-18 --dry-run --auditoria-pedidos logs\privado\meta_ads_conciliacao_2026-11.json
```

A simulação consulta Weni, Meta e as tabelas do PostgreSQL e grava a auditoria somente no arquivo local. Registra o ambiente e a versão READY usados e interrompe se a revisão mudar durante a leitura. Confira `pedidos_validos`, `pedidos_no_resumo`, `receita_no_resumo` e a `situacao` de cada pedido. Esses resultados descrevem o cálculo da simulação sobre a revisão lida. Para confirmar a publicação comercial, confira a revisão resultante e compare os totais da fonte de veiculação no Looker para o mesmo período.

## Separação de FarmaLíder e Pets Líder

A credencial limita as contas acessíveis. **O nome de campanha, conjunto ou anúncio não determina o segmento.** A classificação utiliza evidência oficial Weni associada ao projeto correto, com os tokens próprios de FarmaLíder e Pets Líder.

Um anúncio sem evidência suficiente não vira Farma ou Pets por aproximação de nome. Um anúncio compartilhado não autoriza copiar integralmente o mesmo investimento para as duas marcas. Conversas e cliques não comprovam venda; pedidos continuam sob as validações da API FarmaLíder e os IDs oficiais de pedido.

Os dados são escritos nos destinos analíticos do segmento e nas tabelas próprias da integração, preservando os pedidos e as fontes existentes do Data Studio. Sem cobertura comprovada, não inventar atribuição exclusiva, conversões ou ROAS. Consulte o resultado da etapa para distinguir consulta, classificação e gravação confirmada.

## Instalação e recuperação

- **Atualizar mantendo dados:** token Meta, allowlist e demais dados privados permanecem no lugar, conforme a política geral do Setup.
- **Instalação limpa:** o Setup recupera somente a credencial Meta, além dos documentos de importação já preservados pela regra existente. Não restaura automaticamente credenciais Google, `secrets_config.py` ou estados antigos por causa dessa exceção.
- **Arquivo bloqueado no Windows:** a instalação não ignora falhas nem apaga o token para continuar. A atualização com preservação mantém os dados no lugar; uma instalação limpa que não consiga mover a instalação anterior aborta com os dados preservados.

Depois de reinstalar ou trocar de computador, confira localmente o arquivo de credencial, a allowlist, os perfis e as permissões de edição das planilhas. Nunca envie o token como diagnóstico. Testes de empacotamento usam credenciais fictícias e não executam uma instalação real ou campanha em produção.
