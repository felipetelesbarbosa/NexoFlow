# Versionamento do NexoFlow

A distribuição atual é **1.5.27**, publicada em 08/11/2026. Seus pacotes, tag e os anteriores permanecem preservados. Correções posteriores na main usam `[skip release]` e não estão nos ZIPs públicos. A comparação de autoridades do Drive aguarda o diagnóstico real e a validação antes de outra distribuição. Não reempacotar a 1.5.27; a próxima distribuição corretiva usa 1.5.28 após autorização e checks.

As próximas publicações de atualização, hotfix ou patch seguem **1.5.28 → 1.5.29 → ... → 1.5.99 → 1.6 → 1.6.1**. Cada publicação incrementa uma única vez; commits e novas tentativas de CI da mesma entrega não mudam a numeração. Não há salto automático de versão principal.

A versão da distribuição fica em `VERSION`. A tag é `v{versao}`, o título é `NexoFlow {versao}` e os pacotes são `NexoFlow-{versao}.zip` e `NexoFlow-Setup-{versao}.zip`. Nunca sobrescreva os arquivos de uma versão pública para entregar código novo. O workflow permite retomar somente um rascunho da mesma entrega.

Cada release informa a data real de publicação em **America/Fortaleza**. Enquanto a entrega estiver em validação, use esse estado no changelog. O workflow obtém `publishedAt` do GitHub após publicar e registra a data correspondente nas notas; não reutiliza a data de uma autorização ou de um teste. O calendário operacional das cargas continua em `America/Belem`.

Os recursos Windows usam quatro componentes: **1.5.0.0** para 1.5, **1.5.27.0** para 1.5.27 e **1.6.0.0** para 1.6. O nome dos aplicativos e a pasta de instalação continuam NexoFlow. Os EXEs preservados em `native_launcher/prebuilt/` têm sua própria versão de referência documentada; os executáveis instalados na raiz devem coincidir com a distribuição atual.

Antes da publicação, alinhe programa, instalador, metadados, pacote Python, documentação, tag e workflow; execute os testes e confira os arquivos publicados do mesmo commit. A numeração menor não dispensa a validação.

## Validação contínua e publicação manual

O workflow separa a concorrência por referência Git e evento. A publicação manual (`workflow_dispatch`) não cancela os testes automáticos do `push`. Novos pushes ainda substituem validações antigas da mesma referência; publicações manuais aguardam uma publicação anterior terminar. As guardas do commit atual da `main`, da tag e dos arquivos já publicados continuam obrigatórias.

Commits com `[skip release]` executam qualidade, testes e análise de segredos, sem empacotar ou publicar. Uma correção apenas de CI não exige incrementar a versão Windows nem substituir os pacotes existentes.

No GitHub, `cancelled` indica execução interrompida e não comprova falha de teste. Confira o workflow, a tentativa e o SHA. Falhas reais permanecem no histórico do commit original; a correção é validada em um novo commit, sem reescrever commits ou remover evidências.
