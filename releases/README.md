# NexoFlow 1.5.35 — Downloads

Publicada em 11/11/2026, 21:23:49 (America/Fortaleza), no SHA `c6204f0535914c48fec71ce5c009f0e8f9a1884a`. Checks, pacotes e downloads públicos conferidos. A 1.5.34 e anteriores permanecem intactas. A validação comercial da BI_Itens no Data Studio continua pendente.

A [release v1.5.35](https://github.com/felipetelesbarbosa/NexoFlow/releases/tag/v1.5.35) reúne os pacotes oficiais:

| Arquivo | Uso |
| --- | --- |
| [NexoFlow-Setup-1.5.35.zip](https://github.com/felipetelesbarbosa/NexoFlow/releases/download/v1.5.35/NexoFlow-Setup-1.5.35.zip) | Instalador para Windows; recomendado para usar o NexoFlow. |
| [NexoFlow-1.5.35.zip](https://github.com/felipetelesbarbosa/NexoFlow/releases/download/v1.5.35/NexoFlow-1.5.35.zip) | Projeto completo. |
| [SHA256SUMS-1.5.35.txt](https://github.com/felipetelesbarbosa/NexoFlow/releases/download/v1.5.35/SHA256SUMS-1.5.35.txt) | Hashes para conferir os dois pacotes baixados. |

Extraia todo o ZIP do Setup antes de executar **NexoFlow Setup.exe**. Os pacotes não incluem credenciais; configure seus próprios acessos.

[Instalação](../docs/README%20INSTALACAO.md) · [Guia de operação](../docs/Documentacao%20NexoFlow.md) · [Histórico de mudanças](../CHANGELOG.md)

## Evidências da publicação 1.5.35

- Commit distribuído: `c6204f0535914c48fec71ce5c009f0e8f9a1884a`.
- [Preparação e matriz Windows aprovadas](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/43124192209): Python 3.11/3.14 nas duas codificações, executáveis, Setup Preserve/Clean/rollback, qualidade, dependências e segredos.
- [CodeQL aprovado](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/43124194597) e [Meta/MCP aprovado](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/43124192267), no mesmo SHA.
- [Publicação aprovada](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/43126883069), reutilizando os pacotes da preparação.
- Conferência independente dos downloads públicos: SHA-256, CRC, 494 entradas do manifesto do Setup, 105 módulos Python e 487 arquivos correspondentes ao commit em cada ZIP, com normalização de CRLF nos textos. Sete aplicativos x64, mais o launcher do Setup, com versão 1.5.35.0.
- Regressão local da correção: 2.009 testes Python aprovados, 95 ignorados; 78 testes Node aprovados. Testes locais e Windows não representam execução comercial.

SHA-256 recalculados dos downloads públicos:

```text
c069e892b95bd406e6fa66e021e9f06f4c865eb762ed80f4d062fa363739c5cd  NexoFlow-Setup-1.5.35.zip
ed7165d11179c36fb1a0db1b161f2816b7d63bc425e56011f66d20609e95ab63  NexoFlow-1.5.35.zip
```

Nenhum dado comercial, manifesto remoto ou implantação do Data Studio foi alterado durante a validação e publicação.
