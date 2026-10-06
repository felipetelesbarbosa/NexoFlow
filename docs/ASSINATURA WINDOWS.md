# Assinatura de executáveis Windows — NexoFlow 1.0

## Por que o Windows pode mostrar aviso

SmartScreen e UAC avaliam assinatura digital, reputação do arquivo/editor e origem do download. Um executável novo pode ser legítimo e ainda aparecer como **Editor desconhecido** quando não possui assinatura Authenticode confiável.

Não é recomendado desativar SmartScreen, UAC ou outras proteções para contornar o aviso.

## Forma recomendada

Assine os executáveis do NexoFlow 1.0 com um certificado de assinatura de código:

- certificado OV/EV de uma autoridade certificadora confiável; ou
- certificado corporativo cuja cadeia seja distribuída como confiável nas máquinas da organização por TI/GPO/Intune.

Arquivos que devem ser assinados:

```text
NexoFlow Setup.exe
NexoFlow Analytics.exe
NexoFlow Weni.exe
NexoFlow Terminal.exe
installer/install.ps1
installer/uninstall.ps1
```

Os executáveis e scripts PowerShell podem receber assinatura Authenticode. Use SHA-256 e timestamp confiável para manter a assinatura verificável após o vencimento do certificado.

## Script preparado

O pacote do NexoFlow 1.0 contém `Assinar Release.ps1`. O script:

1. localiza o certificado pelo thumbprint;
2. assina os executáveis do payload;
3. assina os scripts PowerShell;
4. recalcula o manifesto SHA-256 do payload;
5. assina `NexoFlow Setup.exe` por último;
6. valida o status Authenticode dos arquivos assinados.

Nenhuma chave privada ou certificado é incluído no projeto.

## Estado do NexoFlow 1.0

- executáveis PE32+ x64 nativos;
- VERSIONINFO configurado como 1.0.0.0, representação de quatro componentes usada pelo Windows;
- sem packers ou ofuscação;
- sem tokens ou senhas embutidos;
- launchers sem `system()`;
- integridade SHA-256 do payload do instalador;
- hashes SHA-256 externos publicados junto ao NexoFlow 1.0;
- `ExecutionPolicy Bypass` restrito ao entrypoint local do Setup quando o script ainda não estiver assinado.

Essas medidas melhoram transparência e integridade, mas não substituem uma assinatura Authenticode confiável para reputação do Windows.

Consulte também `ANTIVIRUS E CONFIANCA.md`.
