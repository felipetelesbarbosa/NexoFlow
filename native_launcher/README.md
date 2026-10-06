# NexoFlow 1.0 — Launchers nativos

Fontes dos launchers Windows distribuídos no NexoFlow 1.0.

Cada executável é compilado separadamente por tag (`analytics`, `updateweni`, `terminal`, `setup` ou `uninstall`), evitando que um componente carregue código de outro.

Objetivos:

- não usar `system()`;
- iniciar processos filhos por `CreateProcessW` através de `os/exec`;
- resolver caminhos a partir da própria pasta de instalação;
- usar `System32` para `cmd.exe`/PowerShell quando necessários;
- manter `Local\NexoFlowOperationLock` para Analytics, NexoFlow Weni e Setup;
- manter o NexoFlow Terminal independente da trava operacional;
- não embutir tokens, senhas ou credenciais;
- manter código-fonte auditável, sem packer ou ofuscação.

O `NexoFlow Terminal.exe` inicia diretamente `run_terminal.py` com o Python da `.venv` quando disponível e utiliza `assets/NexoFlow_Terminal.ico`.

O Setup usa `ExecutionPolicy Bypass` somente para iniciar o script PowerShell local quando ele não estiver assinado com Authenticode. Analytics e NexoFlow Weni não contêm essa lógica.


O `NexoFlow Uninstall.exe` é um launcher nativo **opcional** para `installer\uninstall.ps1`. Ele é distribuído por conveniência, mas não é requisito do Setup nem do check-up: se um antivírus/EDR corporativo removê-lo, a instalação e a desinstalação continuam disponíveis por **Aplicativos instalados**, `desinstalar_nexoflow.cmd` e `installer\uninstall.ps1`.
