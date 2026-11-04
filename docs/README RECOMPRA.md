# NexoFlow 1.5.13 — Recompra FarmaLíder e Pets Líder

O NexoFlow mantém a elegibilidade dos grupos; a **campanha Weni envia as mensagens**. Use o mesmo executável Recompra e escolha o segmento. Cada marca mantém sua organização, template, campanha, fluxo, evento, revisão e estado.

| Configuração | FarmaLíder | Pets Líder |
| --- | --- | --- |
| Grupo/campanha | Recompra FarmaLíder | Recompra Pets Líder |
| Fluxo | Recompra FarmaLíder D+25 | Recompra Pets Líder D+30 |
| Janela do grupo | D+0 a D+25 | D+0 a D+30 |
| Evento de envio | 25 dias depois de `pedido_data` | 30 dias depois de `pedido_data` |
| Campo principal de marketing | `marketing_opt_in` | `opt_in_marketing`, Sim/Não |
| Produtos | Somente humanos | Produtos do segmento PET |

Configure os campos, o template aprovado e o evento na organização correta, conforme [segmentos e fluxos](SEGMENTOS%20E%20FLUXOS.md). `pedido_data` é **Data e hora** e a referência do evento nos dois perfis. `ultimo_pedido` é Texto e recebe o ID oficial no FARMA; `compra_recente` é Data e hora no PET. Nenhum deles substitui a referência `pedido_data`. Não é necessário criar `ultima_compra` na Farma. Pets não exige maioridade.

## Regras de elegibilidade

A última compra precisa ter identidade, proprietário, emissão e itens confirmados pela API do segmento. O cálculo usa **America/Belem (UTC-3)**. Datas futuras, ausentes ou inválidas não autorizam entrada.

Status documentados não cancelados (-2, -1, 0, 4, 1 e 2) podem participar. **Status 3/Cancelado, pagamento cancelado, pagamento fora dos códigos 1 a 6 ou pedido oficialmente sem itens bloqueiam a Recompra.** Uma compra recente incompleta ou cancelada não autoriza recuperar uma compra antiga para agendar outra mensagem.

O grupo mantém a janela do perfil; o envio ocorre somente no D+25/D+30. Novas inclusões e trocas de referência precisam ter o horário do evento ainda futuro. O NexoFlow não faz recuperação retroativa de mensagens.

Recusa no campo de marketing ou associação ao **Opt-Out Marketing** bloqueia a campanha, mesmo que outro campo esteja afirmativo. No Pets, use somente `opt_in_marketing`: **Sim** para aceite e **Não** para recusa. A política vigente permite analisar campo vazio, sem registrá-lo como consentimento. O NexoFlow não cria aceite nem adiciona o contato ao grupo Opt-In Marketing.

Na Farma, pedidos apenas pet/veterinários são excluídos. Nos pedidos mistos, a mensagem considera somente os itens humanos; no dashboard, somente o valor desses itens, sem o frete do pedido inteiro. No Pets, os itens PET são preservados.

Conversa indicando compra posterior ainda não confirmada pela API mantém a referência antiga bloqueada. O campo opcional Texto `pedido_revisao_pendente` preserva essa pendência entre instalações. A data da conversa não substitui a emissão oficial.

## Consulta geral na Recompra FarmaLíder

A Recompra FARMA carrega `clientes/FARMA` uma vez por fase e consulta o índice em memória por CPF e ID do pedido. A preparação não regrava o histórico da base inteira para cada contato. As métricas `leituras_base_geral` e `pendencias_base_geral` representam leituras locais; o diagnóstico HTTP mostra as requisições reais.

As pendências da base geral são separadas no relatório `.txt` e no resumo de aplicação:

| Código | Significado | Tratamento |
| --- | --- | --- |
| `CPF_NAO_CONFIRMADO_BASE_GERAL` | O CPF consultável não consta da base geral carregada. | Reavaliar na próxima leitura; não concluir que o cliente ou a compra não existem. |
| `PEDIDO_NAO_CONFIRMADO_BASE_GERAL` | Há cadastro, mas o pedido/itens não formam um snapshot completo e inequívoco. | Não admitir nem substituir referência; reavaliar na próxima leitura. |
| `ERRO_BASE_GERAL_INCOMPLETA` | A consulta geral não produziu um índice utilizável, por falha de consulta/formato. | Preservar a pendência e as retentativas da consulta geral; sem HTTP individual. |

Os demais contatos continuam sendo aplicados. Um `ultimoPedido: null` explícito representa ausência de pedido; campo omitido não comprova ausência. Autenticação inválida e circuito aberto continuam críticos.

