# NexoFlow

O **NexoFlow** é um software interno de integração, atualização de contatos e analytics. Ele conecta a Weni, aplica regras de negócio, confirma dados pela API FarmaLíder e mantém informações estruturadas para operação e análise.

Fluxos principais:

```text
Weni -> NexoFlow -> FarmaLíder API -> Google Sheets -> Looker Studio
Weni -> NexoFlow Weni -> Weni
```

## Camada BI / Looker Studio
O NexoFlow Analytics cria e mantém automaticamente: `BI_Resumo_Diario`, `BI_Canais`, `BI_Conversao`, `BI_Vendas`, `BI_Ads` e `BI_Status`. Essas abas centralizam as regras de negócio no NexoFlow e deixam o Looker Studio responsável principalmente pela visualização.

Na primeira execução do NexoFlow 1.0, o fingerprint do schema cria as abas ausentes e adiciona `idade`, `maior_de_18_anos` e `opt_in_lgpd` à `Base_Contatos`. Faça uma carga completa uma vez após atualizar para preencher também os contatos antigos sem CPF/pedido/anúncio e inicializar a camada BI.

## Versão atual

A versão atual é a **NexoFlow 1.0**.

Ela mantém a identificação multicanal, a atribuição conservadora de **Google Ads**, o snapshot congelado para atendimento 24h e a CLI amigável do **NexoFlow Terminal**. O NexoFlow 1.0 adiciona uma camada BI mantida pelo próprio Analytics, pronta para conexão com o Looker Studio.

## Executáveis

O NexoFlow possui executáveis separados por responsabilidade:

- **NexoFlow Analytics.exe**: executa check-up, teste de conexões e sincronização incremental para Google Sheets/analytics. Usa o ícone principal `assets\NexoFlow.ico`.
- **NexoFlow Weni.exe**: atualiza contatos e campos diretamente na Weni, sem exportar/importar planilhas. Usa o ícone exclusivo `assets\NexoFlow_Weni.ico`.
- **NexoFlow Uninstall.exe**: launcher opcional do desinstalador; `desinstalar_nexoflow.cmd / installer\uninstall.ps1` continuam sendo os caminhos independentes e obrigatórios para a desinstalação.
- **NexoFlow Terminal.exe**: abre uma PowerShell em `C:\NexoFlow`, herda a configuração de proxy do `secrets_config.py`, prioriza a `.venv` e disponibiliza a CLI amigável `nexo`.

O `NexoFlow Weni.exe` executa obrigatoriamente:

```text
check-up -> teste de acesso/conexões -> dry-run -> auditoria -> confirmação -> apply
```

Nenhum POST de atualização é executado antes da auditoria do plano.

## Ordem recomendada de uso

### Primeira execução / carga completa

```text
1. Instalar pelo NexoFlow Setup
2. Executar atualizar_weni_carga_completa.bat
3. Revisar o relatório detalhado aberto pelo NexoFlow
4. Confirmar com `CARGA COMPLETA REVISADA`
5. O NexoFlow aplica exatamente o snapshot congelado revisado
6. Contatos alterados durante a revisão são isolados como conflito e ficam para a próxima incremental
7. Executar NexoFlow Analytics
```

O `atualizar_weni_carga_completa.bat` reanalisa o histórico disponível e já executa as verificações obrigatórias antes da aplicação.

No NexoFlow 1.0, o dry-run completo gera `logs\weni_update_review_full.txt` para revisão humana e `logs\weni_update_review_full.json` como snapshot verificável e congelado. O SHA-256 protege a integridade do snapshot. Depois da confirmação manual, o histórico **não é recalculado**. O apply relê cada contato imediatamente antes da sua gravação e compara apenas o estado relevante daquele contato com o que foi revisado. Se houver conflito, somente esse contato é ignorado; novas mensagens e novos contatos continuam entrando normalmente e serão capturados pela próxima incremental a partir do corte temporal do snapshot.

### Uso rotineiro

```text
1. NexoFlow Weni.exe
2. NexoFlow Analytics.exe
```

O NexoFlow Weni deve ser executado primeiro para que o Analytics trabalhe sobre os dados já enriquecidos/atualizados.

## NexoFlow Weni

A rotina consulta mensagens e contatos pela API da Weni e pode atualizar, quando houver evidência válida, somente os campos autorizados:

