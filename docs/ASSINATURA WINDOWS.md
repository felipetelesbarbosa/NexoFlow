# Assinatura Windows e confiança

O build suporta assinatura Authenticode dos executáveis e scripts PowerShell. Isso identifica o editor e detecta alterações, mas não garante aprovação do SmartScreen ou de qualquer antivírus.

## Certificado adequado

Use um certificado **Code Signing** OV/EV de autoridade confiável ou um certificado corporativo cuja cadeia seja administrada pela TI. O nome do editor deve corresponder à pessoa jurídica responsável. Certificados SelfCert do Office ou autoassinados servem para testes locais, sem criar confiança pública. Não são certificados de site HTTPS.

Instale e administre a chave por mecanismos do fornecedor/Windows, preferencialmente hardware ou serviço protegido. Nunca envie PFX, chave privada ou senha por chat, Git ou artefatos públicos. O NexoFlow não importa chaves nem instala certificados em autoridades confiáveis.

## Build assinado

Em um Windows autorizado, com o certificado e a chave já acessíveis no repositório pessoal de certificados:

```powershell
.\scripts\build_release.ps1 -Version '1.5.10' -CertificateThumbprint '{IMPRESSAO_DIGITAL_DO_CERTIFICADO}' -RequireSignature
```

O build valida validade, chave e uso de assinatura de código. Incorpora versão/ícones antes de assinar, usa SHA-256 e timestamp HTTPS, verifica `Valid`, editor esperado e timestamp, e só então gera manifesto, checksums e ZIPs. Falha na assinatura interrompe o build. O instalador oficial do Python mantém a assinatura original.

Sem certificado configurado, o build avisa e produz arquivos **não assinados**, com esse estado registrado em `ASSINATURA.txt` e `RELATORIO DE SEGURANCA.json` no ZIP do Setup. Não existe um editor verificado implícito. O script antigo `Assinar Release.ps1`, que apenas exibia instruções, foi substituído por esse processo de build.

Não assine nem modifique os arquivos depois de publicados: isso altera hashes, invalida a integridade do pacote e exige reconstrução e nova versão. No CI público, não há certificado ou chave privada provisionados automaticamente.

## Conferência pelo operador

```powershell
Get-AuthenticodeSignature -LiteralPath 'C:\NexoFlow\NexoFlow Noturno.exe' |
    Format-List Status,StatusMessage,SignerCertificate,TimeStamperCertificate
Get-FileHash -Algorithm SHA256 -LiteralPath 'C:\NexoFlow\NexoFlow Noturno.exe'
```

Uma assinatura `Valid` e um hash conferido não substituem a análise do software. Para um certificado corporativo, outro computador pode não confiar na cadeia até a distribuição oficial pela TI.
