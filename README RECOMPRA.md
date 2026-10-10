# NexoFlow 1.0 — Recompra FarmaLíder D+25

## Regra operacional vigente

A regra final considera as respostas mais recentes: o grupo **Recompra FarmaLíder** contém os contatos cuja **última compra confirmada tem de 0 a 25 dias**, inclusive, pela data local em `America/Belem`. Com 26 dias ou mais, o contato sai. Datas futuras, ausentes ou inválidas não autorizam entrada. O envio ocorre **exclusivamente no D+25**, pela campanha e pelo fluxo existentes na Weni; o NexoFlow não envia WhatsApp nem cria, ativa ou modifica a campanha.

Exemplo em 09/10/2026: compras de 15/09 ficam no grupo (24 dias), compras de 14/09 ficam no grupo (25 dias) e compras de 13/09 saem (26 dias). Apenas a compra de 14/09 pode passar pela guarda D+25 do fluxo naquele dia. Uma compra de um ano atrás não recebe recuperação retroativa.

A regra de confirmação é a mesma do NexoFlow: status 4, 1 ou 2, validação oficial da identidade e do pedido, produtos identificados e nenhuma condição de cancelamento, incluindo pagamento 0. Status -2, -1, 0 e 3 não autorizam essa campanha. Essa é a classificação operacional adotada; não acrescentamos um comprovante financeiro que a API não fornece.

Conforme a orientação posterior do responsável, bloqueiam **Opt-Out Marketing** e valores de recusa em `marketing_opt_in`, inclusive `recusado`, `Não`, `nao` e `negado`. Campo vazio não bloqueia nesta política, denominada `JANELA_0_A_25_SEM_RECUSA`. Isso não é registrado como consentimento: o NexoFlow não preenche `marketing_opt_in` nem adiciona a Opt-In Marketing. Essa política substitui o critério anterior de exigir autorização positiva em outra origem.

## Arquitetura e salvaguardas

- Reutiliza `WeniClient`, `FarmaliderClient`, a seleção por identidade e `resolve_contact_order`; não introduz um endpoint de histórico inexistente.
- Consulta CPFs válidos primeiro e conclui essa fase antes dos inválidos preenchidos, incluindo zeros; ausentes ficam por último. Compartilha payloads brutos de GET por CPF e pedido na execução, mas valida cada contato por identidade; CPF inválido continua exigindo nome + e-mail ou nome + telefone, sem ambiguidade.
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
- Cada apply exige snapshot revisado do mesmo dia e estrutura da campanha inalterada. Planos que alteram campos, grupo ou estado local exigem releitura do contato, nova confirmação na FarmaLíder e comparação do plano. Recusa ou compra que mudou após a revisão gera conflito, sem POST daquele contato. Planos sem trabalho são contabilizados e pulados antes dos GETs; mudanças posteriores serão propostas no próximo dry-run.
- A rotina de recompra varre os contatos também no incremental: o relógio e novas compras na FarmaLíder não alteram necessariamente `modified_on` na Weni. Sem GET de compras modificadas ou webhook, limitar apenas a contatos modificados perderia essas mudanças.
- Revisão e auditoria são privadas e ignoradas no Git/pacotes. As demais rotinas de Analytics, pedidos, CPF, LGPD e planilhas continuam com seus próprios controles.

## Otimizações de processamento

- O dry-run começa a resolver CPFs válidos durante a leitura das páginas Weni. Contatos inválidos ou sem CPF são adiados em arquivos temporários privados, removidos ao terminar ou falhar. Não carrega a lista completa de contatos antes de começar; o snapshot final ainda contém todos os planos para revisão.
- Até quatro consultas à FarmaLíder ocorrem simultaneamente. Todas usam a mesma instância do cliente, suas sessões por thread e seus limites globais de ritmo, cooldown, recuperação e circuito de falhas. A fila de trabalho contém no máximo oito contatos com a configuração padrão.
- O cache de leitura tem limite de 4.096 respostas brutas e reúne consultas simultâneas à mesma chave. Falhas transitórias não ficam cacheadas; respostas 404 e rejeições 400 podem ser reutilizadas nesta execução. O cache é descartado ao fim de cada dry-run ou apply, evitando usar a confirmação do dry-run na aplicação.
- Na aplicação, campos iguais continuam sem POST, planos sem trabalho dispensam consultas e gravações locais idênticas são evitadas. Inclusões mantêm a persistência de intenção antes do POST e de confirmação depois dele. As escritas e verificações de grupo continuam sequenciais.
- O cliente usado pela recompra faz uma única tentativa de cada POST. Timeout, resposta inválida ou erro HTTP interrompem a aplicação com o estado preservado; a inclusão não é repetida dentro da mesma chamada. As leituras GET continuam usando os controles de retry existentes.
- Os logs mostram contatos processados, tempo, velocidade no dry-run, consultas e reutilizações do cache. O ganho real depende da latência, dos limites das APIs e da quantidade de planos com alterações.

