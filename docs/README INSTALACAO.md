# NexoFlow 1.5.8 — Instalação

## Requisitos

- Windows x64.
- Python 3.11 ou superior, 64 bits. O Setup oferece o Python 3.14.8 x64 incluído se não encontrar um compatível.
- Acesso à Weni, à API FarmaLíder e ao Google Sheets, com suas próprias credenciais para FarmaLíder e/ou Pets Líder.

## Instalar

1. Baixe [NexoFlow-Setup-1.5.8.zip](https://github.com/felipetelesbarbosa/NexoFlow/releases/download/v1.5.8/NexoFlow-Setup-1.5.8.zip).
2. Extraia todo o pacote e execute **NexoFlow Setup.exe**. Autorize a instalação quando o Windows solicitar.
3. Conclua o assistente. O destino padrão é `C:\NexoFlow`, com atalhos dos aplicativos na Área de Trabalho e no Menu Iniciar.

O [release](https://github.com/felipetelesbarbosa/NexoFlow/releases/tag/v1.5.8) também oferece o projeto completo e o arquivo de hashes dos pacotes.

## Configurar os acessos

| Integração | Configuração |
| --- | --- |
| Weni e FarmaLíder | Use `configuracao/secrets_config.example.py` como modelo para criar `C:\NexoFlow\secrets_config.py`. Preencha os tokens e os três IDs de Sheets em `PERFIS["FARMA"]` e `PERFIS["PET"]`, nas organizações corretas. |
| Google Sheets | Salve a sua credencial em `C:\NexoFlow\credentials\google_credentials.json`, configure Dashboard, Operação e Histórico de cada segmento e compartilhe cada arquivo como **Editor** com a conta de serviço. |
| Proxy | Se necessário, siga o [guia de rede e proxy](README%20PROXY.md). |

A mesma credencial Google pode atender aos dois perfis; as planilhas e os tokens Weni são próprios de cada marca. O ambiente da API é produção nos dois perfis. Veja [segmentos e fluxos](SEGMENTOS%20E%20FLUXOS.md).

Para configurar a conta Google, consulte [Google Sheets](GOOGLE%20SETUP.md). Se houver destinos separados de operação e histórico, confira a [divisão em três arquivos](planilhas_separadas.md).

O NexoFlow não inclui chaves, tokens nem credenciais. Mantenha seus acessos privados.

## Preparar a Weni

Configure os campos em cada projeto Weni, respeitando os tipos:

| Tipo | Campos |
| --- | --- |
| Texto — canais | `contact_urn_whatsapp`, `contact_urn_instagram`, `contact_urn_facebook`, `contact_canal_principal` |
| Texto — pedidos | `pedido_id`, `pedido_status`, `pedido_produtos`, `pedido_quantidade_itens`, `pedido_valor_produtos`, `pedido_valor`, `pedido_forma_pagamento` |

`pedido_data` é **Data e hora** nos dois projetos. `ultima_compra` (Farma) e `compra_recente` (Pets) também são Data e hora. No Pets, use `opt_in_marketing` e `opt_in_lgpd` como Texto, com Sim/Não; não há exigência de maioridade.

Confira também os grupos operacionais e os campos opcionais no [guia Weni](README%20WENI.md). As campanhas [Farma D+25 e Pets D+30](README%20RECOMPRA.md) têm grupo, fluxo, template e evento próprios, usando `pedido_data`.

A arquitetura permite incluir novos departamentos e segmentos mediante registro e configuração do perfil, das integrações e das regras, com validação antes da ativação. Consulte [expansão por perfis](SEGMENTOS%20E%20FLUXOS.md#novos-departamentos-e-segmentos).

A rotina Weni retroalimenta os contatos a partir dos pedidos da API do segmento, inclusive compras realizadas fora da Weni. Execute Weni antes de Analytics para consolidar cadastros, pedidos e histórico. Os aplicativos individuais mantêm a revisão; o Noturno aplica automaticamente.

## Validar e executar a primeira carga

Abra **NexoFlow Terminal**, escolha FarmaLíder ou Pets Líder e execute:

```text
nexo diagnostico
```

Depois, siga o [guia de operação](Documentacao%20NexoFlow.md): **Weni completa → Planilha, quando houver exports → Analytics completo → Recompra → Analytics incremental**. Revise os relatórios solicitados. Finalize atualizando os dados e os campos necessários no Data Studio.

As cargas completas oferecem **100%** ou quatro partes de **25%**. Execute as partes em ordem, separadamente para Weni e Analytics. Não avance para a parte seguinte do Analytics se a anterior terminou parcial ou com erro.

## Atualizar

Encerre as rotinas dos dois segmentos e execute o novo **NexoFlow Setup.exe**. Quando houver instalação ou dados anteriores, escolha:

- **Atualizar mantendo dados:** preserva `secrets_config.py`, `credentials/`, `logs/` e o estado de FarmaLíder/Pets Líder.
- **Instalação limpa:** reinicia esses dados locais nos dois segmentos. Configure os acessos novamente e gere novas cargas e revisões.
- **Cancelar:** encerra sem alterar a instalação.

Os arquivos de `importacoes/` são preservados nas duas opções. O Setup não exclui dados na Weni ou no Google Sheets. Se a instalação falhar, tenta restaurar a versão anterior com seus dados.

A série atual é 1.5; patches posteriores seguem 1.5.8 até 1.5.99, antes de 1.6. A versão instalada aparece no Terminal e nos metadados dos aplicativos.

Após atualizar, rode o diagnóstico e gere novas revisões antes de aplicar mudanças. Faça carga completa quando precisar revalidar a base ou preencher novos campos. O [histórico de mudanças](../CHANGELOG.md) informa os ajustes de cada publicação.

## Desinstalar

Use **Configurações do Windows → Aplicativos instalados → NexoFlow**, o atalho do Menu Iniciar ou `C:\NexoFlow\desinstalar_nexoflow.cmd`. O executável Uninstall é opcional.

O desinstalador remove o programa e os atalhos. As importações são preservadas em `C:\NexoFlow Data\importacoes`; a preservação das demais configurações e dos logs é opcional. Na reinstalação, escolha atualizar mantendo dados para recuperar configurações e logs preservados. O Python global permanece instalado.

## Se houver problema

Consulte o resultado exibido e os arquivos em `logs/`. Na verificação de integridade, o Setup aguarda até 30 segundos por arquivo com bloqueio temporário de leitura. O tempo de espera aparece no terminal; uma leitura que não responde também encerra no prazo. Arquivos abertos com compartilhamento de leitura são verificados sem modificá-los. O Setup reconfere a cópia instalada antes de executar a preparação do Python e não dispensa a validação SHA-256. Se uma pasta ou um arquivo continuar em uso, encerre as rotinas e as janelas abertas nessa instalação antes de tentar novamente. Para alertas do antivírus corporativo, consulte o [guia de confiança](ANTIVIRUS%20E%20CONFIANCA.md).

Se o Windows impedir a leitura ou a cópia do launcher `NexoFlow Noturno.exe`, o Setup usa `comandos/executar_noturno.bat` no mesmo atalho. O motor, os scripts e o ícone continuam obrigatórios e têm sua integridade conferida. O EXE indisponível não é utilizado. Não é necessário desativar o antivírus ou mudar permissões para essa opção.

## Capacidade e confiança na distribuição

Para criar continuações no Meu Drive, configure a autorização Google local e depois as fontes do Data Studio; confira [CONTINUACOES.md](CONTINUACOES.md). O Setup preserva credenciais e não configura fontes do relatório sozinho.

O ZIP contém `RELATORIO DE SEGURANCA.json` com o estado das assinaturas. Certificados autoassinados locais não conferem confiança pública. Veja [assinatura Windows](ASSINATURA%20WINDOWS.md) e [antivírus](ANTIVIRUS%20E%20CONFIANCA.md).
