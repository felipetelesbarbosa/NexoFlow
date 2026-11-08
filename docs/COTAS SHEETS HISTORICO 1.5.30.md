# Histórico 1.5.30: controlar quota e retomar a revisão aplicada

## Evidência e diagnóstico

O piloto comercial 1.5.29 confirmou 200 pedidos em um lote. O JSON recebido
conferiu esses pedidos sem diferenças de intervalos ou valores e sem respostas
incertas. Os itens e LTV ainda estavam pendentes. A continuação depois terminou
em `SHEETS_QUOTA`, após repetir leituras de grade, cabeçalho, intervalos,
manifesto e mapa. O saldo de 4.300 lotes era o do piloto; a quantidade aplicada
antes da interrupção posterior ainda depende do journal privado do operador.

A [documentação oficial de cotas](https://developers.google.com/workspace/sheets/api/limits?hl=pt-br)
informa como padrão 300 leituras/minuto por projeto e 60 por usuário/projeto,
com cotas de escrita separadas. Uma conta de serviço concentra suas chamadas na
mesma identidade. Criar arquivos/continuações não cria outra cota por arquivo.
A cota efetiva pode diferir; o log recebido não identifica qual limite exato
foi atingido nem comprova que outra automação esteja concorrendo.

O publicador já usa `values_batch_get` com vários intervalos em uma chamada.
O problema comprovado é a ausência de ritmo preventivo: cada lote exige outras
leituras válidas de controle, e o backoff só começa após consumir a cota.
Uma API simulada com janela de 60 leituras/minuto recusou dez de 70 chamadas
rápidas. Com ritmo preventivo, 250 chamadas passaram nesse mesmo teste.

## Implementação

`app/history_sheets_quota.py` decora o adaptador HTTP da sessão gspread
existente. O cliente, autenticação, permissões, proxy, certificados, TLS,
timeouts e payloads continuam os mesmos. A fábrica histórica original, com
seu registro de schemas e validadores, é preservada por herança. A entrada
`history_publish_cli.py` ativa o ritmo antes da primeira requisição da abertura.

- Padrão de **45 leituras e 45 escritas/minuto por identidade/projeto**,
  distribuídas no tempo, com limite adicional conservador de 240/minuto por
  projeto. GET/HEAD e os POSTs de consulta do Sheets usam o orçamento de leitura.
- Um ledger pequeno e independente em `logs/privado/sheets_quota.sqlite`
  coordena comandos de histórico desta instalação, inclusive FARMA/PET usando
  a mesma identidade. Guarda hashes de escopos, tipos de operação e horários;
  não contém tokens, e-mails, IDs de arquivos, pedidos ou valores comerciais.
- Reservas SQLite atômicas e conexões fechadas antes de esperar. Reiniciar o
  comando preserva prazos. Arquivo desconhecido, estado inválido, relógio
  retrocedido ou indisponibilidade bloqueiam sem liberar chamadas cegamente.
- HTTP 429 impõe pausa compartilhada de pelo menos 65 segundos com pequena
  variação, respeitando `Retry-After` maior, inclusive como data HTTP. As outras
  instâncias cooperantes respeitam essa pausa. A espera de 5/10/20 segundos do
  retry existente pode ser complementada por essa pausa compartilhada.
- O adaptador **não repete POST nem qualquer requisição por conta própria**.
  Os retries existentes continuam limitados. Respostas perdidas mantêm o
  contrato de intenção, releitura e conferência antes de repetir fatos.
- Pausa superior a cinco minutos gera erro acionável, mantendo o prazo no
  ledger e a revisão preservada. Não apagar o ledger para ignorar o prazo.
- A cada aproximadamente um minuto, `[REDE SHEETS]` informa tentativas HTTP,
  429 e tempo de espera. Essas tentativas não equivalem a lotes confirmados;
  o journal e a conferência continuam sendo a evidência de confirmação.

O ritmo só coordena os comandos de histórico desta instalação. Não coordena
outros programas, computadores, Apps Script ou o Data Studio. Outras cargas
podem consumir a mesma cota e ainda produzir 429. O controle não promete
ausência absoluta desses erros nem altera cotas do Google Cloud.

Quando for necessário reservar mais margem, o operador pode reduzir os limites
na sessão, antes de abrir o comando:

```powershell
$env:NEXOFLOW_SHEETS_READ_RPM = "30"
$env:NEXOFLOW_SHEETS_WRITE_RPM = "30"
```

Os valores aceitos são inteiros de 1 a 50, com padrão 45. Valores inválidos
geram erro claro. Não trocar tokens/contas para contornar limites. Se 429
persistir, verificar no Console Google Cloud as cotas e métricas efetivas e
as outras aplicações, sem expor credenciais nos relatórios.

## Compatibilidade de revisão e distribuição

Os dez módulos usados por `publisher_signature()` permanecem inalterados em
relação à 1.5.29. Nenhum hash no plano, assinatura, recibo, estado de lote ou
coordenada é modificado para aceitar a atualização. A mudança de transporte é
exclusivamente de ritmo; o pedido enviado ao adaptador original é preservado.

`scripts/check_history_quota_contract.py` confere os módulos dentro dos DOIS
ZIPs antes da publicação. Exige a assinatura dos bytes oficiais CRLF da
1.5.29: fonte LF semanticamente equivalente não basta para o recibo instalado.
Também exige a presença do controlador e sua ativação na CLI. Divergência
interrompe o workflow antes de publicar.

Uma revisão já reconciliada e aplicada na 1.5.29 deve retomar diretamente na
1.5.30, sem preparar outro plano ou reconciliar o código novamente apenas por
esse ajuste. As validações normais continuam obrigatórias. A atualização não
converte fatos incertos em confirmados e não remove guardas.

## Testes

Os testes usam relógio virtual, SQLite temporário, requests e gspread reais
sobre adaptadores/serviços simulados, sem credenciais ou dados comerciais:

- Reproduzem a rajada antiga e demonstram o limite preventivo por janela.
- Comprovam orçamento compartilhado, retomada do cooldown, orçamento independente
  de leitura/escrita e reservas concorrentes atômicas.
- Cobrem Retry-After em segundos/data, 403 sem retry adicional, timeout sem
  reenvio automático, pausa longa, preservação de banco estranho e configuração
  inválida.
- Exercitam a abertura nativa real desde o primeiro HTTP e chamadas diretas do
  lease pelo mesmo cliente; preservam o validador de schema histórico.
- Retomam uma revisão 1.5.25 reconciliada pela lógica 1.5.29 depois de um piloto,
  injetam quota, resposta perdida após escrita e expiração legítima do lease,
  confirmam sem novo POST, fecham, revertem e reaplicam. JSON, fonte, recibo e
  contrato permanecem iguais; a diferença financeira final é zero.
- Bloqueiam pacote sem controlador, entrada que não o ativa, módulo crítico
  alterado/duplicado e conversão de CRLF para LF incompatível com o recibo.

Os resultados completos de Python, Node, lint, tipos, segurança, CodeQL,
matriz Windows, Setup Preserve/Clean/rollback e pacotes são fechados no mesmo
SHA e registrados nas notas da release. Testes simulados não comprovam a cota
efetiva ou o comportamento na conta comercial do operador.

## Roteiro de retomada para o Work

1. Aguardar o comando atual encerrar. Não executar duas aplicações da revisão
   nem instalar enquanto a carga estiver ativa.
2. Preservar plano, journals, backups, recibos e snapshot vinculado. Instalar
   o Setup 1.5.30 oficial em **Preserve**, conferindo o hash publicado.
3. Selecionar FARMA e usar o MESMO caminho de revisão:

```powershell
nexo versao
$planoFarma = "C:\NexoFlow\logs\privado\revisao-farma-existente.json"
nexo historico --planilhas conferir --revisao $planoFarma `
  --resumo-mensal "C:\NexoFlow\logs\privado\farma-quota-antes-1.5.30.json"
```

A conferência informa quantos lotes avançaram realmente. Se houver alteração
dos intervalos publicados, preservar o relatório e interromper antes de aplicar.
Diferenças de itens/LTV ainda não publicados são próprias do escopo parcial;
não equivalem à aprovação financeira integral. Não tratar `sending` como `done`.

4. Aplicar um lote controlado e conferir:

```powershell
nexo historico --planilhas aplicar --revisao $planoFarma --max-lotes 1
nexo historico --planilhas conferir --revisao $planoFarma `
  --resumo-mensal "C:\NexoFlow\logs\privado\farma-quota-piloto-1.5.30.json"
```

O saldo precisa diminuir pelo lote confirmado ou a resposta anteriormente
incerta precisa ser reconhecida sem novo envio. Zero lotes confirmados não
aprova o piloto. Somente após a conferência, continuar e fechar:

```powershell
nexo historico --planilhas aplicar --revisao $planoFarma
nexo historico --planilhas conferir --revisao $planoFarma `
  --resumo-mensal "C:\NexoFlow\logs\privado\farma-fechamento-1.5.30.json"
```

Se o serviço negar uma chamada, preservar a mensagem sanitizada e a revisão.
As pausas preventivas são esperadas; a carga integral pode ser demorada.
Somente saldo zero e fechamento sem diferenças confirmam a publicação inteira.
Manter `LIMITES_DA_API_NAO_HOMOLOGADOS`, pendências, exclusões autorizadas e
separação FARMA/PET. Nenhum painel publicado, fonte comercial ou VPS foi alterado
nesta validação. PET comercial continua posterior à validação de FARMA.
