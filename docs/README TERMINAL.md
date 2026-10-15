# NexoFlow 1.0 — Terminal

O **NexoFlow Terminal** é a interface de comandos do NexoFlow para uso operacional e diagnóstico. Ele foi pensado para quem não trabalha diariamente com Python, PowerShell ou APIs.

Ao abrir `NexoFlow Terminal.exe`, o NexoFlow:

- entra automaticamente em `C:\NexoFlow`;
- prioriza a `.venv` do projeto;
- carrega a configuração de proxy da sessão sem exibir senha;
- mantém tokens Weni/FarmaLíder e credenciais Google nos arquivos locais, sem exportá-los para o ambiente;
- disponibiliza o comando curto `nexo`.

## Começando

Digite:

```text
nexo
```

para abrir um menu simples.

Para listar todos os comandos disponíveis:

```text
nexo ajuda
```

Também funcionam:

```text
nexo comandos
nexo help
```

## Comandos gerais

### Cargas por planilhas

Coloque `Conversas_Delivery.xlsx` e `Contatos_Delivery.xlsx` em `C:\NexoFlow\importacoes`, preservando as abas e os cabeçalhos originais dos exports.

```text
nexo weni planilhas
nexo analytics planilhas
```

Weni atualiza somente os campos de pedido dos clientes identificados. Analytics atualiza o Google Sheets com os pedidos confirmados e sua data real, sem gravar na Weni. Os comandos consultam primeiro CPFs válidos e depois inválidos. CPFs válidos dispensam comparação de nome, telefone ou e-mail; inválidos exigem primeiro nome correspondente ou número local do telefone correspondente do mesmo cliente, ignorando +55 e DDD, sem ambiguidade. Zeros à esquerda são repostos até 11 dígitos somente quando tornam o CPF matematicamente válido, sem alterar os dígitos existentes. Cada comando gera uma revisão privada e aguarda `PLANILHAS REVISADAS` antes de aplicar. Não exigem o token de integração do Chats. Veja [Carga por planilhas](README%20DELIVERY.md) para a seleção de tags, validações, configuração e limitações de atribuição.

### Status

```text
nexo status
```

Mostra versão, Python, ambiente virtual, proxy, checkpoint do Weni, conflitos pendentes e testa as conexões de leitura com Weni e FarmaLíder.

Para ver somente o estado local, sem consultar APIs:

```text
nexo status --local
```

### Diagnóstico completo

```text
nexo diagnostico
```

Executa o check-up do projeto e depois o teste de conexões do NexoFlow Weni. Não grava contatos.

Aliases:

```text
nexo doctor
nexo check
```

### Versão

```text
nexo versao
```

## Operações do NexoFlow Weni

### Testar acessos

```text
nexo weni testar
```

Verifica os acessos necessários ao NexoFlow Weni sem alterar contatos.

### Dry-run

```text
nexo weni dry-run
```

Calcula e audita as alterações propostas sem gravar na Weni.

### Atualização incremental

```text
nexo weni atualizar
```

Executa o fluxo seguro incremental: check-up, teste, dry-run, auditoria, confirmação e apply.

### Carga completa

```text
nexo weni carga-completa
```

Executa o backfill completo com relatório para revisão humana e snapshot congelado. É a rotina indicada para primeira carga ou reconstrução geral.

Depois de atualizar ou reinstalar o NexoFlow 1.0, execute essa rotina para gerar um novo dry-run completo com a política atual. Revise o relatório antes de confirmar `CARGA COMPLETA REVISADA`; não reutilize o snapshot da instalação anterior. Em seguida, execute `comandos/executar_carga_completa.bat` em `C:\NexoFlow` para recalcular o Analytics/BI e retome o incremental.

Na revisão, pedidos validados pela API com status efetivo -2 (Em aberto), -1 (Pendente de pagamento), 0 (Em processamento), 4 (Pronto para rota), 1 (Em trânsito) ou 2 (Concluído) entram em vendas e `ultima_compra`. Entre os estados documentados, somente o status efetivo 3 (Cancelado) exclui a venda; pagamento 0 ou `_` e cancelamento explícito forçam esse status. Os estados -2, -1, 0, 4 e 1 permanecem em rechecagem, e cada nova carga reconsulta os pedidos atuais no seu escopo. Consulte [README PEDIDOS.md](README%20PEDIDOS.md) para o contrato completo.

