# NexoFlow | Histórico de pedidos, atribuição e LTV

**Estado:** arquitetura preparada; integração histórica **não implementada**.  
**Repositório de referência:** `felipetelesbarbosa/NexoFlow`.  
**Premissa obrigatória:** o novo endpoint de histórico da API FarmaLíder ainda **não possui contrato oficial completo**. Não presumir rota, parâmetros, autenticação, paginação ou estrutura de resposta.

## 1. Diretrizes e compatibilidade

- Usar **Data Studio** na interface, documentação e novos recursos. Manter URLs, IDs, fontes, nomes internos e identificadores técnicos existentes (incluindo `app/looker_bi.py`), sem renomeação funcional desnecessária.
- Manter o comportamento atual de FarmaLíder, Pets Líder, Weni, Meta Ads, Google Ads, Noturno e Recompra até testes e autorização explícita.
- Aplicar integralmente `AGENTS.md`: identidade e segmento verificados; status e pagamento válidos; itens e frete validados; dados suspeitos como pendência, não como ausência; separação de FARMA/PET; `America/Belem` no calendário de negócios.
- Adicionar estruturas e novas rotinas, não substituir tabelas ou snapshots atuais. Toda migração deve ser reversível e não destrutiva.
- O **GitHub** permanece origem única do código; execução automática no Linux/VPS e manual no Windows compartilham regras Python, com configurações e modos de inicialização distintos.

## 2. Responsabilidade de cada componente

| Componente | Responsabilidade | Não deve fazer |
| --- | --- | --- |
| NexoFlow Python | Cliente de API, paginação, validações, unificação de pedidos, cálculos, atribuição, migrações e publicação das fontes | Presumir campos da API histórica sem contrato |
| PostgreSQL na VPS (proposto) | Persistir fatos, eventos publicitários, checkpoints, auditoria e travas interambientes | Misturar segmentos sem identidade comprovada |
| n8n (proposto) | Disparar importações e incrementais, acompanhar tarefas, reagir a falhas, alertar e registrar resultado | Reimplementar a validação de pedidos ou o cálculo financeiro |
| Google Sheets | Expor conjuntos derivados necessários ao Data Studio, respeitando limitações de volume | Ser fonte primária da verdade sobre todos os eventos e pedidos |
| Data Studio | Exibir indicadores por período e visões históricas | Recalcular LTV histórico exclusivamente pelo filtro mensal |
| NexoFlow local (Windows) | Permitir execução manual completa ou incremental e diagnóstico | Gravar concorrentemente sem trava global na mesma fonte |

Os nomes `/processar`, `/status` e quaisquer URLs da futura API do NexoFlow são **apenas ideias de contrato interno**, não endpoints existentes.

## 3. Fluxos separados

### 3.1 Carga histórica inicial, sob demanda

1. Antes de executar, validar documentação e autorização do novo endpoint, credenciais, intervalo histórico coberto, fuso, segmento e consistência das respostas.
2. Criar um plano de faixas de período com estado `pendente`, `em_andamento`, `incompleto` ou `concluido`. Faixas e ordenação serão definidas conforme o filtro real da API.
3. Percorrer todas as páginas **até um critério comprovado pelo contrato**, não pela suposição de que uma página com menos de 100 encerra a coleta.
4. Persistir cada lote atomicamente com um checkpoint do período/segmento e registro dos erros.
5. Aplicar chaves idempotentes, validar pedido/cliente/itens e preservar alterações oficiais legítimas; não apagar um pedido válido por resposta parcial ou omissão.
6. Classificar cobertura incompleta ou incerta como pendência; permitir retomar exatamente os períodos/páginas necessários após queda.
7. Confirmar completude por período e segmento **antes** de publicar números rotulados como históricos completos.
8. Ordenar cronologicamente para análise, independentemente da ordem retornada pela API.

**Nota:** 100 pedidos por página é uma característica informada, **não** uma regra técnica já verificada. Tamanho real, cursor, paginação e encerramento aguardam contrato.

### 3.2 Operação incremental e reconciliação

- Depois do backfill validado, executar incrementais sobre mudanças/eventos detectáveis e reconciliar apenas janelas justificadas pelo endpoint.
- A regra atual de reconsulta de status do Analytics cobre até 20 dias, conforme `AGENTS.md`. **Não ampliar silenciosamente** a reconsulta de pedidos antigos; eventuais mecanismos de alterações históricas exigem análise, testes e autorização da política.
- O Noturno permanece como está em produção até integração e homologação, e **não** deve repetir toda a carga histórica em cada execução.
- Quando a API não comprovar o que mudou, manter pendências rastreáveis e planejar reconciliação controlada, sem confundir `modified_on` da Weni com mudança na API de pedidos.

