# NexoFlow 1.0 — Proxy e rede

Documentação atual de rede do **NexoFlow**.

## Objetivo

O mesmo projeto pode funcionar:

- na rede corporativa, usando proxy autenticado;
- fora da empresa, usando conexão direta;
- em servidor, conforme a política definida para o ambiente.

## Configuração recomendada

Em `secrets_config.py`:

```python
PROXY_MODE = "auto"
PROXY_HOST = "10.1.15.3"
PROXY_PORT = 8020
PROXY_USER = "..."
PROXY_PASSWORD = "..."
PROXY_BYPASS = "localhost,127.0.0.1"
PROXY_DETECTION_TIMEOUT = 1.5
```

Nunca coloque credenciais reais em documentação versionada.

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

## Diagnóstico

`testar_conexoes.bat` exibe uma linha parecida com:

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

## Relação com a concorrência FarmaLíder

A concorrência controlada da FarmaLíder continua respeitando o ambiente de rede.
Cada worker usa sua própria `requests.Session`, enquanto o rate limiter e os
cooldowns são globais.

Se a rede/API começar a responder com 429 ou apresentar falhas transitórias, o
cliente reduz a pressão por meio de cooldown, retry e throttle adaptativo.
