# Prompt para o Work — BI_Itens FARMA privada no PostgreSQL e Data Studio

Atue no ambiente autorizado do NexoFlow. Leia primeiro `AGENTS.md`, `docs/planejamento/DIRETRIZES_E_CONHECIMENTO_NEXOFLOW.md` e **docs/BI ITENS POSTGRESQL FARMA.md** do commit validado da release Windows 1.5.36. Não confunda release de código com implantação/homologação comercial.

## Missão

Implantar e homologar as APIs privadas de publicação e leitura da BI_Itens FARMA no piloto já existente; validar o novo conector numa cópia do Data Studio e só depois migrar a fonte comercial aprovada. O usuário autorizou esse caminho. Não expor PostgreSQL, não misturar bancos, não alterar PET e não recriar infraestrutura.

Destino exato: projeto PostgreSQL `nexoflow-datastudio-piloto`, banco `nexoflow_datastudio_piloto`, tabela `farma.bi_itens`, PK `item_chave`; visão de leitura existente `farma.produtos_itens`. Metabase consulta a visão em modo somente leitura e é referência para comparar. Métricas, Hub, n8n e banco de configuração do Metabase ficam fora desta tarefa.

Referência inicial fornecida: 68.273 linhas, de 20/04/2020 a 06/11/2026. Confirmar o corte atual, não presumir que continuou idêntico. Não repetir a carga anual, transferir SQLite ao servidor ou coletar APIs comerciais para testar o transporte.

## Pré-requisitos reais

1. Confirmar no GitHub tag/SHA, CI/CodeQL e pacotes 1.5.36 efetivamente publicados. Não usar um SHA local diferente do distribuído.
2. Identificar a configuração Compose real e os seis arquivos usados pelo helper da infraestrutura. Conferir redes, nomes dos containers, volumes e backups antes de qualquer extensão.
3. Fazer backup consistente do banco piloto com SHA-256 privado. Rodar `integrations/bi_itens_publisher/audit.sql` somente em leitura. Conferir schema/PK, cabeçalhos/tipos da visão, origem e grão, RLS/triggers, privilégios, contagens, produtos/unidades/receita por mês e TOTAL. Preservar a base atual.
4. A visão precisa expor os 12 IDs originais de BI_Itens, com códigos/chaves Texto, data DATE e medidas NUMERIC. Se não oferecer esse contrato ou tiver dependências adicionais, devolver o diagnóstico sanitizado ao Codex. Não inventar colunas, alterar a visão do Metabase ou retirar a guarda para liberar.

## Implantação privada

- Conferir o checkout no SHA aprovado e informar `NEXOFLOW_SOURCE_SHA` no build; verificar a label `org.opencontainers.image.revision` e `/opt/nexoflow/VERSION` nas imagens.
- Usar o código em `integrations/bi_itens_publisher/`; são **dois processos**, mesma imagem, tokens e DSNs separados. O recebedor não fornece rotas de leitura, e o leitor não fornece publicação.
- Executar a migração aditiva no piloto e criar os logins dedicados sem privilégios administrativos. Aplicar `grants.sql` e `reader-grants.sql`; não reutilizar credenciais de outros aplicativos.
- Implantar os serviços novos com a referência `compose.overlay.example.yaml`, adaptada às redes reais já conferidas. UID 10001, filesystem somente leitura, segredos em arquivos privados, sem `ports`, capabilities removidas e logs rotacionados. Preservar o PostgreSQL e serviços existentes.
- Configurar duas aplicações Cloudflare Access **Service Auth**, com Service Tokens diferentes e sem bypass público, antes de ligar os ingress/DNS. Um hostname/ingress para publicação, outro para leitura. Os nomes sugeridos no guia não são afirmações de DNS já existente.
- Testar: sem Access, Access incorreto, Bearer incorreto, chave trocada, destino/segmento incorretos e saúde dos dois serviços. Não registrar headers, senhas, DSNs, tokens ou linhas comerciais.

Felipe possui configuração privada preparada. Ela preserva os tokens Weni/Farma/Google fornecidos e deixa o destino padrão em `sheets`. Os novos segredos Bearer de publicação/leitura são independentes, mas os campos de hostname e Service Tokens Access dependem da emissão/configuração real. Preencher pela via privada; não pedir tokens no chat e não colocar no Git/CI. Não enviar o `secrets_config.py` inteiro à VPS: os serviços só precisam de seus próprios arquivos.

## Homologação do envio Windows

Não presuma acesso ao C: ou PowerShell. Se o Windows não estiver disponível, entregue a Felipe os comandos exatos para executar.

