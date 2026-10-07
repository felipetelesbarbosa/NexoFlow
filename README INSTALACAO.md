# NexoFlow 1.0 — Instalação e desinstalação


## Versão

Este documento corresponde ao **NexoFlow 1.0**.


## Ordem recomendada após instalar esta atualização

Antes da carga completa, confirme que os oito campos de pedido existem na Weni: `pedido_id`, `pedido_data`, `pedido_status`, `pedido_produtos`, `pedido_quantidade_itens`, `pedido_valor_produtos`, `pedido_valor` e `pedido_forma_pagamento`.

Depois execute, nesta ordem:

```text
1. testar_conexoes.bat
2. atualizar_weni_carga_completa.bat
3. revisar logs\weni_update_review_full.txt
4. confirmar CARGA COMPLETA REVISADA
5. executar_carga_completa.bat
6. atualizar os campos das fontes de dados no Looker Studio
```

A carga completa do Weni atualiza o snapshot operacional dos contatos. A carga completa do Analytics migra os schemas do Google Sheets e preenche as estruturas analíticas, incluindo frete separado e faturamento total (produtos + frete).


No NexoFlow 1.0, o NexoFlow mantém o fluxo 24h, a CLI amigável `nexo`, o isolamento do checkpoint, o check-up limpo e o timeout/retry do Google Sheets. O Analytics reduz leituras e escritas redundantes, usa batches adaptativos e cache seguro da FarmaLíder no incremental; o Update Weni reduz leituras auxiliares e I/O local sem agrupar ou paralelizar as escritas protegidas.


Antes de usar o **NexoFlow Weni**, confirme que `contact_urn_whatsapp`, `contact_urn_instagram`, `contact_urn_facebook` e `contact_canal_principal` existem na Weni como campos de **Texto**. Para o contrato completo de pedidos, mantenha também os campos `pedido_id`, `pedido_data`, `pedido_status`, `pedido_produtos`, `pedido_quantidade_itens`, `pedido_valor_produtos`, `pedido_valor` e `pedido_forma_pagamento`. Para armazenar também o detalhamento de Google Ads, crie opcionalmente como Texto: `primeiro_anuncio_tipo_campanha`, `primeiro_anuncio_canal_destino`, `ultimo_anuncio_tipo_campanha` e `ultimo_anuncio_canal_destino`. O teste de conexão verifica isso automaticamente e bloqueia atualizações se algum estiver ausente.

## Requisitos

O NexoFlow é executado em Windows x64 e utiliza **Python 3.11 ou superior, 64 bits**. O usuário não precisa instalar o Python manualmente antes de iniciar o Setup. Se nenhum runtime compatível for encontrado, o instalador oferece o **Python 3.14.8 x64 incluído no pacote**.

### Camada BI / Looker Studio

Após instalar sobre uma instalação existente, execute `check-up.bat`, `testar_conexoes.bat` e uma vez `executar_carga_completa.bat`. A carga completa cria/preenche `BI_Resumo_Diario`, `BI_Canais`, `BI_Conversao`, `BI_Vendas`, `BI_Ads`, `BI_Pedidos` e `BI_Status`, além de completar `Base_Contatos` com todos os contatos Weni. Depois disso, volte ao fluxo incremental normal.

### Otimizações de desempenho

- carga completa: Base_Contatos é pré-carregada em paralelo à Weni e escrita somente quando há mudança real;
- incremental: validações FarmaLíder recentes podem ser reutilizadas quando o CPF permanece igual;
- Google Sheets: batches adaptativos de até ~1,5 MB e menos leituras redundantes;
- Update Weni: menos consultas auxiliares e menos I/O de auditoria, sem alterar as proteções de apply.

## Instalação

Extraia o pacote completo e execute:

```text
NexoFlow Setup.exe
```

O instalador:

1. solicita elevação administrativa;
2. valida o SHA-256 do payload;
3. verifica um Python 3.11+ x64 compatível;
4. oferece o Python 3.14.8 x64 incluído quando necessário;
5. preserva configurações, credenciais e logs de uma instalação existente;
6. instala o sistema em `C:\NexoFlow`;
7. cria `.venv` e instala as dependências;
8. cria os atalhos **NexoFlow Analytics**, **NexoFlow Weni** e **NexoFlow Terminal** na Área de Trabalho e Menu Iniciar;
9. instala **`installer\uninstall.ps1` + `desinstalar_nexoflow.cmd`**, registra o NexoFlow em Aplicativos instalados e tenta copiar também **`NexoFlow Uninstall.exe`** como launcher opcional.

O `NexoFlow Uninstall.exe` é o launcher opcional do desinstalador. O Setup tenta instalá-lo, verifica se ele permaneceu no destino e emite apenas um aviso se o antivírus/EDR bloquear, remover ou colocar o arquivo em quarentena. **A ausência do EXE não reprova o Setup nem o check-up.** A desinstalação continua funcional pelo Windows, por `desinstalar_nexoflow.cmd` e por `installer\uninstall.ps1`.

No NexoFlow 1.0, se ocorrer uma falha o Setup mantém a janela aberta e informa o código de saída. O log persistente fica em `%TEMP%\NexoFlow-Setup.log`. Em atualização/reinstalação, processos pertencentes a `C:\NexoFlow` são encerrados antes da substituição dos arquivos e a remoção usa tentativas com retry.

No NexoFlow 1.0 foi corrigida a interpolação PowerShell do aviso de timestamp (`${exePath}: ...`), eliminando o `ParserError: InvalidVariableReferenceWithDrive` que podia encerrar a instalação antes da cópia do payload. Os fontes de `native_launcher` também passam a integrar o payload instalado para que testes e auditoria do check-up continuem completos após a instalação.

O instalador do NexoFlow não substitui nem remove uma instalação global válida do Python.

## Primeira configuração

Configure, quando aplicável:

```text
C:\NexoFlow\secrets_config.py
C:\NexoFlow\credentials\google_credentials.json
```

## Executáveis

### NexoFlow Analytics

```text
check-up -> teste de conexões -> sincronização incremental
```

### NexoFlow Weni

```text
check-up -> teste NexoFlow Weni -> dry-run -> auditoria -> confirmação -> apply
```

Para a primeira carga completa da atualização de campos, use `atualizar_weni_carga_completa.bat`. Para apenas simular, use `atualizar_weni_dry_run.bat`.

O atalho **NexoFlow Weni** utiliza o ícone exclusivo `assets\NexoFlow_Weni.ico`.


### NexoFlow Terminal

`C:\NexoFlow\NexoFlow Terminal.exe` abre uma PowerShell já posicionada na pasta do NexoFlow. Antes de abrir o terminal, o launcher Python executa a mesma lógica de `proxy_config.py` usada pelo projeto e repassa `HTTP_PROXY`/`HTTPS_PROXY` apenas para aquela sessão, sem imprimir usuário ou senha.

O Terminal também prioriza `C:\NexoFlow\.venv\Scripts` e a própria pasta `C:\NexoFlow` no `PATH`, além de definir `PYTHONPATH=C:\NexoFlow`. Assim, o comando curto `nexo` funciona diretamente. Tokens Weni/FarmaLíder e credenciais Google continuam armazenados nos arquivos locais e **não** são publicados em variáveis de ambiente.

Comandos iniciais recomendados:

```text
nexo
nexo ajuda
nexo status
nexo diagnostico
```

As consultas de API são somente leitura, por exemplo `nexo api weni contato --uuid <UUID>`, `nexo api farmalider cliente --cpf <CPF>` e `nexo api farmalider pedido <CODIGO>`. Consulte `README TERMINAL.md` para a referência completa.

O **NexoFlow Terminal.exe** incorpora o ícone dedicado `assets\NexoFlow_Terminal.ico`; os atalhos usam esse mesmo recurso visual.

## Atualização de uma instalação existente

Execute o novo `NexoFlow Setup.exe`. O instalador preserva automaticamente, quando existentes:

```text
secrets_config.py
credentials/
logs/
```

O restante é reconstruído a partir do payload validado.

## Desinstalação resiliente
A desinstalação pode ser iniciada por:

