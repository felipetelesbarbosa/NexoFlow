# NexoFlow 1.5.15 — Proxy e rede

A mesma seleção de conexão direta/proxy e os controles de consulta se aplicam a **FarmaLíder e Pets Líder**. O perfil define os tokens e o segmento, sem alterar a regra de rede.

## Objetivo

O mesmo projeto pode funcionar:

- na rede corporativa, usando proxy autenticado;
- fora da empresa, usando conexão direta;
- em servidor, conforme a política definida para o ambiente.

## Configuração recomendada

Em `secrets_config.py`:

```python
PROXY_MODE = "auto"
PROXY_HOST = "proxy.exemplo.invalid"
PROXY_PORT = 8020
PROXY_USER = "..."
PROXY_PASSWORD = "..."
PROXY_BYPASS = "localhost,127.0.0.1"
PROXY_DETECTION_TIMEOUT = 1.5
```

Nunca coloque credenciais reais em documentação versionada.
`proxy.exemplo.invalid` é fictício: substitua pelo endereço autorizado da sua rede.

## Modos

### `auto`

Testa se `PROXY_HOST:PROXY_PORT` está acessível.

Se o proxy responder:

- ativa proxy para o processo Python;
- seleciona a URL FarmaLíder sem a porta `3200`.

Se o proxy não responder e a internet direta estiver disponível:

- força conexão direta;
- seleciona a URL externa da FarmaLíder com a porta `3200`.

### `on`

Força o uso do proxy configurado.

### `off`

Não configura proxy pelo projeto.

## URL FarmaLíder

Com proxy ativo:

```text
https://api.farmalider.net.br/farmalider
```

Sem proxy:

```text
https://api.farmalider.net.br:3200/farmalider
```

A escolha é feita pelo estado de rede detectado pelo projeto.

Durante uma execução, falhas recuperáveis provocam até três sondagens do proxy.
Se ele já estava ativo, uma falha de sondagem e o acesso direto a um site público
não bastam para desativá-lo: o NexoFlow também precisa receber uma resposta HTTPS
na URL externa da FarmaLíder, sem seguir redirecionamentos e sem enviar tokens ou
dados de clientes nesse teste. Se essa rota não for comprovada, o proxy é mantido
e a operação original segue sua política de tentativas. Isso evita trocar para a
porta externa bloqueada na rede corporativa. Uma mudança real para rede direta
continua possível quando a URL externa responde. Os modos explícitos `on` e `off`
continuam prevalecendo.

O teste de rota verifica conectividade; a disponibilidade e a autenticação da API
continuam sendo verificadas pelo teste de conexões. Se o proxy ou serviço estiver
indisponível, o diagnóstico informa a falha em vez de presumir acesso direto.

## Diagnóstico

`comandos/testar_conexoes.bat` exibe uma linha parecida com:

```text
modo=auto | proxy=host:porta | acessível=sim/não | ativo=sim/não | credenciais=sim/não
```

Depois testa separadamente:

- Weni;
- FarmaLíder;
- Google Sheets.

A FarmaLíder também registra aviso quando uma chamada ultrapassa o limite de
requisição lenta configurado.

### Preflight resiliente da FarmaLíder

O teste inicial da FarmaLíder usa a mesma política de resiliência das consultas
reais. Falhas transitórias de rede/timeout, HTTP 429 e HTTP 5xx são tentadas
novamente até o limite de `FARMALIDER_MAX_RETRIES` (4 por padrão), com
backoff/cooldown e recuperação serial.

Falhas não recuperáveis identificadas com segurança, como proxy 407 ou erro de
certificado TLS, interrompem imediatamente para evitar repetir uma falha que
exige correção de configuração.

Uma falha isolada no primeiro GET de `cliente/cpf` não encerra mais o
NexoFlow Weni; o processo só falha no preflight depois de esgotar as tentativas
configuradas ou encontrar uma causa não recuperável.