## Analytics

```text
nexo analytics
```

Executa o NexoFlow Analytics pelo launcher oficial do projeto.

## Consultas da API Weni

Os comandos abaixo são **somente leitura**. Eles não executam POST, PATCH ou DELETE.

### Testar Weni

```text
nexo api weni status
```

### Consultar contato pelo UUID

```text
nexo api weni contato --uuid UUID_DO_CONTATO
```

Exibe de forma amigável nome, URNs, canal principal, CPF, idade, LGPD e datas.

### Consultar contato pela URN

```text
nexo api weni contato --urn "whatsapp:5591987654321"
```

A URN pode ser de WhatsApp, Instagram, Facebook/Messenger ou outro canal reconhecido pela Weni.

### Consultar mensagens

```text
nexo api weni mensagens --uuid UUID_DO_CONTATO --limite 10
```

ou:

```text
nexo api weni mensagens --urn "whatsapp:5591987654321" --limite 10
```

O limite aceito é de 1 a 100 mensagens.

### Listar grupos

```text
nexo api weni grupos
```

Filtrar por nome:

```text
nexo api weni grupos --nome "Opt-In LGPD"
```

### Listar campos

```text
nexo api weni campos
```

Consultar uma chave específica:

```text
nexo api weni campos --chave cpf
nexo api weni campos --chave contact_urn
```

## Consultas da API FarmaLíder

Os comandos abaixo também são **somente leitura** e usam os mesmos tokens/proxy já configurados no NexoFlow.

### Testar FarmaLíder

```text
nexo api farmalider status
```

Mostra ambiente, HTTP retornado e URL base usada. O token nunca é mostrado.

### Consultar cliente por CPF

```text
nexo api farmalider cliente --cpf 52998224725
```

Também aceita CPF com pontuação.

A consulta usa o endpoint de leitura de cliente por CPF já suportado pelo NexoFlow.

### Consultar pedido

```text
nexo api farmalider pedido 123456
```

Consulta o pedido pelo código oficial usando o endpoint de leitura já suportado pelo NexoFlow.

## JSON e salvar resposta

Nas consultas de API, use `--json` para ver a resposta completa:

```text
nexo api weni contato --uuid UUID --json
nexo api farmalider pedido 123456 --json
```

`--raw` funciona como alias de `--json`.

Para salvar em arquivo:

```text
nexo api farmalider pedido 123456 --salvar pedido.json
nexo api weni campos --salvar campos_weni.json
```

O arquivo é salvo em `C:\NexoFlow` quando não for informado um caminho absoluto.

## Logs

### Últimas linhas do Weni

```text
nexo logs weni
```

Por padrão mostra as 50 últimas linhas.

```text
nexo logs weni --linhas 100
```

### Acompanhar ao vivo

```text
nexo logs weni --seguir
```

Encerre o acompanhamento com `Ctrl+C`.

### Log do Analytics

```text
nexo logs analytics
```

## Segurança dos comandos de API

A família `nexo api` foi criada como ferramenta de consulta e diagnóstico. Na versão 1.0 ela expõe apenas operações de leitura já suportadas pelos clientes oficiais do NexoFlow.

Ela não oferece comando genérico para POST, PATCH ou DELETE. Atualizações da Weni continuam obrigatoriamente passando por `nexo weni atualizar` ou `nexo weni carga-completa`, preservando dry-run, auditoria e confirmação.

Os tokens não são exibidos nos resultados nem adicionados aos arquivos JSON exportados pelo Terminal.

## Referência rápida

```text
nexo
nexo ajuda
nexo status
nexo status --local
nexo diagnostico
nexo versao

nexo weni testar
nexo weni dry-run
nexo weni atualizar
nexo weni carga-completa

nexo analytics

nexo api weni status
nexo api weni contato --uuid <UUID>
nexo api weni contato --urn <URN>
nexo api weni mensagens --uuid <UUID> --limite 10
nexo api weni grupos
nexo api weni campos

nexo api farmalider status
nexo api farmalider cliente --cpf <CPF>
nexo api farmalider pedido <CODIGO>

nexo logs weni
nexo logs weni --seguir
nexo logs analytics
```
