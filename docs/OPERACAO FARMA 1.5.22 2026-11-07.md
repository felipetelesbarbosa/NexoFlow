# Operação FARMA 1.5.22 — situação em 07/11/2026

A publicação comercial FARMA continua pendente. Nesta sessão o Work conferiu o código, o resumo agregado recebido, os destinos comerciais e parte do relatório, sem acesso ao SQLite do Windows e sem aplicar lotes. **Não há comprovação de READY, fechamento SQLite → Sheets → Data Studio ou idempotência comercial.**

## Código e limites desta execução

- Versão de publicação autorizada: **NexoFlow Windows 1.5.22**.
- Tag `v1.5.22` e `main` consultadas antes desta atualização documental: `cfb382ef7a98ece76ad66588f4a4c54205a8eae8`, sem diferenças.
- [CI Windows/publicação 42412427249](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/42412427249) e [CodeQL 42412427399](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/42412427399): jobs consultados com conclusão `success`.
- [Release 1.5.22](https://github.com/felipetelesbarbosa/NexoFlow/releases/tag/v1.5.22) publicada em 07/11/2026. Digest do asset Setup: `4c951530692f77b92ebf38023c7a4ace2169e61d2a503c1ec8e4a0e9f88cf987`.
- O ambiente Work desta sessão é Linux e não acessa `C:\NexoFlow\logs\privado\clientes_observados.sqlite`. A versão instalada no PC permanece **não verificada**. O último escritor 1.5.15 informado por `BI_Status` não comprova a versão instalada atual.
- Não foram efetuados backup local Windows, atualização Preserve, configuração das origens, preparo comercial, aplicação, rollback ou consulta histórica completa pela API nesta sessão.
- Nenhum arquivo SQLite, registro de cliente, credencial, journal ou auditoria individual integra este registro.

A correção 1.5.22 das três origens foi conferida no código e na documentação. A ausência de metadados oficiais observáveis pelas respostas normalizadas do conector Drive não caracteriza nova ocorrência de `ORIGEM_DO_ARQUIVO_NAO_COMPROVADA`. A verificação operacional deve usar o configurador oficial.

## Resumo agregado recebido

Arquivo recebido: `farma-resumo-1.5.21(1).json`, formato `historico_conferencia_v1`.

- SHA-256 do **arquivo agregado**, não do SQLite: `2b88894887fbfbb03f84299bdb1f62442fc3c6c9752e2ea68e861cad842f258f`.
- Instante informado: `2026-11-07T20:05:41.942670Z`.
- Período observado: 20/04/2020 a 07/11/2026; 80 competências mensais, abril/2020 a novembro/2026.
- O contexto recebido é vazio (`{}`): não identifica snapshot de publicação, revisão ou assinatura de manifesto comercial.

| Indicador | Valor de referência |
|---|---:|
| Pedidos únicos | 267.672 |
| Compras válidas | 207.582 |
| Cancelados | 60.077 |
| Pendentes | 13 |
| Compradores distintos no TOTAL | 39.365 |
| Linhas válidas de produtos | 552.168 |
| Unidades válidas | 780.749 |
| Produtos | R$ 33.803.469,34 |
| Frete | R$ 36.200,56 |
| Faturamento observado | R$ 33.839.669,90 |

A aritmética interna fecha: `267672 = 207582 + 60077 + 13`; `3380346934 + 3620056 = 3383966990` centavos. Os valores aditivos das competências mensais mais `SEM_EMISSAO` fecham com o `TOTAL`. Compradores únicos não são somados entre meses.

A diferença interna verificada do agregado é **R$ 0,00**. Isso **não** é conciliação da cópia SQLite com as planilhas ou com o Data Studio. O resumo deve ser recalculado sobre o snapshot efetivamente usado no preparo. Permanece `LIMITES_DA_API_NAO_HOMOLOGADOS`.

Abril/2026 (R$ 5.397.367,81; 2.636 compras; 41.568 unidades) e junho/2025 (R$ 561.867,52; 2.012 compras; 32.293 unidades) continuam com concentração de valor/quantidade a investigar. Sem o SQLite não foi possível determinar a causa. Aplicar o [procedimento pontual privado](AUDITORIA%20PONTUAL%20HISTORICO.md) sobre a cópia consistente; preservar os fatos e a ressalva, sem divulgar pedidos/SKUs individuais.

## Destinos comerciais conferidos

A identificação considerou IDs, hierarquia Drive, propriedade, permissões e o mapa `NexoFlow_Arquivos`, não apenas os títulos.

| Papel | ID |
|---|---|
| Pasta NexoFlow | `1337rXNNY6kV4dIfVRPlPcgUFYkq6JE3u` |
| Pasta FarmaLíder | `141QW-guqlxWWFtG0PLhywrxWqUJ7-yKh` |
| Dashboard | `1eBO9Dt86mEDptzsijiufb8AjtxrAZhBLxXKjI25Re6s` |
| Operação | `1KDae_AH1jCnPwAaLLr9NRizU57n2P-y5Lf0BYDZ97q0` |
| Histórico | `1euqaB9E2t7YCAwp_FG0uoya_sgY0efdFjMJINBA-4oU` |

A pasta consultada tem apenas o proprietário; as três planilhas têm proprietário e a mesma conta de serviço com edição. Não se observaram permissões `anyone` ou `domain`. Isso não substitui a conferência do usuário OAuth, conta de serviço e perfil local pelo publicador no instante da carga.

| Arquivo | Células alocadas observadas |
|---|---:|
| Dashboard | 3.264.789 |
| Operação | 7.883.327 |
| Histórico | 18.413.260 |

A leitura nativa da estrutura não apresentou `NexoFlow_Continuidade` nem as cinco novas tabelas históricas nessas origens. Os marcadores oficiais de origem não puderam ser verificados pela resposta normalizada disponível; seu estado permanece desconhecido até `armazenamento configurar/status`.

A grade do Histórico já ultrapassa a margem configurada de 18 milhões; o código usa teto configurado de 20 milhões. O preparo oficial ainda precisa calcular reservas globais, índice, partes e permissões. Não se remove, trunca ou substitui histórico para liberar espaço.

A pasta privada de ensaio `1YnS-qzU5hbf0dxbhpBOyRGRrM1ztlBKs` permanece de homologação e não é destino comercial.

## Estado efetivo do publicador nesta sessão

| Evidência | Situação |
|---|---|
| Versão instalada Windows | Não verificada |
| Snapshot comercial e SHA-256 | Não disponíveis |
| Revisão comercial e corte de publicação | Não preparados |
| Manifesto/origens no Windows | A conferir pelo mecanismo oficial |
| Lotes aplicados nesta sessão | 0 |
| Linhas comerciais novas/alteradas nesta sessão | 0 |
| Continuações criadas nesta sessão | 0 |
| Lotes totais restantes | Desconhecidos; preparo não executado |
| READY | Não comprovado |
| Conciliação financeira de três fontes | Não executada |
| Idempotência comercial | Não executada |

Não interpretar zero aplicações nesta sessão como prova de ausência de dados comerciais anteriores, nem como zero lotes necessários.

## Relatório FARMA e indicadores

O [relatório comercial FARMA](https://datastudio.google.com/reporting/e60ba3bc-fe88-417d-8a39-d8512debf175) ficou acessível para edição e apresentou 10 páginas. Foram inspecionadas **Resumo**, **Anúncios** e **Atualização dos dados**; não se concluiu revisão visual ou funcional das dez páginas. As cinco fontes históricas novas não constavam da lista comercial consultada. Não foram salvas alterações de páginas, estilos, logomarca ou fontes nesta sessão.

A página Atualização informou processamento efetivo em **06/11/2026 às 21:17:43** (America/Belem), correspondente a `2026-11-07T00:17:43Z` em `BI_Status`. A atualização do navegador em 07/11 às 18:27 não é um novo processamento dos dados.

Na página Anúncios, com seleção de 01–07/11/2026, foram exibidos R$ 251,02 de investimento, 68 conversas Meta, 2.002 conversas Weni e ROAS 0,59. A parcela da fonte Meta classificada como FARMA até 06/11 soma R$ 251,02 e 68 conversas; a API Weni de 01–06/11 confirmou independentemente 2.002 conversas. Essa conferência de um recorte não homologa cobertura histórica, clientes novos, CAC, LTV ou atribuição causal.

### Atribuição e separação das marcas

- A fonte Meta da conta `898435729140540` contém campanhas de marcas diferentes: 380 linhas no corte inspecionado, 19 classificadas FARMA e 361 sem classificação. Todas apresentam segmento BI FARMA. Portanto filtrar apenas o segmento não é uma regra segura de separação; exigir classificação comprovada de campanha/anúncio.
- Os cartões consultados coincidem com a parcela classificada; não há prova de que o valor exibido já inclua todo o gasto das outras marcas.
- As duas linhas de conversões Meta inspecionadas têm política `ULTIMO_TOQUE_OBSERVADO_SEM_JANELA_CAUSAL`, origem `API_FARMALIDER`, venda válida e registro ativo. Somam R$ 189,89 nas datas 31/10 e 02/11, sendo R$ 149,00 em 02/11.
- `149,00 / 251,02 = 0,593578...` explica aritmeticamente o cartão 0,59. O vínculo é uma associação por último toque observado sem janela causal; **não homologa ROAS causal**. Regra temporal de atribuição, identificação de clientes novos e consistência de escopo continuam pendentes.
- Primeiro e último toque devem permanecer separados. Não atribuir todo pedido posterior a um anúncio, nem tratar ID de clique como ad_id oficial.
- `Eventos_Anuncios!A1:I10` apresentou somente cabeçalho. Isso comprova ausência de eventos no intervalo consultado, não que o webhook nunca tenha sido habilitado. A aba depende do webhook opcional, não da simples execução do Terminal ou do Weni Update.
- Projeto Weni FARMA confirmado: `2fce09fb-c0ae-4c68-a0b0-7ad225f767a1`. Outubro/2026 retornou 9.842 conversas, 6.959 contatos e 1.814 contatos recorrentes. São métricas de conversa/contato, não compradores oficiais.
- Não foi encontrada conexão Google Ads no inventário Windsor consultado. Isso não comprova ausência de fonte Google Ads em outras integrações ou planilhas.
- CAC requer compradores novos atribuídos e custo no mesmo escopo. Payback requer margem/contribuição e regra de recuperação. Sem fonte comprovada, exibir indisponibilidade, não zero.

## Continuidade autorizada

Não há necessidade de nova homologação prolongada: o início comercial FARMA está autorizado com a versão corrigida, nas origens definitivas, seguido de um lote de segurança.

1. No Windows, encerrar escritores, registrar versão instalada e fazer snapshot privado pelo `history_snapshot.snapshot`, incluindo WAL confirmado. Preservar configuração, credenciais, importações, revisões e todos os journals.
2. Atualizar pelo Setup 1.5.22 em **Preserve**; confirmar `nexo versao` e selecionar FARMA.
3. Conferir perfil local e os três destinos acima. Executar `armazenamento configurar`, `status` e autorização das cinco tabelas lógicas; aguardar lease se houver resposta incerta.
4. Auditar a cópia consistente e preparar capacidade/revisão sem fatos remotos. Analisar snapshot real, destinos, papéis, permissões, deltas, reservas, continuações e conflitos.
5. Com preparo aprovado, aplicar `--max-lotes 1`, conferir o lote e, se passar, continuar imediatamente **a mesma revisão**, sem nova autorização ou novo plano.
6. Exigir READY, zero lotes e divergências, igualdade mensal/total e pedidos válidos × LTV ao centavo. Preservar evidências e preparar outra revisão somente para comprovar zero deltas idênticos.
7. Após READY, conectar/conferir as cinco fontes históricas comerciais via conector privado de continuações. Não usar HML nem uma única aba física para representar todo o histórico.
8. Validar mensal, anual, acumulado, período vazio, clientes, cancelamentos, itens e partes. Usar resumo para consultas grandes e preservar grão, filtro `vigente=Sim` e estado válido.
9. Concluir somente os KPIs cuja fonte, cálculo e filtros tenham sido verificados. Guardar exportação visual quando disponível.
10. PET permanece sem escrita comercial até conciliação e aprovação operacional FARMA; depois usa snapshot, destinos, revisão e conferência próprios.

Código 3 de auditoria pode indicar as pendências históricas conhecidas, com resumo gerado. Código 3 após o lote limitado pode ser pausa esperada; também pode sinalizar pendência/divergência. Verificar o estado e o relatório. Nunca declarar conclusão a partir do código de pausa.

Os comandos oficiais, o snapshot real e a retomada estão no [roteiro do publicador](PUBLICADOR%20HISTORICO%20SQLITE%20SHEETS.md). Esta atualização é documental: não altera código operacional, versão, tag, release Windows, VPS, anúncios, contatos, campanhas ou Recompra.
