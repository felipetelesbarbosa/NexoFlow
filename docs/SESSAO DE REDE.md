# Rede durante uma execução

Os BAT operacionais criam um identificador temporário, herdado pelas etapas filhas. A primeira configuração bem-sucedida guarda apenas `personal` ou `corporate` em um JSON no TEMP do usuário. Os processos irmãos consultam essa decisão antes de configurar sua conexão: a escolha não precisa voltar do Python ao BAT. Não há token, senha, endereço de proxy ou informação de clientes nesse arquivo. Não se altera `secrets_config.py`.

Cada nova execução independente recebe outro identificador, inclusive FARMA e PET. BATs chamados dentro do mesmo fluxo reutilizam o identificador. Os arquivos temporários dos BATs podem ser removidos pela limpeza normal do TEMP após encerrar a execução; não são configuração permanente. O Noturno iniciado diretamente por Python também cria uma sessão e remove seu arquivo ao terminar. No Noturno, a seleção inicial ocorre no processo que possui o console, antes das etapas com entrada redirecionada.

Durante falhas de transporte recuperáveis, as três primeiras tentativas usam a rota escolhida e o backoff já existente dos clientes. Após a terceira falha, o console oferece somente `1` para conexão pessoal/direta autorizada, `2` para proxy corporativo e `0` para cancelar. A mesma regra vale para a pergunta inicial quando a rede não foi confirmada. Qualquer outra entrada, inclusive `3` ou vazia, exibe um aviso e repete a pergunta sem alterar a rota ou encerrar a execução. A decisão válida atualizada vale para as etapas seguintes; escolher a rota atual permite tentá-la novamente. Não existe mudança automática para uma rota direta. Uma resposta lenta do servidor não deve ser confundida com comprovação de queda da internet.

HTTP 407, recusas de autenticação e certificados TLS inválidos mantêm os diagnósticos específicos. HTTP 5xx da Weni não solicita troca de rede. A sondagem TCP de proxy usa três tentativas por padrão e continua sem comprovar acesso HTTPS. TLS e políticas corporativas permanecem ativos.

Operações de escrita sem confirmação preservam os bloqueios existentes: não são repetidas apenas para atingir três tentativas. Nas tarefas sem console, uma mudança de rota não é autorizada por ausência de resposta; o erro é registrado e a reexecução exige corrigir ou selecionar explicitamente a rede. Não se reinicia automaticamente uma aplicação auditada inteira.

## Homologação

1. Execute Weni incremental, em FARMA ou PET, escolhendo a rede quando necessário. Conexões, dry-run e aplicação devem reutilizar a mesma decisão.
2. Em simulação, provoque uma indisponibilidade temporária. Se voltar antes da terceira falha, não deve haver pergunta nem mudança de rota.
3. Se persistir, confira as três tentativas/backoff e a pergunta de troca no console. Só escolha uma rota autorizada naquele ambiente.
4. Confira o resumo, revisão e checkpoint. Não repita aplicações de resultado incerto nem desative proteções.

Os testes usam transporte e credenciais sintéticos. A autenticação real do proxy e a homologação do computador continuam dependentes do ambiente do usuário.