```text
contact_urn
contact_urn_whatsapp
contact_urn_instagram
contact_urn_facebook
contact_canal_principal
cpf
idade
maior_de_18_anos
opt_in_lgpd
pedido_id
pedido_data
pedido_status
pedido_produtos
pedido_quantidade_itens
pedido_valor
ultima_compra
primeiro_anuncio_origem
primeiro_anuncio_id
primeiro_anuncio_titulo
primeiro_anuncio_url
primeiro_anuncio_clique_id
primeiro_anuncio_data
primeiro_anuncio_tipo_campanha
primeiro_anuncio_canal_destino
ultimo_anuncio_origem
ultimo_anuncio_id
ultimo_anuncio_titulo
ultimo_anuncio_url
ultimo_anuncio_clique_id
ultimo_anuncio_data
ultimo_anuncio_tipo_campanha
ultimo_anuncio_canal_destino
```

Regras importantes:

- respostas ambíguas não alteram cadastro;
- as URNs nativas retornadas pela Weni são a fonte de verdade para identificação de canal;
- `contact_urn` passa a representar a URN principal, com prioridade **WhatsApp > Instagram > Facebook/Messenger > outra URN nativa**;
- `contact_urn_whatsapp`, `contact_urn_instagram` e `contact_urn_facebook` armazenam separadamente as URNs oficiais de cada canal quando existirem;
- `contact_canal_principal` recebe `whatsapp`, `instagram`, `facebook` ou `outro`, conforme a URN principal;
- antes do dry-run ou apply, o NexoFlow consulta os campos cadastrados na Weni e exige que `contact_urn_whatsapp`, `contact_urn_instagram`, `contact_urn_facebook` e `contact_canal_principal` já existam como campos de **Texto**; se algum estiver ausente, a rotina é bloqueada antes de qualquer gravação;
- anúncios não geram URN e não alteram o canal do contato: `primeiro_anuncio_*` e `ultimo_anuncio_*` continuam separados da identidade de canal;
- Google Ads só é atribuído quando existe evidência explícita em campos/metadados estruturados recebidos pela Weni, como `gclid`, `gbraid`, `wbraid`, origem/UTM Google Ads ou metadado equivalente; um link comum do Google não é suficiente e um URL com `gclid` apenas colado pelo cliente no texto livre da conversa não é usado como prova de origem;
- quando a evidência indicar **Performance Max**, **Search**, **Display/Banner**, **YouTube**, **Demand Gen** ou **Shopping**, o tipo pode ser registrado em `primeiro_anuncio_tipo_campanha`/`ultimo_anuncio_tipo_campanha`; `utm_medium=cpc` sozinho não é usado para adivinhar Search ou Performance Max;
- `primeiro_anuncio_canal_destino` e `ultimo_anuncio_canal_destino` registram `whatsapp`, `instagram`, `facebook` ou `outro` quando o canal é comprovado pela URN da mensagem; em contato multicanal sem URN na evidência, o NexoFlow deixa o destino em branco em vez de inferir;
- o primeiro anúncio válido não é substituído; o último anúncio só é atualizado quando a nova evidência possui data mais recente;
- os quatro campos extras de tipo/canal de campanha são opcionais. Se não existirem na Weni, o NexoFlow avisa e continua com os campos genéricos de anúncio que estiverem disponíveis;
- uma URN nunca é inventada e um campo de canal não é apagado apenas porque determinada URN não apareceu em uma resposta posterior da API;
- CPF só é capturado quando o cliente o identifica explicitamente como CPF ou responde a uma solicitação contextual; somente CPF válido é aceito;
- quando o CPF informado recentemente difere do campo `cpf`, o valor mais recente substitui o anterior; se for o mesmo CPF apenas com outra formatação, não há regravação;
- `Sim`, `Não` ou uma idade isolada só são usados quando existe contexto explícito na conversa;
- `opt_in_lgpd_status` permanece controlado pelos flows/agentes da Weni;
- `ultimo_pedido` pode ser fornecido como JSON estruturado; a rotina NexoFlow Weni não reescreve esse campo. O Analytics também aceita os campos separados `pedido_*` e deriva o JSON quando necessário;
- quando `ultimo_pedido` está preenchido e possui ID válido, seus dados têm prioridade; a API consulta somente esse mesmo pedido por ID para confirmar o status, sem buscar outro pedido pelo CPF;
- somente quando `ultimo_pedido` está ausente, vazio ou `null`, a rotina pode consultar o CPF confirmado, obter `ultimoPedido` na resposta da API e validar esse pedido pela FarmaLíder;
- pedidos são validados pelo identificador e pelo vínculo com o titular. Cancelamentos são preservados no registro, mas não confirmam uma compra nem atualizam `ultima_compra`;
- `opt_in_lgpd = ativo` garante o contato no grupo **Opt-In LGPD** e remove **Opt-Out LGPD**, se necessário;
- `opt_in_lgpd = recusado` garante o contato no grupo **Opt-Out LGPD** e remove **Opt-In LGPD**, se necessário;
- os dois grupos são mutuamente exclusivos e o campo `opt_in_lgpd` é a fonte de verdade para a sincronização;
- valores válidos nunca são substituídos por vazio;
- a rotina não grava campos fora da allowlist;
- falha durante uma gravação impede o avanço do checkpoint;
- em caso de falha, a próxima execução reprocessa a janela com segurança;
- toda alteração aplicada possui registro de auditoria.

