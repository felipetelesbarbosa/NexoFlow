# Versionamento do NexoFlow

A **1.5.38 foi publicada em 12/11/2026, 22:39:37 (America/Fortaleza)**, no SHA `ace7c8f12361fe2bc0256323cb59f3b56b55cd0d`. [Release e pacotes conferidos](https://github.com/felipetelesbarbosa/NexoFlow/releases/tag/v1.5.38). A 1.5.37 e anteriores permanecem intactas.

A **1.5.31 foi publicada em 10/11/2026 às 17:07:39 (America/Fortaleza)**, no SHA `a31237c088e4b699f166086d01abfbb7da0b9a18`. A 1.5.30 e as anteriores permanecem intactas. Ver [release e evidências](https://github.com/felipetelesbarbosa/NexoFlow/releases/tag/v1.5.31). A consolidação documental posterior não altera essa tag, seus pacotes ou VERSION. Novas publicações exigem checks e pacotes instalados validados no mesmo commit.

A **1.5.32 foi publicada em 10/11/2026, 19:16:49 (America/Fortaleza)**, no SHA `9d4be5d911a817a09773fc843f7674a6480e0b71`, com agrupamento de intervalos do histórico. [Release e evidências](https://github.com/felipetelesbarbosa/NexoFlow/releases/tag/v1.5.32). A 1.5.31 permanece intacta.

A **1.5.33 foi publicada em 10/11/2026, 23:28:34 (America/Fortaleza)**, no SHA `7884d7007fd0c65cbf90bfc30c5c35dc6c9056fb`, com recuperação da leitura da trava Sheets. [Release e pacotes conferidos](https://github.com/felipetelesbarbosa/NexoFlow/releases/tag/v1.5.33).

As próximas publicações de atualização, hotfix ou patch seguem **1.5.39 → ... → 1.5.99 → 1.6 → 1.6.1**. Cada publicação incrementa uma única vez; commits e novas tentativas de CI da mesma entrega não mudam a numeração. Não há salto automático de versão principal.

A versão da distribuição fica em `VERSION`. A tag é `v{versao}`, o título é `NexoFlow {versao}` e os pacotes são `NexoFlow-{versao}.zip` e `NexoFlow-Setup-{versao}.zip`. Nunca sobrescreva os arquivos de uma versão pública para entregar código novo. O workflow permite retomar somente um rascunho da mesma entrega.

Cada release informa a data real de publicação em **America/Fortaleza**. Enquanto a entrega estiver em validação, use esse estado no changelog. O workflow obtém `publishedAt` do GitHub após publicar e registra a data correspondente nas notas; não reutiliza a data de uma autorização ou de um teste. O calendário operacional das cargas continua em `America/Belem`.

Os recursos Windows usam quatro componentes: **1.5.0.0** para 1.5, **1.5.30.0** para 1.5.30 e **1.6.0.0** para 1.6. O nome dos aplicativos e a pasta de instalação continuam NexoFlow. Os EXEs preservados em `native_launcher/prebuilt/` têm sua própria versão de referência documentada; os executáveis instalados na raiz devem coincidir com a distribuição atual.

Antes da publicação, alinhe programa, instalador, metadados, pacote Python, documentação, tag e workflow; execute os testes e confira os arquivos publicados do mesmo commit. A numeração menor não dispensa a validação.

## Validação contínua e publicação manual

O workflow separa a concorrência por referência Git e evento. A publicação manual (`workflow_dispatch`) não cancela os testes automáticos do `push`. Novos pushes ainda substituem validações antigas da mesma referência; publicações manuais aguardam uma publicação anterior terminar. As guardas do commit atual da `main`, da tag e dos arquivos já publicados continuam obrigatórias.

Commits com `[skip release]` executam qualidade, testes e análise de segredos, sem publicar. Sem o marcador adicional `[preparar pacotes]`, também não empacotam. Uma correção apenas de CI não exige incrementar a versão Windows nem substituir os pacotes existentes.

No GitHub, `cancelled` indica execução interrompida e não comprova falha de teste. Confira o workflow, a tentativa e o SHA. Falhas reais permanecem no histórico do commit original; a correção é validada em um novo commit, sem reescrever commits ou remover evidências.

## Reutilização segura de pacotes aprovados

O commit final pode usar `[skip release] [preparar pacotes]` para gerar os pacotes na mesma execução do CI, sem publicar. Depois, `workflow_dispatch` com `publish_release=true` e `validated_run_id` publica os mesmos ZIPs, sem repetir build ou suíte completa. SHA, origem e checks completos, CodeQL/Meta e integridade dos artefatos permanecem exigidos. A matriz Windows mantém suas quatro combinações; o build conserva suas verificações específicas. Não atualizar a main entre gerar e publicar. Ver [comandos e critérios](RELEASE%20EFICIENTE.md). Este mecanismo é posterior à publicação 1.5.33; os pacotes daquela versão permanecem intactos.

## Preparação 1.5.34

Publicação autorizada em 11/11/2026 para corrigir confirmação incerta da trava Sheets. Manter uma única geração de pacotes no SHA final e publicar somente após checks aprovados. 1.5.33 e anteriores preservadas.

## Publicação 1.5.34

Publicada em 11/11/2026, 19:12:49 (America/Fortaleza), no SHA `a25ae828b6dc732ecfcafa60db145e8cf27c84f5`, com reutilização dos pacotes da execução 43106347604 pela publicação 43109707841. Tag, downloads públicos, hashes, CRC, manifesto e módulos conferidos; releases anteriores preservadas.

## Preparação 1.5.35

Publicação autorizada para distribuir a prévia de expansão BI e o tratamento de fonte não confirmada. Manter uma única geração no SHA final, preservando a tag e os pacotes 1.5.34. A migração comercial da BI_Itens não é autorizada nem realizada pela publicação desta versão.

## Publicação 1.5.35

Publicada em 11/11/2026, 21:23:49 (America/Fortaleza), no SHA `c6204f0535914c48fec71ce5c009f0e8f9a1884a`. Checks, pacotes e downloads públicos conferidos. A 1.5.34 e anteriores permanecem intactas. A validação comercial da BI_Itens no Data Studio continua pendente.

Preparação aprovada: https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/43124192209. Os mesmos artefatos foram usados na publicação oficial, sem novo build.

## Preparação 1.5.36

Publicação autorizada para o destino PostgreSQL BI_Itens FARMA e leitura privada Data Studio. Uma única geração no SHA final, incluindo o novo job PostgreSQL/Docker obrigatório; reutilizar os mesmos pacotes aprovados. A 1.5.35 e anteriores permanecem intactas. Implantação na VPS e homologação comercial são etapas do Work, distintas da release Windows.


A **1.5.36 foi publicada em 12/11/2026, 03:06:30 (America/Fortaleza)**, SHA `2cc09b864efedbb0ca2d2dc10c62c6bc23091e61`. [release](https://github.com/felipetelesbarbosa/NexoFlow/releases/tag/v1.5.36), [preparação](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/43163283247), [CodeQL](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/43163283110) e [Meta](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/43163597855). Pacotes, hashes e downloads conferidos; a 1.5.35 permanece intacta. Esta publicação não implanta nem homologa a integração comercial PostgreSQL/Data Studio.

## Preparação 1.5.37

Backend definitivo PostgreSQL opt-in, separado do piloto. Manter uma única geração de pacotes no SHA final, publicação somente após checks completos e conferência independente. Implantação e migração comercial pelo Work.

## Publicação 1.5.37

Publicada em **12/11/2026, 19:18:38 (America/Fortaleza)**, SHA `2683717431b1c4313efaaaef35cfaaf20236958a`. [Release](https://github.com/felipetelesbarbosa/NexoFlow/releases/tag/v1.5.37), [CI e pacotes](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/43314024652), [CodeQL](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/43314024795), [Meta](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/43314026009) e [publicação reutilizando os artefatos](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/43318519275). Downloads públicos conferidos: hashes, CRC, 571 entradas do manifesto, 123 módulos e versões dos executáveis. Sem implantação ou migração comercial.
