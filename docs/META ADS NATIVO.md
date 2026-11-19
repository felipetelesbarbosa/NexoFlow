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
