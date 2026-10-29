# NexoFlow 1.0 — Instalação

## Requisitos

- Windows x64.
- Python 3.11 ou superior, 64 bits. O Setup oferece o Python 3.14.8 x64 incluído se não encontrar um compatível.
- Acesso às integrações Weni, FarmaLíder e Google Sheets, com suas próprias credenciais.

## Instalar

1. Baixe [NexoFlow-Setup-1.0.zip](https://github.com/felipetelesbarbosa/NexoFlow/releases/download/v1.0/NexoFlow-Setup-1.0.zip).
2. Extraia todo o pacote e execute **NexoFlow Setup.exe**. Autorize a instalação quando o Windows solicitar.
3. Conclua o assistente. O destino padrão é `C:\NexoFlow`, com atalhos dos aplicativos na Área de Trabalho e no Menu Iniciar.

O [release](https://github.com/felipetelesbarbosa/NexoFlow/releases/tag/v1.0) também oferece o projeto completo e o arquivo de hashes dos pacotes.

## Configurar os acessos

| Integração | Configuração |
| --- | --- |
| Weni e FarmaLíder | Use `configuracao/secrets_config.example.py` como modelo para criar `C:\NexoFlow\secrets_config.py`. Preencha os seus tokens e as opções aplicáveis. |
| Google Sheets | Salve a sua credencial em `C:\NexoFlow\credentials\google_credentials.json`, configure o ID da planilha e compartilhe o arquivo como **Editor** com a conta de serviço. |
| Proxy | Se necessário, siga o [guia de rede e proxy](README%20PROXY.md). |

Para configurar a conta Google, consulte [Google Sheets](GOOGLE%20SETUP.md). Se houver destinos separados de operação e histórico, confira a [divisão em três arquivos](planilhas_separadas.md).

O NexoFlow não inclui chaves, tokens nem credenciais. Mantenha seus acessos privados.

## Preparar a Weni

Crie os campos abaixo como **Texto**, quando ainda não existirem:

| Grupo | Campos |
| --- | --- |
| Canais | `contact_urn_whatsapp`, `contact_urn_instagram`, `contact_urn_facebook`, `contact_canal_principal` |
| Pedidos | `pedido_id`, `pedido_data`, `pedido_status`, `pedido_produtos`, `pedido_quantidade_itens`, `pedido_valor_produtos`, `pedido_valor`, `pedido_forma_pagamento` |

Confira também os grupos operacionais e os campos opcionais no [guia Weni](README%20WENI.md). A [Recompra D+25](README%20RECOMPRA.md) tem configuração própria de grupo, campos e campanha.

## Validar e executar a primeira carga

Abra **NexoFlow Terminal** e execute:

```text
nexo diagnostico
```

Depois, siga o [guia de operação](Documentacao%20NexoFlow.md): **Weni completa → Planilha, quando houver exports → Analytics completo → Recompra → Analytics incremental**. Revise os relatórios solicitados. Finalize atualizando os dados e os campos necessários no Looker Studio.

As cargas completas oferecem **100%** ou quatro partes de **25%**. Execute as partes em ordem, separadamente para Weni e Analytics. Não avance para a parte seguinte do Analytics se a anterior terminou parcial ou com erro.

## Atualizar

Encerre as rotinas e execute o novo **NexoFlow Setup.exe**. O instalador preserva `secrets_config.py`, `credentials/`, `logs/` e `importacoes/`.

Após atualizar, rode o diagnóstico e gere novas revisões antes de aplicar mudanças. Faça carga completa quando precisar revalidar a base ou preencher novos campos. O [histórico de mudanças](../CHANGELOG.md) informa os ajustes de cada publicação.

## Desinstalar

Use **Configurações do Windows → Aplicativos instalados → NexoFlow**, o atalho do Menu Iniciar ou `C:\NexoFlow\desinstalar_nexoflow.cmd`. O executável Uninstall é opcional.

O desinstalador remove o programa e os atalhos. As importações são preservadas em `C:\NexoFlow Data\importacoes`; a preservação das demais configurações e dos logs é opcional. Uma reinstalação restaura os arquivos preservados. O Python global permanece instalado.

## Se houver problema

Consulte o resultado exibido e os arquivos em `logs/`. Na verificação de integridade, o Setup aguarda até 30 segundos por arquivo com bloqueio temporário de leitura. Ele não dispensa a validação SHA-256. Se uma pasta ou um arquivo continuar em uso, encerre as rotinas e as janelas abertas nessa instalação antes de tentar novamente. Para alertas do antivírus corporativo, consulte o [guia de confiança](ANTIVIRUS%20E%20CONFIANCA.md).
