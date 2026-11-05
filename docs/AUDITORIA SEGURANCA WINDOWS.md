# Segurança Windows e rede — auditoria de desenvolvimento

Escopo: repositório felipetelesbarbosa/NexoFlow, main; sem nova release. Este documento não representa aprovação do Kaspersky ou da rede corporativa.

## Diagnóstico confirmado no código

- O modo auto selecionava conexão direta após falha TCP e sondagem externa. Agora, com proxy configurado, só pode sondar/selecionar alternativa direta quando `PROXY_ALLOW_DIRECT_FALLBACK = True` estiver explicitamente autorizado pela TI. O padrão é False. `PROXY_MODE = off` continua sendo escolha explícita de rota direta, para redes onde ela é autorizada.
- Uma resposta TCP seleciona a rota proxy; não comprova autenticação, CONNECT nem TLS. O resumo agora informa essa limitação. 407 é erro de autenticação não retentável; CONNECT 403 exige TI; 502/503 são falhas de transporte retentáveis com limites existentes. Certificado inválido bloqueia a conexão, sem desabilitar TLS.
- O auxiliar Codex baixava um script HTTPS e apenas conferia sintaxe antes de executar. Agora também exige SHA-256 fixado no código para o snapshot consultado. Alteração remota bloqueia o componente opcional e exige revisão; não se aceita hash fornecido pelo mesmo download. Isso comprova correspondência de bytes, não a ausência de vulnerabilidades no software remoto. O instalador oficial ainda faz seus próprios downloads; o pin do script não elimina riscos da cadeia inteira.
- O Setup chama o auxiliar opcional em processo filho separado, evitando que uma terminação fatal desse filho encerre o processo principal. Isso não protege o Setup de um encerramento direto pelo antivírus.
- `instalar.bat` prepara venv, proxy e dependências pip. O Setup executa esse BAT após validar o manifesto/cópia. A elevação é usada para C:\NexoFlow, atalhos compartilhados e registro HKLM. Alterar o modelo de instalação exigiria testes Windows próprios; não foi realizado nesta correção.
- O pip é iniciado com o ambiente do processo, incluindo proxy e CA configurados. O auxiliar Codex usa Windows PowerShell e a pilha .NET: não se pode presumir que use as mesmas regras de requests/pip. PAC, NTLM/Kerberos e inspeção HTTPS exigem conferência da TI; os campos usuário/senha por URL não implementam todos esses protocolos.

## Hipóteses e evidências faltantes

PDM:Trojan.Win32.Generic é uma detecção comportamental. Elevação, cadeia CMD/PowerShell/Python, downloads e alterações de programa são comportamentos candidatos, sem prova de qual disparou o evento. Falta correlacionar data/hora, PID, árvore de processos, ação e hash da amostra exata. Ausência de assinatura não é causa comprovada. O desaparecimento de instalar.bat pode decorrer da quarentena relatada; é necessário confrontar o evento com manifesto e hash para comprovar. Não restaurar automaticamente uma amostra detectada.

`0x40000015` indica encerramento anormal; sozinho não identifica Kaspersky ou a biblioteca responsável. Logs de aplicação/Windows/antivírus são necessários. Não confundir erro TLS, HTTP de API e rejeição CONNECT pelo proxy.

## Homologação na máquina real

