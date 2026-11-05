# Check-up operacional e testes de desenvolvimento

`comandos/check-up.bat` verifica os arquivos Python públicos obrigatórios, a sintaxe dos módulos de `app` e do cliente Meta, as dependências nativas, o fuso America/Belem e a consistência entre arquivos. Não executa scripts PowerShell opcionais, Codex CLI, testes de instalador nem campanhas. Arquivo obrigatório ausente, sintaxe inválida ou dependência que não carrega reprova a verificação.

O Noturno utiliza a mesma pré-verificação local pelo caminho histórico `app/run_checkup_tests.py`, antes da auditoria de consistência e do diagnóstico de conexão Weni. O perfil FARMA/PET e a seleção de rede da sessão são preservados. Não há leitura de credenciais/estado, acesso às APIs ou gravação de contatos/planilhas nessa pré-verificação. Os diagnósticos de cada integração continuam responsáveis pela validação das configurações e conexões; aprovação local não comprova autenticação nem acesso HTTPS.

## Falha com scripts não assinados

O log de 05/11/2026 mostrou nove falhas em testes de desenvolvimento que tentavam carregar os auxiliares PowerShell opcionais. O Windows recusou os scripts sem assinatura. A versão anterior executava a suíte inteira durante o check-up operacional, fazendo essas recusas bloquearem também as rotinas principais.

A correção separa os escopos: o uso normal realiza a verificação local, e o CI continua executando toda a suíte. Isso não corrige nem ignora erros internos dos auxiliares opcionais. A política/assinatura desses scripts precisa ser validada separadamente no Windows. Não é necessário desativar proteções, remover marcas de origem ou configurar bypass para executar o check-up Python.

## Testes completos

Na raiz do ambiente de desenvolvimento, com dependências instaladas:

```text
python -m unittest discover -s tests -t . -p "test_*.py" -v
```

Ou, para saída resumida e isolamento dos diagnósticos sintéticos:

```text
python app/run_checkup_tests.py --development-tests
```

Essa opção continua executando os testes opcionais aplicáveis e retorna erro se falharem. Não é utilizada pelo BAT, pelos launchers ou pelo Noturno. Não representa uma carga de clientes. Os testes completos e o smoke test do pacote instalado permanecem obrigatórios no workflow.

## Homologação Windows

1. Atualize pelo pacote de teste em modo Preserve. Mantenha Kaspersky, SmartScreen e TLS ativos.
2. Execute `comandos\check-up.bat`. Deve apresentar duas etapas: componentes/dependências locais e auditoria de consistência. Não deve apresentar `Ran ... tests` nem iniciar Codex/PowerShell.
3. Execute o diagnóstico de conexões Weni e a simulação do perfil desejado, usando a seleção de rede pessoal ou corporativa adequada. A aprovação do check-up não substitui esse teste.
4. Se falhar, guarde a saída completa, o commit/hash do pacote, o perfil selecionado e a hora. Não envie credenciais ou dados de clientes. Se surgir uma nova mensagem de bloqueio, registre o nome do arquivo, a detecção e o evento do produto de segurança sem desativá-lo.

Os testes automatizados reproduzem a separação e verificam o pacote no Windows do CI. Eles não comprovam aprovação pelo Kaspersky nem pelas políticas da máquina/rede corporativa.
