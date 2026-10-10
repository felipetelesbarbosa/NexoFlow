# NexoFlow 1.0 — Segurança

O código, o histórico do Git e os pacotes de distribuição podem ser públicos. Credenciais, dados reais de clientes e registros da operação devem permanecer privados.

## Configuração e dados locais

Use [secrets_config.example.py](secrets_config.example.py) como modelo para criar o arquivo local `secrets_config.py`. Guarde a credencial do Google em `credentials/google_credentials.json`. Configure tokens com as permissões mínimas necessárias e revogue os que deixarem de ser usados.

Não adicione ao Git nem aos pacotes tokens, senhas, chaves privadas, credenciais JSON, arquivos `.env`, exports de contatos/conversas ou relatórios com CPF, telefone, e-mail e pedidos reais. As configurações locais, `importacoes`, logs e diagnósticos privados têm exclusões no Git e no empacotamento; confira os arquivos antes de publicar. A exclusão de um arquivo atual não apaga cópias já presentes no histórico ou em releases antigos.

Se uma credencial for exposta, revogue ou substitua a credencial primeiro. Depois, investigue as cópias no histórico e nos pacotes publicados e remova os dados expostos. Não reutilize a credencial apenas porque o arquivo foi apagado.

## Verificação antes da publicação

O workflow do release verifica segredos com Gitleaks e mantém suas regras padrão. A varredura cobre o histórico disponível no checkout, incluindo as referências obtidas do remoto, e o conteúdo extraído dos dois ZIPs. Os checksums dos pacotes são conferidos antes da extração; caminhos inseguros no ZIP bloqueiam a verificação. Um achado ou uma falha do scanner impede a publicação.

A configuração em `.gitleaks.toml` contém uma exceção exata para `3200/farmalider`, trecho de porta e caminho da URL pública da FarmaLíder reconhecido incorretamente como chave. A exceção não libera arquivos inteiros nem outros valores de credenciais. Os relatórios da varredura usam valores ocultos e ficam fora dos pacotes públicos.

Os testes e o build usam permissão de leitura no GitHub. A permissão de escrita fica no job que publica os artefatos já validados; as Actions usadas pelo workflow têm revisões fixadas por SHA.

O CI verifica o conteúdo **após o push**. Ele não substitui o bloqueio de segredos antes do push oferecido pelo GitHub, nem garante a ausência de todos os dados pessoais ou de formatos de segredos desconhecidos. Confira também nomes de arquivos, conteúdo de exemplos, histórico e assets antes de tornar o projeto público.

## Relatar uma vulnerabilidade

Na aba **Security**, use **Report a vulnerability** quando o recurso de relato privado estiver ativado. Envie uma descrição, os passos para reproduzir e a versão afetada, com exemplos fictícios e sem credenciais ou dados de clientes.

Se essa opção não estiver disponível, solicite ao proprietário um canal privado antes de enviar detalhes sensíveis. Não publique tokens, dados pessoais ou instruções de exploração em issues, comentários ou pull requests públicos.

## Configurações do GitHub para o proprietário

Estas opções são administrativas e devem ser conferidas no GitHub. O workflow e este documento não ativam essas configurações na conta.

1. **Visibilidade:** depois de revisar o histórico e os pacotes, abra **Settings → General → Danger Zone → Change repository visibility → Make public**. Essa escolha dá acesso público ao projeto inteiro, incluindo código, histórico, documentação e releases.
2. **Proteção da main:** em **Settings → Rules → Rulesets**, crie uma regra ativa para a branch `main` com **Restrict deletions** e **Block force pushes**, quando o recurso estiver disponível. Preserve as atualizações diretas na `main`; pull request obrigatório não faz parte do padrão atual do projeto. A regra deve atingir somente a branch, sem bloquear a atualização da tag `v1.0`.
3. **Segredos e dependências:** em **Settings → Security**, procure **Code security** e **Secret scanning** (os nomes podem variar na interface). Ative o gráfico de dependências, **Dependabot alerts**, **Secret scanning** e **Push protection** onde estiverem disponíveis. Ative também o relato privado de vulnerabilidades para disponibilizar **Report a vulnerability**. Analise os alertas e substitua qualquer credencial exposta.
4. **Permissões das Actions:** em **Settings → Actions → General → Workflow permissions**, selecione **Read repository contents and packages permissions** e deixe desmarcado **Allow GitHub Actions to create and approve pull requests**. O job de publicação declara sua permissão de escrita explicitamente.
5. **Release estável:** mantenha **release immutability** desativada para este projeto. O processo atualiza a tag `v1.0`, republica o release **NexoFlow 1.0** e substitui `NexoFlow-Setup-1.0.zip`, `NexoFlow-1.0.zip` e `SHA256SUMS-1.0.txt`. A imutabilidade impediria esse padrão de atualização.

Downloads públicos não devem conter configurações reais de uma instalação. Para operar o NexoFlow, cada instalação precisa fornecer suas próprias credenciais locais e seguir a revisão humana das rotinas de escrita.
