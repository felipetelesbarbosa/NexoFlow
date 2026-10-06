# Proxy e rede - NexoFlow

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
