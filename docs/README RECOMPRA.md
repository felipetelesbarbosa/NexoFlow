# NexoFlow 1.5.9 — Recompra FarmaLíder e Pets Líder

O NexoFlow mantém a elegibilidade dos grupos; a **campanha Weni envia as mensagens**. Use o mesmo executável Recompra e escolha o segmento. Cada marca mantém sua organização, template, campanha, fluxo, evento, revisão e estado.

| Configuração | FarmaLíder | Pets Líder |
| --- | --- | --- |
| Grupo/campanha | Recompra FarmaLíder | Recompra Pets Líder |
| Fluxo | Recompra FarmaLíder D+25 | Recompra Pets Líder D+30 |
| Janela do grupo | D+0 a D+25 | D+0 a D+30 |
| Evento de envio | 25 dias depois de `pedido_data` | 30 dias depois de `pedido_data` |
| Campo principal de marketing | `marketing_opt_in` | `opt_in_marketing`, Sim/Não |
| Produtos | Somente humanos | Produtos do segmento PET |

Configure os campos, o template aprovado e o evento na organização correta, conforme [segmentos e fluxos](SEGMENTOS%20E%20FLUXOS.md). `pedido_data` é **Data e hora** e a referência do evento nos dois perfis. `ultima_compra` (Farma) e `compra_recente` (Pets) não substituem essa referência. Pets não exige maioridade.

## Regras de elegibilidade

A última compra precisa ter identidade, proprietário, emissão e itens confirmados pela API do segmento. O cálculo usa **America/Belem (UTC-3)**. Datas futuras, ausentes ou inválidas não autorizam entrada.

Status documentados não cancelados (-2, -1, 0, 4, 1 e 2) podem participar. **Status 3/Cancelado, pagamento cancelado, pagamento fora dos códigos 1 a 6 ou pedido oficialmente sem itens bloqueiam a Recompra.** Uma compra recente incompleta ou cancelada não autoriza recuperar uma compra antiga para agendar outra mensagem.

O grupo mantém a janela do perfil; o envio ocorre somente no D+25/D+30. Novas inclusões e trocas de referência precisam ter o horário do evento ainda futuro. O NexoFlow não faz recuperação retroativa de mensagens.

Recusa no campo de marketing ou associação ao **Opt-Out Marketing** bloqueia a campanha, mesmo que outro campo esteja afirmativo. No Pets, use somente `opt_in_marketing`: **Sim** para aceite e **Não** para recusa. A política vigente permite analisar campo vazio, sem registrá-lo como consentimento. O NexoFlow não cria aceite nem adiciona o contato ao grupo Opt-In Marketing.

Na Farma, pedidos apenas pet/veterinários são excluídos. Nos pedidos mistos, a mensagem considera somente os itens humanos; no dashboard, somente o valor desses itens, sem o frete do pedido inteiro. No Pets, os itens PET são preservados.

Conversa indicando compra posterior ainda não confirmada pela API mantém a referência antiga bloqueada. O campo opcional Texto `pedido_revisao_pendente` preserva essa pendência entre instalações. A data da conversa não substitui a emissão oficial.

## Executar

1. Atualize Weni e Analytics no perfil escolhido.
2. Abra **NexoFlow Recompra**, escolha a marca e aguarde o diagnóstico e a simulação.
3. Confira o relatório e confirme a aplicação solicitada.
4. Execute Analytics para refletir os resultados no Sheets e no dashboard.

O BAT principal é `comandos/atualizar_recompra.bat`; `comandos/atualizar_recompra_pets.bat` fixa o perfil Pets. `RECOMPRA_ENABLED` controla a integração da etapa nas outras rotinas. No Noturno, a revisão é automática, mantendo as validações.

A aplicação sincroniza os campos essenciais do pedido (`pedido_id`, `pedido_data`, `pedido_produtos`, `pedido_status`, `pedido_forma_pagamento`) e a última compra (`ultima_compra` na Farma; `compra_recente` no Pets). O evento continua usando somente `pedido_data`. Confere a persistência antes da admissão e novamente depois de confirmar a inclusão. Se os campos ou a elegibilidade mudarem após o POST, remove preventivamente o grupo, confirma a remoção e deixa o contato pendente; os demais continuam. O estado preservado impede repetir uma admissão que pode ter sido observada pela campanha.

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