### 3.3 Operação manual e automática no mesmo período

- A VPS deverá coordenar execução por segmento, fonte e tipo de carga, com lock distribuído durável e identificação de tarefa.
- A execução local Windows deve consultar a coordenação compartilhada antes de escrever em fontes compartilhadas; travas Win32 existentes **não** protegem a VPS.
- Persistir eventos de webhook na entrada e reprocessá-los depois de uma carga longa, com deduplicação; evitar bloqueio ou perda silenciosa.
- Se estiver sem comunicação com o coordenador, não assumir exclusividade para escrita em destino compartilhado; oferecer diagnóstico/execução local controlada.

## 4. Modelo de dados proposto (aditivo)

O modelo abaixo é **conceitual** e depende do contrato oficial, do volume e dos schemas atuais. IDs da API permanecem texto, dinheiro usa decimal, datas têm instante, fuso e origem.

| Estrutura proposta | Grão / chave sugerida | Campos e função |
| --- | --- | --- |
| `historico_pedidos` | `segmento + origem + pedido_id_oficial` | cliente oficial, data/hora, situação, pagamento, valor reconhecido, frete, descontos, datas de atualização, fonte, versão e validação |
| `historico_itens` | `pedido_chave + identificador/posição de item validado` | código, descrição, quantidade, valores, desconto e classificação de frete |
| `clientes_identidades` | identidade oficial verificada no segmento | vínculo entre cliente da API, contato Weni e evidências verificadas, sem merge por CPF/telefone isolado |
| `eventos_publicitarios` | ID nativo comprovado por origem + segmento | instante, plataforma Meta/Google, evidência CTWA/URN/clique/UTM, campanha/anúncio e origem da prova |
| `jornada_cliente` | evento individual, pedido ou interação | referência e instante para ordenar eventos sem criar registros sintéticos de interação |
| `atribuicao_pedido` | `pedido + modelo + versão` com crédito explícito | evento elegível, janela declarada, regra, crédito, valor atribuível, estado da evidência |
| `cobertura_historica` | `segmento + origem + faixa` | primeiro/último período confirmado, lacunas, páginas, completude, erros |
| `checkpoint_importacao` | `segmento + origem + faixa + execução` | cursor/página (se suportado), posição, estado, hash e data do último commit atômico |
| `auditoria_importacao` | ID da execução e da etapa | contagens, conflitos, atualizações, omissões e tentativas, sem expor tokens ou dados pessoais em logs |

As chaves finais de itens, paginação, histórico de revisão e idempotência exigem confirmação no contrato. Não considerar data/nome como prova de identidade nem sobrescrever linhas válidas por campos nulos/incompletos.

## 5. Regras de vendas, LTV e cobertura

**LTV histórico realizado por cliente** = soma do **valor reconhecido de compras válidas** de toda a cobertura histórica disponível, sem duplicação de pedido.

- A definição final de receita (bruta/líquida, descontos, frete, devoluções e valor efetivamente pago) deve ser documentada em uma **política monetária versionada** após inspecionar o contrato oficial. Até lá, evitar divulgar um LTV definitivo baseado em pressupostos.
- Reutilizar `_sales_order_is_valid`, `_order_revenue_parts`, `pedido_utils` e as regras do `AGENTS.md`. Não introduzir regra nova de cancelamento/pagamento nem usar valores publicitários da Meta/Google como faturamento de pedidos.
- Métricas: LTV realizado, pedidos históricos, ticket médio histórico (LTV/pedidos válidos), primeira/última compra, frequência, intervalo médio entre compras consecutivas, novos e recorrentes, receita acumulada por cliente e período.
- Para 0 ou 1 pedido, intervalo médio de compras não é zero: exibir **não aplicável**.
- A identificação de cliente novo/recorrente depende da cobertura anterior ao intervalo analisado; quando a base estiver incompleta, indicar classificação **não comprovada**.
- Armazenar `cobertura_status` e `historico_ate` para distinguir **LTV histórico completo dentro da cobertura comprovada** de **LTV observado parcial**. Não apresentar receita projetada como realizada.
- O período filtrado em **Vendas** e **Anúncios** não altera o universo histórico do LTV do cliente. A receita do período é outro cálculo.

## 6. Jornada publicitária e atribuição temporal

