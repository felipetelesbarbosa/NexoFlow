# Integração nativa Meta Ads — relatório técnico

## Implementação

O Analytics chama o cliente Python diretamente. O Noturno herda a etapa nas suas execuções do Analytics. Não são iniciados Codex CLI, servidor MCP ou processos externos para consultar anúncios. O cliente HTTP é compartilhado com o MCP opcional e restringe a Meta a GET, contas autorizadas e `ads_read`; `ads_management` é recusado.

Módulos novos: `meta_ads_native` (coleta e checkpoints), `meta_ads_evidence` (evidência Weni por projeto), `meta_ads_model` (transformação pura), `meta_ads_sheets` (revisão, backup e upsert) e `run_meta_ads` (simulação e aplicação explícita). `main.py` integra a etapa sem invalidar as operações principais em caso de falha isolada. `google_sheets.py` oferece abertura sem inicialização de schemas legados e métodos específicos para as novas tabelas.

## Tabelas adicionais

| Tabela | Destino | Granularidade e finalidade |
| --- | --- | --- |
| `Meta_Ads_Diario` | Operação | Conta + anúncio + dia da conta + política de atribuição; métricas originais e investimento atribuível separado. |
| `Meta_Ads_Campanhas` | Operação | Catálogo oficial de campanhas, nomes, objetivos e status. |
| `Meta_Ads_Anuncios` | Operação | Catálogo de anúncios e respectivos conjuntos/campanhas. |
| `BI_Meta_Resultados` | Dashboard | Fato diário e indicadores por anúncio, sem multiplicar custos ao relacionar pedidos. |
| `BI_Meta_Conversoes` | Dashboard | Pedido único por segmento/conta, contato, anúncio, exposição e compra em datas separadas, produtos e quantidades quando disponíveis. |

Os cabeçalhos completos são definidos em `app/meta_ads_model.py:SCHEMAS`. IDs são texto. Informações opcionais ausentes ficam indisponíveis. Ações, valores e custos por ação da Meta permanecem em JSON próprio, separados das vendas oficiais. As tabelas existentes `Campanhas_Meta`, `Eventos_Anuncios`, `BI_Ads`, `BI_Canais`, `BI_Conversao` e `BI_Pedidos` não são reconstruídas nem recebem cabeçalhos incompatíveis.

## Atribuição e cálculos

A classificação utiliza o ID oficial do anúncio nos eventos CTWA e o projeto Weni validado, nunca o nome de campanha. Sem cobertura suficiente dos dois projetos, o investimento não é atribuído exclusivamente. Anúncios compartilhados conservam o custo original como referência, mas não recebem 100% desse custo em ambos os perfis. Não somar `investimento_original` de cópias dos dois segmentos; usar `investimento_atribuivel` apenas no seu contexto validado.

O vínculo comercial usa pedidos aprovados pelas regras existentes da API FarmaLíder, UUID exato e último toque observado anterior à compra. Isso documenta uma associação observada, **não prova causalidade**. Primeiro e último anúncio não geram duas vendas. Pedidos cancelados deixam de compor receita; o detalhe histórico preservado deve ser filtrado por `venda_valida = Sim`.

- CPA confirmado = investimento atribuível / pedidos confirmados associados.
- ROAS confirmado = receita confirmada / investimento atribuível, somente com moeda compatível e cobertura suficiente.
- CTR = cliques / impressões × 100; CPC = investimento / cliques; CPM = investimento / impressões × 1.000.
- Custo por conversa Weni exige IDs oficiais de conversa. Eventos CTWA e cliques não são tratados como conversas distintas.
- Taxa de conversão observada usa compradores/contatos identificados no mesmo contexto; não é causalidade.
- CAC permanece indisponível: o histórico observado de último pedido não comprova primeira compra.

Alcance e frequência são preservados no grão retornado pela Meta, sem soma como audiência única. Conversões/ROAS atribuídos pela Meta permanecem separados das vendas e do ROAS calculados pelo NexoFlow. Fuso e moeda da conta não são substituídos pelo fuso operacional.

## Incremental, falhas e segurança

A primeira coleta utiliza a data histórica configurada. As seguintes reconsultam uma janela recente para ajustes tardios. Checkpoints são independentes por conta e segmento e só avançam após confirmação da escrita correspondente. Paginação incompleta e falhas conservam dados e checkpoints anteriores. Repetir uma coleta atualiza as mesmas chaves.

A etapa não considera falha como investimento zero. Autenticação e permissão recebem diagnóstico explícito e sanitizado. Credenciais permanecem exclusivamente em `credentials/mcp/meta_ads_credentials.json`, ignorado pelo Git e bloqueado no empacotamento público. Não são copiadas para `secrets_config.py`, logs, workflows ou configuração Codex.

