# NexoFlow 1.0 — Recompra FarmaLíder D+25

## Regra operacional vigente

A regra final considera as respostas mais recentes: o grupo **Recompra FarmaLíder** contém os contatos cuja **última compra confirmada tem de 0 a 25 dias**, inclusive, pela data local em `America/Belem`. Com 26 dias ou mais, o contato sai. Datas futuras, ausentes ou inválidas não autorizam entrada. O envio ocorre **exclusivamente no D+25**, pela campanha e pelo fluxo existentes na Weni; o NexoFlow não envia WhatsApp nem cria, ativa ou modifica a campanha.

Exemplo em 09/10/2026: compras de 15/09 ficam no grupo (24 dias), compras de 14/09 ficam no grupo (25 dias) e compras de 13/09 saem (26 dias). Apenas a compra de 14/09 pode passar pela guarda D+25 do fluxo naquele dia. Uma compra de um ano atrás não recebe recuperação retroativa.

A regra de confirmação é a mesma do NexoFlow: status 4, 1 ou 2, validação oficial da identidade e do pedido, produtos identificados e nenhuma condição de cancelamento, incluindo pagamento 0. Status -2, -1, 0 e 3 não autorizam essa campanha. Essa é a classificação operacional adotada; não acrescentamos um comprovante financeiro que a API não fornece.

Conforme a orientação posterior do responsável, bloqueiam **Opt-Out Marketing** e valores de recusa em `marketing_opt_in`, inclusive `recusado`, `Não`, `nao` e `negado`. Campo vazio não bloqueia nesta política, denominada `JANELA_0_A_25_SEM_RECUSA`. Isso não é registrado como consentimento: o NexoFlow não preenche `marketing_opt_in` nem adiciona a Opt-In Marketing. Essa política substitui o critério anterior de exigir autorização positiva em outra origem.

## Arquitetura e salvaguardas

- Reutiliza `WeniClient`, `FarmaliderClient`, a seleção por identidade e `resolve_contact_order`; não introduz um endpoint de histórico inexistente.
- Consulta CPFs válidos primeiro e inválidos depois. Compartilha GET por CPF na execução, mas valida cada contato por identidade; CPF inválido continua exigindo nome + e-mail ou nome + telefone, sem ambiguidade.
- Atualiza `pedido_data` com ISO 8601 com offset `-03:00`, `pedido_produtos` com CSV compatível com as listas atuais, `ultimo_pedido` com o serializador oficial. A recompra usa exclusivamente `pedido_data`; não exige, consulta ou altera `ultima_compra`.
- Atualiza também ID, quantidades, valores unitários, total, status e pagamento usando o plano de pedido existente; não mistura campos de duas compras no Analytics. Itens incompletos bloqueiam a admissão.
- Produtos com vírgulas mantêm aspas de CSV; não são artificialmente divididos. Produtos não são substituídos por códigos.
- Não substitui uma compra confirmada mais recente por um pedido antigo. Um pedido recente cancelado ou pendente não apaga a compra confirmada anterior.
- Quando o último pedido da API não é uma venda, tenta revalidar um ID de compra anterior conhecido pelo estado ou JSON Weni. Só aceita GET oficial com o mesmo cliente. Sem um ID conhecido, não inventa nem afirma ter percorrido todo o histórico de compras da FarmaLíder.
- Retira o grupo antes de alterar uma referência que já estava agendada; verifica a remoção, atualiza campos e relê o contato antes da admissão. Nova compra recalcula a janela usando sua data.
- A atualização Weni convencional também inclui no seu plano auditado uma remoção preventiva quando a referência muda, o pedido deixa de ser venda, há recusa ou o prazo expira. Executa essa remoção antes dos campos; a admissão fica na rotina de recompra revisada.
- `logs/recompra_state.json` registra por UUID e ID do pedido a compra de referência, intenção pendente e admissão reconhecida. Não registra admissão como mensagem enviada.
- Intenção persistida antes do POST, gravação atômica e lock impedem execução simultânea e reentrada após timeout/resposta perdida. Estado corrompido bloqueia aplicação, em vez de zerar a proteção.
- O mesmo pedido não reentra depois de o fluxo removê-lo, inclusive após reiniciar o NexoFlow. Uma intenção indeterminada exige investigação; não há reset automático para tentar disparar novamente.
- Cada apply exige snapshot revisado do mesmo dia, estrutura da campanha inalterada, releitura do contato, nova confirmação na FarmaLíder e comparação do plano. Recusa ou compra que mudou após a revisão gera conflito, sem POST daquele contato.
- A rotina de recompra varre os contatos também no incremental: o relógio e novas compras na FarmaLíder não alteram necessariamente `modified_on` na Weni. Sem GET de compras modificadas ou webhook, limitar apenas a contatos modificados perderia essas mudanças. A API de CPF é deduplicada; os controles de retry/throttle existentes continuam ativos.
- Revisão e auditoria são privadas e ignoradas no Git/pacotes. As demais rotinas de Analytics, pedidos, CPF, LGPD e planilhas continuam com seus próprios controles.

## Comandos

No NexoFlow Terminal:

