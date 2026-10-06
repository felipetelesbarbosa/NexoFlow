# NexoFlow 1.0 — Installer

Scripts de instalação e desinstalação do NexoFlow 1.0.

- `install.ps1`: instala/atualiza o NexoFlow em `C:\NexoFlow`, prepara a `.venv`, valida o payload e cria os atalhos.
- `uninstall.ps1`: remove os componentes do NexoFlow e pode preservar dados privados em `C:\NexoFlow Data`.

O Setup valida integridade por SHA-256 e não incorpora credenciais.
