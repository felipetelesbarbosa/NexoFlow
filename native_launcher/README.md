# NexoFlow 1.5.6 — Launchers nativos

Fontes dos launchers Windows distribuídos no NexoFlow 1.5.6.

Cada executável é compilado separadamente por tag (`noturno`, `analytics`, `updateweni`, `recompra`, `planilha`, `terminal`, `setup` ou `uninstall`), evitando que um componente carregue código de outro.

Objetivos:

- não usar `system()`;
- iniciar processos filhos por `CreateProcessW` através de `os/exec`;
- resolver caminhos a partir da própria pasta de instalação;
- usar `System32` para `cmd.exe`/PowerShell quando necessários;
- manter `Local\NexoFlowOperationLock` para Analytics, NexoFlow Weni e Setup;
- manter o NexoFlow Terminal independente da trava operacional;
- não embutir tokens, senhas ou credenciais;
- manter código-fonte auditável, sem packer ou ofuscação.

O `NexoFlow Terminal.exe` inicia diretamente `app/run_terminal.py` com o Python da `.venv` quando disponível e utiliza `assets/NexoFlow_Terminal.ico`.

### Ícones incorporados nos executáveis

Os ícones dos oito programas são incorporados ao próprio PE como recursos `RT_ICON` e `RT_GROUP_ICON` durante a criação dos ZIPs. Assim, o Explorador do Windows exibe o ícone específico mesmo ao visualizar o arquivo `.exe`, sem depender de um atalho ou de um arquivo `.ico` ao lado.

| Executável | Ícone |
|---|---|
| `NexoFlow Noturno.exe` | `assets/NexoFlow_Noturno.ico` |
| `NexoFlow Setup.exe` | `assets/installer.ico` |
| `NexoFlow Analytics.exe` | `assets/NexoFlow.ico` |
| `NexoFlow Weni.exe` | `assets/NexoFlow_Weni.ico` |
| `NexoFlow Recompra.exe` | `assets/NexoFlow_Recompra.ico` |
| `NexoFlow Planilha.exe` | `assets/NexoFlow_Planilha.ico` |
| `NexoFlow Terminal.exe` | `assets/NexoFlow_Terminal.ico` |
| `NexoFlow Uninstall.exe` | `assets/uninstaller.ico` |

A criação dos pacotes usa `scripts/embed_windows_icon.ps1`. O GitHub Actions executa `scripts/test_executable_icons.ps1` e **bloqueia a publicação** se o Windows não conseguir extrair algum ícone do executável ou se o PE não contiver as imagens correspondentes. O Setup também atualiza o cache de ícones do Explorer ao instalar.

O Setup usa `ExecutionPolicy Bypass` somente para iniciar o script PowerShell local quando ele não estiver assinado com Authenticode. Analytics e NexoFlow Weni não contêm essa lógica.


O `NexoFlow Uninstall.exe` é um launcher nativo **opcional** para `installer\uninstall.ps1`. Ele é distribuído por conveniência, mas não é requisito do Setup nem do check-up: se um antivírus/EDR corporativo removê-lo, a instalação e a desinstalação continuam disponíveis por **Aplicativos instalados**, `desinstalar_nexoflow.cmd` e `installer\uninstall.ps1`.

### Português brasileiro

Os pacotes recompilam os oito launchers a partir destes fontes. A saída do console usa UTF-8 e os recursos de versão usam a tabela pt-BR 0416/04B0, preservando acentos e cedilha. A versão permanece NexoFlow 1.5.6.

## NexoFlow Planilha

O Setup instala **NexoFlow Planilha.exe** com ícone próprio e atalho na Área de Trabalho. O menu permite executar as cargas por planilha para Weni ou Analytics/Google Sheets e abrir `importacoes`. Use `Conversas_Delivery.xlsx` e `Contatos_Delivery.xlsx`; cada carga mantém a revisão humana antes de aplicar.

## Executável Recompra

`NexoFlow Recompra.exe` foi adicionado como lançador dedicado para `comandos/atualizar_recompra.bat`. Não altera nem ignora os passos do BAT: check-only, dry-run, revisão humana e confirmação antes do apply. O workflow Windows executa o EXE compilado em uma pasta temporária com BAT sintético e verifica retorno 0 e propagação de falha; a validação de POST/GET para grupo Weni usa API simulada nos testes Python, sem atualizar contatos reais.

## NexoFlow Noturno

`NexoFlow Noturno.exe` inicia `app/run_noturno.py` com o Python da instalação, mantendo a trava operacional durante a carga. Em console interativo, mostra o resultado e aguarda ENTER ao terminar, inclusive em falhas de inicialização; libera a trava antes da espera. Sem console, encerra preservando o código de saída. A sequência e o agendamento estão em [NOTURNO.md](../docs/NOTURNO.md).

Na Weni, `--build-info` inspeciona o executável sem iniciar uma carga ou adquirir a trava. Não aceita argumentos adicionais. O check-up usa esse caminho; o CI também verifica a execução normal com BAT sintético e a recusa por trava ativa.
