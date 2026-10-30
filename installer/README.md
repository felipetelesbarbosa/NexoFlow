# Instalador do NexoFlow 1.5.4

Scripts de instalação, atualização e desinstalação para Windows.

Para instalar ou atualizar, use o [Setup oficial](../releases/README.md) e siga o [guia de instalação](../docs/README%20INSTALACAO.md).

- `install.ps1`: instala em `C:\NexoFlow`, configura o ambiente e cria os atalhos. Atualizações preservam configurações, credenciais, logs e importações.
- `uninstall.ps1`: remove o programa e os atalhos; preserva as importações em `C:\NexoFlow Data\importacoes` e oferece preservar as demais configurações e os logs.

O **NexoFlow Uninstall.exe** é opcional. A desinstalação também está disponível pelo Windows e por `desinstalar_nexoflow.cmd`.