1. Baixar o pacote de desenvolvimento identificado pelo commit; conferir SHA256SUMS e procedência pelo canal oficial. Não usar um ZIP anterior como se contivesse esta correção.
2. Antes de instalar, registrar o hash sem executar o arquivo: `Get-FileHash -Algorithm SHA256 -LiteralPath '{arquivo}'`. Conferir o editor com `Get-AuthenticodeSignature -LiteralPath '{arquivo}'`. Unsigned é um estado a registrar; não autoriza ignorar detecção.
3. Manter Kaspersky/UAC/SmartScreen/firewall ativos. Não remover Zone.Identifier, não criar exclusões e não mudar ExecutionPolicy global. Se houver bloqueio, interromper e preservar log/evento/hash para análise.
4. Validar Preserve com configurações, credenciais, logs, checkpoints e importações existentes. Validar Clean/rollback apenas em máquina de homologação, com dados sintéticos e backup. O CI Windows tem fixtures de dados abertos; isso não comprova aceitação do Kaspersky corporativo.
5. Selecionar PET e FARMA separadamente, conferir destinos, fazer diagnósticos e simulações antes de autorizar gravações. Em proxy obrigatório manter `PROXY_ALLOW_DIRECT_FALLBACK = False` e usar `PROXY_MODE = on` se essa for a política da TI.
6. Registrar por serviço: horário UTC-3, hostname, porta 443, rota selecionada, status CONNECT/HTTP, categoria de falha, quantidade de tentativas e versão. Nunca registrar token, CPF, senha, Proxy-Authorization ou resposta de cliente.
7. Para TLS corporativo, a TI deve fornecer cadeia PEM aprovada para requests/pip e instalar a cadeia Windows conforme sua política. Não usar verify=False, trusted-host ou certificados arbitrários como correção.

## Solicitação à TI

Validar CONNECT HTTPS pelo proxy 10.1.15.3:8020, método de autenticação (Basic, NTLM, Kerberos), permissão do usuário e logs do proxy no horário da falha. A porta TCP aberta não comprova liberação. Para 407 conferir credenciais/método; para 403 conferir regra de destino; para 502/503 conferir resolução/upstream, bloqueio, disponibilidade e inspeção TLS do proxy. Não afirmar que 503 identifica sozinho um bloqueio de firewall.

Conferir, conforme recursos habilitados: flows.weni.ai; api.farmalider.net.br; graph.facebook.com; sheets.googleapis.com; www.googleapis.com/Drive; oauth2.googleapis.com; googleads.googleapis.com; pypi.org e files.pythonhosted.org. Downloads opcionais envolvem chatgpt.com, releases.openai.com, github.com e hosts de assets oficiais. Autorizar somente hosts efetivamente necessários e confirmados, inclusive redirecionamentos, sem liberar HTTPS indiscriminadamente. IPs internos/endpoints diretos adicionais devem ser extraídos da configuração privada pela TI, sem publicação.

## Kaspersky e distribuição de baixo custo

Usar o portal oficial https://opentip.kaspersky.com/ para consulta por hash e envio de amostra quando permitido pela empresa. Se o evento corporativo exigir suporte, abrir chamado pelo portal oficial https://companyaccount.kaspersky.com/ com export do evento, versão/base do produto, hash, pacote/commit, assinatura e passos mínimos de reprodução. O fabricante decide a classificação. Remover configurações privadas antes de enviar; não enviar secrets_config.py, credentials, logs de clientes ou bases de pedidos. Não restaurar/quebrar quarentena para executar a amostra enquanto não houver avaliação autorizada.

Distribuição com custo zero: builds Windows reproduzíveis a partir de commit identificado, checks obrigatórios, manifesto SHA-256, varredura de segredos, dependências auditadas e canal oficial. O orçamento de R$ 50 não exige comprar certificado comercial. A infraestrutura Authenticode existente aceita certificado legítimo já fornecido pela empresa e verifica EKU, validade, identidade e timestamp. Certificado autoassinado não cria confiança pública nem garante SmartScreen/Kaspersky; não instalar raízes automaticamente.

O uso atual de ExecutionPolicy Bypass é limitado aos processos de instalação/desinstalação e ainda merece migração futura testada para um modelo de confiança/assinatura; não muda a política global, mas também não resolve detecção. Não foi removido sem testar a cadeia completa no Windows.

## Próximo pacote

Sem release automática e sem renumerar a versão nesta rodada. O pacote experimental precisa incluir commit e aviso de desenvolvimento, passar pelos checks Windows e pela varredura dos ZIPs antes de disponibilização. Não declara a auditoria ampla anterior (Noturno/Sheets) concluída. Aprovação de antivírus e de rede continua dependente de homologação real.
