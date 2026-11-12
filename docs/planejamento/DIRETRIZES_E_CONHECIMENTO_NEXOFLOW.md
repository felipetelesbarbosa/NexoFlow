# Base Mestre de Conhecimento do NexoFlow

Consolidação documental em **10/11/2026**. Referência compartilhada para Codex, Work e futuros responsáveis. Este documento organiza decisões e liga os contratos especializados; não autoriza implementar o roadmap, iniciar cargas, alterar fontes comerciais, publicar agentes, implantar serviços ou gerar releases.

## Navegação e ordem de consulta

1. [AGENTS.md](../../AGENTS.md): regras operacionais vigentes e limites da tarefa autorizada.
2. [README](../../README.md), [changelog](../../CHANGELOG.md) e [versionamento](../VERSIONAMENTO.md): entrega distribuída e seu histórico.
3. Esta Base Mestre: escopos, invariantes, evidências e pendências.
4. [Cronograma mestre](CRONOGRAMA_MESTRE_HUB_METRICAS.md) e [paridade Data Studio](etapa-3-5/F_PARIDADE_DATA_STUDIO.md): produtos planejados e inventário datado.
5. Documentação especializada abaixo, código, testes e evidências do mesmo SHA. Conferir novamente main, tag, release e ambiente instalado a cada tarefa.

Uma nota de planejamento não substitui contrato executável; uma divergência entre código, regra autorizada e documentação exige investigação, sem remover proteções para fazê-los concordar. Novas decisões devem registrar fonte, data, ambiente, segmento, corte, teste e limite da prova. Não usar memória de conversa como substituto desse registro.

## 1. Estado e evidências

