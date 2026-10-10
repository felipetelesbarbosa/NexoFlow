# NexoFlow 1.0 — Scripts

Scripts usados para empacotamento e validação do NexoFlow 1.0.

- `build_release.ps1`: monta o projeto completo, o Setup, checksums e notas da distribuição NexoFlow 1.0.
- `embed_windows_icon.ps1`: incorpora o ícone correspondente em cada executável Windows.
- `test_executable_icons.ps1`: valida os ícones incorporados nos executáveis dos pacotes.
- `test_setup_windows.ps1`: executa smoke tests do Setup em Windows.
- `test_recompra_launcher_windows.ps1`: valida o executável dedicado de recompra e a propagação do código de saída no Windows.

A publicação da [release v1.0](https://github.com/felipetelesbarbosa/NexoFlow/releases/tag/v1.0) segue o [workflow de publicação](../.github/workflows/release-v1.yml) e só prossegue após testes, auditoria do projeto, validação dos ícones e smoke tests do Setup.

Os nomes e links estáveis dos pacotes estão em [Downloads](../releases/README.md).