1. Atualizar Windows com Setup Preserve; `nexo versao` deve mostrar 1.5.36.
2. Validar primeiro os serviços e a leitura da base atual, sem nova escrita comercial.
3. Com o canal aprovado, FARMA configura `BI_ITENS_DESTINO="postgres"`, modo `simular` e JSON de credenciais preenchido. Uma atualização normal do Analytics informa inserções/alterações/mantidos previstos e não avança checkpoint PostgreSQL. **A simulação é do destino PG; as demais etapas do Analytics permanecem reais.** Não tratá-la como dry-run global.
4. Conferir o delta esperado contra o corte atual. Depois da validação autorizada, passar para `aplicar` e usar a rotina Analytics. Ela envia as mesmas linhas que gerou para BI_Itens, sem depender de gravá-las no Sheets antes. Não habilitar PET.
5. Em falha de rede, retomar a outbox existente, sem recolher Weni/Sheets:

```powershell
nexo bi-itens-postgres status
nexo bi-itens-postgres retomar
```

Lotes e plano têm confirmação do banco; uma resposta HTTP 200 isolada não basta. Não editar UUID, digest, checkpoints ou estados. Se houver plano/revisão revertida ou superada, usar exclusivamente a reconciliação administrativa descrita no guia. Não criar READY manualmente.

## Nova fonte Data Studio — primeiro cópia privada

Preservar produção e fazer backup atualizado do relatório FARMA:
https://datastudio.google.com/reporting/e60ba3bc-fe88-417d-8a39-d8512debf175

1. Criar projeto Apps Script privado separado com `Code.js`, `Schema.js` e `appsscript.json` de **connectors/bi_itens_api/**, do mesmo SHA. Não misturar com o conector de continuações.
2. Nas propriedades privadas do script, configurar `NF_READ_ENDPOINT`, `NF_ACCESS_CLIENT_ID` e `NF_ACCESS_CLIENT_SECRET`, exclusivos da leitura. Autorizar a fonte pelo tipo **Chave**, usando a chave da API leitora; nunca a do Windows/publicador.
3. Conferir IDs e tipos dos 12 campos, `atualizado_em` Texto e SKU como dimensão numérica. Para o cartão, usar **Produtos distintos no período (SKU informado)** diretamente, sem COUNT_DISTINCT ou SUM adicional.
4. Comparar os mesmos recortes e filtros na cópia do Data Studio e no Metabase/SQL: 01–03/11/2026, 02/11/2026, 30/11/2026 vazio, mês, ano e todo o período observado. As antigas referências 216/331/R$17.675,89 e 90/134/R$4.753,02 só valem se o corte ainda corresponder; reconciliar mudanças reais.
5. Conferir receita ao centavo, unidades, produtos distintos, rankings/Top 5 e pesquisa/seleção por produto, controle de datas e todos os **nove usos** individualmente. Validar mesclagem com BI_Clientes_Vendas e Pedidos por cliente, preservando chaves e evitando multiplicar receita do pedido por quantidade de itens.
6. Reabrir e repetir os três recortes; exigir resultado correto e ausência de aviso. Confirmar também bloqueio de publicação incompleta e erro explícito de filtro/limite, sem total parcial. Não ampliar o limite para esconder um problema.
7. Só após envio homologado, plano READY, cortes compatíveis e nove usos aprovados, migrar as ligações necessárias em produção, mantendo a fonte anterior para reversão. Formatar moeda em BRL e preservar controles/cálculos/IDs dependentes.
8. **Não confirmar BI_Itens em `armazenamento ativar-data-studio` por causa desta API.** Essa confirmação pertence ao destino Sheets/continuações. A nova rota não altera o manifesto antigo.

## Reversão e entrega

Se um teste falhar, manter a fonte comercial atual, parar o publicador e voltar o destino Windows a `sheets`, preservando outbox, planos, recibos e backup. A antiga rota Sheets pode continuar bloqueada pela necessidade de continuações; não contornar. Rollback de lote é administrativo, transacional e recusa edições posteriores; seguir o código do guia e não restaurar dump sobre uma carga ativa.

Entregar relatório curto com: SHA/versões implantadas; schema/origem da visão; canais e permissões comprovados; corte inicial/final; deltas e recibos; resultado de idempotência/retomada; mês/TOTAL; nove usos e mesclagens; migração realizada ou bloqueada; rollback disponível; pendências. Identificar o que foi simulado, lido e realmente escrito. Não publicar segredos ou amostras comerciais.
