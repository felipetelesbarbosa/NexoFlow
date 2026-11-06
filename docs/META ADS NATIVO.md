# Meta Ads no NexoFlow Analytics

A integração nativa consulta a Marketing API da Meta pelo próprio NexoFlow Windows, de forma autônoma. **Não exige Codex CLI, SDK MCP, servidor MCP ou ChatGPT para executar a carga.** Usa o cliente HTTP compartilhado de `connectors/meta_ads_mcp/client.py`, sem importar o servidor. O nome dessa pasta não torna o SDK MCP uma dependência da operação nativa.

Use a instalação normal em `C:\NexoFlow`, com o Python e as dependências principais preparados pelo Setup. Não é necessário manter uma segunda instalação em `C:\NexoFlow-Codigo` nem executar o programa a partir de uma pasta específica. O pacote Python também inclui os módulos nativos e o cliente compartilhado.

## Credencial local e contas permitidas

Se já utiliza Meta Ads MCP neste computador, a integração nativa reutiliza o mesmo arquivo local:

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
| `META_ADS_ENABLED` | Padrão `False`; habilitar com `True` após conferir credencial, contas e os arquivos de destino. Autoriza preparar as cinco abas Meta ausentes ou vazias com o schema canônico. |
| `META_ADS_START_DATE` | Data inicial histórica desejada, no formato ISO `AAAA-MM-DD`. |
| `META_ADS_OVERLAP_DAYS` | Sobreposição da incremental; padrão **7 dias**, para reconciliar indicadores que a Meta pode atualizar após a primeira coleta. |

Os tokens Weni e as três planilhas de cada segmento continuam configurados nos perfis existentes. Nenhuma credencial é criada automaticamente a partir de outra. Habilitar a integração não substitui permissões Meta/Google/Weni ausentes.

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

## Separação de FarmaLíder e Pets Líder

A credencial limita as contas acessíveis. **O nome de campanha, conjunto ou anúncio não determina o segmento.** A classificação utiliza evidência oficial Weni associada ao projeto correto, com os tokens próprios de FarmaLíder e Pets Líder.

Um anúncio sem evidência suficiente não vira Farma ou Pets por aproximação de nome. Um anúncio compartilhado não autoriza copiar integralmente o mesmo investimento para as duas marcas. Conversas e cliques não comprovam venda; pedidos continuam sob as validações da API FarmaLíder e os IDs oficiais de pedido.

Os dados são escritos nos destinos analíticos do segmento e nas tabelas próprias da integração, preservando os pedidos e as fontes existentes do Data Studio. Sem cobertura comprovada, não inventar atribuição exclusiva, conversões ou ROAS. Consulte o resultado da etapa para distinguir consulta, classificação e gravação confirmada.

## Instalação e recuperação

- **Atualizar mantendo dados:** token Meta, allowlist e demais dados privados permanecem no lugar, conforme a política geral do Setup.
- **Instalação limpa:** o Setup recupera somente a credencial Meta, além dos documentos de importação já preservados pela regra existente. Não restaura automaticamente credenciais Google, `secrets_config.py` ou estados antigos por causa dessa exceção.
- **Arquivo bloqueado no Windows:** a instalação não ignora falhas nem apaga o token para continuar. A atualização com preservação mantém os dados no lugar; uma instalação limpa que não consiga mover a instalação anterior aborta com os dados preservados.
- **Codex/MCP opcionais:** os auxiliares continuam disponíveis para quem quiser usar ferramentas interativas. Não são pré-requisito da carga nativa; a falha de sua instalação opcional não torna o SDK obrigatório para o Analytics.

Depois de reinstalar ou trocar de computador, confira localmente o arquivo de credencial, a allowlist, os perfis e as permissões de edição das planilhas. Nunca envie o token como diagnóstico. Testes de empacotamento usam credenciais fictícias e não executam uma instalação real ou campanha em produção.
