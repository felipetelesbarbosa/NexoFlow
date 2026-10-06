# Google Sheets: configuração da Service Account

A autenticação usa uma **Service Account**, adequada para execução automatizada porque não depende do login Google de uma pessoa nem do usuário do Windows.

## 1. Crie a planilha

Crie uma planilha no Google Sheets, por exemplo:

`NexoFlow - FarmaLíder Analytics`

Não é necessário criar as abas manualmente. O NexoFlow cria a estrutura automaticamente.

## 2. Google Cloud

Crie ou selecione um projeto no Google Cloud e habilite:

- Google Sheets API
- Google Drive API

## 3. Crie uma Service Account

No Google Cloud, crie uma Service Account e gere uma chave do tipo JSON.
Baixe o arquivo e renomeie para:

`google_credentials.json`

Coloque em:

`credentials/google_credentials.json`

## 4. Compartilhe a planilha

Abra o JSON e localize `client_email`.
Compartilhe a planilha com esse e-mail como **Editor**.

## 5. ID da planilha

Exemplo:

`https://docs.google.com/spreadsheets/d/1AbCdEfGh123456/edit`

O ID é:

`1AbCdEfGh123456`

Cole em `secrets_config.py` no campo `GOOGLE_SPREADSHEET_ID`.

## Segurança

O JSON contém uma chave privada. Não publique em GitHub nem compartilhe fora da equipe responsável.
