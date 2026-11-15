# Release Windows 1.5.41 conferida

Publicada em **15/11/2026, 12:53:30 (America/Fortaleza)**, SHA `abdb789c20c42f4e0c22799c47a73993f23b2d04`. [Release](https://github.com/felipetelesbarbosa/NexoFlow/releases/tag/v1.5.41), [preparação e pacotes](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/43730215188), [CodeQL](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/43730215202), [Meta](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/43730215178) e [publicação com os mesmos artefatos](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/43732329821) aprovados. Downloads públicos conferidos: SHA-256, CRC, 593 entradas do manifesto, 124 módulos e 586 arquivos do commit por pacote, executáveis x64 1.5.41.0. Sem instalador Python ou dados comerciais nos ZIPs. A 1.5.40 e anteriores preservadas. Nenhuma implantação/recuperação comercial executada.

Hashes recalculados dos downloads públicos:

- NexoFlow-Setup-1.5.41.zip: `9c7e0d664a403651f0aa193ef3e8a9a7e9607833be7e0b70077272319a79ccf7`.
- NexoFlow-1.5.41.zip: `a18272cb975e006034d9cc47be765058bfc1229107f3293cdd09c157e936d096`.

A preparação aprovou matriz Windows 3.11/3.14 em UTF-8 e codificação padrão, PostgreSQL/API descartáveis, lint, tipos, dependências, segurança, launchers, executáveis, Setup Preserve/Clean, rollback e pacote instalado. A publicação reutilizou os mesmos artefatos sem build. O transporte local bloqueou o artefato intermediário; o validador oficial conferiu seus bytes antes de publicar. Os downloads públicos foram conferidos independentemente após a publicação.

O Setup tem oito executáveis x64 (incluindo Setup), o projeto sete. Todos foram inspecionados como PE x64 com versão 1.5.41.0. Os 124 módulos Python e 586 arquivos versionados em cada payload correspondem ao commit, tolerando apenas CRLF. Manifesto do Setup com 593 entradas teve tamanho/hash conferidos. Verificadas guardas contra itens defasados, recuperação dry-run e ausência de SQLite/secrets_config.py reais e instalador Python nos ZIPs. Módulos históricos assinados passaram na verificação do workflow.

Instalar em Preserve; confirmar `nexo versao` = `NexoFlow 1.5.41`. A instalação não implanta serviços ou conector. Recuperação dos 204 pedidos continua exclusivamente em simulação, pelo [roteiro do Work](CORTE%20BI%20ITENS%20DEFASADOS%20E%20RECUPERACAO.md). Nenhum fato, manifesto, assinatura, hash ou recibo comercial foi alterado. A revisão READY v1 e DS_ABC_BASE_INCOMPLETA permanecem protegidos. Compras juntas anual continua uma pendência comercial separada; a release inclui o escopo Top explícito já testado no código.
