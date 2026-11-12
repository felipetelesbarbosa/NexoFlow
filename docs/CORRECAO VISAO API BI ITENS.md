# Correção da visão API BI_Itens FARMA

## Causa e escopo — 12/11/2026

O Work auditou o piloto às 08h23 de Belém e informou que `farma.produtos_itens`, usada pelo Metabase, tem sete campos. A API da entrega 1.5.36 exigia doze e apontava a essa visão. O bloqueio de schema era correto; o destino configurado no leitor e a fixture de doze campos da visão legada mascaravam a incompatibilidade.

Os cinco campos ausentes (`item_chave`, `venda_chave`, `cliente_chave`, `valor_unitario`, `atualizado_em`) já existem em `farma.bi_itens`, cuja PK é `item_chave`. Não fabricar esses campos nem modificar a visão do Metabase.

## Correção

- `migration_002_read_view.sql` cria `farma.produtos_itens_datastudio` como SELECT direto dos doze campos originais da tabela. Não há casts, filtros, joins, agregações, cópia ou atualização de fatos. A PK da fonte assegura uma linha por item; tipos, precisão/escala e collation são preservados.
- `admin --migrar` valida a tabela e a PK, executando as migrações 001 e 002 na mesma transação. Um conflito reverte toda a execução, inclusive DDL inicial. Um objeto existente incompatível é recusado; não há substituição cega. Repetir a definição correta mantém OID/owner/ACL.
- A API leitora e `connectors/bi_itens_api/Code.js` apontam ao novo alvo fechado `nexoflow_datastudio_piloto.farma.produtos_itens_datastudio`. Implantar os dois lados do mesmo SHA. O alvo antigo é recusado explicitamente, sem apresentar um subconjunto como completo.
- `reader-grants.sql` concede ao login exclusivo somente SELECT na visão nova e na visão de estado. Não toca em privilégios da visão antiga ou do Metabase, nem concede acesso à tabela-base/journals.
- Permanecem as guardas de schema, origem, chaves, tipos, transação READ ONLY, publicação incompleta, limites e ausência de total parcial.
- `audit.sql` identifica as duas visões antes/depois, incluindo tipos e owner/ACL. `audit_read_view.sql` confere os doze campos por EXCEPT ALL nos dois sentidos, tipos exatos e agregados de tabela/API/Metabase por mês e TOTAL. A saída contém agregados/metadados, sem IDs individuais.

Windows continua 1.5.36, sem alteração de `app/`, do protocolo publicador, das regras comerciais ou dos dez módulos de assinatura histórica. O checkout/imagem Linux e o conector precisam receber o SHA desta correção, posterior à tag Windows. A publicação 1.5.36 e seus ZIPs permanecem intactos.

## Evidências e testes

A fixture legada agora contém os sete campos reais do formato auditado. A regressão falhou antes da mudança: a visão dedicada estava ausente e o leitor recusava a visão legada incompleta.

A suíte PostgreSQL real temporária cobre:

- Fonte legada de sete campos e destino dedicado de doze; igualdade de cada valor e chave.
- Definição, OID, owner, ACL e dados Metabase preservados após duas reaplicações.
- Login Metabase sintético lendo apenas sua visão e login API lendo a nova, sem acesso à tabela-base.
- Tipos NUMERIC com precisão/escala, VARCHAR e precisão de timestamp preservados.
- Visão conflitante com filtro, duplicação ou sete campos: bloqueio e rollback integral de DDL/fatos.
- Auditorias SQL executadas e reconciliadas; publicação WRITING/PARCIAL continua bloqueada após migração.
- Recortes, rankings, SKU repetido, valores em centavos, vazio e detalhe acima de limite; idempotência, retomada e rollback do publicador continuam cobertos.
- APIs em Docker com credenciais dedicadas e filesystem somente leitura; conector SDK/HTTP simulado em Node, inclusive rejeição do alvo legado.

Os resultados de CI e CodeQL devem ser conferidos no mesmo SHA entregue pelo Codex. Testes sintéticos não constituem nova auditoria comercial ou implantação na VPS.

## Evidência comercial recebida, sem nova leitura pelo Codex

O Work relatou unicidade das chaves e conciliação da tabela/visão legada nos meses e TOTAL, além dos recortes comerciais de um dia, três dias e período vazio. Os totais financeiros e o backup/hash permanecem na evidência privada do Work, fora do Git. Revalidar o corte atual e registrar diferenças sem forçar valores de uma referência antiga. Não inferir cobertura civil completa; `LIMITES_DA_API_NAO_HOMOLOGADOS` permanece.

Validação local desta correção: **36 testes PostgreSQL/Docker aprovados**, **90 testes Node aprovados**, Ruff, Pyright e consistência aprovados. Docker/HTTP e PostgreSQL 18.6 são reais e descartáveis; SDK e dados são sintéticos. CI e CodeQL devem ser verificados no SHA entregue ao Work, sem confundir com execução comercial.

## Retomada pelo Work

1. Confirmar o SHA/CI/CodeQL entregues e atualizar o checkout Linux para esse SHA, mantendo Windows 1.5.36. Preservar o backup validado e a configuração Compose existente.
2. Executar `audit.sql` por conexão administrativa em leitura; preservar evidência de OID/owner/ACL da visão Metabase. Windows em `sheets`; Analytics/Noturno FARMA pausados.
3. No checkout, com DSN do piloto em arquivo privado:

```bash
PYTHONPATH=app:. python -m integrations.bi_itens_publisher.admin --dsn-file /caminho/privado/admin-dsn --migrar
```

4. Criar/conferir o login exclusivo da API; aplicar `reader-grants.sql`. Executar `audit_read_view.sql` como administrador em modo leitura; a conta API não precisa ganhar acesso à tabela ou à visão Metabase para realizar auditoria.
5. Exigir zero divergências nos doze campos e nos agregados e tipos preservados; repetir a migração e comparar OID/owner/ACL/dados. Não criar READY manualmente.
6. Compilar/implantar APIs do mesmo SHA com as redes privadas/segredos definidos no [guia](BI%20ITENS%20POSTGRESQL%20FARMA.md), preservando o PostgreSQL e os outros serviços. Conferir a label `org.opencontainers.image.revision`; a identificação Windows 1.5.36 não substitui o SHA do servidor.
7. Atualizar `Code.js`, `Schema.js` e `appsscript.json` de `connectors/bi_itens_api/` no projeto privado; manter a fonte comercial atual. Validar recortes e campos na cópia do Data Studio, contra o Metabase, incluindo nove usos e mesclagens.
8. Só avançar ao envio Windows na etapa posterior aprovada. Esta correção não executa carga, não coleta API e não ativa Analytics/Noturno.

Se houver falha, parar a API leitora e preservar a nova visão/backup/evidências. Não apagar fatos, alterar a visão Metabase ou restaurar dump sobre rotina ativa. A produção Data Studio segue na fonte anterior.
