# Manutenção do armazenamento da VPS e R2
Rotinas autorizadas em 27/11/2026, sem publicação comercial ou mudanças no Noturno.

## Escopo
- n8n: **NexoFlow VPS | Limpeza segura (30 dias)**, dia a cada 30 dias às 06h30 (Belém).
- n8n: **NexoFlow R2 | Monitoramento diário**, todos os dias às 07h30 (Belém).
- O fluxo chama um serviço interno de gatilho com credencial exclusiva de cabeçalho HTTP; o bridge não monta Docker socket, segredos R2 ou diretórios operacionais e não possui porta publicada.
- Um serviço systemd no host lê um marcador de formato fixo e executa o script root-owned. Nenhuma URL, comando ou caminho enviado pelo n8n é aceito como entrada. Há locks compartilhados com backup e implantação, e piso de 29 dias entre limpezas bem-sucedidas.
- Cache APT, cache Docker não usado com mais de 30 dias, cópias tar.gz de fontes com mais de 30 dias e byte a byte verificadas contra o diretório extraído, e clones temporários root-owned privados, sem alterações, arquivos ignorados, commits sem remoto, montagens ou arquivos abertos. Os logs e evidências irmãos dos clones são preservados.
- **Não** remove bancos, volumes, containers, imagens, revisões READY, arquivos de credenciais, publicações, ou backups locais de dados.
- R2: retenção autorizada 7 diários, 4 semanais, 3 mensais, agrupando host/tags; aplicar somente aos IDs explicitamente simulados com tags exatas de backup diário. Snapshots manuais, de arquivo e reversão ficam protegidos. Confere backup recente, inventário, integridade antes, lista de IDs e integridade depois; usa Restic forget/prune, nunca exclui objetos diretamente pelo S3.
- Monitoramento lista todos os objetos do bucket com a credencial S3 privada já existente (somente operação LIST), informa bytes por classe e limiares de 8 GB e 10 GB Standard, estimativa ilustrativa para volume constante por 30 dias. Não é a fatura real nem um teto de cobrança.

## Implantação
Instale os dois scripts Python em /usr/local/lib/nexoflow-storage-maintenance, arquivos root-owned e somente leitura para o bridge. Instale as unidades systemd fornecidas e efetue daemon-reload. Use diretório privado /srv/nexoflow/manutencao/limpeza: requests com dono UID/GID 10001 e modo 0700, status root-owned modo 0755, state/audit root-private, token root:10001 0440. Configuração root-only /etc/nexoflow/storage-maintenance.json contém endpoint R2, bucket nexoflow-backups, credentials_file e password_file já usados pelo Restic. Nunca versionar tokens/chaves.
Crie o bridge usando imagem Python existente, rede privada compartilhada com n8n, UID/GID 10001, read-only, cap-drop ALL, no-new-privileges e apenas montagens dos scripts, requests, status e token. Não publique portas. Importe hub/n8n/manutencao-armazenamento.json e credencial HTTP Header Auth exclusiva (Authorization: Bearer, segredo gerado na VPS); teste cada fluxo e publique apenas estes dois agendamentos. O Noturno continua desativado.
Os logs privados e planos ficam em audit; status sanitizado é retornado ao n8n. Desabilitar os dois workflows e a unidade .path interrompe novas solicitações; não interromper prune/backup em curso. Remover o bridge somente depois de confirmar nenhuma solicitação pendente. Não apagar backups ou dados na reversão da automação.

## Testes
`cd hub/maintenance && python -m unittest -v`: formato do marcador, recusa de snapshots protegidos e do último backup, verificação byte a byte de arquivos e limiares R2, autenticador do bridge. Implantação requer teste manual real e confirmação da publicação no editor.
