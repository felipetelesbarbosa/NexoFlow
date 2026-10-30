# Assinatura de executáveis Windows — NexoFlow 1.5.4

## Por que o Windows pode mostrar aviso

SmartScreen e UAC avaliam assinatura digital, reputação do arquivo/editor e origem do download. Um executável novo pode ser legítimo e ainda aparecer como **Editor desconhecido** quando não possui assinatura Authenticode confiável.

Não é recomendado desativar SmartScreen, UAC ou outras proteções para contornar o aviso.

## Forma recomendada

Assine os executáveis do NexoFlow 1.5.4 com um certificado de assinatura de código:

- certificado OV/EV de uma autoridade certificadora confiável; ou
- certificado corporativo cuja cadeia seja distribuída como confiável nas máquinas da organização por TI/GPO/Intune.

Arquivos que devem ser assinados:

```text
NexoFlow Setup.exe
NexoFlow Analytics.exe
NexoFlow Weni.exe
NexoFlow Planilha.exe
NexoFlow Recompra.exe
NexoFlow Terminal.exe
NexoFlow Uninstall.exe (quando distribuído)
installer/install.ps1
installer/uninstall.ps1
```

Os executáveis e scripts PowerShell podem receber assinatura Authenticode. Use SHA-256 e timestamp confiável para manter a assinatura verificável após o vencimento do certificado.

## Procedimento de assinatura

O pacote do NexoFlow 1.5.4 contém `Assinar Release.ps1`, que apenas informa que a assinatura Authenticode não é automatizada. Ele não procura certificados, assina arquivos nem recalcula hashes. A distribuição atual não recebe assinatura automaticamente.

Quando houver certificado corporativo confiável, a equipe responsável deve:

1. assinar os executáveis e scripts PowerShell do payload e do projeto completo;
2. validar o status Authenticode dos arquivos assinados;
3. recalcular `payload manifest.json` depois de assinar os arquivos do payload;
4. assinar `NexoFlow Setup.exe` e os scripts externos do Setup;
5. recalcular `checksums SHA256.txt`, gerar os dois ZIPs e atualizar `SHA256SUMS-1.5.4.txt`.

Nenhuma chave privada ou certificado é incluído no projeto.

## Estado do NexoFlow 1.5.4

- executáveis PE32+ x64 nativos;
- VERSIONINFO configurado como 1.5.0.0, representação de quatro componentes usada pelo Windows;
- sem packers ou ofuscação;
- sem tokens ou senhas embutidos;
- launchers sem `system()`;
- integridade SHA-256 do payload do instalador;
- hashes SHA-256 externos publicados junto ao NexoFlow 1.5.4;
- `ExecutionPolicy Bypass` restrito ao entrypoint local do Setup quando o script ainda não estiver assinado.

Essas medidas melhoram transparência e integridade, mas não substituem uma assinatura Authenticode confiável para reputação do Windows.

Consulte também `ANTIVIRUS E CONFIANCA.md`.
<!-- NexoFlow 1.5.4 -->