### Arquivos operacionais do NexoFlow Weni

- `testar_update_weni.bat`: diagnóstico/teste da função de atualização;
- `atualizar_weni_dry_run.bat`: analisa e audita sem gravar alterações;
- `atualizar_weni.bat`: rotina incremental normal com auditoria e confirmação;
- `atualizar_weni_carga_completa.bat`: reprocessamento completo do histórico disponível, com auditoria e confirmação;
- `logs/weni_update_audit.jsonl`: trilha estruturada de auditoria;
- `logs/nexoflow_update_weni.log`: log operacional da rotina.

Consulte [README WENI.md](README%20WENI.md) para o procedimento detalhado.


## NexoFlow Terminal

No NexoFlow 1.0, o Terminal possui uma CLI própria para uso operacional sem precisar decorar nomes de `.bat`, comandos Python ou URLs de API.

```text
nexo
nexo ajuda
nexo status
nexo diagnostico
nexo weni dry-run
nexo weni atualizar
nexo weni carga-completa
nexo api weni contato --uuid <UUID>
nexo api farmalider cliente --cpf <CPF>
nexo api farmalider pedido <CODIGO>
nexo logs weni --seguir
```

A família `nexo api` é **somente leitura**. Ela reutiliza o proxy e os tokens já configurados no NexoFlow, mas nunca exibe os tokens. Atualizações da Weni continuam passando pelas rotinas auditadas do NexoFlow Weni.

Para a lista completa, exemplos e explicação de cada comando, consulte [README TERMINAL.md](README%20TERMINAL.md).

## Analytics

O **NexoFlow Analytics** permanece separado do NexoFlow Weni.

Ele é responsável pela sincronização analítica e pela atualização das estruturas usadas em Google Sheets/Looker Studio. O NexoFlow 1.0 expõe também os metadados de tipo de campanha e canal de destino de anúncios quando disponíveis, além de `contact_urn_whatsapp`, `contact_urn_instagram`, `contact_urn_facebook` e `contact_canal_principal`. IDs de Instagram/Facebook não são tratados como telefone. O Analytics não substitui a rotina NexoFlow Weni e não deve ser usado como mecanismo de escrita dos campos de contato.

Na operação rotineira, execute o NexoFlow Weni antes do Analytics.

### Pedidos por JSON ou campos separados

O NexoFlow 1.0 usa `ultimo_pedido` como fonte prioritária quando ele está preenchido. O JSON pode fornecer diretamente ID, data/hora, nomes dos produtos, quantidades, valores unitários e valor total; desses dados são derivados `pedido_id`, `pedido_data`, `pedido_produtos`, `pedido_quantidade_itens` e `pedido_valor`. Após a consulta do mesmo ID na API, `pedido_status` recebe o estado oficial atual. Esses campos também são preservados na `Base_Contatos`.

Quando `ultimo_pedido` estiver preenchido, seus dados são usados como Caminho 1 e o NexoFlow consulta somente o mesmo `pedido_id` para confirmar o status atual. O fluxo `CPF → ultimoPedido → pedido` é Caminho 2 e só é usado quando `ultimo_pedido` estiver ausente, vazio ou `null`. Produtos permanecem em JSON e os seis campos de pedido (`pedido_id`, `pedido_data`, `pedido_status`, `pedido_produtos`, `pedido_quantidade_itens` e `pedido_valor`) são mantidos em qualquer estado válido.

