# NexoFlow 1.5.8 — VS Code

Documentação de desenvolvimento e manutenção do **NexoFlow**.

## Abrindo o projeto

1. Abra a pasta raiz `NexoFlow` no VS Code.
2. Pressione `Ctrl+Shift+P`.
3. Execute **Python: Select Interpreter**.
4. Escolha:

```text
.venv\Scripts\python.exe
```

5. Aguarde o Pylance concluir a indexação.
6. Execute `comandos/check-up.bat`.

Evite abrir apenas um arquivo `.py` isolado. O workspace deve ser a pasta raiz do projeto.

## Check-up

`comandos/check-up.bat` executa:

```text
[1/3] sintaxe
[2/3] testes automatizados
[3/3] auditoria de consistência
```

A auditoria verifica, entre outros pontos:

- parâmetros de concorrência e rate limit da FarmaLíder;
- cooldown e throttle após HTTP 429;
- sessões por thread e circuit breaker;
- diagnóstico de requisições lentas;
- autenticação da FarmaLíder por QueryString;
- ausência de Bearer;
- proteção de cota e retry do Google Sheets;
- otimizações estruturais do Google Sheets;
- ciclo Windows de instalação, execução e desinstalação;
- requisito de Python no instalador;
- alinhamento da documentação ativa.

## FarmaLíder

URLs:

```text
com proxy: https://api.farmalider.net.br/farmalider
sem proxy: https://api.farmalider.net.br:3200/farmalider
```

Autenticação:

```text
?token=...
```

Não usar `Authorization: Bearer`.

As configurações operacionais ficam em `app/config.py` e devem permanecer como fonte da verdade.

## Concorrência

A concorrência é controlada:

- poucos CPFs usam menos workers;
- a partir do limiar configurado, são usados até 4 workers;
- os lotes têm até 500 CPFs;
- cada CPF continua sendo uma chamada individual;
- existe um rate limiter global entre todos os workers;
- cada thread possui sua própria `requests.Session`;
- HTTP 429 ativa cooldown global e aumento adaptativo do intervalo;
- falhas individuais permanecem pendentes e são resumidas por lote; falhas 5xx persistentes em consultas distintas podem abrir o circuito e interromper o acesso global.

## Latência e diagnóstico

`FARMALIDER_SLOW_REQUEST_SECONDS` define o limiar para registrar uma chamada como lenta.

Os logs mostram:

```text
HTTP requests
retries
429
5xx
erros de rede
requisições lentas
latência média
latência p95
latência máxima
delay adaptativo final
```

As latências da FarmaLíder são exibidas em segundos nos logs de execução. Os campos técnicos da aba `Controle` continuam em milissegundos por compatibilidade.

Avisos de latência não devem exibir CPF nem código de pedido.

## Google Sheets

O cliente atual:

- faz retry em erros 429 e 5xx de escrita;
- espaça operações de escrita;
- usa fingerprint da estrutura das abas;
- evita reformatar cabeçalhos sem necessidade;
- lê apenas a coluna necessária ao buscar UUIDs;
- evita regravar métricas idênticas;
- ignora o recálculo de `Metricas_Vendas` no incremental sem alteração de pedidos.

`comandos/testar_conexoes.bat` força a validação completa da estrutura para garantir a integridade da planilha.

## Requisito Python no instalador

O `NexoFlow Setup.exe` verifica se existe Python 3.11 ou superior, 64 bits, incluindo versões mais novas como o Python 3.14. A detecção consulta PATH, Python Launcher, Registro do Windows e diretórios comuns de instalação.

Se não houver um runtime compatível, o instalador explica que o Python é necessário e oferece o Python 3.14.8 x64 incluído no próprio pacote. O Setup não usa WinGet e não instala Python 3.12.

O instalador atualiza temporariamente o `PATH` da própria execução após a instalação para conseguir criar `.venv` sem exigir que o usuário abra uma nova sessão.

## Pylance

`app/secrets_config.pyi` serve apenas para declarar nomes e tipos ao Pylance. Ele não contém credenciais e não substitui `secrets_config.py` em tempo de execução.

Módulos opcionais de webhook usam FastAPI/Uvicorn e permanecem fora da análise padrão quando essas dependências não estão instaladas.

## Processo antes de mudanças

Antes de alterar comportamento ou configuração:

1. use `app/auditar_mudanca.py` para localizar impactos;
2. identifique código, testes e documentação afetados;
3. altere a fonte da verdade;
4. ajuste testes e documentação ativa;
5. execute `comandos/check-up.bat`;
6. procure referências antigas novamente.

## Ciclo Windows

A distribuição possui quatro executáveis no ciclo Windows, considerando o Setup externo e três componentes instalados:

```text
NexoFlow Setup.exe
  instala, atualiza e registra o desinstalador

NexoFlow Analytics.exe
  check-up -> conexões -> sincronização incremental

NexoFlow Weni.exe
  check-up -> teste de acesso -> dry-run/auditoria -> confirmação -> apply

desinstalar_nexoflow.cmd / installer\uninstall.ps1
  remove a aplicação e pergunta se dados privados devem ser preservados
```

O mutex `Local\NexoFlowOperationLock` impede Analytics, NexoFlow Weni, instalação e desinstalação concorrentes.

## Desenvolvimento do NexoFlow Weni

A rotina de write-back fica separada da sincronização analítica. `app/contact_enrichment.py` extrai apenas evidências conservadoras; `app/weni_update.py` monta e audita planos; `app/weni_client.py` concentra os endpoints. Nenhum novo campo pode ser escrito sem entrar em `ALLOWED_WRITE_FIELDS` e nos testes de auditoria.

Antes de publicar o NexoFlow 1.5.8, valide especialmente que `audit_plans(plans)` aparece antes de `update_contact_fields`, que o checkpoint vem depois das escritas e que o dry-run não executa POST.

Mudanças em pedidos devem manter o enum de status -2 a 4, os nomes oficiais aceitos pelos normalizadores e a separação entre dados brutos da API e status efetivo na Weni/BI. Verifique a rechecagem de -2, -1, 0, 1 e 4 e a elegibilidade de vendas e `ultima_compra` para os status efetivos -2, -1, 0, 4, 1 e 2. Entre os estados documentados, somente 3 exclui a venda; cancelamento explícito ou pagamento 0/`_` força esse status. Toda nova carga deve consultar novamente os pedidos atuais no seu escopo. Para componentes do Data Studio baseados em `BI_Pedidos`, use `venda_valida = 1`; em `BI_Delivery_Pedidos`, use `venda_realizada = 1`. O contrato detalhado está em [docs/PEDIDOS.md](PEDIDOS.md).

Depois de atualizar ou reinstalar uma instalação de validação, gere um novo dry-run completo com `comandos/atualizar_weni_carga_completa.bat`, revise o plano sob a política atual e só então confirme o apply. Execute depois `comandos/executar_carga_completa.bat` para recalcular o Analytics/BI.

## Assinatura

Não desative SmartScreen ou UAC para contornar avisos do Windows. Para exibir um editor verificado, assine a distribuição com Authenticode. Consulte `docs/ASSINATURA WINDOWS.md`.