Criar uma linha do tempo comum de **eventos comprovados** de Meta Ads, Google Ads, Weni e pedidos oficiais, com vínculo de identidade e segmento verificável.

Exemplo obrigatório:
- Dia 1: anúncio A comprovado; dia 5: pedido 1; dia 10: anúncio B comprovado; dia 15: pedido 2.
- Pedido 1 pode considerar somente interações elegíveis até o dia 5; **nunca** atribuir a B do dia 10.
- Pedido 2 considera apenas evidências que o precedem, conforme a janela e a política definidas.
- Todo pedido é preservado, inclusive os intermediários e os não atribuídos.
- Não repartir 100% da receita em vários anúncios simultaneamente. Uma política de modelo simples (ex.: último toque válido) precisará de versão, janela, prioridade, regras de desempate e evidência; modelos multitoque futuros terão créditos cuja soma por pedido não ultrapasse 100%.
- Separar `receita_total_cliente`, `receita_pedidos_periodo`, `receita_atribuida_publicidade` e `receita_nao_atribuida`.
- Dados agregados das APIs de mídia servem para investimento, campanhas e métricas da plataforma; **não provam**, sozinhos, que um pedido identificado pertence ao anúncio.
- Respeitar limitações CTWA/URN, `gclid`, `gbraid`, `wbraid` e metadados efetivamente disponíveis; ausência de prova não autoriza criação de toque, merge de contatos ou atribuição inferida.
- Não misturar personas/perfis FARMA e PET, mesmo que anúncios ou pessoas pareçam semelhantes, sem identidade comprovada e autorização da visão consolidada.

## 7. Publicação para Google Sheets e Data Studio

Manter abas e IDs atuais: `BI_Clientes`, `BI_Clientes_Vendas`, `BI_Pedidos`, `BI_Ads`, `BI_Status` e outras existentes. Criar fontes derivadas **aditivas** como:

| Nova fonte candidata | Finalidade |
| --- | --- |
| `BI_Historico_Pedidos` | pedidos oficiais validados por período e cliente |
| `BI_LTV_Clientes` | LTV, cobertura, pedidos, primeira/última compra, frequência |
| `BI_Jornada_Anuncios` | eventos comprovados ordenados e referência de pedidos |
| `BI_Pedidos_Anuncios` | cada pedido, eventos elegíveis, política e valor atribuído |
| `BI_Cobertura_Historica` | períodos completos/incompletos, erros, última confirmação |
| `BI_Aquisicao_Recompra` | classificações comprovadas de aquisição e recorrência |

Páginas do **Data Studio**:
- **Meus clientes:** LTV histórico, cobertura e frequência, separados de métricas filtradas.
- **Vendas:** receita e pedidos da janela selecionada; histórico preservado no backend.
- **Anúncios:** investimento, contatos, compradores e receita atribuída com política e evidência.
- **Pedidos dos Anúncios:** todos os pedidos ligados à jornada, inclusive entre interações, com distinção entre relacionados e atribuídos.

Evitar enviar histórico bruto ilimitado para todas as abas do Sheets; avaliar dimensão e particionamento. Preservar a divisão atual entre planilhas de Operação, Histórico e Dashboard por segmento.

## 8. Módulos a revisar quando o contrato chegar

**Existentes, identificados no repositório atual:**
- `app/farmalider_client.py` e `app/farmalider_integration.py`: cliente HTTP, validação de contrato e propriedade do pedido.
- `app/observed_orders.py` e `app/analytics.py`: coexistência dos snapshots e da nova base, reconciliação, deduplicação e critérios de venda.
- `app/pedido_utils.py`: status, pagamento, data, itens, frete e receita reconhecida.
- `app/ad_attribution.py`, `app/meta_events.py`, `app/meta_ads_native.py`: evidências e linha do tempo (sem substituição de CTWA por métricas agregadas).
- `app/looker_bi.py`, `app/google_sheets.py`, `app/sheets_storage.py`: novas fontes e migrações aditivas do Data Studio.
- `app/run_noturno.py` e rotinas de Recompra: **somente avaliar integração, sem alterar fluxo/regra em produção nesta fase**.
- `docs/PEDIDOS.md`, `docs/DATA STUDIO.md`, `docs/GOOGLE ADS.md` e testes relacionados: documentar comportamento e limites após homologação.