**Contato já no grupo:** enquanto o pedido continuar sem validação, a partir de **sete dias completos (168 horas) de `pedido_data` registrado na Weni**, o NexoFlow propõe retirar o contato do grupo. A regra vale para FARMA e PET; o motivo é `PEDIDO_PENDENTE_7_DIAS`. O prazo não parte da primeira falha nem do início da execução. Antes de sete dias, ou sem data válida, o contato permanece pendente. Não inferir data a partir de `ultimo_pedido`, `compra_recente` ou de uma compra antiga do estado.

A aplicação reconsulta a fonte e relê o contato imediatamente antes da remoção. Se o pedido for validado ou a referência mudar, a proposta antiga fica bloqueada para nova revisão. A retirada não apaga o contato, seus pedidos, campos ou histórico de admissões; continua sendo revalidado nas próximas cargas. Uma reentrada precisa cumprir as guardas existentes, inclusive evento D+25/D+30 futuro e proteção contra repetição de admissão. A regra de sete dias não antecipa o disparo da campanha.

O relatório `.txt` mostra integrantes pendentes e remoções propostas. A auditoria confirma a retirada e preserva a pendência de consulta. Assim, o resultado ainda pode ser parcial (código 3): `aplicados` e `consultas_pendentes` podem contar o mesmo contato quando a remoção foi aplicada, mas a compra continua sem validação. As guardas do fluxo Weni continuam necessárias. Cancelamento, pagamento inválido ou recusa já comprovados na Weni permitem remoção imediata, sem esperar sete dias.

O histórico observado é gravado uma vez por índice carregado, sem regravar todos os pedidos a cada contato. A marca de observação só é confirmada após a gravação bem-sucedida.

Antes da aplicação, uma nova consulta geral substitui a base usada na simulação. Identidade, status, pagamento, itens, recusa, janela D+25 e alterações concorrentes continuam sendo validados. A política exclusiva da base geral aplica-se à Recompra FARMA; os demais módulos e o perfil PET mantêm seus contratos de consulta.

## Carga completa e incremental

O índice em memória da base geral já existia. A versão 1.5.12 conserva essa implementação: uma consulta geral por fase carrega o JSON e permite leituras por CPF/ID sem GET individual quando o snapshot suficiente está disponível. `leituras_base_geral` contabiliza acesso local, não requisições HTTP. A aplicação mantém uma leitura nova, independente da simulação; não reutiliza a preparação como autorização para gravar.

| Modo | Coleta e processamento |
| --- | --- |
| Primeira execução ou estado sem índice compatível | Lê toda a base Weni, valida os contatos e prepara o cache do segmento. |
| Completa (`--full`) | Cobre todos os contatos e valida as regras; compartilha o índice da API e não escreve campos idênticos. Reconstrói o índice de contatos ativos sem apagar o histórico de admissões. |
| Incremental | Busca na Weni alterações desde o cursor confirmado com **15 minutos de sobreposição**. Reaproveita snapshots dos demais contatos e compara a base geral atual localmente. Seleciona novos/alterados, compras/status divergentes, prazos da campanha e pendências. |

`modified_on` da Weni é confiável para o cursor de contatos, mas não comprova alteração de compra na API FarmaLíder. Por isso, a base geral ainda pode ser carregada integralmente na incremental; comparar seus hashes localmente não equivale a consultar ou atualizar todos os clientes pela rede. Não foi criado um endpoint redundante nem um `updated_at` fictício da API.

Estado, cache, cursor e auditoria permanecem separados em FARMA/PET. A simulação não avança o checkpoint. A aplicação registra resultados confirmados e conserva as falhas como retentativas explícitas; uma falha isolada não faz perder o trabalho dos demais. Interrupção crítica não confirma um cursor incompleto. CPF não encontrado pode ser rechecado no próximo dia; fonte ausente/incompleta não se torna prova permanente de ausência de compra.

A janela continua sendo **0 a 25 dias** para preparar a campanha FARMA e **0 a 30 dias** no PET. Os envios são responsabilidade da Weni e ocorrem somente no D+25/D+30. A passagem do dia reavalia os prazos; não cria envio retroativo e não repete admissão confirmada ou indeterminada. Recusa/Opt-Out e pedido cancelado permanecem bloqueantes.

No PET, uma resposta geral explícita e válida com `ultimoPedido: null` também é reutilizada: não exige uma consulta individual para confirmar o mesmo null. Campo omitido, cliente ausente, identidade ambígua e erro HTTP continuam tendo tratamento próprio.

## Escritas, confirmação e métricas

O contador `estado_local` identifica compras que precisavam apenas ser salvas no estado privado. Esse caminho não faz GET ou POST Weni por contato; acumula o trabalho local e confirma o checkpoint atomicamente. Não representa agendamento ou disparo. A intenção de inclusão/alteração de grupo continua persistida antes do POST para impedir repetição após resposta incerta.

