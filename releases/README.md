# NexoFlow 1.0

Distribuição oficial do **NexoFlow 1.0**.

A versão do produto permanece **1.0**.

## Downloads

Use a página oficial do **NexoFlow 1.0**:

- **NexoFlow-Setup-1.0.zip** — Setup validado;
- **NexoFlow-1.0.zip** — projeto completo correspondente ao mesmo código;
- **SHA256SUMS-1.0.txt** — hashes SHA-256 dos dois pacotes.

NexoFlow 1.0:
https://github.com/felipetelesbarbosa/NexoFlow/releases/tag/v1.0

## Estabilidade do Setup

O Setup 1.0 é validado automaticamente em Windows antes da publicação. A validação cobre:

- primeira instalação;
- atualização sobre uma instalação existente;
- preservação de `secrets_config.py`, `credentials` e `logs`;
- execução do `check-up.bat` após a instalação;
- cenário em que antivírus/EDR remove `NexoFlow Uninstall.exe` do pacote extraído.

O `NexoFlow Uninstall.exe` é opcional. Se for bloqueado ou removido, o Setup continua funcionando e a desinstalação permanece disponível por `installer\uninstall.ps1` e `desinstalar_nexoflow.cmd`.

Atualizações preservam temporariamente a instalação anterior. Se a nova instalação falhar depois de iniciada, o Setup tenta restaurar automaticamente a versão anterior, evitando deixar o NexoFlow parcialmente atualizado.

O Setup também solicita elevação UAC automaticamente quando necessário.

Os pacotes são gerados automaticamente a partir da `main` somente depois de testes, auditoria e smoke test do instalador. Credenciais reais não entram nos artefatos.