**Novos módulos candidatos (nomes propostos, não existentes):**
- `app/historico_pedidos_client.py`: adaptador versionado do contrato oficial.
- `app/historico_pedidos_sync.py`: importação histórica, paginação, janela e retomada.
- `app/historico_pedidos_store.py`: gravações idempotentes e checkpoints.
- `app/ltv_historico.py`: indicadores e estado de cobertura.
- `app/jornada_atribuicao.py`: linha do tempo e política de atribuição versionada.
- `tests/test_historico_*.py`, `tests/test_ltv_*.py`, `tests/test_jornada_*.py`: regressões e cenários de risco.

## 9. Workflows n8n propostos (não implantados)

1. **Importação histórica manual:** solicitação autenticada → plano por segmento/faixa → job Python → consulta de status → checkpoints → relatório de cobertura; controlada e pausável, sem executar automaticamente no Noturno.
2. **Pedidos incrementais:** webhook comprovado ou consulta programada → validação → fila/controle por segmento → Python → persistência e atualização de fontes.
3. **Reconciliação:** janela comprovada + lacunas/incompletos → Python → comparação → relatório de divergências.
4. **LTV e BI:** após confirmação de lotes → recalcular agregações afetadas → publicar fontes derivadas → registrar cobertura.
5. **Jornada Meta + Google Ads:** atualizar evidências e custos → solicitar conciliação de eventos/pedidos → relatório de receita atribuída versus não atribuída.
6. **Observabilidade:** checagens de saúde, limites de API, falhas recuperáveis, tentativas com backoff e alertas (sem ciclos infinitos).

O n8n executa **orquestração**, não cálculos financeiros detalhados. Os workflows poderão ser exportados/versionados como JSON sem exigir uso do controle de versão de planos pagos do n8n.

## 10. Testes mínimos antes de produção

Fixtures sintéticas e testes de integração, incluindo:
- mais de 100 pedidos, múltiplas páginas, fim verdadeiro de paginação, anos/meses diferentes e faixas sobrepostas;
- IDs repetidos, paginação reexecutada, ordem fora de sequência e atualização oficial válida de um pedido;
- cliente com identidade inconsistente, segmento desconhecido, itens ausentes, frete e descontos;
- cancelamentos, forma de pagamento 0, mudanças de status e resposta parcial;
- falha de rede/autenticação, queda após persistir lote, checkpoint atômico e retomada sem duplicar;
- fontes históricas ainda incompletas, janela não coberta e proibição de interpretar omissão como ausência;
- primeiro, último e eventos intermediários Meta/Google; compras antes/entre/depois; interações posteriores não recebem crédito retroativo;
- LTV, intervalos e novos/recorrentes, além de separação FARMA/PET;
- concorrência VPS/Windows, filas de webhook, operação manual durante incremental e retorno da conexão;
- preservação do Noturno, Recompra e schemas anteriores, sem migração destrutiva.

## 11. Contrato externo ainda pendente

Solicitar a documentação oficial **antes de qualquer implementação definitiva**:
- endpoint, verbo, autenticação e permissões; intervalo histórico realmente coberto;
- parâmetros de período, inclusividade dos limites, fuso, formato de datas;
- paginação, totalizadores e critério inequívoco de encerramento;
- contrato dos campos e IDs oficiais de cliente, pedido, itens, status, pagamento, valor, desconto, frete, devolução e alterações;
- possibilidade de filtro por atualização, exclusões/correções, limites de taxa e erros;
- eventual escopo de múltiplos segmentos e diferenças de resposta.

Se o contrato não comprovar determinada capacidade, registrar **indisponível**, sem inventar valores ou regras.

## 12. Etapas de liberação

1. **Agora:** documentação de arquitetura e inventário de componentes; nenhuma mudança funcional.
2. **Após documentação oficial:** contratos de dados, política monetária e de atribuição explícitas; fixtures e testes sintéticos.
3. **Implementação isolada:** cliente, histórico, persistência, checkpoints e idempotência, sem Noturno/BI de produção.
4. **Homologação:** backfill controlado, reconciliação com fontes atuais, métricas de cobertura e auditoria, testes Linux/Windows.
5. **Publicação gradual:** novas fontes Google Sheets e páginas Data Studio, incrementais via n8n, monitoramento e rollback.
6. **Proteção contínua:** GitHub como fonte única, credenciais fora do Git, backups, validação da mesma versão nos dois ambientes.

**Critério de entrega:** somente declarar histórico completo, LTV realizado e atribuição confiável quando contrato, execução, cobertura e testes tiverem evidência verificável. Esta documentação, sozinha, **não** ativa a nova coleta.
