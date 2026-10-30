# Versionamento do NexoFlow

A versão atual é **1.5.7**, preservando cargas parciais do Analytics e corrigindo a conferência de campos da Recompra PET. A linha 1.5 reúne Pets Líder, pedidos recebidos diretamente da API, retroalimentação de contatos Weni e histórico observado.

As próximas publicações de atualização, hotfix ou patch seguem **1.5.8 → 1.5.9 → ... → 1.5.99 → 1.6 → 1.6.1**. Cada publicação incrementa uma única vez; commits e novas tentativas de CI da mesma entrega não mudam a numeração. Não há salto automático de versão principal.

A versão pública fica em `VERSION`. A tag é `v{versao}`, o título é `NexoFlow {versao}` e os pacotes são `NexoFlow-{versao}.zip` e `NexoFlow-Setup-{versao}.zip`. Versões anteriores permanecem no histórico do GitHub.

Os recursos Windows usam quatro componentes: **1.5.0.0** para 1.5, **1.5.1.0** para 1.5.1 e **1.6.0.0** para 1.6. O nome dos aplicativos e a pasta de instalação continuam NexoFlow.

Antes da publicação, alinhe programa, instalador, metadados, pacote Python, documentação, tag e workflow; execute os testes e confira os arquivos publicados do mesmo commit. A numeração menor não dispensa a validação.