- Configurações do Windows > Aplicativos instalados;
- Menu Iniciar > NexoFlow > Desinstalar NexoFlow;
- `C:\NexoFlow\NexoFlow Uninstall.exe` (quando disponível);
- `C:\NexoFlow\desinstalar_nexoflow.cmd`.

O desinstalador remove os atalhos, executáveis, módulos, BATs e demais arquivos do NexoFlow. Ele pergunta se configurações, credenciais e logs devem ser preservados.

A remoção final acontece fora da pasta instalada:

1. o Stage2 é copiado para `%TEMP%`;
2. é iniciado com `WorkingDirectory=%TEMP%`;
3. executa `Set-Location` para `%TEMP%` antes da exclusão;
4. encerra processos do NexoFlow que ainda estejam usando arquivos da instalação;
5. limpa atributos `ReadOnly`, `System` e `Hidden` quando necessário;
6. repete a remoção de `C:\NexoFlow` por até **60 ciclos** enquanto o Windows libera handles;
7. remove atalhos e chaves de registro restantes.

O comando registrado em Aplicativos instalados chama diretamente o Windows PowerShell com `C:\NexoFlow\installer\uninstall.ps1`; o script solicita elevação via UAC quando necessário. Se `NexoFlow Uninstall.exe` não estiver presente porque foi bloqueado pelo antivírus, isso **não** altera o registro de desinstalação nem impede a remoção do NexoFlow. O atalho do Menu Iniciar usa `desinstalar_nexoflow.cmd`. O Stage2 permanece fora de `C:\NexoFlow` e sua janela não é ocultada.

Se a preservação for escolhida, os dados privados são mantidos em:

```text
C:\NexoFlow Data
```

A preservação contempla, quando existentes:

```text
secrets_config.py
credentials/
logs/
```

O desinstalador **não desinstala o Python global do Windows**.

## Se a pasta estiver bloqueada

Feche janelas de terminal, Explorador de Arquivos ou editores que estejam abertos diretamente em `C:\NexoFlow` e tente novamente. O NexoFlow 1.0 já remove os bloqueios gerados pelos próprios processos do NexoFlow, mas um programa externo também pode manter um handle aberto.

## SmartScreen, antivírus e assinatura

Os executáveis não contêm credenciais. No NexoFlow 1.0, os launchers deixaram de usar `system()`, receberam informações formais de versão no PE e os scripts reduziram uso desnecessário de shell/processos genéricos. O desinstalador não encerra terminais `cmd.exe`/PowerShell genéricos e não executa Stage2 oculto.

Essas medidas reduzem padrões comuns de falso positivo, mas um binário novo e sem reputação ainda pode ser alertado ou colocado em quarentena. Não desative SmartScreen, UAC ou antivírus para contornar isso. A medida mais importante para distribuição corporativa é assinar os executáveis com Authenticode usando o certificado real da empresa.

## Revisão humana da carga completa
Na primeira carga/backfill, execute `atualizar_weni_carga_completa.bat`. Antes do apply, o NexoFlow gera e abre `logs\weni_update_review_full.txt`. Revise especialmente LGPD, idade/maioridade, entradas/saídas dos grupos Opt-In LGPD e Opt-Out LGPD e campos de pedido.

A confirmação exigida é `CARGA COMPLETA REVISADA`. No NexoFlow 1.0, depois dela o NexoFlow carrega exatamente `logs\weni_update_review_full.json` e não recalcula o histórico. Cada contato é relido imediatamente antes da gravação. Se aquele contato mudou desde a revisão, somente ele é ignorado e registrado como conflito; os demais continuam. O checkpoint permanece no corte temporal do dry-run para que tudo que mudou depois seja reprocessado pela próxima incremental.


## Ícone do NexoFlow Weni

No NexoFlow 1.0, a atualização força o Windows Explorer a invalidar/recarregar o cache de ícones após instalar `NexoFlow Weni.exe`. O executável usa internamente `assets\NexoFlow_Weni.ico`, e o instalador também atualiza o timestamp do arquivo para impedir reaproveitamento visual de um ícone antigo.