## Segurança

As credenciais de proxy ficam somente em `secrets_config.py`.

O projeto não deve imprimir:

- senha;
- token;
- URL completa do proxy contendo credenciais.

Arquivos privados devem permanecer no `.gitignore`.

## HTTP 407

Se houver:

```text
407 Proxy Authentication Required
```

pode existir incompatibilidade entre o mecanismo de autenticação do proxy e
autenticação HTTP simples por usuário/senha.

Antes de adicionar bibliotecas ou mecanismos NTLM/Kerberos/Negotiate, confirme a
política com a equipe de TI.

## Mudança de rede durante uma carga

Em `PROXY_MODE = "auto"`, a rota não fica congelada no início da execução.
Quando Weni, FarmaLíder ou Google Sheets encontram uma falha de rede
recuperável, o NexoFlow executa nova detecção de conectividade.

Exemplos suportados:

```text
internet direta -> proxy corporativo
proxy corporativo -> internet direta
```

Quando a mudança é confirmada, o processo atualiza as variáveis de proxy e
repete **a operação que estava em andamento**. Na FarmaLíder também troca
automaticamente entre a URL externa com `:3200` e a URL via proxy sem
`:3200`.

A carga não volta ao primeiro contato: a paginação/requisição atual é repetida,
CPFs já concluídos permanecem em memória, e escritas do Google Sheets continuam
no lote em execução. Na aplicação do snapshot completo da Weni, contatos já
gravados continuam protegidos pela verificação de estado
`already_satisfied`; se for necessário reiniciar o processo depois de uma
falha prolongada, o mesmo snapshot pode ser aplicado novamente sem refazer
alterações que já estão satisfeitas.

A redetecção é serializada para que vários workers da FarmaLíder não tentem
alterar a rota ao mesmo tempo.

## Relação com a concorrência FarmaLíder

A concorrência controlada da FarmaLíder continua respeitando o ambiente de rede.
Cada worker usa sua própria `requests.Session`, enquanto o rate limiter e os
cooldowns são globais.

Se a rede/API começar a responder com 429 ou apresentar falhas transitórias, o
cliente reduz a pressão por meio de cooldown, retry e throttle adaptativo.

## Rota corporativa e homologação

Com proxy configurado e modo auto, uma falha TCP mantém a rota proxy. A alternativa direta automática exige `PROXY_ALLOW_DIRECT_FALLBACK = True`, somente após autorização da TI. O padrão é False; modo off continua sendo escolha explícita de conexão direta. Proxy ativo significa rota selecionada, não comprovação de CONNECT ou TLS. Consulte [auditoria e homologação Windows](AUDITORIA%20SEGURANCA%20WINDOWS.md) para 407/503, CA corporativa, Kaspersky e coleta de evidências.

## Escolha da rede por sessão (desenvolvimento)

O Setup pergunta qual rede será usada antes da instalação: pessoal com conexão direta autorizada ou corporativa com proxy obrigatório. Não altera secrets_config.py nem apaga as credenciais preservadas. A escolha é herdada por BAT, pip e MCP; o processo do Setup restaura seu ambiente ao encerrar. Instalações não interativas podem fornecer `-NetworkMode Personal` ou `-NetworkMode Corporate`. Sem escolha, Auto mantém a política existente; se a sondagem falhar, o modo sem interação encerra por REDE_AMBIGUA.

Nos aplicativos, `PROXY_MODE=off` é uma escolha explícita de conexão direta; `on` exige proxy. Em auto, a porta acessível indica apenas um proxy candidato, não HTTPS validado. Se o proxy não responder e não houver autorização explícita de fallback, a execução interativa exige escolha; o modo sem interação falha. Falha TCP nunca identifica rede pessoal. A seleção explícita fica em NEXOFLOW_NETWORK_MODE apenas na sessão e nos filhos. Por exemplo, no PowerShell do PC pessoal autorizado: `$env:NEXOFLOW_NETWORK_MODE='personal'`; no trabalho: `'corporate'`. Remover com `Remove-Item Env:NEXOFLOW_NETWORK_MODE` ao trocar de ambiente. Não usar escolha pessoal para contornar política corporativa. Sem sinal confiável, o programa não tenta adivinhar a rede por SSID/IP privado.