| Componente | Estado documentado neste corte | Limite da conclusão |
| --- | --- | --- |
| Windows/Local, Terminal, Weni, Analytics, Noturno e Recompra | [1.5.33 publicada](https://github.com/felipetelesbarbosa/NexoFlow/releases/tag/v1.5.33), SHA `7884d7007fd0c65cbf90bfc30c5c35dc6c9056fb`, 10/11/2026, 23:28:34 UTC−3 | Release não comprova instalação ou ativação em cada PC. |
| Validação da distribuição | [Workflow oficial aprovado](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/42943029299): Windows, Setup e pacotes; conferência independente registrada nas notas da release | Testes sintéticos/CI não equivalem à conciliação comercial, aprovação de antivírus ou autenticação no proxy real. |
| Hub/Cloud | Núcleo Python, FastAPI, worker, PostgreSQL e Docker desenvolvidos em homologação; implantação isolada na VPS relatada pelo Work, originalmente SHA `23f2806` | Não houve inspeção da VPS nesta consolidação; SHA instalado atual e fontes reais precisam de conferência pelo Work. Sem release comercial do Hub. |
| Central de Operações e NexoFlow Métricas | Planejados no cronograma e na Etapa 3.5 | URLs propostas e requisitos não comprovam serviços implantados. |
| Data Studio FARMA/PET | Relatórios existentes; inventário datado e matriz de paridade disponíveis | Não foram abertos/alterados nesta tarefa; toda ligação, fórmula e total comercial exige evidência do corte correspondente. |
| IA Manager, agentes personalizados e Weni CLI | Base de pesquisa disponível e referenciada | Não comprova integração comercial de agentes ao NexoFlow nem autorização de disparos. |

Registrar separadamente: **código desenvolvido → teste aprovado → release publicada → versão instalada → implantação no Hub → integração ativada → homologação comercial**. Nenhum estágio implica automaticamente o seguinte. Totais de snapshots comerciais são evidências privadas datadas, nunca constantes de homologação para execuções futuras.

## 2. Arquitetura e fronteiras

Windows permanece operacional e autônomo em `C:\NexoFlow`, sem dependência de Codex CLI, servidor MCP, clone de desenvolvimento ou VPS. Ver [aplicativos](../../README.md), [Noturno](../NOTURNO.md) e [núcleo Hub](../../hub/README.md).

No Hub, Python mantém identidade, pedidos, finanças, segmentação, elegibilidade, reconciliação e atribuição. Worker controla tarefas, tentativas, checkpoints, leases e retomada; PostgreSQL persiste estados e coordenação; FastAPI fornece API interna autenticada. n8n agenda/orquestra e não duplica regras de negócio. Os conectores comerciais e a escrita real permanecem bloqueados no contrato de homologação descrito no repositório.

Preservar serviços, redes, volumes, backups e helper Compose existentes; não reconstruir a infraestrutura. Atualizar Windows não implanta o mesmo SHA na VPS. Locks PostgreSQL coordenam participantes Hub e locks Win32 coordenam a operação local: **isso não resolve concorrência Windows/VPS**. Uma futura transição exige proprietário único de escrita por destino/segmento e reconciliação de respostas incertas.

A Central é o produto técnico de admins/devs; Métricas é BI para gestores e convidados com acesso próprio. `painel.nexoflowhub.com.br` e `metricas.nexoflowhub.com.br` são propostas. Usuário exclusivo de Métricas não herda acesso a SQL, n8n, segredos ou administração. Consulte [arquitetura web](etapa-3-5/E_ARQUITETURA_WEB.md).

## 3. Grãos e invariantes dos dados

| Entidade | Identidade/grão a preservar |
| --- | --- |
| Pedido | Segmento + ID oficial de pedido; cliente oficial é a identidade financeira. |
| Item | Segmento + pedido + item oficial; dois itens do mesmo SKU não são uma única linha. |
| Cliente / contato / conversa | Cliente oficial, UUID/URN Weni e conversa têm identidades distintas. |
| Mídia | Conta, anúncio oficial e dia; clique, campanha e evento de atribuição são entidades separadas. |
| Execução / snapshot | Revisão, origem, SHA, corte, segmento, manifesto e comprovantes próprios. |

Dinheiro usa Decimal/centavos. Preservar estados, pagamentos, frete, descontos, revisões, deduplicação, cobertura e proveniência. Não multiplicar receita de cabeçalho por itens, custo de mídia por pedidos, LTV por contato ou compradores distintos por meses. Taxas agregadas são razões entre totais elegíveis, não médias simples de percentuais. Comparar apenas universos do mesmo corte, política, segmento e cobertura.

## 4. API de pedidos, identidade e política financeira

Fonte oficial: `GET /api/Delivery/pedidos/{segmento}`, com `dataInicio`, `dataFim`, `pagina`, `limite` e token privado. Limite validado **1–500**. O token em query nunca pode aparecer em logs/URLs públicas. Ver [contrato e evidência do fim civil](../HISTORICO%20PEDIDOS.md), [API](../FARMALIDER%20API.md) e [auditoria](../AUDITORIA%20HISTORICO%20FARMA%201.5.16.md).

A data final civil inclusiva é serializada pelo cliente como fim do dia. A evidência FARMA pontual dessa política não comprova cobertura anual ou homologação de todos os segmentos. Manter `LIMITES_DA_API_NAO_HOMOLOGADOS` enquanto aplicável. Janelas paginadas completas e todos os pedidos do período civil comprovadamente recebidos são afirmações diferentes. Apenas o 404 oficial de período vazio, nas condições documentadas de página/rota/formato, permite avançar a janela; um 404 genérico continua erro.

| Código de status | Significado |
| --- | --- |
| -2 | EmAberto |
| -1 | PendenteDePagamento |
| 0 | EmProcessamento |
| 1 | EmTransito |
| 2 | Concluido |
| 3 | Cancelado |
| 4 | ProntoParaRota |

| Pagamento | Significado |
| --- | --- |
| 0 | Cancelado |
| 1 | Dinheiro |
| 2 | Débito |
| 3 | Crédito |
| 4 | Ticket |
| 5 | Pix por Link de Pagamento |
| 6 | Pix no POS |

Status 3 ou pagamento 0 excluem venda; os estados não cancelados documentados contam como venda validada pela política vigente. Isso não comprova liquidação ou entrega. Resposta oficial verificada com lista de itens vazia tem regra própria de cancelamento; falha de rede, omissão e payload malformado não comprovam ausência de compra.

No histórico, frete oficial do cabeçalho entra uma única vez. Lançamento técnico de frete não é produto/unidade. Divergência isolada entre esse lançamento e o cabeçalho é aviso preservado; demais inconsistências financeiras continuam protegidas. Não aplicar a política do histórico automaticamente a validadores legados.

CPF válido exige unicidade e cliente oficial comprovado; CPF vazio, zerado ou malformado não autoriza consulta/vínculo. O vínculo histórico com CPF inválido exige nome completo normalizado + telefone ou nome completo + e-mail concordantes, sem ambiguidade. Os validadores legados têm regras específicas no AGENTS; não uniformizá-los silenciosamente. Associação por nome, telefone ou contato multicanal isolados não prova identidade. Compra sem Weni continua elegível ao histórico/LTV oficial.

## 5. LTV, receita e cobertura

LTV observado = soma das compras válidas únicas do cliente oficial e segmento na base observada. Receita do mês, LTV acumulado, ticket, frequência, recorrência e aquisição são métricas diferentes. Filtro mensal de receita não reduz a vida histórica do cliente. LTV projetado e LTV até um corte passado exigem contratos próprios; o LTV acumulado existente não prova uma consulta temporal retrospectiva implementada.

Cliente novo exige primeira aquisição comprovada e cobertura suficiente; ausência de pedido em uma fonte incompleta não a comprova. Preservar fatos antigos quando uma consulta/atualização é inconclusiva, com pendência explícita. Não apagar dados para ajustar médias ou zerar diagnósticos.

## 6. Analytics e modos de carga publicados

Referência operacional: [Analytics e histórico automático 1.5.31](../ANALYTICS%20HISTORICO%20AUTOMATICO.md).

| Rotina | Comportamento e escopo |
| --- | --- |
| Analytics diário | Coleta recente hoje..D−20, inclusive em America/Belem, quando habilitada; publica diferenças nas fontes configuradas e nas cinco históricas quando habilitadas. |
| Histórico completo | Exige início/fim explícitos; carga completa de contatos não implica buscar anos de pedidos. |
| Weni em quatro partes | Manifesto congelado de contatos/UUIDs; partes ordenadas de 25%. |
| `nexo analytics --percentual 25` | Limita lotes da publicação histórica; aceita 25/50/75/100. Não fraciona consultas nem todas as etapas do Analytics. |
| Noturno | Executa Weni, Analytics e Recompra; menu incremental ou completo 100%, sem seleção própria de percentual histórico na 1.5.31. |

Não confundir essas frações. O Analytics diário não retoma automaticamente janelas anuais antigas fora do recorte recente. A revisão automática interrompida retoma o mesmo snapshot; fatos coletados depois desse corte ficam para a próxima execução. Não assumir revisão manual WRITING. Pendência histórica impede checkpoint de sucesso e deve aparecer como resultado parcial, preservando as demais etapas confirmadas. Espera preventiva é acumulada; exibição humana converte segundos em minutos/horas, mantendo métricas numéricas em segundos.

## 7. Sheets, continuações e publicador

[Publicador histórico](../PUBLICADOR%20HISTORICO%20SQLITE%20SHEETS.md), [continuações](../CONTINUACOES.md) e [três papéis](../planilhas_separadas.md) são os contratos especializados. Cada segmento tem Dashboard, Operação e Histórico próprios, organizados nas subpastas da marca. Conferir IDs, pasta, permissões, origens e manifesto; ID/nome isolado não autoriza sobrescrever marcador. Visões OAuth e conta de serviço têm autoridades diferentes.

Cinco tabelas lógicas: `Historico_Pedidos`, `Historico_Itens`, `BI_LTV_Clientes`, `BI_Cobertura_Historica`, `BI_Historico_Resumo`. Upsert deve alcançar a parte onde a chave já existe. Capacidade considera grades alocadas, cabeçalhos, reservas, expansão e partes, não somente células preenchidas. Valores configurados de margem/teto precisam ser reconferidos no ambiente; não são garantia universal do provedor.

Fluxo: backup consistente SQLite incluindo WAL → preparo/revisão → capacidade → lote de segurança → releitura/conferência → retomada da mesma revisão → fechamento/conciliar. Não executar esse roteiro comercial por uma autorização exclusivamente documental. Preservar snapshots, journals, reservas, intenção durável, hashes e backups por intervalo. Resposta perdida exige reconciliar chaves/células antes de reaplicar. Rollback do lote recusa sobrescrever edição posterior de terceiro.

Fechamento exige manifesto READY, zero lotes restantes e zero divergências, inclusive financeiras. Piloto parcial não autoriza apresentar total completo. Filtrar vigência e estado financeiro pertinentes; não somar MES/ANO ao TOTAL nem compradores mensais para obter distintos do período. Nova preparação idêntica não deve reenviar fatos. Exclusões expressamente autorizadas são restritas à cópia de publicação e não apagam a base bruta nem criam exclusão global em API/Weni.

## 8. Weni, Recompra e agentes

A [integração Weni existente](../README%20WENI.md) consulta contatos, mensagens, campos, grupos e eventos oficiais, prepara revisão e revalida antes de escrita. API de pedidos continua sendo fonte financeira oficial. Preservar UUID/URN, consentimento, evidência de anúncios e isolamento. [Segmentos](../SEGMENTOS%20E%20FLUXOS.md), [Recompra](../README%20RECOMPRA.md) e [webhook](../WENI%20WEBHOOK.md) detalham seus contratos.

FARMA usa D+25 e política de produtos humanos; PET usa D+30, vínculo PET oficial e não exige maioridade. Recusa/Opt-Out prevalece; campo vazio não vira consentimento. Ausência de dados não prova ausência de compra. Recompra conserva regras de referência futura, revalidação, consulta geral e remoção preventiva por pendência descritas no AGENTS; não inferir autorização de envio a partir do cálculo de elegibilidade.

A [Base Weni CLI, IA Manager, agentes e Flows](../WENI%20CLI%20AGENTES%20E%20FLUXOS.md) é a referência especializada obrigatória, sem duplicar seu conteúdo aqui. IA Manager/Agent Builder gerencia agentes; agentes passivos reagem; agentes ativos seguem pré-processamento/regras; tools executam integrações autorizadas; Flows executa fluxos. Publicar agente não significa iniciar fluxo.

`POST /api/v2/flow_starts.json` é uma operação de início documentada, não uma autorização para qualquer agente usá-la. Antes de futura implementação, mapear evento → agente → regra → tool → parâmetros/identidade/segmento → fluxo autorizado → destinatários elegíveis → idempotência → confirmação/erro → auditoria/retorno ao humano. Validar versão CLI, permissões, consentimento e política do canal; linguagem natural não concede privilégios no backend. Não criar/publicar agentes, disparar fluxos ou modificar IA Manager nesta consolidação.

## 9. Mídia e atribuição

[Meta nativo](../META%20ADS%20NATIVO.md), [rastreamento](../RASTREAMENTO_META.md) e [Google Ads](../GOOGLE%20ADS.md) distinguem coleta oficial e metadados de origem. Meta usa o cliente Python compartilhado com MCP opcional e somente leitura; `ads_read`, sem `ads_management`. Token apenas no JSON privado previsto. Google `gclid`, `gbraid` e `wbraid` não comprovam coleta autenticada de investimento ou campanhas.

O projeto Weni comprova FARMA/PET, não o nome da campanha. Anúncio sem evidência permanece não classificado; anúncio compartilhado não recebe 100% do custo em cada marca. Preservar primeiro/último toque, IDs oficiais versus clique, canal, data e janela comprovada. Não somar modelos nem atribuir pedido a toque posterior. Sem evidência, manter compra sem crédito de anúncio.

Conversas diárias por projeto/data medem o projeto: join por data não as transforma em conversas de anúncio ou vendas. Registrar cobertura/corte de mídia, Weni e pedidos. Preservar moeda, fuso e atribuição da conta; diferença de fuso não autoriza redistribuir totais diários sem dados horários. Alcance/frequência não são aditivos.

| Indicador | Definição/condição |
| --- | --- |
| CPA de anúncio | Investimento comprovado / pedidos válidos únicos atribuídos no mesmo escopo; denominador zero ou custo desconhecido não gera valor fictício. |
| CAC de mídia | Custo de mídia / compradores novos cuja aquisição foi comprovada; não trocar pedidos por clientes. |
| ROAS | Receita atribuída / investimento correspondente; receita somente associada deve ter outro rótulo. |
| Conversão | Identificar se contato→comprador, conversa→venda ou clique→pedido; denominadores e cobertura compatíveis. |
| LTV de clientes relacionados a anúncio | Definir coorte, modelo e corte; receita vitalícia desses clientes não equivale a receita causal do anúncio. Métrica desejada não é prova de implementação. |
| Payback | Recuperação do custo de aquisição por margem/contribuição ao longo do tempo; faturamento bruto não substitui margem. |

## 10. Data Studio e paridade Métricas

Baselines: [FARMA](https://datastudio.google.com/reporting/e60ba3bc-fe88-417d-8a39-d8512debf175) e [PET](https://datastudio.google.com/reporting/35c02ed5-901b-4134-a735-5ac9a9290306). Ver [inventário e provas por componente](etapa-3-5/F_PARIDADE_DATA_STUDIO.md) e [matriz detalhada](etapa-3-5/matriz_paridade.csv). O inventário de 07/11 não é auditoria atual nem homologação de todas as fórmulas.

| Página | Requisito a preservar/validar |
| --- | --- |
| Resumo / Vendas | Receita, pedidos, compradores, ticket, evolução diária/mensal e comparação coerente com período; lacuna não é zero comprovado. |
| Meus clientes / busca | Ranking, histórico, frequência, recorrência, primeira/última compra e LTV observado do cliente oficial. |
| Pedidos por cliente | Pedido e item em grãos distintos; não multiplicar total por linhas de produto. |
| Produtos mais vendidos | Receita, unidades e pedidos; Top 5 = receita dos cinco líderes / receita de todos os produtos elegíveis no mesmo período. |
| Curva ABC | Receita, participação e acumulada recalculados no período; convenção 80/15/5 e fronteiras conforme contrato especializado. |
| Público / Base | Contato, comprador, ativo e sem compra observada distintos; geografia e demografia somente comprovadas. |
| Anúncios / Pedidos dos anúncios | Custos, evidências, coortes e pedidos verificáveis, sem duplicar receita ou inventar CAC/ROAS. |
| Atualização | Coleta, gravação, publicação, conciliação, conector, cache e cobertura explicitados separadamente. |

Preservar fontes atuais, visuais e permissões até aceitação formal. Campos com mesmo nome podem ter IDs distintos: validar bindings de controles/filtros, tipos, data/moeda e dimensão temporal. Blends podem multiplicar fatos; união vertical exige deduplicação e continuidade, sem substituir automaticamente o conector próprio.

O conector deve ler somente tabelas autorizadas e partes confirmadas pelo manifesto; parte ausente/ilegível, publicação WRITING ou limite excedido não pode virar total parcial silencioso. Usar resumo para anual e detalhe filtrado, respeitando tempo, payload e quota do Google. Cache não dispensa integridade. A interação `dateRangeRequired=false` com detalhes dependentes de período é ponto de investigação, não bug comercial comprovado nesta tarefa. API pública administrativa/Linking API/Community Connectors não equivalem a API de edição geral de layouts.

## 11. UX, observabilidade e segurança futuras

Novos produtos web: pt-BR, hierarquia visual clara, fontes legíveis, filtros globais previsíveis, tabelas pesquisáveis, drill-down/paginação/exportação autorizados, responsividade e dark com opção clara. Preservar identidade FARMA; PET azul `#20AFE9` e laranja `#F69F11`. Reportei e Iota.hub são referências de usabilidade, sem copiar código, marca ou layout proprietário.

Central planejada: CPU/RAM/disco/rede, Docker/PostgreSQL/backups, filas/execuções/checkpoints, status HTTP, latência/p95, retries/timeouts/proxy/TLS/autenticação, correlação opaca e cobertura. Agentes/tools/flows só entram na observabilidade quando houver coleta autorizada. Grafana/Prometheus/Loki são candidatos sujeitos a medição e dimensionamento, não stack instalada comprovada.

Login individual, sessões seguras, RBAC e autorização no backend/consultas; revogação, auditoria, isolamento de ambientes e LGPD. Nunca incluir tokens, senhas, chaves, headers, DSN, URLs autenticadas, CPF, telefone, endereço ou payload comercial integral em Git, CI, pacotes ou logs comuns. Relatórios privados necessários devem ficar protegidos e separados.

Preserve mantém configuração, credentials, SQLite, logs, importações e journals; atualizações devem usar distribuição oficial validada, não módulos avulsos. Proxy indisponível não prova rede pessoal: rota explícita/autorizada, herança nos subprocessos, TLS validado e retries controlados. Não desativar antivírus/SmartScreen/firewall/TLS, criar exclusões automáticas ou contornar a TI para fazer a aplicação funcionar.

## 12. Aprendizados, conflitos e pendências

| Registro | Classificação e orientação |
| --- | --- |
| Indicadores de janela versus acumulado (1.5.16) | Problema de apresentação documentado; separar execução, período e base acumulada. Recebimentos podem repetir IDs. |
| Origens, continuações, grade e quota (1.5.22–30) | Correções e evidências nos relatórios especializados; não atribuir toda falha HTTP 400 à mesma causa. Reconferir estado atual antes de retomar. |
| Índice SQLite na conferência (1.5.24) | Correção comprovada em código/testes; tamanho do journal ou CPU alta não prova término nem falta de disco. |
| “Em validação” após publicação da 1.5.31 | Desatualização documental corrigida nesta consolidação; tag e pacotes anteriores permanecem intactos. |
| “Hub futuro” versus núcleo implementado | Separar núcleo HML e roadmap de produtos; implantação atual depende de evidência do Work. |
| Inventário inicial versus complementar do Data Studio | A inspeção especializada mais detalhada prevalece nos componentes que ela documenta, sem generalizar para todos. |
| Limites de datas, descontos e qualidade de concentrações | Evidência pontual não elimina ressalvas globais; análises futuras somente no recorte autorizado, sem inventar causa ou alterar fatos. |
| CPA/LTV de anúncios e clientes, paridade e filtros | São requisitos; conferir fonte, grão e implementação antes de declarar disponibilidade no painel. |
| Windows/Hub, fontes comerciais PET e agentes | Não inferir ativação por passagem de CI, flags preenchidas ou permissões disponíveis. |

Critério de conciliação quando aplicável: mesmos pedidos únicos, válidos/cancelados, compradores distintos, itens/unidades, produtos/frete/receita e recortes mensais/TOTAL, **diferença de R$ 0,00**. Incluir SEM_EMISSAO para fechar universo; recebimentos brutos só por mês quando os metadados permitirem. Aritmética correta não comprova completude temporal nem ausência de anomalias comerciais.

## 13. Referências oficiais e contextuais

Contratos externos devem ser conferidos na versão atual antes de desenvolver. Nesta consolidação os links foram organizados; não se afirma leitura integral ou revalidação online de toda a documentação.

- Weni: [CLI original](https://weni-ai.github.io/weni-cli/), [VTEX CLI](https://developers.vtex.com/docs/guides/using-the-weni-by-vtex-cli), [agentes](https://developers.vtex.com/docs/guides/working-with-weni-by-vtex-agents), [API Flows](https://flows.weni.ai/api/v2/explorer/), [repositório CLI](https://github.com/weni-ai/weni-cli). O guia especializado registra migração da documentação para VTEX.
- Google: [desempenho](https://docs.cloud.google.com/data-studio/improve-performance?hl=pt-br), [problemas](https://docs.cloud.google.com/data-studio/troubleshooting-guide?hl=pt-br), [erros de conectores](https://docs.cloud.google.com/data-studio/community-connector-errors?hl=pt-br), [referência Community Connector](https://developers.google.com/data-studio/connector/reference), [release notes](https://docs.cloud.google.com/data-studio/release-notes), [API](https://developers.google.com/data-studio/integrate/api/reference), [quotas Sheets](https://developers.google.com/workspace/sheets/api/limits?hl=pt-br).
- Contexto/UX: [Reportei](https://reportei.com/dashboard/), [Wanalytics](https://wanalytics.medium.com/confira-os-8-melhores-recursos-do-google-data-studio-para-an%C3%A1lise-e-visualiza%C3%A7%C3%A3o-de-dados-40507b49047), [Avaus](https://www.avaus.com/blog/the-6-most-common-google-data-studio-problems-and-how-to-fix-them/). Artigos antigos não substituem contratos atuais.

## 14. Manutenção e passagem Codex → Work

Antes de cada tarefa: atualizar main sem reescrever histórico; conferir release/SHA e ambiente instalado; ler AGENTS, Base Mestre e guia especializado; delimitar contrato, autorização, segmento, impacto financeiro, dependências, testes, backup e recuperação. Não implementar toda a lista de melhorias a cada release.

Codex mantém código, testes e documentação conforme a tarefa autorizada. Work confere ambiente, configuração visual, implantação e evidências reais quando autorizado. Ambos consultam este índice e registram mudanças nos documentos especializados, evitando edições simultâneas contraditórias. Sem memória própria persistente, usar o link do GitHub e o SHA como ponto de retomada.

Nesta tarefa: somente consolidação documental, sem código, testes alterados, dependências, bancos, APIs comerciais, Sheets, Data Studio, Weni/agentes/Flows, anúncios, Jira, VPS, workflows ativados manualmente, versões, tags ou releases. O push documental pode disparar CI já existente com `[skip release]`; isso não autoriza novas automações comerciais.

### Histórico desta base

- **10/11/2026:** primeira consolidação; release Windows 1.5.31 comprovada no GitHub; contratos existentes reaproveitados; regras e hipóteses separados; referências Weni incorporadas; estado instalado/comercial/VPS não revalidado. Próximas alterações devem acrescentar data, decisão, evidência e pendências sem apagar a história anterior.

- **10/11/2026, tarefa posterior:** usuário autorizou otimizações Windows/Local. Desenvolvimento de agrupamento de intervalos documentado no [relatório específico](../OTIMIZACAO%20INTERVALOS%20HISTORICO.md); isso não muda a distribuição 1.5.31 ou comprova desempenho comercial. A restrição documental acima descreve a missão original de consolidação.

- **10/11/2026, preparação 1.5.32:** publicação da otimização autorizada após checks/pacotes aprovados. Avisar sempre quando uma mudança precisar de release para alcançar o Windows instalado; dispensar o aviso quando não houver essa necessidade. A 1.5.31 publicada continua sendo a referência até a conclusão dessa publicação.

- **10/11/2026, publicação 1.5.32:** tag/pacotes e downloads conferidos no SHA `9d4be5d911a817a09773fc843f7674a6480e0b71`; a 1.5.31 permanece intacta. A orientação de avisar quando uma mudança exige release está registrada no AGENTS. Sem carga comercial ou implantação nesta entrega.

- **10/11/2026, preparação 1.5.33:** usuário autorizou publicação da correção da leitura da trava após HTTP 429/5xx. Preservar os dez módulos de assinatura e a release 1.5.32; anúncio depende dos checks e pacotes do novo SHA. Não inicia cargas comerciais.

- **10/11/2026, 23:28:34, publicação 1.5.33:** checks, Setup e downloads públicos conferidos no SHA `7884d7007fd0c65cbf90bfc30c5c35dc6c9056fb`. 1.5.32 preservada. A otimização de CI posterior usa uma geração e reutilização dos mesmos pacotes; não altera a versão Windows nem seus artefatos. Ver [guia](../RELEASE%20EFICIENTE.md).

- **11/11/2026, conferência inicial de BI_Itens:** o Work encontrou raiz registrada sem estado e não confirmou a fonte. O leitor Apps Script foi ajustado para conferir exclusivamente o legado principal estável, sem fabricar READY, mantendo bloqueios de escrita, partes pendentes e cruzamentos. Ver [diagnóstico e passagem](../INICIALIZACAO%20BI%20ITENS.md). Os testes são sintéticos; atualização da implantação e comparação comercial permanecem com o Work. Pacotes Windows preservados.


## Atualização autorizada — piloto BI_Itens PostgreSQL (12/11/2026)

O usuário autorizou integrar somente FARMA/BI_Itens ao banco piloto `nexoflow_datastudio_piloto`, preservando Windows, Sheets das demais tabelas e PET. Implementação 1.5.36 em preparação: Analytics reutiliza as linhas oficiais, outbox local com exclusão mútua, API transacional de publicação, staging/upsert, recibos e reconciliação explícita por venda. Carga parcial não autoriza remoções. Serviços de leitura e publicação usam logins, Bearers e aplicações Cloudflare Access separados; o PostgreSQL continua privado.

Data Studio é o painel prioritário. O novo conector privado lê a visão existente `farma.produtos_itens` por API de somente leitura; Metabase é referência para comparar. A visão real, seus tipos/origem, as credenciais Access e a infraestrutura ainda dependem da conferência do Work. Testes sintéticos/Docker não são implantação ou homologação comercial. Não editar o manifesto Sheets, criar READY manualmente, ativar PET ou migrar produção por causa desta nota. A referência de 68.273 itens é um corte fornecido pelo usuário, sem nova leitura comercial nesta entrega.

Ver [implementação e homologação](../BI%20ITENS%20POSTGRESQL%20FARMA.md) e [roteiro do Work](../PROMPT%20WORK%20BI%20ITENS%20POSTGRESQL.md). Segredos particulares permanecem fora do Git e da distribuição; hostnames e Service Tokens só podem ser preenchidos após emissão real.


### Auditoria Work e correção da visão API — 12/11/2026

A auditoria do Work confirmou sete campos em `farma.produtos_itens` (Metabase), doze em `farma.bi_itens` e PK `item_chave`. A correção posterior à release Windows 1.5.36 (`2cc09b8`) cria a visão dedicada `farma.produtos_itens_datastudio` pela migração aditiva 002; preserva a visão e os privilégios Metabase. Servidor e conector usam o SHA validado dessa correção, com publicação incompleta ainda bloqueante. Ver [diagnóstico e roteiro](../CORRECAO%20VISAO%20API%20BI%20ITENS.md). A evidência real é do Work; testes Codex são sintéticos. Manter Windows em `sheets` e Analytics/Noturno FARMA pausados nesta etapa; não editar manifesto, ativar PET ou executar carga comercial por causa dessa migração.

## Atualização autorizada — backend definitivo Data Studio, 12/11/2026

Implementação opt-in 1.5.37 em validação: ver [contrato e comandos](../MIGRACAO%20WINDOWS%20POSTGRESQL%20DATA%20STUDIO.md), [inventário](../ESTRUTURA%20POSTGRESQL%20DATA%20STUDIO.md) e [relatório](../RELATORIO%20BACKEND%20DATA%20STUDIO.md). Sheets permanece padrão; PostgreSQL selecionado explicitamente usa o banco definitivo dedicado por API privada, sem depender do Hub ou exigir credenciais Google para a operação nova. A exportação inicial Sheets é leitura controlada de migração.

O Work informou que a 001 foi aplicada com schemas vazios; não a repetir. A 002 é aditiva. Preservar piloto e Metabase. As 37 fontes e três mesclagens observadas são dependências de corte, sem comprovação de ausência de células manuais. Não usar a base SQLite parcial para substituir a revisão histórica READY. Implantação e migração comercial são etapas distintas da distribuição do código.
