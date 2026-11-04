# Plano de integração Meta Ads com Analytics

Estado: a implementação nativa está disponível no código, com ativação explícita e fontes independentes dos schemas legados. Veja o [guia operacional](META%20ADS%20NATIVO.md) e o [relatório técnico](RELATORIO%20META%20ADS%20NATIVO.md). Nenhuma planilha ou dashboard de produção foi alterado nesta entrega. A versão permanece 1.5.12, sem novo release.

## Contratos existentes conferidos no código

| Componente | Comportamento atual | Consequência para a integração |
| --- | --- | --- |
| `app/meta_events.py` | Eventos CTWA oficiais Weni, `campaign_source`, `ctwa_id`, `external_msg_id` e URN nativa | Preservar provas e deduplicação dos eventos; não substituir por ações agregadas da Meta. |
| `app/ad_attribution.py` | Primeiro/último anúncio; origem separada do canal | Um anúncio Instagram que abre WhatsApp conserva destino WhatsApp. |
| `app/analytics.py`: `META_CAMPAIGN_COLUMNS` | `anuncio_id`, nomes/IDs de conjunto e campanha, investimento, impressões, cliques, atualização | Falta conta, período, moeda e janela. Não pode receber diretamente fatos diários. |
| `app/analytics.py`: `BI_ADS_COLUMNS` e `build_bi_ads_rows()` | Snapshot por primeiro/último anúncio, origem, tipo de campanha, destino, ID e título; contatos, compradores, pedidos e receita validada | Não é fato diário de investimento, nem contagem de todos os cliques. Primeiro e último são visões alternativas; não somar as duas receitas. |
| `app/google_sheets.py` | Cria/valida `Campanhas_Meta`, `Eventos_Anuncios` e `BI_Ads` segundo os cabeçalhos atuais | Não alterar cabeçalhos ou upserts silenciosamente; preservar arquivos de Operação, Histórico e Dashboard de cada perfil. |

Os pedidos de `BI_Ads` passam por `_bi_valid_orders()` e excluem atribuição comprovadamente posterior à compra. A receita é a receita de pedidos confirmados da API FarmaLíder, não `action_values` ou `purchase_roas` da Meta.

## Modelo implementado, sem migração destrutiva

Os schemas atuais são preservados. Os novos contratos estão em `app/meta_ads_model.py`: `Meta_Ads_Diario`, `Meta_Ads_Campanhas`, `Meta_Ads_Anuncios`, `BI_Meta_Resultados` e `BI_Meta_Conversoes`. A ativação exige conferir os destinos e revisar os novos schemas.

Grão de uma linha: **conta + anúncio + dia na zona da conta + especificação de atribuição/relatório**. Chave idempotente sugerida: hash desses valores, com versão da política e dimensões de breakdown, se houver. IDs são texto; valores monetários usam decimal, com moeda explícita.

Campos mínimos propostos:

- `conta_id`, `anuncio_id`, `conjunto_id`, `campanha_id`, nomes retornados e perfil autorizado;
- `data_inicio`, `data_fim`, fuso da conta, moeda e versão da API;
- especificação de atribuição, `action_report_time` quando aplicável, nível, breakdowns e versão do contrato;
- investimento, impressões e cliques; alcance/frequência identificados como não aditivos;
- ações e valores atribuídos pela Meta, separados dos pedidos e receitas confirmados;
- chave do fato, instante da consulta, completude/paginação e hash dos dados normalizados, sem token.

O cliente compartilhado mantém consultas agregadas e oferece `daily_insights` com `time_increment=1`, usado pela operação nativa. Nunca rotular um total mensal como dado diário. Se a janela efetiva de atribuição não estiver comprovada na consulta/resposta, registrar desconhecida e manter indicadores que a exigem indisponíveis.

Alcance e frequência não podem ser somados entre anúncios ou dias para representar audiência única. Não somar moedas diferentes. O dia da conta Meta não equivale automaticamente ao dia operacional America/Belem: declarar a origem e reconciliar períodos/fusos antes dos cruzamentos.

## Separação FarmaLíder e Pets Líder

A conta inicialmente permitida é `898435729140540`. A allowlist concede somente consulta; **não define que a conta pertence a FARMA ou PET**. O mapeamento conta/campanha/anúncio para segmento precisa ser explícito e validado. Contas compartilhadas exigem separação por campanhas/anúncios autorizados; itens sem mapeamento ou com mapeamento conflitante ficam fora da carga do segmento, com diagnóstico agregado.

Não usar nome da campanha, telefone, idioma ou permissão pessoal para inferir segmento. Uma conta técnica com acesso a outras contas não amplia a allowlist. Reutilizar os destinos e estados isolados dos perfis existentes.

