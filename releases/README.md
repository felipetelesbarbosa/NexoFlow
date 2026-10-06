# NexoFlow 1.0

Distribuição oficial do NexoFlow 1.0.

- [Baixar Setup instalável](https://github.com/felipetelesbarbosa/NexoFlow/raw/refs/tags/v1.0/releases/NexoFlow-Setup-1.0.zip)
- [Baixar projeto completo](https://github.com/felipetelesbarbosa/NexoFlow/raw/refs/tags/v1.0/releases/NexoFlow-1.0.zip)
- [Conferir SHA-256](SHA256SUMS.txt)

Extraia **todo** o ZIP do Setup e execute `NexoFlow Setup.exe` dentro da pasta `NexoFlow Setup`, mantendo `payload`, `installer` e `prerequisites` juntos. O pacote inclui o instalador Python 3.14.8 x64. Os executáveis Windows identificam o produto como NexoFlow 1.0; VERSIONINFO usa a representação técnica 1.0.0.0.

As credenciais devem ser configuradas somente na instalação local; não há credenciais reais no pacote. Consulte o [changelog](../CHANGELOG.md) e a [documentação de instalação](../README%20INSTALACAO.md).

Os ZIPs mantêm integralmente os arquivos recebidos. Os 108 itens do manifesto do Setup e os 115 checksums globais foram validados. Os arquivos e as strings dos executáveis passaram pela varredura por segredos. A instalação e a desinstalação no Windows ainda precisam ser validadas nesse sistema.

Os downloads ficam no repositório e são vinculados na Release porque a API de anexos recusou a transferência com `Bad Content-Length`, inclusive para o arquivo de checksum. A visibilidade do repositório foi preservada; para baixar, use uma conta com acesso.
