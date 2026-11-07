# C. PostgreSQL / DBeaver Community no Windows
Preparação realizada na VPS em 07/11/2026. DBeaver não foi instalado no Windows ou na VPS. O teste completo do cliente Windows continua pendente.

## Conexões preparadas
| Ambiente | Banco | Usuário individual | Views | Destino privado na VPS |
| --- | --- | --- | --- | --- |
| Hub HML | nexoflow_hub_hml | hub_leitura_felipe | consulta_hub.tarefas_agregadas, historico_agregado, cobertura | 127.0.0.1:15432 |
| n8n | n8n | n8n_leitura_felipe | consulta_n8n.execucoes_agregadas, workflows_agregados | 127.0.0.1:15433 |

Credenciais distintas, aleatórias e privadas. Os arquivos ficam em /srv/nexoflow/configuracoes/consulta, root 0700, arquivos 0600. O operador deve colocá-las no cofre por canal seguro; nunca em issue, chat, screenshot, log ou commit. Não usar os tokens/DSNs da aplicação.

Grupos hub_consulta/n8n_consulta são NOLOGIN; membros individuais herdam explicitamente privilégios. Somente CONNECT no banco próprio, USAGE do schema de consulta e SELECT das views saneadas. Sem acesso concedido a tabelas de pedidos/clientes, credenciais n8n ou payloads. Usuários sem SUPERUSER/CREATEDB/CREATEROLE; limite de três conexões, statement_timeout 15s, idle-in-transaction 60s e default read-only.

As views são agregadas, com security_barrier e ownership administrativo; leitores não são seus donos. O SET default_transaction_read_only=off não permite escrita persistente porque os grants a impedem. A preferência read-only do DBeaver é adicional.

## Rede
A porta 5432 não foi publicada. Dois sockets systemd escutam somente em loopback e encaminham para as instâncias Docker já existentes. Os proxies rodam como nobody, com memória limitada, proteção de filesystem e allowlist de IP. UFW permanece permitindo apenas SSH para acesso externo.

O relay Hub aponta ao IP privado 172.21.0.2; o n8n a 172.18.0.2, medidos na preparação. Se o contêiner PostgreSQL for recriado, conferir o IP e atualizar somente o relay correspondente, com validação. Não assumir que o IP é permanente. Não abrir 5432 para corrigir um relay.

## Procedimento no Windows
1. Instalar DBeaver Community pela distribuição oficial e usar o driver PostgreSQL oficial. Validar política do computador antes de instalar.
2. Usar uma chave SSH individual já autorizada para nexoadmin@srv2132956.hstgr.cloud, porta 22. Não compartilhar a chave privada. Os demais desenvolvedores precisam de identidades próprias aprovadas.
3. Confirmar a fingerprint ED25519 por canal conhecido: SHA256:hUGoaBK2Kn44mQ+e5bRU9BbbbtgNxqipQskVXaqgZP0. Nunca ignorar uma mudança inesperada.
4. No PowerShell/OpenSSH, abrir um encaminhamento local:
```powershell
ssh -N -o ExitOnForwardFailure=yes -o StrictHostKeyChecking=yes -L 127.0.0.1:25432:127.0.0.1:15432 -L 127.0.0.1:25433:127.0.0.1:15433 nexoadmin@srv2132956.hstgr.cloud
```
5. No DBeaver, criar duas conexões PostgreSQL. Host 127.0.0.1; Hub porta 25432 e banco/usuário da tabela; n8n porta 25433 e sua identidade distinta. Inserir a senha individual no cliente/cofre local. Como o túnel já está aberto, não adicionar outro túnel embutido na mesma conexão.
6. Conservar a validação SSH e executar SELECT current_user, current_database(); SHOW transaction_read_only; SELECT * FROM consulta_hub.tarefas_agregadas; ou a view n8n correspondente.
7. O tráfego remoto é protegido pelo SSH; a conexão local relay→contêiner mantém o isolamento privado atual. PostgreSQL ainda não tem TLS próprio. Não configurar um endpoint público nem usar bypass de certificado.
8. Em futura implantação de TLS PostgreSQL, instalar CA confiável e usar verify-full com hostname apropriado; homologar o driver, sem desativar validação.

O comando não contém senha. Se o servidor ainda não estiver no known_hosts, registrar a chave validada pelo fluxo normal antes de usar StrictHostKeyChecking=yes.

## Auditoria e revogação
Conexões/desconexões PostgreSQL estão registradas sem SQL integral. SSH e journald mantêm identidade/horário; pg_stat_activity permite conferir sessões do leitor. Esses registros não constituem auditoria completa de todas as consultas SQL. Antes de acesso a dados comerciais individualizados, avaliar auditoria específica sem capturar parâmetros pessoais.

Para suspender um usuário: ALTER ROLE <usuario> NOLOGIN; encerrar apenas suas sessões por pg_terminate_backend após conferir a identidade; revogar sua associação ao grupo. Não revogar os papéis das aplicações. Para encerrar os relays, desabilitar somente nexoflow-consulta-hub.socket / nexoflow-consulta-n8n.socket e seus services, preservando banco e dados.

Não distribuir a conta de Felipe a outros desenvolvedores. Criar um papel e uma credencial individual por pessoa, concessão explicitamente aprovada e escopo necessário. Usuários do Métricas não recebem nenhum desses acessos.

## Provas e limites
Conexão real SCRAM por ambos os relays aprovada na VPS. SELECT nas views passou; raw SELECT, CREATE persistente e DELETE foram recusados. As instâncias permanecem separadas. Falha inicial de herança de papel corrigida e repetida. Falta testar o caminho Windows→SSH→relay→PostgreSQL com o DBeaver instalado.

Referência: [GRANT PostgreSQL 18](https://www.postgresql.org/docs/18/sql-grant.html).

