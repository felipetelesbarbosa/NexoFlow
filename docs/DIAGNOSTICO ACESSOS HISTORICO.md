# Diagnóstico de pasta e permissões do histórico

## Estado e causa

A release 1.5.27 está publicada e permanece intacta. Após o operador informar
`PASTA_OU_PERMISSOES_ALTERADAS`, foi identificado um defeito reproduzível: para
continuações já registradas, `preflight` comparava `parents` retornado à conta de
serviço com `parents` aprovado pelo usuário OAuth. São autoridades diferentes;
a pasta pode não ser visível para a conta que recebeu somente o arquivo.

As fixtures antigas usavam `parents=[]` em ambas as visões e retornavam sucesso
em verificações importantes. Esse formato nem corresponde ao contrato real de
`prepare_intent`, que exige uma pasta OAuth comprovada. As fixtures passaram a
usar uma pasta OAuth válida, omissão de parents na visão de serviço e os métodos
reais de preparação, origem, propriedade, compartilhamento e verificação privada
sobre respostas sintéticas. Os testes de retomada/reconciliação e rollback
falharam antes da correção na mesma comparação.

A main agora verifica a localização com o usuário OAuth, exigindo ID, tipo,
arquivo ativo, edição e a mesma pasta aprovada. A conta de serviço continua
precisando editar o arquivo. Ausência de pasta na visão de serviço não é prova
suficiente de localização. Erro de leitura OAuth, pasta realmente diferente,
compartilhamento amplo ou perda de acesso continuam bloqueando. Nenhuma permissão
é concedida automaticamente.

A auditoria também reproduziu uma lacuna na retomada: um compartilhamento amplo
adicionado à continuação depois do piloto não era conferido naquele preflight.
A main reutiliza agora `verify_private_access` antes de continuar, com regressão
que exige bloqueio sem novas linhas. Esse cenário foi somente simulado; não há
evidência de compartilhamento amplo ou exposição comercial no ambiente do operador.

Isso comprova um defeito no código, mas **não comprova sozinho a causa da
ocorrência do operador**: o mesmo erro tinha quatro origens possíveis. Uma
mudança real de acesso continua possível. O diagnóstico abaixo precisa fechar
essa distinção antes de nova distribuição ou aplicação. A correção operacional
não está nos ZIPs 1.5.27; não copiar módulos da main sobre a instalação.

## Auditor independente para a instalação original 1.5.27

Arquivo público: `scripts/diagnosticar_acessos_historico.py`. Baixar o arquivo de
um commit revisado do repositório oficial e salvar fora de `app/`, por exemplo
em Downloads. O script valida versão e hashes dos cinco módulos da release,
inclusive a normalização CRLF. Não exige clone, instalação de dependências ou
novo Setup. Usa o Python e as credenciais locais já instalados; não enviar esses
arquivos ao desenvolvedor.

Encerrar cargas e escolher FARMA no Terminal. Ajustar somente os caminhos do
plano existente e da saída nova:

```powershell
& "C:\NexoFlow\.venv\Scripts\python.exe" "$env:USERPROFILE\Downloads\diagnosticar_acessos_historico.py" `
  --instalacao "C:\NexoFlow" --perfil FARMA `
  --revisao "C:\NexoFlow\logs\privado\revisao-farma-existente.json" `
  --saida "C:\NexoFlow\logs\privado\diagnostico-acessos-farma-1.5.27.json"
```

A saída precisa ser nova; o auditor recusa sobrescrever arquivos. Não usar a
pasta dos journals como destino. A versão do auditor deve ser fixada por SHA de
commit e seu SHA-256 conferido antes da execução.

O script:

- lê o plano e apenas os metadados/estados do journal, com `mode=ro`,
  `PRAGMA query_only=ON`, conexão fechada e hashes antes/depois;
- recusa journal ativo com WAL/rollback pendente, perfil/raiz divergente,
  revisão ou metadados alterados;
- abre os três arquivos pelo caminho somente leitura do aplicativo e consulta
  origens, arquivos, intenções, pastas e acessos nas duas autoridades;
- coleta todas as comparações de acesso e a guarda de compartilhamento privado,
  sem parar na primeira divergência;
- confere somente cabeçalhos e estruturas das partes novas com grade mínima;
  não lê fatos ou grades grandes para inspecionar esses cabeçalhos;
- proíbe métodos de escrita no transporte Drive/Sheets e não toma lease remoto;
- grava exclusivamente um relatório JSON novo na pasta privada do perfil,
  sem e-mails, tokens, nomes ou registros de pedidos/clientes.

A atualização técnica do token OAuth, quando necessária para autenticar GETs,
continua sendo feita pela biblioteca Google. Isso não é gravação comercial.

O relatório `historico_acessos_diagnostico_v1` contém IDs técnicos de arquivos/pastas,
papéis, contagens, comparações booleanas, estados de lotes e códigos sanitizados.
Pode ser devolvido nesta conversa para análise, mas deve permanecer fora de Git,
CI e pacotes. O script não emite recibo de compatibilidade nem autoriza aplicar.

## Como interpretar

- `tipo=continuacao_nova`, `oauth_confere=true`,
  `comparacao_cruzada_1_5_27_confere=false` e edição de serviço confirmada:
  evidência da comparação entre visões diferentes. Conferir também marcador,
  compartilhamento, cabeçalhos, estados e as demais origens.
- `oauth_confere=false`: não presumir visibilidade; pode haver mudança real ou
  localização não comprovada. Preservar o bloqueio.
- `falha_leitura.http=403`: falha de consulta/permissão, não prova de pasta movida.
- Permissões literais diferentes e semânticas iguais: diferença de representação
  a investigar; não remover acessos automaticamente.
- `compartilhamento_privado_confere=false`, metadados/manifesto diferentes,
  cabeçalho/estrutura divergente ou lotes enviados/incertos: preservar tudo e
  investigar antes de outra aplicação.

Nenhuma planilha comercial foi consultada por esta implementação no ambiente do
Codex. O diagnóstico real será executado pelo operador. Aprovação de testes
sintéticos não equivale a homologação das planilhas.
