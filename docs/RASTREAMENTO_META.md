# Anúncios Meta: preenchimento imediato e conferência posterior

FARMA/Lili e PET/Oscarzinho usam os mesmos campos e regras, com tokens, estados e planilhas separados. Os 16 campos de anúncio foram conferidos nos dois projetos. As duas datas são `datetime`; os demais campos são texto.

## Instruções para o IA Manager

Cole a instrução correspondente nas orientações do agente e disponibilize as ferramentas `get_context` e `contact-fields`:

- [Oscarzinho — Pets Líder](INSTRUCAO_MANAGER_PETS.txt)
- [Lili — FarmaLíder](INSTRUCAO_MANAGER_FARMA.txt)

A instrução tenta o preenchimento imediato, mas depende da execução das ferramentas pelo modelo. Não se deve pedir ao Manager que inicie um fluxo; o suporte Weni confirmou que ele não faz isso. Os gatilhos por palavra-chave não substituem essa integração.

## NexoFlow Weni

A rotina consulta `GET /api/v2/events.json` com `event_name=ctwa`, `date_start` e `date_end`. Na resposta oficial verificada, `metadata.campaign_source` identifica o anúncio e `metadata.ctwa_id` identifica o clique. `date` é o instante do evento; `contact_urn` vincula o contato. A consulta usa o mesmo cliente HTTP, autenticação, proxy, limites e retentativas da Weni, com períodos de até sete dias por lote.

Não há consulta individual por CPF ou por contato para identificar anúncios. O vínculo exige URN nativa exata e única, sem acrescentar dígitos ou reutilizar identidade de outro segmento. Eventos repetidos são deduplicados; divergências entre registros do mesmo evento ficam pendentes.

- Campos vazios são completados com os dados comprovados.
- Valores corretos, inclusive datas em formatos equivalentes, não são regravados.
- Um registro existente é corrigido quando o clique oficial, ou o anúncio e instante exatos, comprovam seu vínculo. O ID do anúncio sozinho não distingue cliques.
- Primeiro anúncio anterior à cobertura conhecida é preservado. Uma leitura incompleta não congela um primeiro anúncio novo.
- Primeiro e último são ordenados pela data do evento, não pela hora da carga. Anúncios Google existentes continuam participando da mesma linha temporal.
- Edição externa depois da revisão gera conflito apenas no contato afetado. O NexoFlow não sobrescreve a informação nova.
- Falhas isoladas de consulta, formato, vínculo ou gravação mantêm o cursor Meta no ponto pendente, e os demais dados válidos seguem a carga. Autenticação inválida continua bloqueante.

Na primeira execução com esse recurso há uma consulta inicial de 90 dias, mesmo se existir checkpoint antigo da Weni. A carga completa amplia a consulta até a mensagem mais antiga disponível quando essa data for anterior. Isso representa o histórico acessível, sem comprovar eventos anteriores à retenção da Weni. Cargas de 25% mantêm o cursor conservador para a próxima reconciliação global.

Título e URL não foram retornados pelo endpoint de eventos testado. O NexoFlow não os inventa nem afirma que foram validados. Pode preservar os detalhes do Manager quando o evento é o mesmo; numa troca comprovada para outro anúncio, limpa detalhes do anúncio anterior que não pertencem ao novo registro. Objetivo de campanha também não é inferido de `headline`, formato da mídia ou domínio Instagram.

## Analytics, Google Sheets e Data Studio

O Analytics lê os campos da Weni e mantém os 16 atributos na `Base_Contatos`, no arquivo de Operação do segmento. Os pedidos guardam os dados de atribuição disponíveis, incluindo URL e clique. As quatro colunas adicionais ficam no fim da tabela para preservar a ordem das colunas anteriores.

As tabelas `BI_Ads`, `BI_Canais`, `BI_Conversao` e `BI_Pedidos` ficam no arquivo Dashboard definido no perfil e em `NexoFlow_Arquivos`. O histórico continua no seu destino. As continuações de planilhas seguem as regras já existentes; não se deve trocar o Dashboard por uma planilha de outro segmento.

`BI_Ads` usa primeiro/último anúncio por contato: não é uma contagem de todos os cliques ou anúncios intermediários e não comprova causalidade de venda. O preenchimento desses campos não cria campanha, investimento, impressões ou ROAS. Título vazio pode ser apresentado pelo ID do anúncio. A exibição no Data Studio depende da fonte/aba vinculada e da atualização do conector; este patch não altera automaticamente o layout do relatório publicado.

Um anúncio comprovadamente posterior ao pedido não recebe o faturamento daquela compra. Datas são gravadas com fuso explícito e normalizadas para America/Belem nas métricas diárias.

Pedidos continuam exigindo confirmação na API FarmaLíder com cliente, identidade, segmento, status, pagamento e itens. Clique em anúncio não é prova de compra. Cancelados, pagamento zero e pedidos sem itens seguem as exclusões existentes. Pedido ou contato com falha fica pendente, sem invalidar os demais.

O Noturno executa a mesma simulação/revisão/aplicação Weni e o Analytics seguinte; não mantém uma cópia diferente das regras de anúncio. A Recompra conserva seus bloqueios e não usa metadados Meta como autorização de campanha ou de venda.

## Conferência da atualização

Os testes usam APIs sintéticas e a lógica real de planejamento, revisão, aplicação, conflito e retomada. Cobrem FARMA e PET em processos separados, pedidos confirmados/cancelados, escrita das tabelas com o protocolo Sheets em memória e a sequência Noturno. Foram feitas consultas reais somente de leitura aos eventos e campos dos dois projetos. As instruções não foram inseridas nos agentes por este patch e nenhuma carga de escrita em produção foi executada durante esses testes.
