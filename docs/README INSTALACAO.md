# Instalação do NexoFlow Windows

## Requisitos

- Windows x64.
- Python 3.11 ou superior, 64 bits. O Setup oferece baixar o Python 3.14.8 x64 do site oficial, com SHA-256 conferido, se não encontrar um compatível. O instalador Python não acompanha os ZIPs.
- Credenciais da Weni e da API FarmaLíder para o segmento usado.
- Credencial do destino de publicação do perfil. Na operação FARMA com a VPS, use a credencial da API publicadora PostgreSQL. Perfis legados em modo Sheets usam a conta de serviço Google.

## Instalar

1. Abra as [releases do NexoFlow](https://github.com/felipetelesbarbosa/NexoFlow/releases/latest) e baixe o arquivo `NexoFlow-Setup-<versão>.zip` da versão estável. O [guia operacional](OPERACAO_WINDOWS_VPS.md) identifica os pacotes de homologação e os destinos correspondentes.
2. Extraia todo o pacote e execute **NexoFlow Setup.exe**. Autorize a instalação quando o Windows solicitar.
3. Conclua o assistente. O destino padrão é `C:\NexoFlow`, com atalhos dos aplicativos na Área de Trabalho e no Menu Iniciar.

A página da release também oferece o projeto completo e os hashes dos pacotes.

## Configurar os acessos

| Integração | Configuração |
| --- | --- |
| Weni e FarmaLíder | Use o [modelo de configuração](../configuracao/secrets_config.example.py) para criar `C:\NexoFlow\secrets_config.py`. Preencha as credenciais em `PERFIS["FARMA"]` ou `PERFIS["PET"]` conforme a organização usada. |
| PostgreSQL na VPS | No perfil ativo, confira `ARMAZENAMENTO_BACKEND = "postgres"`, `DATASTUDIO_AMBIENTE` e `DATASTUDIO_CREDENTIALS_FILE`. Use a credencial privada da API publicadora para o mesmo perfil e ambiente. [Guia operacional](OPERACAO_WINDOWS_VPS.md) |
| Google Sheets legado | No perfil em modo Sheets, configure `credentials/google_credentials.json`, os três IDs de Dashboard, Operação e Histórico e a permissão de edição da conta de serviço. [Configuração Google](GOOGLE%20SETUP.md) |
| Proxy | Se necessário, siga o [guia de rede e proxy](README%20PROXY.md). |

Cada marca tem sua própria organização Weni e seu próprio perfil. O exemplo do repositório conserva os valores legados e de homologação. Confira explicitamente o destino antes de usar a instalação comercial. [Segmentos e fluxos](SEGMENTOS%20E%20FLUXOS.md)

O NexoFlow não inclui chaves, tokens nem credenciais. Mantenha seus acessos privados.

## Preparar a Weni

Configure os campos em cada projeto Weni, respeitando os tipos:

| Tipo | Campos |
| --- | --- |
| Texto — canais | `contact_urn_whatsapp`, `contact_urn_instagram`, `contact_urn_facebook`, `contact_canal_principal` |
| Texto — pedidos | `pedido_id`, `pedido_status`, `pedido_produtos`, `pedido_quantidade_itens`, `pedido_valor_produtos`, `pedido_valor`, `pedido_forma_pagamento` |

`pedido_data` é **Data e hora** nos dois projetos. Na Farma, `ultimo_pedido` é Texto para o ID oficial; não é exigido `ultima_compra`. No Pets, `compra_recente` é Data e hora. No Pets, use `opt_in_marketing` e `opt_in_lgpd` como Texto, com Sim/Não; não há exigência de maioridade.

Confira também os grupos operacionais e os campos opcionais no [guia Weni](README%20WENI.md). As campanhas [Farma D+25 e Pets D+30](README%20RECOMPRA.md) têm grupo, fluxo, template e evento próprios, usando `pedido_data`.

A arquitetura permite incluir novos departamentos e segmentos mediante registro e configuração do perfil, das integrações e das regras, com validação antes da ativação. Consulte [expansão por perfis](SEGMENTOS%20E%20FLUXOS.md#novos-departamentos-e-segmentos).

A rotina Weni retroalimenta os contatos a partir dos pedidos da API do segmento, inclusive compras realizadas fora da Weni. Execute Weni antes de Analytics para consolidar cadastros, pedidos e histórico. Os aplicativos individuais mantêm a revisão; o Noturno aplica automaticamente.

## Validar e executar a primeira carga

Abra **NexoFlow Terminal**, escolha FarmaLíder ou Pets Líder e execute:

```text
nexo diagnostico
```

Para um perfil PostgreSQL, rode também `nexo armazenamento postgres diagnosticar` e confira segmento, ambiente e revisão ativa, conforme o [guia operacional](OPERACAO_WINDOWS_VPS.md#conferir-o-windows-antes-de-uma-carga).

Depois, siga o [guia de operação](Documentacao%20NexoFlow.md): **Weni completa → Planilha, quando houver exports → Analytics completo → Recompra → Analytics incremental**. Revise os relatórios solicitados. Finalize atualizando os dados e os campos necessários no Data Studio.

As cargas completas oferecem **100%** ou quatro partes de **25%**. Execute as partes em ordem, separadamente para Weni e Analytics. Não avance para a parte seguinte do Analytics se a anterior terminou parcial ou com erro.

## Atualizar

Encerre as rotinas dos dois segmentos e execute o novo **NexoFlow Setup.exe**. Quando houver instalação ou dados anteriores, escolha:

- **Atualizar mantendo dados:** preserva `secrets_config.py`, `credentials/`, `logs/` e o estado de FarmaLíder/Pets Líder.
- **Instalação limpa:** reinicia esses dados locais nos dois segmentos. Configure os acessos novamente e gere novas cargas e revisões.
- **Cancelar:** encerra sem alterar a instalação.

Os arquivos de `importacoes/` são preservados nas duas opções. Se a instalação falhar, o Setup tenta restaurar a versão anterior com seus dados.

Confira a versão instalada no Terminal com `nexo versao` e nos metadados dos aplicativos.

Após atualizar, rode o diagnóstico e gere novas revisões antes de aplicar mudanças. Faça carga completa quando precisar revalidar a base ou preencher novos campos. O [histórico de mudanças](../CHANGELOG.md) informa os ajustes de cada publicação.

## Desinstalar

Use **Configurações do Windows → Aplicativos instalados → NexoFlow**, o atalho do Menu Iniciar ou `C:\NexoFlow\desinstalar_nexoflow.cmd`. O executável Uninstall é opcional.

O desinstalador remove o programa e os atalhos. As importações são preservadas em `C:\NexoFlow Data\importacoes`; a preservação das demais configurações e dos logs é opcional. Na reinstalação, escolha atualizar mantendo dados para recuperar configurações e logs preservados. O Python global permanece instalado.

## Se houver problema

Consulte o resultado exibido e os arquivos em `logs/`. Na verificação de integridade, o Setup aguarda até 30 segundos por arquivo com bloqueio temporário de leitura. O tempo de espera aparece no terminal; uma leitura que não responde também encerra no prazo. Arquivos abertos com compartilhamento de leitura são verificados sem modificá-los. O Setup reconfere a cópia instalada antes de executar a preparação do Python e não dispensa a validação SHA-256. Se uma pasta ou um arquivo continuar em uso, encerre as rotinas e as janelas abertas nessa instalação antes de tentar novamente. Para alertas do antivírus corporativo, consulte o [guia de confiança](ANTIVIRUS%20E%20CONFIANCA.md).

Se o Windows impedir a leitura ou a cópia do launcher `NexoFlow Noturno.exe`, o Setup usa `comandos/executar_noturno.bat` no mesmo atalho. O motor, os scripts e o ícone continuam obrigatórios e têm sua integridade conferida. O EXE indisponível não é utilizado. Não é necessário desativar o antivírus ou mudar permissões para essa opção.

## Capacidade e confiança na distribuição

Continuações no Meu Drive fazem parte do modo Sheets legado. [Guia de continuações](CONTINUACOES.md)

A publicação PostgreSQL e o vínculo das fontes do Looker têm configuração própria. [Guia operacional](OPERACAO_WINDOWS_VPS.md)

O ZIP contém `RELATORIO DE SEGURANCA.json` com o estado das assinaturas. Certificados autoassinados locais não conferem confiança pública. Veja [assinatura Windows](ASSINATURA%20WINDOWS.md) e [antivírus](ANTIVIRUS%20E%20CONFIANCA.md).

## Atualização com dados locais abertos

Na opção de atualizar mantendo dados, o Setup conserva `secrets_config.py`, `credentials`, `logs` e `importacoes` no lugar. Um handle de Explorer/terminal que impede renomear essas pastas não exige apagar logs ou estado. O backup privado continua obrigatório; apenas o programa é preparado para rollback. Se a instalação falhar, o programa anterior é restaurado sem remover os dados preservados. Arquivos novos do programa continuam sujeitos à validação de integridade; bloqueios de leitura/gravação não são ignorados. Encerre as cargas FARMA e PET antes de instalar.

A instalação limpa reinicia configuração/estado e precisa conseguir mover os dados anteriores para a recuperação. Se houver bloqueio, ela aborta preservando a instalação anterior; não é convertida silenciosamente em atualização.

## Conclusão e coleta Meta Ads

Confira no resumo do Setup o modo de instalação, a pasta de destino, o log e os seis atalhos de Analytics, Weni, Recompra, Terminal, Planilha e Noturno. Use `comandos/check-up.bat` para verificar os componentes locais e `comandos/testar_conexoes.bat` para o diagnóstico de conexão antes da carga.

Na 1.5.42, o Setup instala o cliente nativo de leitura da Meta junto com o Analytics e encerra sem oferecer Meta Ads MCP ou Codex CLI. Na atualização em modo **Preserve**, mantenha a credencial Meta já existente em `credentials/mcp/meta_ads_credentials.json` e a configuração dos perfis em `secrets_config.py`. O nome histórico da pasta `mcp` continua sendo usado pelo cliente nativo. [Guia de ativação e revisão da coleta Meta](META%20ADS%20NATIVO.md).