```text
nexo weni recompra auditoria
nexo weni recompra dry-run
nexo weni recompra dry-run --contato UUID_WENI
nexo weni recompra aplicar --revisao logs/recompra_review.json
nexo weni recompra atualizar
```

`atualizar` executa diagnóstico, dry-run, abre o relatório e solicita **RECOMPRA REVISADA** em uma janela separada. Fechar o Bloco de Notas não confirma nem encerra a espera. Cancelar ou falhar não aplica a recompra.

Também pode usar a entrada existente, inclusive no Linux para testes/desenvolvimento:

```text
python run_update_weni.py --recompra --check-only
python run_update_weni.py --recompra --dry-run
python run_update_weni.py --recompra --dry-run --full
python run_update_weni.py --recompra --apply --require-review logs/recompra_review.json
```

Para encadear após os launchers incrementais e completos do Weni, inclua em seu `secrets_config.py`, depois da auditoria inicial:

```python
RECOMPRA_ENABLED = True
```

Essa configuração habilita a **etapa NexoFlow**, não ativa a campanha. A etapa tem revisão própria antes de qualquer aplicação. Em carga de quatro partes, roda após a parte 4; na carga completa integral, depois da aplicação integral. Se a etapa de recompra falhar, o launcher informa a pendência sem afirmar que a carga Weni já concluída foi desfeita. Sem essa configuração, é executada pelos comandos próprios e não altera o roteiro de uso anterior.

Agendar somente o dry-run prepara um relatório; não aplica automaticamente uma autorização antiga. A exigência de revisão humana permanece. Não reutilize um snapshot de ontem no agendador para tentar recuperar mensagens.

## Auditoria real realizada em 09/10/2026

A API Weni retornou o grupo Recompra FarmaLíder, Opt-Out Marketing e Opt-In Marketing; organização com `America/Belem`; uma campanha com um evento de **25 dias depois de pedido_data**, `delivery_hour=-1`, fluxo Recompra FarmaLíder D+25. O fluxo real e o JSON fornecido foram inspecionados: Opt-Out/recusa levam ao encerramento, a guarda D25 usa data local, falta de produtos encerra e o template é `recompra`.

A configuração de recompra não depende de `ultima_compra`: conforme a última orientação, `pedido_data` é a única referência temporal. O export contém duas representações da campanha, uma sem eventos; não foi reimportado para evitar duplicar configuração.

Houve tentativa de dry-run em uma amostra de contatos reais. A FarmaLíder retornou HTTP 500/503, impedindo confirmação segura. Um diagnóstico pelo launcher local também encontrou conexão recusada na rota corporativa a partir da nuvem. Essas falhas não são apresentadas como clientes inexistentes. Nenhum POST de contato, grupo, fluxo ou campanha foi realizado durante essa validação.

## Eventos Weni: evidência e limites

Referências consultadas:

- [Explorador oficial da API Weni](https://flows.weni.ai/api/v2/explorer/): GET de campanhas, eventos, campos, grupos e definições; DateTime e deslocamento de evento.
- [Mecanismo de campanhas do Mailroom upstream](https://github.com/rapidpro/mailroom/blob/main/core/models/campaigns.go): horário no passado não cria um novo evento.
- [Recalculo por grupo/data no upstream](https://github.com/rapidpro/mailroom/blob/main/core/hooks/update_campaign_events.go): saída do grupo remove eventos não disparados; alteração da referência remove e recalcula agendamentos.
- [Processamento de eventos no upstream](https://github.com/rapidpro/mailroom/blob/main/core/tasks/campaigns/fire_campaign_event.go): eventos já processados não devem ser disparados de novo pelo mesmo registro.

O código upstream explica o mecanismo, mas não prova a versão exata implantada na Weni. A validação de cancelar/agendar por alteração de grupo deve ser feita com um contato de teste e campanha de teste antes da primeira aplicação operacional; essa sessão não acionou produção para fazer esse teste.

Com `delivery_hour=-1`, o horário é o da compra +25 dias. Se entrar no grupo no D+25 depois desse horário, a entrada **não garante envio naquele dia** e o NexoFlow não altera a data para provocar envio atrasado. Se uma fila retomar em D+26, a guarda D25 do fluxo inspecionado termina sem enviar. Remover do grupo cancela eventos não disparados; não garante interromper um fluxo que já começou.

Não há confirmação de entrega do WhatsApp nesta rotina. A proteção local impede reentrada iniciada pelo NexoFlow, mas não impede edições manuais externas do grupo/campo nem duplicações causadas por outros sistemas. Se uma compra nova ocorrer na FarmaLíder enquanto o NexoFlow estiver parado e a Weni ainda guardar a compra antiga, o fluxo atual não faz GET à FarmaLíder antes de enviar. Garantir essa situação exige webhook de compra ou confirmação no fluxo antes do envio; nenhuma dessas alterações de produção foi ativada automaticamente.

## Testes

Fixtures sintéticas cobrem 0, 24, 25, 26 e 365 dias, futuro, fuso local, campos vazios, produtos com vírgula, recusas e Opt-Out, estados de pedido, proteção contra regressão de compra, referência nova, reprocessamento/reinicialização, resposta incerta, estado corrompido, revisão adulterada/expirada, recusa concorrente, cancelamento antes de atualizar a data e rotas do fluxo que tentariam contornar as guardas.
