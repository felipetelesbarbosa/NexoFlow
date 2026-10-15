# NexoFlow 1.0 — Instalador

Scripts de instalação e desinstalação do NexoFlow 1.0.

- `install.ps1`: instala/atualiza o NexoFlow em `C:\NexoFlow`, prepara a `.venv`, valida o payload e cria os atalhos.
- `uninstall.ps1`: remove os componentes do NexoFlow e sempre preserva `importacoes` e seus arquivos em `C:\NexoFlow Data\importacoes`. A preservação de configurações, credenciais e logs continua opcional.

Setup e projeto completo incluem `importacoes` vazia, sem XLSX exportados. O instalador cria a pasta em `C:\NexoFlow\importacoes` e restaura seus arquivos na reinstalação. Backups conflitantes são mantidos em `historico_preservado`; falha na cópia ou na validação SHA-256 das importações impede a remoção da instalação.

O Setup valida integridade por SHA-256 e não incorpora credenciais.

Use o [Setup da release v1.0](https://github.com/felipetelesbarbosa/NexoFlow/releases/download/v1.0/NexoFlow-Setup-1.0.zip). Os demais pacotes e hashes estão em [Downloads](../releases/README.md).

Após instalar, atualizar ou reinstalar, execute `comandos/check-up.bat` e `comandos/testar_conexoes.bat`. Revalide os contatos com `comandos/atualizar_weni_carga_completa.bat`: revise o relatório do dry-run e confirme `CARGA COMPLETA REVISADA` antes da aplicação. Depois execute uma vez `comandos/executar_carga_completa.bat` para atualizar os dados analíticos sob as regras atuais e retome o incremental.

Consulte [Instalação](../docs/README%20INSTALACAO.md) e [NexoFlow Weni](../docs/README%20WENI.md) para os requisitos e o fluxo completo de revisão.
