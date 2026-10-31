# NexoFlow 1.5.10 — Processo de mudanças

Este documento define como alterações devem ser feitas e validadas no NexoFlow 1.5.10. Ele documenta o processo atual do **NexoFlow 1.5.10**; o histórico público fica concentrado em `CHANGELOG.md`.

A publicação automática confere a origem na `main` antes de gerar os pacotes. Use mensagens de commit curtas que descrevam a área ou a alteração. Na lista de arquivos do GitHub, esses textos são as mensagens dos últimos commits, não descrições independentes. A versão atual usa o título `NexoFlow 1.5.10`, a tag `v1.5.10` e pacotes com sufixo `1.5.10`. Cada próxima publicação recebe um patch, de 1.5.10 até 1.5.99; depois 1.6. Tags e releases anteriores são preservados. Veja [versionamento](VERSIONAMENTO.md).

## Princípios

1. preservar compatibilidade das rotinas operacionais;
2. manter credenciais fora do repositório/pacote;
3. atualizar testes junto com qualquer mudança de comportamento;
4. executar `comandos/check-up.bat` e `app/auditar_consistencia.py` antes de empacotar;
5. regenerar `payload manifest.json` e `checksums SHA256.txt` após qualquer alteração;
6. não alterar snapshot/checkpoint do Update Weni sem testes específicos de concorrência e rollback;
7. não alterar schemas do Analytics/BI sem migração compatível e validação do Data Studio.

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
- publicar apenas artefatos identificados como **NexoFlow 1.5.10**.

## Mudanças de maior risco

Exigem atenção adicional: escrita na Weni, LGPD, pedido/última compra, checkpoint, snapshot congelado, leitura/escrita do Google Sheets, cache FarmaLíder, schemas BI e instalador/desinstalador.

## Conferência antes da entrega

- Reproduzir o problema com dados sintéticos e validar a correção com um teste de regressão.
- Percorrer a integração afetada com a CLI, revisões, estado e códigos de saída reais; APIs e recursos externos permanecem simulados.
- Conferir sucesso, pendências isoladas, falhas críticas, mudanças após a revisão e retomada sem duplicidade, conforme a alteração.
- Revisar o diff, executar as verificações exigidas e conferir os executáveis e a instalação no Windows quando houver impacto operacional.
- Confirmar que workflow, tag e pacotes publicados correspondem ao mesmo commit antes de anunciar o release.
- Informar os testes realizados e as limitações restantes. Aprovação automática não garante ausência de erros.

O teste `tests/test_noturno_recompra_integration.py` percorre a Recompra dentro do Noturno com a CLI real, validação de pedidos, revisão em arquivo, estado persistido e contrato HTTP Weni simulado. As etapas Weni e Analytics têm validações próprias; esse teste não usa serviços de produção.