Alterações reais enviam somente campos diferentes. Uma resposta de atualização que confirma o UUID e todos os campos esperados pode comprovar uma alteração apenas de campos; resposta insuficiente exige releitura. Admissões e remoções mantêm as conferências próprias de grupo e de prazo. O cache só registra o resultado após sua confirmação.

Os logs separam contatos carregados, selecionados e sem mudança; tempo da base e comparação local; estado local; campos enviados; HTTP real GET/POST por serviço; retries, erros, conflitos, velocidade e duração. Nenhum contador de acesso local deve ser apresentado como requisição HTTP. Escritas remotas seguem o controle de estado e de confirmação por contato; não se presume suporte da API a batch de campos individuais.

## Executar

1. Atualize Weni e Analytics no perfil escolhido.
2. Abra **NexoFlow Recompra**, escolha a marca e aguarde o diagnóstico e a simulação.
3. Confira o relatório e confirme a aplicação solicitada.
4. Execute Analytics para refletir os resultados no Sheets e no dashboard.

O BAT principal é `comandos/atualizar_recompra.bat`; `comandos/atualizar_recompra_pets.bat` fixa o perfil Pets. `RECOMPRA_ENABLED` controla a integração da etapa nas outras rotinas. No Noturno, a revisão é automática, mantendo as validações.

A aplicação sincroniza os campos essenciais do pedido (`pedido_id`, `pedido_data`, `pedido_produtos`, `pedido_status`, `pedido_forma_pagamento`) e o campo auxiliar (`ultimo_pedido` com ID textual na Farma; `compra_recente` com data no Pets). O evento continua usando somente `pedido_data`. Confere a persistência antes da admissão e novamente depois de confirmar a inclusão. Se os campos ou a elegibilidade mudarem após o POST, remove preventivamente o grupo, confirma a remoção e deixa o contato pendente; os demais continuam. O estado preservado impede repetir uma admissão que pode ter sido observada pela campanha.

No Pets, os campos antigos de rótulo **Pedido** e **Ultima_compra** são distintos de `pedido_data` e **Compra recente**. Não os use para conferir o agendamento atual.

A aplicação confere novamente os dados relevantes antes de alterar campos ou grupo. Alterações confirmadas são preservadas. Contatos com falha isolada de consulta ficam pendentes para nova revisão; os demais podem ser aplicados. Uma resposta incerta após gravação exige reconciliação e não autoriza repetir o POST às cegas.

## Conferir ou limpar o grupo

- `comandos/auditar_grupo_recompra.bat`: escolha o perfil para conferir os integrantes sem alterar dados.
- `comandos/limpar_cancelados_recompra.bat`: escolha o perfil, revise o relatório e confirme **LIMPEZA REVISADA** para remover cancelados do grupo existente.

A limpeza não exclui contatos, não cria eventos e não envia mensagens. Use apenas o evento vigente da campanha; o [guia de fluxos](SEGMENTOS%20E%20FLUXOS.md) descreve os vínculos.

## Resultados e retomada

Código **0** indica conclusão; **3** indica pendências; outros códigos indicam interrupção. Consulte o resultado e a auditoria indicada. Gere nova revisão para revalidar pendências; não reaplique indiscriminadamente uma revisão antiga nem apague estado para tentar novamente.

Os arquivos ficam em `logs/` para Farma e `logs/PET/` para Pets. Preserve-os nas atualizações. Pendência local não comprova envio de mensagem; o histórico da campanha deve ser conferido na Weni.

Consulte também [Noturno](NOTURNO.md), [pedidos](PEDIDOS.md) e [API](FARMALIDER%20API.md).

Pedido sem segmento comprovado é inelegível, sem pendência de consulta. `ultimoPedido: null` não admite contato nem reconstrói pedido antigo. Rede/timeout e respostas malformadas continuam pendentes.

## Medir antes de publicar

Execute uma simulação FARMA sem `--apply`, preservando estado e auditoria existentes:

```powershell
cd C:\NexoFlow
.\.venv\Scripts\python.exe app\run_recompra.py --perfil FARMA --dry-run --full --review-out logs\privado\recompra_medicao_farma.json
```

Confira o `HTTP=` real nos logs, a duração, as leituras locais e as contagens dos três motivos acima. A preparação e a aplicação usam leituras separadas, portanto uma leitura HTTP na simulação não comprova toda a execução. Retentativas da consulta geral podem elevar o HTTP sem haver consulta individual.

Se a proporção de pendências for alta, compare uma amostra somente por leitura entre a base geral e a consulta individual, fora da rotina operacional. Não use essa comparação para autorizar inclusão ou alterar campos sem uma nova revisão. Os resultados dos testes sintéticos não comprovam equivalência dos endpoints em produção nem substituem os testes Windows e do pacote instalado.
