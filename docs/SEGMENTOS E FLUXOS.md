# FarmaLíder e Pets Líder

O NexoFlow usa os mesmos aplicativos nos dois segmentos. Ao abrir Weni, Analytics, Planilha, Recompra, Noturno ou Terminal, escolha a marca antes de executar. Instale uma única vez; configure os dois perfis separadamente.

O NexoFlow identifica pedidos registrados na API **independentemente de terem sido feitos por conversa na Weni, ligação telefônica ou outro atendimento externo**. A rotina Weni faz a correspondência com os contatos e retroalimenta a base com os dados disponíveis, propondo criar os cadastros ausentes com identidade e pedido validados. Nos aplicativos individuais, a aplicação segue a revisão solicitada; no Noturno, ela é automática. O canal específico da compra só é informado quando há evidência: estar na API não prova que o pedido veio da Weni ou de uma ligação.

## Configuração por segmento

| Configuração | FarmaLíder | Pets Líder |
| --- | --- | --- |
| Perfil | `FARMA` | `PET` |
| Organização Weni | Delivery FarmaLíder | Delivery Pets Líder |
| Token Weni | Próprio da organização Farma | Próprio da organização Pets |
| API | `clientes/FARMA` | `clientes/PET` |
| Ambiente | Produção | Produção |
| Google Sheets | Dashboard, Operação e Histórico Farma | Dashboard, Operação e Histórico Pets |
| Importações | `importacoes/` | `importacoes/PET/` |
| Logs, revisões e estado | `logs/` | `logs/PET/` |
| Recompra | D+25 | D+30 |
| Referência do evento | `pedido_data` | `pedido_data` |
| Campo de compra confirmada | `ultima_compra` | `compra_recente` |
| Campo principal de marketing | `marketing_opt_in` | `opt_in_marketing`: Sim/Não |
| Maioridade | Regras Farma existentes | Não exigida |
| Produtos no BI/Recompra | Produtos humanos; pedidos mistos usam os itens humanos | Produtos do segmento PET |

Preencha `PERFIS["FARMA"]` e `PERFIS["PET"]` em `secrets_config.py`, conforme o [modelo](../configuracao/secrets_config.example.py). Cada perfil possui token Weni, token autorizado da API e os três IDs de planilhas. A mesma credencial `google_credentials.json` pode ser usada nos dois; compartilhe os seis arquivos com a conta de serviço como Editor. Não use destinos Farma no perfil Pets.

A instalação e o compartilhamento estão nos guias de [instalação](README%20INSTALACAO.md) e [Google Sheets](GOOGLE%20SETUP.md).

## Campos da Weni

Nos dois projetos, configure os campos de canal e `pedido_*` descritos no [guia Weni](README%20WENI.md). **`pedido_data` deve ser Data e hora**. `pedido_id`, `pedido_status`, `pedido_produtos`, `pedido_quantidade_itens`, `pedido_valor_produtos`, `pedido_valor` e `pedido_forma_pagamento` são Texto.

Use Data e hora para `ultima_compra` na Farma e `compra_recente` no Pets. No Pets, mantenha `opt_in_marketing` e `opt_in_lgpd` como Texto, com Sim/Não, sem recriar o campo antigo `marketing_opt_in` nem exigir o campo de maioridade. Grupo Opt-Out Marketing e recusas continuam bloqueando a Recompra.

## Campanhas e fluxos de Recompra

| Elemento na Weni | FarmaLíder | Pets Líder |
| --- | --- | --- |
| Grupo e campanha | Recompra FarmaLíder | Recompra Pets Líder |
| Fluxo | Recompra FarmaLíder D+25 | Recompra Pets Líder D+30 |
| Evento | 25 dias depois de `pedido_data` | 30 dias depois de `pedido_data` |

Configure ou importe o fluxo na organização correspondente, selecione-o no evento da campanha e confira os campos, grupos, template aprovado e destino do atendimento. Use apenas o evento vigente de cada campanha, evitando duplicar o agendamento. Não use o antigo evento Pets baseado em Compra recente.

Antes do template, o fluxo deve bloquear status 3/Cancelado, pagamento cancelado ou não elegível, recusa/Opt-Out e data fora do D+25 ou D+30. O NexoFlow Recompra faz a validação preventiva antes de alimentar o grupo. O envio das mensagens pertence à campanha Weni.

No fluxo Pets, **Comprar novamente** encaminha para a fila de Atendimento do Delivery Pets Líder; **Não preciso** encerra essa oferta; **SAIR** registra Não em `opt_in_marketing` e mantém o bloqueio de marketing. Cada organização usa seu próprio template e seus próprios vínculos de atendimento.

Depois de conferir grupo, campanha, fluxo, evento e template, habilite `RECOMPRA_ENABLED` no perfil desejado. Use o executável Recompra para gerar a revisão ou `comandos/auditar_grupo_recompra.bat` para conferir os integrantes sem alterar dados. Consulte [Recompra](README%20RECOMPRA.md).

## Rastreamento de anúncios e atendimento

Os fluxos de rastreamento na Weni devem pertencer ao projeto da marca, preservando os metadados de origem do anúncio nos campos `primeiro_anuncio_*` e `ultimo_anuncio_*`. O NexoFlow usa apenas evidências recebidas; um telefone cadastrado ou um pedido da API não comprova origem em anúncio ou venda pela Weni.

O rastreamento de anúncios recebidos pela Weni é diferente da integração de custos e campanhas com a Meta Marketing API, que continua futura. Veja [Meta](META%20FUTURO.md) e [Google Ads](GOOGLE%20ADS.md). Os fluxos, templates, filas e eventos são configurados na Weni; a instalação do NexoFlow não os importa nem os cria automaticamente.

## Cargas, histórico e dashboard

Execute **Weni → Analytics** na marca escolhida, ou use o Noturno. Planilha e Recompra seguem a mesma seleção de perfil. A Weni propõe os cadastros ausentes com identidade/pedido validados; não presume consentimento nem inclui grupos na criação. Falhas isoladas ficam pendentes.

A Weni mantém o pedido mais recente. O Analytics acumula os pedidos observados por ID e atualiza as tabelas `BI_*` do Dashboard do segmento. A API de último pedido não recupera compras intermediárias nunca observadas. Preserve os logs ao atualizar, incluindo o histórico local ainda não entregue ao Sheets.

Para um painel Pets com o mesmo desenho do Farma, duplique o relatório no Data Studio e substitua **cada fonte** pela aba `BI_*` equivalente do Dashboard Pets. Confira filtros, datas e atualização antes de compartilhar. As planilhas têm o mesmo esquema; a separação dos arquivos identifica a marca. O NexoFlow atualiza os dados, sem duplicar automaticamente o relatório do Data Studio.

## Novos departamentos e segmentos

O NexoFlow já tem arquitetura organizada por perfis para inclusão de novos departamentos e segmentos. A habilitação inclui registrar o novo perfil nos seletores e configurar organização Weni, credenciais, API autorizada, destinos Sheets, campos, fluxos e regras próprias, com validação antes de ativar. Os perfis operacionais disponíveis nesta versão são **FARMA** e **PET**. Não basta acrescentar credenciais: o cadastro do perfil deve abranger os menus e a execução correspondente. Reaproveite os componentes comuns e mantenha dados e regras próprios do novo segmento.
