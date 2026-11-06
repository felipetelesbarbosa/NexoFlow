# Meta Ads MCP local — especificação NexoFlow

## Escopo inicial

- Aplicativo Meta Developers: **NexoFlow Ads MCP** — ID `29468534812833595`.
- Token de usuário do sistema com escopo `ads_read`; jamais `ads_management`.
- Conta inicialmente autorizada: `898435729140540` (somente leitura).
- Contas adicionais exigem ID real e acesso de visualização pela conta técnica.
- Mesmo nas contas em que o usuário pessoal tem acesso total, o MCP permanece
  exclusivamente de leitura em todas elas.

## Arquitetura

```
Codex local ──STDIO──> connectors/meta_ads_mcp/server.py
                                 │
                                 ▼
                     client.py (somente GET)
                                 │
                                 ▼
                       Meta Marketing API
                                 ▲
              credentials/mcp/meta_ads_credentials.json
```

O GitHub guarda o código e os testes, nunca o processo local ou o token.
O NexoFlow pode importar o mesmo cliente Python em futuras rotinas de Analytics.

## Ferramentas públicas

- `contas_permitidas()` — IDs permitidos pela configuração, sem checar Meta.
- `detalhes_conta(conta_id)` — ID, nome, moeda, status, fuso.
- `campanhas(conta_id, limite=50, paginas=2)`.
- `conjuntos(conta_id, limite=50, paginas=2)`.
- `anuncios(conta_id, limite=50, paginas=2)`.
- `insights(conta_id, data_inicio, data_fim, nivel='campaign', limite=100, paginas=3)`.

Limites: até 100 resultados/página, 10 páginas/chamada e intervalo máximo
entre datas de 92 dias. Saída `parcial=true` indica paginação interrompida.
Não existem ferramentas de modificar, criar, pausar ou excluir ativos.

## Integração futura com NexoFlow Analytics

No repositório inspecionado, `app/analytics.py` define `META_CAMPAIGN_COLUMNS`
com `anuncio_id, anuncio_nome, conjunto_id, conjunto_nome, campanha_id,
campanha_nome, investimento, impressoes, cliques, atualizado_em`.

O projeto também possui `app/ad_attribution.py`, `app/meta_events.py`,
`docs/RASTREAMENTO_META.md`, `BI_Ads`, `Eventos_Anuncios` e `Campanhas_Meta`.

**Não gravar Insights diretamente na tabela sem analisar o grão.** O schema
atual de `Campanhas_Meta` não possui conta de anúncios nem período: somar
custos de diferentes dias/contas sem incluir a data gera dupla contagem ou
sobrescrita. Codex deve propor alteração compatível com migração e testes,
antes de qualquer escrita. Conservar FARMA e PET separados, preservar dados
históricos e rotinas de Recompra.

Conversões Meta (ações/ROAS) são atribuídas pela plataforma de anúncios e
não significam pedidos confirmados na API FarmaLíder; atribuição por CTWA
na Weni exige identidade explícita, sem inferir causalidade somente por ID.

## Exemplos

`insights` de 1º a 31 de outubro de 2026, por campanha:

```text
Use a ferramenta insights de nexoflow-meta-read com:
conta_id: 898435729140540
data_inicio: 2026-10-01
data_fim: 2026-10-31
nivel: campaign
```

## Diagnóstico de erro

- HTTP 400/403: token inválido, sem `ads_read`, conta não atribuída ao usuário
  do sistema ou field não suportado pela versão da API.
- HTTP 429: taxa de consulta excedida; implemente retry com `Retry-After`
  antes de automatizar sincronizações em lote.
- MCP não aparece: confira `codex mcp list`, Python da `.venv` e caminho `server.py`.
- Proibição de conta: confirme lista `allowed_ad_account_ids`, sem desativar
  sua proteção para contornar a autorização.

## Instalação e estado de validação

Execute na instalação local do Windows:

```powershell
cd C:\NexoFlow
powershell -NoProfile -File .\scripts\instalar_meta_ads_mcp.ps1 -Perfil FARMA
```

O cadastro esperado usa o Python isolado `connectors\meta_ads_mcp\.venv\Scripts\python.exe` e o argumento absoluto `connectors\meta_ads_mcp\server.py`. O token não participa do cadastro e não deve ser passado por `--env`. Preserve servidores Codex já existentes; um registro divergente precisa de diagnóstico antes de qualquer substituição.

