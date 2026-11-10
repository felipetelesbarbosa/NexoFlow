# Frações e leituras agrupadas do histórico

Estado: incluído na entrega 1.5.31 em validação.
Não alterar a instalação nem a execução comercial em andamento. Os comandos
abaixo são do código em desenvolvimento: não estão disponíveis no Setup 1.5.30.
Nenhuma carga comercial, API de pedidos, Weni, Noturno ou Recompra é executada
para preparar estas melhorias.

## Frações

```powershell
nexo historico --planilhas aplicar --revisao $planoFarma --percentual 25
```

Aceita 25, 50, 75 e 100. Cada chamada limita a quantidade de lotes que ela pode
confirmar ao teto da fração do total ORIGINAL. Não significa atingir uma meta
cumulativa de 25%; não se calcula sobre o saldo, nem sobre dias/receita.
Em 4.301 lotes, 25% permite até 1.076 lotes/215.200 linhas nessa execução;
o motor para no saldo disponível. A quarta execução recebe só o saldo final.
`--percentual 100`, ou ausência de limites, processa todo o saldo.
`--max-lotes 1` continua sendo o piloto de até 200 linhas. Não combinar limites.
Não há agendamento automático: o operador escolhe quando executar as frações.

Uma fração confirmada NÃO libera o leitor para apresentar a carga como inteira.
O fechamento, itens/LTV, receita e cobertura só são aprovados na conferência
integral. Não inativar fatos fora da fração.

## Aceleração sem remover proteções

`history_sheets_bulk.py` especializa o transporte original. `read_rows` lê o
cabeçalho completo e as posições existentes em UMA chamada `values.batchGet`,
com `valueRenderOption=FORMULA`. A geometria atual continua sendo lida. Não
usa cache de cabeçalho, manifesto, intervalos, capacidade ou permissões.

Quando há posições existentes, elimina uma requisição por chamada de
`read_rows`, até duas por lote (antes e depois da escrita). Para coordenadas
futuras, só consulta o cabeçalho: não expande a grade antes de backup/intenção.
As demais requisições, dados e guardas continuam iguais. O ganho total depende
da estrutura, partes e rede; não equivale a multiplicar a velocidade por dois.

Continua usando 45 leituras/escritas por minuto, ledger compartilhado,
cooldown de 429/Retry-After e nenhum reenvio automático de POST. Não há garantia
de ausência de 429 se outros aplicativos/computadores consomem a mesma quota.
O controle de pacote mantém os dez módulos críticos byte a byte; a revisão,
recibo e journal existentes não são editados para aceitar código novo.

## Falha de lote e retomada específica

Uma interrupção deixa confirmados os lotes já `done`. A CLI tenta registrar
um relatório `interrupcao_<evento>.json` e o resumo `ultima_interrupcao.json`
no diretório privado do journal, com data, classe de erro, código HTTP e número do
primeiro lote pendente, tabela, parte e estado. Não inclui valores comerciais,
identidades, tokens ou resposta do provedor. O cursor NÃO prova que a causa do
erro foi exclusivamente aquele lote: manifesto, permissão ou rede podem falhar
antes de alcançá-lo. A mensagem de erro sanitizada continua visível no terminal.

Para retomar apenas o lote indicado, depois de avaliar a causa:

```powershell
nexo historico --planilhas aplicar --revisao $planoFarma --retomar-lote 33
nexo historico --planilhas conferir --revisao $planoFarma --resumo-mensal $relatorio
```

O número é exemplo, não instrução para a carga comercial atual. Só o primeiro
lote pendente é aceito; não pode pular dependências nem um rollback pendente.
A retomada passa pelas validações normais, lê as células, reconhece resposta
incerta sem novo POST quando os valores já correspondem, ou grava após comprovar
os valores anteriores. Alteração de terceiros, permissão ou schema bloqueia.
Não há opção de ignorar falha e continuar cegamente.

## Validação e distribuição

Testes usam SQLite e serviços simulados, lógica real da CLI/publicador,
frações consecutivas, retomada, fechamento ao centavo, repetição sem nova
escrita, cabeçalho alterado entre leituras, resposta incompleta, coordenadas
futuras, geometria alterada e falha por lote preservada. O Setup futuro requer
CI Windows 3.11/3.14, executáveis/pacotes, Preserve/Clean/rollback e conferência
dos bytes do contrato. Simulação não comprova performance ou quota comercial.

## Resultados desta implementação

- Regressão local Linux: 1.963 testes Python, 73 ignorados, zero falhas;
  33 testes Node aprovados. Ruff, Pyright, consistência e auditoria de
  dependências aprovados.
- Cenário sintético aquecido de releitura do mesmo intervalo: três chamadas
  de leitura no caminho anterior, duas no agrupado. A redução é uma chamada
  por releitura com linhas existentes, não uma promessa de ganho comercial
  equivalente. A primeira abertura tem custos adicionais e não é comparável
  a um lote aquecido.
- Quatro frações fecham a mesma revisão; valores, centavos e estado remoto
  conferidos. Repetição após conclusão não gera nova escrita de fatos.
- Quota, perda de resposta após escrita, retomada e rollback também executados
  com o transporte agrupado real sobre serviços simulados.
- Wheel privado construído sem baixar dependências, conferindo presença/bytes
  dos novos módulos. Não substitui validação de EXE/Setup instalado no Windows.
- A instalação 1.5.30 e sua carga comercial continuam inalteradas. CI Windows,
  CodeQL e empacotamento da próxima distribuição precisam ser aprovados antes
  de disponibilizar o Setup seguinte. Nenhum release novo foi publicado nesta
  etapa de desenvolvimento.