Para usar apenas uma consulta por vez no dry-run, execute `nexo weni recompra dry-run --workers 1`. O padrão de quatro consultas já vale para os launchers existentes. `--full` mantém a auditoria completa; não usa dados antigos para dispensar a confirmação oficial.

## Comandos

No NexoFlow Terminal:

```text
nexo weni recompra auditoria
nexo weni recompra dry-run
nexo weni recompra dry-run --workers 4
nexo weni recompra dry-run --contato UUID_WENI
nexo weni recompra aplicar --revisao logs/recompra_review.json
nexo weni recompra atualizar
```

`atualizar` executa diagnóstico, dry-run, confere a validade do snapshot, abre o relatório e solicita **RECOMPRA REVISADA** em uma janela separada. Fechar o Bloco de Notas não confirma nem encerra a espera. Cancelar a confirmação ou falhar nas etapas anteriores à aplicação não inicia gravações.

Se o dia mudar antes de qualquer gravação, o launcher renova o dry-run uma vez, abre um novo arquivo de relatório e pede outra confirmação. A confirmação anterior não autoriza o relatório renovado. Se o próprio dry-run atravessar a meia-noite, seus planos não são publicados sob a data nova: o cálculo é refeito com o dia atual.

A aplicação verifica a data também entre contatos, depois das consultas e antes dos POSTs. Uma virada de dia após o início das gravações interrompe o processo sem renovação automática. Admissões confirmadas continuam registradas; resultados incertos continuam pendentes. Confira `logs/recompra_audit.jsonl` e gere outra revisão antes de retomar, preservando `logs/recompra_state.json`.

Para conferir apenas a integridade e o dia de um snapshot, sem inicializar as APIs:

```text
python run_recompra.py --check-review --require-review logs/recompra_review.json
```

O retorno `4` identifica revisão expirada sem aplicação iniciada. Erros de revisão inválida, conflito, falha ou aplicação já iniciada não acionam a renovação automática. Se a revisão renovada também expirar, a rotina encerra e informa que precisa ser executada novamente.

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

## Falhas e diagnóstico seguro (10/10/2026)

Após interrupção do apply, **não repita o snapshot** nem apague `logs/recompra_state.json`, `logs/recompra_audit.jsonl` ou `logs/recompra_state.lock` sem investigar. O log anterior, com apenas `RuntimeError`, não prova se o problema foi Weni, checagem local ou rede FarmaLíder; a resposta HTTP 200 da FarmaLíder não confirma POSTs à Weni.

Para inspecionar **somente os arquivos locais**, sem rede ou gravação:

```text
.venv\\Scripts\\python.exe run_recompra.py --diagnose-state
```

O resultado exibe totais de admissão local, `pending`, eventos da auditoria e as últimas pendências. `pending` significa **intenção de inscrição cujo resultado remoto não pode ser presumido**, não mensagem enviada. A amostra de UUIDs permite conferência manual na Weni; os arquivos privados não devem ser publicados no GitHub. Auditorias anteriores à correção podem não ter `stage` ou `error_type`.

Em novas falhas, `logs/nexoflow_recompra.log` registra etapa, tipo e origem (arquivo/linha/função) sem corpo da API, CPF ou token; a auditoria anota etapa e tipo. Divergência de guarda ou desaparecimento de contato **antes de tentar o POST de inclusão** agora vira conflito auditado, desfaz o `pending` criado na execução e continua nos demais contatos, exigindo uma nova revisão para aquele contato. Falha ao adicionar no grupo continua bloqueando o reenvio automático: reconcilie a intenção com o estado real da Weni antes de considerar qualquer ação manual.

Somente após reconciliar as pendências, gere um **novo dry-run e nova revisão humana do dia**. O NexoFlow não faz reenvio retroativo nem altera a campanha por conta própria.

## Testes

Fixtures sintéticas cobrem 0, 24, 25, 26 e 365 dias, futuro, fuso local, campos vazios, produtos com vírgula, recusas e Opt-Out, estados de pedido, proteção contra regressão de compra, referência nova, reprocessamento/reinicialização, resposta incerta, estado corrompido, revisão adulterada/expirada, recusa concorrente, cancelamento antes de atualizar a data e rotas do fluxo que tentariam contornar as guardas.

Os testes de otimização verificam paginação sob demanda, concorrência limitada, prioridade global dos CPFs, cache de payloads sem compartilhamento de identidade, descarte de falhas transitórias, limpeza de temporários e aplicação sem consultas para planos sem trabalho.

Os testes de virada do dia verificam expiração antes das gravações, interrupção após alterações parciais, preservação de uma inclusão confirmada que atravessou a meia-noite, renovação de todo o dry-run e ausência de repetição interna de POST.
