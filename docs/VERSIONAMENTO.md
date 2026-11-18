# Versionamento do NexoFlow

## Preparação 1.5.43

A prévia de homologação 7b3d4bc não gerou tag pública. A primeira release estável 1.5.43 distribui o coletor corrigido do Flows v2. Quem instalou a prévia deve instalar o Setup público em Preserve. [Procedimento e controle do recorte](CONVERSAS%20DIARIAS%20WENI.md).

## Publicação 1.5.42

Publicada em **17/11/2026, 20:52:15 (America/Fortaleza)**, no [commit `f4a9ecf78bdff2158a7f2e9451248bc784c54879`](https://github.com/felipetelesbarbosa/NexoFlow/commit/f4a9ecf78bdff2158a7f2e9451248bc784c54879). [Release](https://github.com/felipetelesbarbosa/NexoFlow/releases/tag/v1.5.42) · [CI e pacotes](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/44199455757) · [CodeQL](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/44199455758) · [Meta nativo](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/44199455745) · [Publicação](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/44203002028).

A conferência dos downloads públicos validou o CRC dos dois ZIPs, 589 entradas do manifesto do Setup, 125 módulos Python por pacote e a versão x64 1.5.42.0 dos executáveis. Os arquivos publicados são idênticos aos da preparação aprovada.

- NexoFlow-Setup-1.5.42.zip · SHA-256 `7be5519f0880f60f6d2f5b02e332d091637a9e0a29c9d36849d76aaa8b593f74`
- NexoFlow-1.5.42.zip · SHA-256 `99e10b2014c7c94386a82ade06a1ac6036190a8e86b63770dbad0d19664bd2c2`

## Publicação 1.5.41

Publicada em **15/11/2026, 12:53:30 (America/Fortaleza)**, SHA `abdb789c20c42f4e0c22799c47a73993f23b2d04`. [Release](https://github.com/felipetelesbarbosa/NexoFlow/releases/tag/v1.5.41), [preparação e pacotes](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/43730215188), [CodeQL](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/43730215202), [Meta](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/43730215178) e [publicação com os mesmos artefatos](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/43732329821) aprovados. Downloads públicos conferidos: SHA-256, CRC, 593 entradas do manifesto, 124 módulos e 586 arquivos do commit por pacote, executáveis x64 1.5.41.0. Sem instalador Python ou dados comerciais nos ZIPs. A 1.5.40 e anteriores preservadas. Nenhuma implantação/recuperação comercial executada.


## Preparação 1.5.41

Publicação autorizada em 15/11/2026. Uma geração no SHA final, checks e pacotes conferidos antes de publicar os mesmos artefatos. Preservar 1.5.40 e anteriores. Nenhuma recuperação de dados ou implantação comercial nesta entrega.

A **1.5.40 foi publicada em 13/11/2026, 00:41:51 (America/Fortaleza)**, no SHA `c5da21c05c9a8c220bb55538b74957e8052e8624`. [Release e pacotes conferidos](https://github.com/felipetelesbarbosa/NexoFlow/releases/tag/v1.5.40). Sem instalador Python nos ZIPs; versões anteriores preservadas.

A **1.5.39 foi publicada em 12/11/2026, 23:42:16 (America/Fortaleza)**, no SHA `25f287dbc21a51e3702eeb04fda27469cbe2a27a`. [Release e downloads conferidos](https://github.com/felipetelesbarbosa/NexoFlow/releases/tag/v1.5.39). Versões anteriores preservadas.

A **1.5.38 foi publicada em 12/11/2026, 22:39:37 (America/Fortaleza)**, no SHA `ace7c8f12361fe2bc0256323cb59f3b56b55cd0d`. [Release e pacotes conferidos](https://github.com/felipetelesbarbosa/NexoFlow/releases/tag/v1.5.38). A 1.5.37 e anteriores permanecem intactas.

A **1.5.31 foi publicada em 10/11/2026 às 17:07:39 (America/Fortaleza)**, no SHA `a31237c088e4b699f166086d01abfbb7da0b9a18`. A 1.5.30 e as anteriores permanecem intactas. Ver [release e evidências](https://github.com/felipetelesbarbosa/NexoFlow/releases/tag/v1.5.31). A consolidação documental posterior não altera essa tag, seus pacotes ou VERSION. Novas publicações exigem checks e pacotes instalados validados no mesmo commit.

A **1.5.32 foi publicada em 10/11/2026, 19:16:49 (America/Fortaleza)**, no SHA `9d4be5d911a817a09773fc843f7674a6480e0b71`, com agrupamento de intervalos do histórico. [Release e evidências](https://github.com/felipetelesbarbosa/NexoFlow/releases/tag/v1.5.32). A 1.5.31 permanece intacta.

A **1.5.33 foi publicada em 10/11/2026, 23:28:34 (America/Fortaleza)**, no SHA `7884d7007fd0c65cbf90bfc30c5c35dc6c9056fb`, com recuperação da leitura da trava Sheets. [Release e pacotes conferidos](https://github.com/felipetelesbarbosa/NexoFlow/releases/tag/v1.5.33).

As próximas publicações de atualização, hotfix ou patch seguem **1.5.43 → ... → 1.5.99 → 1.6 → 1.6.1**. Cada publicação incrementa uma única vez; commits e novas tentativas de CI da mesma entrega não mudam a numeração. Não há salto automático de versão principal.

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