Pip principal e MCP compartilham preparação da rota/CA e preflight HTTPS HEAD do índice, com limite de 10 segundos e sem redirecionamentos. CONNECT 407/503, TLS ou timeout bloqueiam a etapa antes de solicitar dependências; não iniciam fallback direto. O preflight não comprova acesso aos hosts de todos os wheels. O pip principal limita retries a zero e timeout a 15 segundos; o BAT para na primeira etapa com erro. O MCP mantém seu limite de tentativas já documentado para falhas transitórias, sem trocar rota. Índices/CA fornecidos apenas em pip.ini exigem configuração de ambiente aprovada pela TI, pois a rota da sessão não pode ser sobrescrita por pip.ini.

O Setup não executa mais upgrade automático do pip. Mantém o fornecido pelo Python/venv; eventual incompatibilidade deve ser diagnosticada e resolvida em manutenção versionada e validada. Setuptools/wheel e requisitos da aplicação continuam explícitos. Avisos de versão nova não autorizam upgrade.

### Homologação pessoal e corporativa

1. PC pessoal: pacote do commit correto, backup privado, atualização Preserve e escolha Personal. Manter Kaspersky/SmartScreen/TLS ativos. Confirmar que as credenciais antigas do proxy continuam no arquivo, mas não são utilizadas nessa sessão. Conferir o preflight, instalação e tentativa MCP separada; validar PET e FARMA em processos próprios.
2. Fechar a sessão antes de trocar rede. PC corporativo: Preserve e escolha Corporate, sem fallback. Confirmar CONNECT/TLS para os destinos necessários. Se o proxy estiver indisponível, a instalação deve parar rapidamente com diagnóstico, sem tentativas por dependência. Em 407, solicitar à TI método/credenciais; em TLS, cadeia de CA aprovada. Guardar horário, categoria e código, sem valores privados.
3. Sem interação e sem escolha: simular falha TCP e confirmar REDE_AMBIGUA. A rotina agendada precisa de uma rota explicitamente autorizada, não de um fallback silencioso. Não usar Noturno para testar apenas conexão: ele pode gravar dados.

### Procedência e SmartScreen

O workflow oficial compila a partir do commit e verifica hashes/segredos. Os builds padrão não recebem certificado Authenticode; o suporte a certificado legítimo existe, mas não equivale a assinatura efetivamente aplicada. Isso é evidência sobre a distribuição, não prova da causa exata do alerta. Um aviso SmartScreen não comprova malware nem falso positivo. O pacote pode manter Zone.Identifier e executável sem reputação conhecida. Sem acesso ao evento/arquivo exato no Windows, a decisão permanece pendente.

No Windows, registrar `Get-FileHash -Algorithm SHA256 -LiteralPath '{arquivo}'` e `Get-AuthenticodeSignature -LiteralPath '{exe}'`, comparar procedência/commit e hash com o workflow. Não remover marca de origem nem desligar proteções. Se houver bloqueio, interromper, guardar captura com editor exibido, horário e hash e encaminhar à TI/fabricante. Não restaurar uma amostra detectada para executá-la. Não há nova assinatura, release ou aprovação SmartScreen nesta correção.

## Sessão entre etapas

A escolha de rede é compartilhada entre os processos da mesma execução, inclusive dry-run e aplicação. Uma queda recuperável mantém a rota por pelo menos três tentativas antes de oferecer troca explícita no console. Consulte [Sessão de rede](SESSAO%20DE%20REDE.md) para os limites das gravações, tarefas sem console e homologação. Não há fallback direto automático para contornar o proxy corporativo.
