# NexoFlow 1.5.15 — Cadastro por segmento

Weni, Analytics, Recompra e Planilha compartilham o cliente da API FarmaLíder. O perfil selecionado determina a listagem **`clientes/FARMA`** ou **`clientes/PET`**, sempre em produção, com a mesma seleção de conexão direta/proxy.

## Consultas e identidade

A listagem pode conter `cliente`, `ultimoPedido` e `itens`, ou somente cadastro. Snapshots completos são conferidos por proprietário, emissão, itens, valores e segmento, e reutilizados durante a execução. Dados incompletos ou ausência na lista usam consulta individual por CPF e, quando necessário, por ID do pedido. No retorno individual, o segmento precisa ser comprovado.

CPF válido dispensa comparação de nome e telefone. Zeros à esquerda só são repostos quando tornam os verificadores válidos. CPF inválido consultável exige primeiro nome ou telefone local correspondente ao contato Weni, sem ambiguidade. Ausência, zero e formato malformado ficam pendentes; não autorizam inventar CPF ou titularidade.

A base de uma marca não fornece identidade ou pedido à outra. Respostas divergentes de um mesmo ID e múltiplos candidatos compatíveis não são resolvidos pela primeira ocorrência.

## Preencher cadastros

Em contatos existentes, valores cadastrados são preservados e lacunas podem receber gênero, idade e localização com evidência na revisão. O endereço deve corresponder de forma única ao último pedido do mesmo cliente, inclusive quando for secundário. CEP isolado não comprova o endereço completo. Dados incompletos ou conflitantes ficam pendentes.

A rotina Weni também propõe criar clientes ausentes com CPF válido, identidade única e pedido validado no segmento. Confere CPF/telefone para evitar duplicação, preenche os campos disponíveis e revalida a fonte antes da criação. CPF inválido sem vínculo independente e conflitos ficam pendentes. A criação não presume consentimento nem adiciona grupos.

Farma usa `pedido_data` e `ultimo_pedido` (ID oficial), sem exigir `ultima_compra`; Pets usa `pedido_data` e `compra_recente`. No PET, `maior_de_18_anos` não é exigido, calculado, validado nem gravado; idade permanece apenas informativa. A idade/maioridade da FarmaLíder mantém a política existente. A conferência do endereço recebe explicitamente o segmento PET ou FARMA do pedido. O recorte de produtos humanos é exclusivo da Farma. Veja [segmentos, campos e fluxos](SEGMENTOS%20E%20FLUXOS.md).

## Histórico e desempenho

A resposta da listagem completa pode aguardar até **600 segundos** por tentativa; consultas individuais mantêm **90 segundos**. O índice é reutilizado na execução. A descoberta global de Weni/Analytics consulta a base do segmento mesmo em incrementais; o modo incremental continua útil para o processamento de mensagens e mudanças.

Pedidos completos observados são guardados privadamente e entregues pelo Analytics ao Sheets por ID. Mudanças de pedido mais recente não apagam os anteriores já observados. O histórico comercial fica nas planilhas; a Weni conserva o snapshot mais recente. Compras intermediárias nunca observadas dependem de um endpoint de pedidos por período, ainda não usado pelo NexoFlow.

O Analytics mantém a reconsulta de status dos pedidos já registrados somente até 20 dias. Leituras da simulação não dispensam a conferência exigida pela aplicação. Revise os relatórios e preserve o histórico local ao atualizar.

## Diagnóstico de criação na Weni

A auditoria privada distingue a etapa anterior ao POST, rejeição HTTP, tentativa anterior indeterminada e confirmação de campos. O resumo agrupa motivos, sem repetir uma linha por contato. Em HTTP 400/422, preserva a explicação da API com valores conhecidos ocultados, hash da resposta e request ID quando disponível. Se uma execução antiga não preservou a explicação, o total `WeniError` sozinho não determina a causa da rejeição. Não apague o registro de uma tentativa incerta nem repita o POST sem reconciliar os contatos existentes.

A prevenção de duplicados compara também a variação brasileira de celular com/sem o nono dígito, preservando DDD e restringindo a regra aos prefixos móveis de migração. Essa equivalência serve somente para localizar um contato já existente: não autoriza preencher/substituir CPF, fundir ou excluir contatos. CPF ausente/divergente e múltiplos contatos são apresentados separadamente para reconciliação. A conferência é repetida antes de qualquer novo POST, inclusive quando o contato apareceu depois da revisão.

## Pedidos observados sem contato Weni único

Falhar a criação ou o vínculo de um contato não faz desaparecer uma venda já comprovada. O histórico observado pode manter o pedido sem UUID Weni, com o cliente oficial, proprietário e demais guardas válidos, para entregá-lo ao Analytics. Isso não atribui a compra ao WhatsApp, a uma conversa ou a um anúncio. Deduplicar contatos e validar vendas são operações diferentes.

Os dados entregues pela API continuam limitados ao último pedido de cada cliente em cada coleta. A preservação dessas observações não recupera pedidos que nunca foram recebidos; comparar com faturamento mensal exige conciliação por ID/data/valor e a mesma definição de frete.
