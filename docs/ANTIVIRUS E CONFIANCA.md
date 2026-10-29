# Antivírus e confiança — NexoFlow 1.5.1

O NexoFlow 1.5.1 foi empacotado para reduzir padrões que costumam gerar falsos positivos sem ocultar o funcionamento do software.

## Princípios de distribuição

- launchers Windows nativos e auditáveis;
- sem packer ou ofuscação;
- sem credenciais, tokens ou senhas embutidos nos executáveis;
- processos filhos iniciados por `CreateProcessW`/`os/exec`, sem `system()`;
- scripts e fontes incluídos no projeto completo para auditoria;
- payload do Setup validado por SHA-256 antes da instalação;
- suporte a assinatura Authenticode dos executáveis quando houver certificado adequado.

## Componentes

- `NexoFlow Analytics.exe`: inicia o fluxo analítico seguro;
- `NexoFlow Weni.exe`: inicia a atualização auditada da Weni;
- `NexoFlow Terminal.exe`: abre o terminal operacional;
- `NexoFlow Setup.exe`: inicia o instalador PowerShell local;
- `installer\uninstall.ps1`: realiza a desinstalação com elevação UAC quando necessária.

## Comportamento de segurança

O NexoFlow não tenta desativar ou contornar antivírus/EDR. Caso uma política corporativa bloqueie um componente, a ação correta é revisar o hash, a origem e a assinatura do arquivo e liberar o software pelos mecanismos oficiais da organização.

O Update Weni mantém revisão humana na carga completa, snapshot congelado, controle de concorrência por contato, checkpoint seguro e logs de auditoria. O Analytics mantém timeout/retry controlado para serviços externos e não amplia permissões de API além das credenciais configuradas pelo operador.

## NexoFlow 1.5.1

Toda a distribuição deve ser identificada como **NexoFlow 1.5.1**. Os executáveis Windows usam `1.5.0.0` somente no recurso VERSIONINFO, formato de quatro componentes do Windows.
<!-- NexoFlow 1.5.1 -->