Datas de pedidos usam **America/Belem (UTC−3 / GMT−3)**. Para os indicadores, **pedido feito** significa status 0, 1, 2 ou 4 confirmado pela API e não cancelado; somente status 3 fica fora. Os seis campos de pedido continuam registrados em todos os estados válidos, e `ultima_compra` avança para o pedido não cancelado mais recente confirmado pela API. A leitura do último pedido não recupera automaticamente todo o histórico comercial.

Consulte [Pedidos no NexoFlow 1.0](docs/PEDIDOS.md) para o contrato e as regras de validação.

## Instalação no Windows

Extraia todo o pacote **NexoFlow Setup** e execute:

```text
NexoFlow Setup.exe
```

O instalador:

- valida a integridade do payload;
- verifica o Python;
- prepara o ambiente;
- instala as dependências;
- registra o NexoFlow no Windows;
- cria os atalhos **NexoFlow Analytics**, **NexoFlow Weni** e **NexoFlow Terminal** na Área de Trabalho e no Menu Iniciar;
- aplica o ícone próprio de cada rotina;
- inclui o **NexoFlow Uninstall.exe** como launcher opcional; a ausência/bloqueio desse EXE não interrompe a instalação.

O instalador reconhece Python 3.11 ou superior, 64 bits, inclusive versões mais novas como o Python 3.14. Se nenhum runtime compatível for encontrado, oferece o Python 3.14.8 x64 incluído no próprio pacote.

A instalação padrão é:

```text
C:\NexoFlow
```

Consulte [README INSTALACAO.md](README%20INSTALACAO.md) para detalhes.

## Desinstalação

Você pode usar qualquer uma destas opções:

```text
NexoFlow Uninstall.exe
desinstalar_nexoflow.cmd
installer\uninstall.ps1
```

O `NexoFlow Uninstall.exe` é apenas uma conveniência. Em ambientes corporativos onde antivírus/EDR bloqueiem ou coloquem esse EXE em quarentena, o **Setup e o check-up não falham por sua ausência**. A desinstalação continua registrada no Windows via `installer\uninstall.ps1`, e o wrapper `desinstalar_nexoflow.cmd` permanece disponível.

No NexoFlow 1.0, o desinstalador usa uma etapa auxiliar fora da pasta de instalação para evitar que o próprio processo mantenha `C:\NexoFlow` bloqueado. O Stage2 é executado em `%TEMP%`, encerra processos relacionados ao NexoFlow quando necessário, limpa atributos que possam impedir a exclusão e repete as tentativas enquanto o Windows libera handles.

O desinstalador remove os componentes e atalhos do NexoFlow, incluindo **Analytics**, **NexoFlow Weni** e **NexoFlow Terminal**. Quando solicitado, preserva `secrets_config.py`, `credentials` e `logs` em:

```text
C:\NexoFlow Data
```

O Python global instalado no Windows não faz parte da remoção do NexoFlow.

## Segurança

Nunca distribua nem versione credenciais reais:

```text
secrets_config.py
credentials/google_credentials.json
tokens
senhas do proxy
```

O instalador valida o payload por SHA-256. Os executáveis não armazenam tokens ou senhas. A NexoFlow Terminal também não exporta tokens Weni/FarmaLíder ou credenciais Google para variáveis de ambiente; esses segredos continuam sendo lidos pelos módulos locais quando necessário.

No NexoFlow 1.0, os launchers Windows são nativos, não usam `system()` e iniciam filhos por `CreateProcessW` através de `os/exec`. Os recursos PE incluem `CompanyName`, `ProductName`, `FileDescription`, `FileVersion`, `ProductVersion` e `OriginalFilename`. Isso reduz padrões heurísticos desnecessários, mas não substitui assinatura Authenticode confiável.

## Manutenção e validação

Antes de qualquer release, execute:

```text
check-up.bat
```

O check-up valida sintaxe, testes automatizados e consistência entre código, configurações, executáveis, instalador e documentação.

A auditoria de consistência também valida a identificação multicanal, a detecção conservadora de Google Ads, o ícone dedicado do **NexoFlow Weni** e o fluxo de desinstalação resiliente.
