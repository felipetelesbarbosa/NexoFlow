# NexoFlow Noturno

Execute **NexoFlow Noturno.exe** para atualizar Weni, Analytics e Recompra sem confirmações humanas durante a carga. Ao abrir, escolha **[1] Incremental**, **[2] Carga completa 100%** ou **[0] Sair**. Depois da escolha, não será solicitada revisão humana. O Setup instala o executável e seus atalhos. Configure e teste as credenciais e o proxy pelos aplicativos individuais antes da primeira noite.

A sequência é: check-up → Weni no modo escolhido (simulação, auditoria e aplicação) → Analytics no modo escolhido → Recompra (simulação, validação e aplicação) → Analytics incremental para refletir as mudanças finais.

Os snapshots são gerados novamente a cada execução e aplicados sem abrir Bloco de Notas ou pedir autorização. A Weni também pode excluir duplicados comprovados pelas regras existentes. Identidade, recusa de marketing, produtos pet, propriedade dos pedidos, conflitos e validade do evento D+25 continuam sendo conferidos. A campanha Weni continua responsável pelo envio das mensagens.

Os modos incrementais ainda percorrem a base para descobrir novas compras e mudanças que não alteram a data do contato. A opção completa usa 100% da base; o Analytics final permanece incremental para refletir a Recompra. O programa não importa arquivos XLSX e não configura o agendamento automaticamente.

## Agendar no Windows

No **Agendador de Tarefas**, crie uma tarefa com o horário desejado:

- **Programa:** `C:\NexoFlow\NexoFlow Noturno.exe`.
- **Argumentos:** `--incremental` ou `--full`, conforme o modo desejado. Esse argumento dispensa o menu inicial para permitir o agendamento sem interação.
- **Iniciar em:** `C:\NexoFlow`.
- Use a mesma conta Windows em que as credenciais e o proxy foram configurados.
- Em instâncias simultâneas, selecione **Não iniciar uma nova instância**.
- Se necessário, habilite **Ativar o computador para executar esta tarefa** e mantenha-o conectado à energia e à rede. O computador precisa estar ligado; essa opção pode despertá-lo da suspensão.

A rotina não solicita privilégios administrativos. Ela pode executar sem sessão interativa se a conta usada pela tarefa tiver acesso à instalação, às credenciais, às planilhas e à rota de rede. Teste a tarefa manualmente com essa conta antes de deixá-la agendada.

## Conferir pela manhã

Ao abrir o executável em um terminal interativo, a janela permanece aberta após sucesso, resultado parcial ou erro, inclusive falhas de inicialização. O resultado e o caminho dos relatórios ficam visíveis até você pressionar **ENTER**. A trava da carga é liberada antes dessa espera, permitindo uma nova execução mesmo com a janela anterior aberta. A opção **[0] Sair** fecha o menu normalmente.

Tarefas agendadas sem console interativo encerram ao terminar e preservam o código de saída e os relatórios em arquivo. Para deixar a janela visível, execute com uma sessão interativa do usuário.

Cada execução preserva seus arquivos em `logs/noturno/<execução>/`: `resultado.json`, `execucao.log` e os snapshots de Weni e Recompra. Os relatórios são privados e podem conter dados de contatos; não os publique.

Código **0** indica sequência concluída; **3**, resultado parcial; outros códigos indicam interrupção. O resumo registra a etapa e o código de saída. Falha crítica ou Analytics parcial impede as etapas seguintes. Pendências isoladas da Weni seguem a regra existente: os contatos afetados ficam para a próxima incremental.

A revisão da Recompra é renovada uma vez se atravessar a mudança de dia. Outras falhas de aplicação não são repetidas automaticamente pelo orquestrador. Gravações confirmadas permanecem salvas; respostas incertas continuam sujeitas à reconciliação e ao bloqueio contra duplicidade da Recompra. Não apague arquivos de estado para tentar novamente.

Não execute outras cargas enquanto o Noturno estiver ativo. O executável usa a mesma trava dos demais aplicativos, além do bloqueio próprio da rotina. Os atalhos individuais continuam solicitando revisão humana.
