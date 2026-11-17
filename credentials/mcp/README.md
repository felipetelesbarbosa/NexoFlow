# Credencial da integração nativa Meta Ads

O Analytics e o Noturno usam o arquivo privado `credentials/mcp/meta_ads_credentials.json` para consultar a Marketing API. O caminho mantém a compatibilidade com as instalações anteriores à versão 1.5.42.

Se já houver uma credencial válida, mantenha o arquivo no local. Em uma instalação nova, copie `configuracao/meta_ads_credentials.example.json` para esse caminho e preencha localmente o token com escopo `ads_read`, a versão da API e a lista `allowed_ad_account_ids`. Inclua apenas as contas autorizadas.

Guarde o JSON fora do Git, dos pacotes e dos logs. [Configuração e validação da integração Meta](../../docs/META%20ADS%20NATIVO.md).