## Fluxo nativo e ativação

1. Analytics importa `MetaAdsClient` diretamente; não inicia o servidor MCP e não precisa do Codex. Credenciais continuam exclusivamente no JSON privado local já definido.
2. Executar uma simulação por conta/período autorizado. Validar permissão de leitura, paginação completa, IDs, moeda, fuso, período e mapeamento do segmento. Resposta parcial não confirma cobertura completa.
3. Normalizar fatos e produzir diff privado: inserções, diferenças reais e linhas sem mudança. Falha isolada não apaga fatos anteriores nem confirma ausência de investimento.
4. Revisar a proposta de migração, testar em planilha sintética/cópia isolada e conferir fontes Data Studio. Criar novas abas somente após autorização; manter as abas atuais intactas durante a transição.
5. Aplicar upserts por chave de fato após revisão. Reconsultar uma janela de sobreposição definida para ajustes tardios de atribuição; atualizar a mesma chave, sem acumular versões como novas vendas. Avançar checkpoint por conta/segmento somente após confirmação das operações; preservar tentativas pendentes.
6. Criar uma camada BI Meta separada e com versão de esquema. Relacionar dimensões somente por conta e ID de anúncio comprovados, agregando previamente ao mesmo grão. Nunca multiplicar custo ao juntá-lo diretamente a várias linhas de contatos/pedidos.
7. Ativar a etapa no Analytics/Noturno apenas após testes do fluxo completo, migração reversível e validação explícita dos relatórios.

## Indicadores e evidências

| Indicador | Fonte e requisito |
| --- | --- |
| Investimento, impressões, cliques | Meta Marketing API; conta, período e moeda explícitos. |
| Conversas CTWA Weni | Eventos oficiais acessíveis, com cobertura e identidade comprovadas; não equivalem automaticamente à métrica de conversas atribuídas da Meta. |
| Compras atribuídas Meta / ROAS Meta | Valores da plataforma, rotulados como atribuídos e com janela/fuso conhecidos. Não são vendas confirmadas. |
| Receita confirmada por anúncio | Pedidos validados pela API FarmaLíder e evidência de atribuição Weni anterior/compatível com a compra. |
| CPA confirmado / ROAS confirmado | Numerador e denominador no mesmo segmento, conta, moeda, período e política; cobertura compatível. Caso contrário, indisponível. |
| CAC | Exige definição de aquisição e histórico suficiente para distinguir comprador novo. Último pedido observado não comprova primeira compra; sem cobertura, indisponível. |

Não declarar causalidade ou atribuição individual usando apenas o ID de anúncio. `Eventos_Anuncios` e os campos de primeiro/último anúncio preservam suas provas; não fabricar `ctwa_clid`, URN, CPF, compra ou consentimento a partir de métricas agregadas.

## Testes exigidos antes de habilitar cargas

- Mesma extração repetida não duplica fatos; ajustes tardios substituem somente a chave correspondente.
- Dias, contas, moedas, janelas e breakdowns diferentes não colidem; IDs longos mantêm precisão textual.
- Paginação parcial, timeout, 429, permissão ausente e resposta malformada conservam estado anterior e pendências.
- Conta compartilhada não mistura FARMA/PET; credenciais e dados de um perfil não alimentam outro.
- Cruzamento muitos-para-muitos não multiplica investimento; primeiro/último anúncio não duplica vendas somadas.
- Conversões Meta não criam pedidos, agendamentos ou elegibilidade de Recompra; cancelamentos e recusas seguem as regras atuais.
- Schemas legados, continuações, dashboards e Noturno permanecem compatíveis, com APIs e planilhas simuladas.

## Pendências desta fase

A operação nativa não exige registro STDIO nem Codex. A instalação final no computador do usuário e a ativação das novas fontes ainda precisam ser conferidas. Foi validada uma consulta real limitada de leitura à Meta; testes de escrita usam Sheets simulado. Não houve escrita em planilhas, edição de campanhas ou publicação de release para esta integração.

## Dashboard de referência informado

[Data Studio — abas Anúncios e Pedidos dos Anúncios](https://datastudio.google.com/reporting/e60ba3bc-fe88-417d-8a39-d8512debf175/page/oeZAG). O usuário confirmou filtro por data nas duas abas; a configuração das fontes ainda precisa ser inspecionada com acesso autorizado. Preservar as páginas e controles existentes. A nova fonte deve separar dia da veiculação, data da compra e janela de atribuição; usar conta + anúncio + dia para custos sem multiplicá-los ao juntar pedidos. Confirmar qual segmento e fonte cada página utiliza antes de vincular dados. Nenhuma alteração no relatório foi realizada nesta integração.
