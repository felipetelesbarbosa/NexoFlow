# Processo de mudanças — NexoFlow 1.0

Este documento define como alterações devem ser feitas e validadas no NexoFlow 1.0. Ele documenta o processo atual do **NexoFlow 1.0**; o histórico público fica concentrado em `CHANGELOG.md`.

## Princípios

1. preservar compatibilidade das rotinas operacionais;
2. manter credenciais fora do repositório/pacote;
3. atualizar testes junto com qualquer mudança de comportamento;
4. executar `check-up.bat` e `auditar_consistencia.py` antes de empacotar;
5. regenerar `payload manifest.json` e `checksums SHA256.txt` após qualquer alteração;
6. não alterar snapshot/checkpoint do Update Weni sem testes específicos de concorrência e rollback;
7. não alterar schemas do Analytics/BI sem migração compatível e validação do Looker Studio.

## Fluxo recomendado

- editar o projeto completo;
- executar testes unitários;
- executar auditoria de consistência;
- validar sintaxe e arquivos BAT/PowerShell;
- validar launchers e VERSIONINFO;
- sincronizar o payload do Setup;
- regenerar manifest e checksums;
- testar integridade dos ZIPs;
- assinar os executáveis quando houver certificado corporativo;
- publicar apenas artefatos identificados como **NexoFlow 1.0**.

## Mudanças de maior risco

Exigem atenção adicional: escrita na Weni, LGPD, pedido/última compra, checkpoint, snapshot congelado, leitura/escrita do Google Sheets, cache FarmaLíder, schemas BI e instalador/desinstalador.