A única origem operacional da credencial é `credentials/mcp/meta_ads_credentials.json`. O modelo público `configuracao/meta_ads_credentials.example.json` contém somente placeholder e IDs autorizados. Não colocar token no `.env`, `config.toml`, `secrets_config.py`, workflows, comandos ou logs. Não forçar inclusão da credencial no Git.

O instalador e os testes offline preparam a integração; eles não comprovam que o usuário do sistema tem acesso real à conta. A consulta real e a confirmação do registro no Codex do Windows permanecem pendentes até execução nesse computador. Não usar o nível de acesso pessoal como autorização para escrita: as seis ferramentas continuam somente de leitura, sem administração de anúncios.

O plano de reutilização direta do cliente pelo Analytics, com grão diário, migração compatível, separação dos segmentos e regras dos indicadores, está em [Plano Meta Ads Analytics](PLANO%20META%20ADS%20ANALYTICS.md). Nenhuma etapa de escrita ou mudança de schema foi ativada nesta fase; a versão operacional foi preservada.

## Validação desta integração

Foram executados 19 testes offline do conector com o SDK MCP instalado em ambiente separado, incluindo initialize/tools/list/tools/call por STDIO; 1.575 testes do projeto passaram (68 específicos de ambiente ignorados). Lint e auditoria de consistência passaram. Nenhum token real foi lido e nenhuma consulta à Meta ou escrita de produção foi executada. A instalação PowerShell/Python 3.14 é conferida pelo workflow dedicado e ainda precisa ser executada no computador do usuário. O registro real no Codex desse computador permanece pendente.

Na fase preparatória, os commits usaram `[skip release]` e preservaram a versão 1.5.12. A entrega **1.5.13** distribuiu a integração nativa e os auxiliares opcionais e permanece preservada. A **1.5.14** tem seus próprios pacotes e validação do mesmo commit; MCP e Codex não são requisitos da integração nativa.

## Instalação MCP independente de Codex

O Setup oferece somente o ambiente opcional **Meta Ads MCP**, por `-InstallMetaAdsMcp` no modo não interativo. Preserve valida/reutiliza ambientes compatíveis; Clean reinstala somente o ambiente MCP selecionado, com recuperação se falhar. Não instala, consulta, valida, registra nem remove Codex CLI e não altera seus arquivos de autenticação/configuração. O registro em um cliente de IA é uma operação manual separada e opcional. Analytics/Noturno continuam usando Meta nativa sem MCP ou cliente de IA.

```powershell
cd C:\NexoFlow
powershell -NoProfile -File .\scripts\instalar_meta_ads_mcp.ps1 -Perfil FARMA
# Ou -Perfil PET. Para recriar apenas o ambiente MCP: adicionar -Reinstall.
```

O perfil é escolhido antes dos imports de rede. O Setup utiliza NEXOFLOW_PERFIL herdado ou FARMA quando não definido. O helper explícito permite testar PET separadamente. Não reutiliza credenciais de aplicação FARMA para PET; usa o seletor existente. Os parâmetros antigos `-InstalarCodex` e `-SemRegistroCodex` são aceitos apenas para compatibilidade, com aviso e sem executar Codex ou registro. As orientações novas não os utilizam.

### Proxy, certificados e erro 407

O script anterior chamava o pip do venv MCP diretamente, sem carregar a configuração NexoFlow. O novo `app/run_mcp_pip.py`, executado pelo Python principal já instalado, carrega a mesma política de proxy do NexoFlow, com o perfil selecionado. O pip MCP recebe a rota no ambiente, nunca em argumentos ou logs. Não é criada alternativa direta por falha de autenticação. Configuração ausente/inválida bloqueia a instalação de dependências e deixa a integração pendente.

Somente no subprocesso pip, configurações globais/locais pip.ini são desconsideradas para impedir sobreposição da rota do NexoFlow. Índices HTTPS e certificados podem ser definidos por variáveis de ambiente aprovadas pela TI. Não são alterados pip.ini, registro do Windows ou arquivos de configuração privados. A CA explícita é selecionada na ordem REQUESTS_CA_BUNDLE, CURL_CA_BUNDLE, PIP_CERT, SSL_CERT_FILE e propagada para PIP_CERT/REQUESTS_CA_BUNDLE; arquivo inexistente bloqueia a operação. Sem CA explícita, mantém o comportamento TLS padrão do pip/Python, incluindo seu suporte ao repositório de certificados do sistema quando disponível. Não importa certificados nem desativa TLS. Políticas PAC/NTLM/Kerberos não são implementadas pelo simples par usuário/senha: confirmar com a TI.

