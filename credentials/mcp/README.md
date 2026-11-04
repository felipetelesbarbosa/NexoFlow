# Credenciais locais dos servidores MCP

O arquivo `meta_ads_credentials.json` deve existir apenas em cada computador
que executa o NexoFlow/Meta Ads MCP. Ele NÃO é versionado e não vem no ZIP.

Copie o modelo `configuracao/meta_ads_credentials.example.json` para
`credentials/mcp/meta_ads_credentials.json` e substitua apenas o placeholder
do token por sua credencial real, com escopo `ads_read`.

A lista `allowed_ad_account_ids` limita as contas consultáveis no MCP; não
concede acesso novo na Meta. Nunca cole o conteúdo do token em chats, logs,
issues, workflows, commits, screenshots ou no Codex como texto.
