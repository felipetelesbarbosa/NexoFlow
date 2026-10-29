# Comandos Windows

Rotinas BAT para cargas completas e incrementais, importação de planilhas, revisão e diagnóstico.

- `atualizar_tudo.bat`: percorre Weni, Planilha, Analytics e Recompra com as revisões solicitadas.
- `atualizar_weni_carga_completa.bat`: inicia a carga completa da Weni.
- `executar_carga_completa.bat`: inicia a carga completa do Analytics.
- `atualizar_recompra.bat`: prepara a revisão e aplica a Recompra após confirmação.
- `limpar_cancelados_recompra.bat`: revisa e remove cancelados do grupo existente, escolhendo FarmaLíder ou Pets Líder.
- `atualizar_recompra_pets.bat`: executa a prevenção e manutenção Pets D+30 com credenciais e estado separados.
- `check-up.bat`: verifica sintaxe, testes e consistência.

Para a ordem de execução e os pré-requisitos, consulte o [guia de operação](../docs/Documentacao%20NexoFlow.md).

`executar_noturno.bat` abre a rotina noturna em script: escolha o segmento e o modo incremental ou completo. O resultado fica visível até um novo ENTER. O Setup usa essa entrada no atalho quando o launcher EXE do Noturno está indisponível.
