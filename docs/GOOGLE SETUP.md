# Google Sheets — FarmaLíder e Pets Líder

O NexoFlow usa uma conta de serviço Google para atualizar as planilhas. A mesma credencial pode atender aos dois segmentos; os arquivos são próprios de cada marca.

## Criar e compartilhar os arquivos

Para cada segmento, crie **Dashboard**, **Operação** e **Histórico**. Com os dois perfis ativos, são seis arquivos. Sugestão de organização no Drive:

```text
NexoFlow/
  FarmaLíder/
    Dashboard
    Operação
    Histórico
  Pets Líder/
    Dashboard
    Operação
    Histórico
```

No Google Cloud, habilite Google Sheets API e Google Drive API. Crie uma conta de serviço ou use a que já está configurada e autorizada. Salve sua chave JSON em `C:\NexoFlow\credentials\google_credentials.json`.

Localize `client_email` nesse JSON e compartilhe **cada um dos arquivos** como **Editor** com esse e-mail. Usar o mesmo JSON não compartilha automaticamente novos arquivos.

## Configurar os perfis

No arquivo `secrets_config.py`, preencha em `PERFIS["FARMA"]` e `PERFIS["PET"]`:

- `GOOGLE_SPREADSHEET_ID`: Dashboard.
- `GOOGLE_OPERATIONS_SPREADSHEET_ID`: Operação.
- `GOOGLE_HISTORY_SPREADSHEET_ID`: Histórico.

Em `https://docs.google.com/spreadsheets/d/{id}/edit`, copie somente `{id}`. Use os IDs da marca correta. O [modelo de configuração](../configuracao/secrets_config.example.py) mostra a estrutura.

O NexoFlow cria as abas necessárias; não copie dados Farma para inicializar o Pets. Para separar uma instalação que já usa um único arquivo, siga a [migração em três destinos](planilhas_separadas.md). Confira o mapa `NexoFlow_Arquivos` do Dashboard antes de executar.

## Validar e conectar o dashboard

Abra o Terminal, escolha o perfil e execute `nexo diagnostico`. Depois rode Weni e Analytics na mesma marca. O Analytics preenche as abas `BI_*` do Dashboard correspondente.

No Data Studio, a conta responsável pelas fontes precisa ter acesso ao Dashboard. Ao duplicar o painel Farma para Pets, substitua todas as fontes pelas abas Pets equivalentes. Veja [Data Studio](DATA%20STUDIO.md).

O projeto não inclui credenciais. Use seus próprios acessos e mantenha o JSON privado.