A saída bruta do pip não é impressa nem gravada. Mensagens são classificadas em categorias seguras. 407 não é repetido pelo wrapper e não comprova ausência de uma distribuição MCP. Credencial ausente, rejeitada, método incompatível e regra de proxy exigem evidências distintas. CONNECT 502/503 e timeouts podem ter até três tentativas com backoff, sem mudar rota; TLS e erros não reconhecidos encerram a etapa. A validação offline continua obrigatória após instalação. O JSON `logs/meta_ads_mcp_instalacao.json` indica instalado/pendente e orienta executar o helper por perfil, sem `-InstalarCodex`. Status instalado comprova dependências/testes offline, não autenticação Meta ou registro em cliente de IA.

### Diagnóstico da instalação de dependências

Quando a etapa pip é executada, `logs/meta_ads_mcp_dependencias.json` registra perfil, rota, horário UTC, resultado do preflight HTTPS, tentativas realizadas, código de saída, categoria e último estágio reconhecido. A gravação é atômica e substitui o resultado da execução anterior. O arquivo não contém a saída bruta do pip, argumentos, URLs, caminhos privados, variáveis de ambiente, usuário, senha ou token. Os dois relatórios MCP são locais e ignorados pelo Git. Se a gravação falhar, um aviso explícito preserva o resultado da instalação apresentado no console.

Os códigos diferenciam autenticação proxy (`PROXY_AUTENTICACAO`), recusa CONNECT, erro HTTP de índice/download (`PIP_HTTP`), certificado (`TLS_CERTIFICADO`), timeout, pip ausente, versão Python incompatível, conflito de dependências, arquivo em uso, acesso negado, falta de espaço e compilação. A classificação descreve o que o pip informou; acesso negado não identifica quem bloqueou o arquivo, nem comprova intervenção do antivírus. `PIP_CANDIDATO` informa que nenhuma distribuição foi selecionada, sem concluir que o pacote não existe. Uma saída não reconhecida permanece `PIP_INSTALACAO`, com o código de saída preservado para investigação.

Preflight aprovado comprova apenas a verificação HTTPS inicial do índice: downloads de arquivos e outros destinos ainda podem ser recusados. `tentativa 1/3` indica a primeira tentativa de um limite de três; erros permanentes encerram sem repetir. O diagnóstico mantém todas as tentativas da execução, inclusive uma recuperação posterior. Não há troca automática para conexão direta, atualização automática do pip ou mudança de versões de dependências nesta correção.

Se o ambiente compatível for reutilizado, ou a falha ocorrer antes de iniciar o auxiliar Python, o diagnóstico pip pode não existir ou pertencer a uma execução anterior. Compare o horário com o status e com o terminal; sucesso das dependências também não comprova a validação offline posterior nem o acesso à Meta. Ao solicitar suporte, envie os dois JSON locais, a versão do pacote e a mensagem final do terminal. Não envie credenciais. O transcript `%TEMP%\\NexoFlow-Setup.log` pode acumular instalações e não registrar a saída do subprocesso opcional; ele sozinho pode ser insuficiente.

### Homologação

1. PC pessoal: pacote do commit validado, atualização Preserve, backup privado e Kaspersky ativo. Conferir preservação de secrets, credentials, logs e ambientes. Confirmar que a oferta menciona somente MCP e que o Codex existente não é consultado/modificado. Não reduzir ExecutionPolicy nem remover bloqueios de origem para prosseguir.
2. Nesse PC, executar o helper primeiro com FARMA, depois PET em processos separados. Confirmar conclusão offline e a coleta Meta nativa independentemente. Preservar JSON/relatório sem tokens. Se não houver configuração válida de rede, corrigir localmente antes de repetir.
3. PC corporativo: mesmo pacote e Preserve, proxy obrigatório conforme TI, fallback direto desabilitado. Conferir rota e indicação de credenciais configuradas; isso não comprova autenticação. Em 407 parar e solicitar à TI correlação do horário, domínio/porta e método de autenticação. Em TLS solicitar a CA aprovada; em 502/503 solicitar logs CONNECT/upstream. Não enviar secrets_config.py ou o JSON Meta como evidência.
4. Só após sucesso local, registrar manualmente o servidor STDIO no cliente de IA escolhido, se desejado. Configurações já existentes não são sobrescritas pelo instalador. O token permanece exclusivamente em credentials/mcp/meta_ads_credentials.json.

Os testes sintéticos não aprovam Kaspersky, proxy corporativo ou autenticação real. Não houve consulta de credenciais reais nem escrita de produção para demonstrar funcionamento desta correção.