O Setup instala os módulos nativos e dependências principais. Codex/MCP continuam opcionais. Atualização e instalação limpa preservam o JSON Meta existente e sua allowlist; essa exceção não restaura as demais credenciais apagadas por uma instalação limpa.

## Validação real limitada

Em 04/11/2026, uma consulta GET real à conta autorizada e ao relatório diário de 29/10/2026 retornou **43 linhas**, sem paginação incompleta. Foram confirmados BRL, fuso **America/Noronha** e os campos diários de ações, valores, custos e identificadores disponibilizados pela API. A verificação de permissão do cliente passou. Não houve escrita na Meta.

Uma leitura dos eventos oficiais Weni do mesmo intervalo UTC retornou **21 eventos PET e nenhum FARMA**, com cobertura das duas consultas. A conferência usou deliberadamente listas vazias de contatos: valida o contrato e a classificação, mas **não comprova associação real a clientes ou pedidos**. A transformação desses dados identificou cinco anúncios PET; os demais ficaram sem classificação. A fronteira UTC dessa sondagem não é uma conciliação de dias completos no fuso da conta.

Não houve escrita em Google Sheets nem edição dos dashboards de produção. Testes de escrita, falhas e retomada usam APIs e planilhas simuladas. Resultados finais de regressão e workflows são informados na entrega do commit validado.

## Ativação e pendências

Siga [Meta Ads nativo](META%20ADS%20NATIVO.md). Faça primeiro uma simulação, confira perfil, três arquivos Sheets, intervalo, contas e manifestos. A aplicação inicial exige revisão explícita do novo modelo. Após ativação, o Analytics e o Noturno usam a integração nativa.

As fontes estão preparadas para as páginas Anúncios e Pedidos dos Anúncios. A edição dos relatórios Data Studio, seus gráficos e filtros ainda depende de acesso à configuração do relatório. Nenhum dashboard foi anunciado como atualizado. O detalhe deve manter data da compra separada da exposição e evitar junção que replique investimento por item/pedido.

A versão **NexoFlow 1.5.13** já foi publicada e permanece preservada. Este relatório registra a implementação e os testes daquela entrega. A próxima publicação usa **1.5.14**, com validação própria do mesmo commit; confira o [changelog](../CHANGELOG.md) e o [guia atualizado](META%20ADS%20NATIVO.md). Use o novo pacote validado; não copie módulos manualmente sobre a instalação como substituto da distribuição.

## Verificações locais da fase preparatória

A regressão completa executou **1.673 testes**, com **70 ignorados** por requisitos de plataforma/ambiente, sem falhas. A suíte do cliente/MCP executou **27 testes**, sem falhas. O fluxo integrado em memória passou para FARMA e PET, incluindo simulação sem escrita, aplicação, repetição sem nova gravação e cancelamento com invalidação do vínculo. Os leitores JavaScript do Data Studio passaram em **20 testes**. Ruff, auditoria de consistência, correspondência da documentação HTML e verificação de segredos passaram; a auditoria de dependências principais não encontrou vulnerabilidades conhecidas.

O wheel foi compilado e instalado em diretório temporário; os módulos nativos importaram sem SDK MCP a partir de outro diretório. A execução do Setup no computador do usuário e a ativação de fontes reais continuam distintas desses testes. As novas abas Meta não fazem continuação automática: ao faltar capacidade, preservam dados, registram pendência e não avançam checkpoint; continuações existentes das fontes de contatos/pedidos/itens são lidas normalmente.

## Correções encontradas na validação Windows

A primeira execução da matriz Windows identificou duas falhas no ambiente de teste: Python 3.11 tinha setuptools antigo sem o comando `bdist_wheel`, e Python 3.14 não tinha setuptools. O workflow agora prepara explicitamente `setuptools>=77` e `wheel`; o check-up da instalação nova recebe as mesmas ferramentas durante a preparação do ambiente. O teste de wheel permanece ativo, sem download de dependências dentro da fixture offline.

Uma comparação de caminho no teste também precisava tratar o nome Windows curto `RUNNER~1` e o caminho expandido como o mesmo local. Essa conferência usa resolução de caminho; não altera token, seleção de conta ou permissões. A validação Windows deve ser repetida no commit final antes da publicação.

## Preparação da estrutura 1.5.14

Foram preparadas e conferidas **dez abas Meta**, cinco por segmento: três no arquivo de Operação e duas no Dashboard de FARMA, com a mesma divisão em PET. Os arquivos permanecem nas pastas de cada segmento, com os mesmos IDs e as 54 abas anteriores preservadas. Nenhum ID privado ou token faz parte deste relatório.

A 1.5.14 automatiza o bootstrap aditivo e a retomada de abas ausentes ou vazias com cabeçalhos canônicos; divergências continuam bloqueadas para revisão manual. A preparação comprova a estrutura, sem anunciar carga real de métricas ou edição das páginas do Data Studio. As verificações do pacote Windows e os resultados finais pertencem ao commit que será publicado.
