# NexoFlow 1.5.5 — Guia de operação

O NexoFlow integra Weni e a API FarmaLíder para **FarmaLíder e Pets Líder**, mantendo dados separados por perfil. O objetivo é manter contatos e pedidos atualizados e alimentar o Google Sheets e os painéis do Data Studio.

O NexoFlow identifica pedidos registrados na API **independentemente de terem sido feitos por conversa na Weni, ligação telefônica ou outro atendimento externo**. A rotina Weni faz a correspondência com os contatos e retroalimenta a base com os dados disponíveis, propondo criar os cadastros ausentes com identidade e pedido validados. Nos aplicativos individuais, a aplicação segue a revisão solicitada; no Noturno, ela é automática. O canal específico da compra só é informado quando há evidência: estar na API não prova que o pedido veio da Weni ou de uma ligação.

## Escolha o aplicativo

| Aplicativo | Uso |
| --- | --- |
| **Weni** | Atualizar cadastros, pedidos e grupos; excluir duplicados confirmados após revisão. |
| **Analytics** | Atualizar a base, o histórico de pedidos e as tabelas analíticas do Sheets. |
| **Planilha** | Revalidar exports de conversas e contatos antes de atualizar Weni ou Analytics. |
| **Recompra** | Revisar e aplicar a elegibilidade das campanhas FarmaLíder D+25 e Pets Líder D+30. |
| **Noturno** | Executar Weni, Analytics e Recompra na marca escolhida sem confirmações durante a carga. |
| **Terminal** | Executar comandos, consultar dados e diagnosticar a instalação. |

## Antes de começar

Instale pelo [Setup oficial](https://github.com/felipetelesbarbosa/NexoFlow/releases/tag/v1.5.5), configure suas próprias credenciais e compartilhe as planilhas com a conta de serviço Google. O diretório padrão é `C:\NexoFlow`. Confira os requisitos e os campos necessários no [guia de instalação](README%20INSTALACAO.md).

Abra o mesmo aplicativo e escolha **FarmaLíder** ou **Pets Líder** antes da carga. Configure tokens Weni e três destinos Sheets em cada perfil. A credencial Google pode ser compartilhada. Veja [configuração dos segmentos e fluxos](SEGMENTOS%20E%20FLUXOS.md).

Abra **NexoFlow Terminal** no perfil desejado e execute:

```text
nexo diagnostico
```

Resolva as pendências de conexão ou configuração antes das cargas. Evite executar cargas simultâneas que gravem na mesma base.

## Atualização completa

| Ordem | O que executar |
| --- | --- |
| 1 | **Weni:** `comandos/atualizar_weni_carga_completa.bat`, opção **[0] 100%**; revise e confirme a aplicação. |
| 2 | **Planilha, se houver exports:** opção **[1] Atualizar Weni**, depois **[2] Atualizar Analytics e Google Sheets**; revise cada destino. |
| 3 | **Analytics:** `comandos/executar_carga_completa.bat`, opção **[0] 100%**. |
| 4 | **Recompra:** abra o aplicativo, gere a revisão e confirme depois de conferir as pendências. |
| 5 | **Analytics:** sincronização incremental; em seguida, atualize o Data Studio. |

Com os dois exports em `importacoes/` (Farma) ou `importacoes/PET/` (Pets), `comandos/atualizar_tudo.bat` executa essa sequência e aguarda as revisões. Falha, cancelamento ou resultado parcial interrompe o fluxo.

Sem exports, execute as etapas necessárias pelos aplicativos e dispense a etapa Planilha. Para cargas em partes, siga **1 → 2 → 3 → 4** separadamente na Weni e no Analytics. Uma parte do Analytics com erro ou resultado parcial precisa ser concluída antes da próxima.

## Rotina diária

1. Execute **NexoFlow Weni** para atualizar contatos, pedidos e grupos.
2. Execute **NexoFlow Recompra** quando precisar revisar a campanha Farma D+25 ou Pets D+30.
3. Execute **NexoFlow Analytics** para refletir as alterações no Sheets.
4. Atualize os dados do painel no Data Studio.

A atualização da Recompra após a Weni pode ser habilitada na configuração; confira o resultado antes de executá-la novamente. Os [guias dos aplicativos](README.md) detalham suas opções.

## Carga por planilhas

Coloque os exports originais, sem alterar abas ou cabeçalhos, em `C:\NexoFlow\importacoes` (Farma) ou `C:\NexoFlow\importacoes\PET` (Pets):

```text
Conversas_Delivery.xlsx
Contatos_Delivery.xlsx
```

Abra **NexoFlow Planilha**. A opção 1 atualiza a Weni; a opção 2 atualiza Analytics e Google Sheets. Cada destino tem relatório e confirmação próprios. Veja [Planilha e Delivery](README%20DELIVERY.md).

## Revisão, progresso e pendências

**Dry-run** é a simulação anterior à aplicação. Leia o relatório e confirme somente as alterações esperadas. Na carga completa Weni, digite `CARGA COMPLETA REVISADA` quando solicitado.

O log da Weni apresenta percentual, lotes de 1.000 contatos, velocidade e tempo restante. Durante esperas, há atualizações a cada 15 segundos. Bloqueios repetidos são resumidos por motivo, com detalhes no relatório privado. Enquanto o total é desconhecido, a coleta mostra a quantidade recebida.

Os resumos distinguem contatos processados, pedidos validados e alterações aplicadas. Essas contagens não equivalem a pedidos únicos. Falhas isoladas na Weni ficam para a próxima incremental; um resultado parcial do Analytics exige conferir o log e repetir a carga ou a mesma parte. Para aplicação parcial de Planilha ou Recompra, siga a retomada indicada no relatório antes de gerar outra revisão.

Os arquivos ficam em `logs/`. Para acompanhar a Weni pelo Terminal:

```text
nexo logs weni --seguir
```

## Pedidos e Recompra

A API FarmaLíder confirma os dados do cliente e do pedido. CPF válido dispensa comparação de nome, telefone ou e-mail; identificadores inválidos consultáveis exigem primeiro nome ou telefone local correspondente. Cadastros ambíguos ficam pendentes. Veja [regras de pedidos](PEDIDOS.md).

Todos os status documentados não cancelados contam como venda validada. Status 3, pagamento cancelado e pedidos oficialmente sem itens ficam fora das vendas. O Analytics reconsulta o status dos pedidos já registrados de hoje até 20 dias atrás; preserva os anteriores e continua buscando novas compras.

Na **FarmaLíder**, o recorte comercial inclui produtos para humanos. Em pedidos mistos, entram somente os itens humanos e seu valor, sem o frete do pedido inteiro. Pedidos apenas pet ou veterinários são excluídos. No **Pets Líder**, são preservados os produtos do segmento PET, sem exigência de maioridade. A listagem do segmento ajuda a reduzir consultas; o [cadastro oficial](CADASTRO%20FARMA.md) explica as validações.

A Recompra mantém o grupo para compras confirmadas entre D+0 e D+25 (Farma) ou D+0 e D+30 (Pets), bloqueando recusas de marketing. O envio ocorre no D+25/D+30 pela campanha Weni, usando `pedido_data` nos dois eventos. Veja [Recompra](README%20RECOMPRA.md).

## Google Sheets e Data Studio

O Analytics alimenta as planilhas; o Data Studio lê as fontes conectadas a elas. Atualizar o Sheets não cria nem configura os gráficos automaticamente.

A configuração pode separar **Operação**, **Histórico** e **Dashboard** em três arquivos. As abas `BI_*` ficam no arquivo de dashboard; confira os destinos no [guia de divisão](planilhas_separadas.md).

Depois de uma atualização, confira a data da última carga, atualize os dados do painel e, se houver novas colunas, os campos das fontes. Cada segmento tem seu próprio arquivo Dashboard. Para usar o mesmo desenho no Pets, duplique o relatório e substitua todas as fontes pelas abas `BI_*` Pets correspondentes.

A Weni propõe criar clientes ausentes com pedido/identidade validados, sem presumir consentimentos ou grupos. Pedidos completos observados são guardados localmente e entregues pelo Analytics ao Sheets por ID. Preserve os logs ao atualizar.

O histórico cobre os pedidos capturados nas coletas; a API de último pedido não comprova todas as compras antigas. As fórmulas, fontes e limites dos indicadores estão no [guia do Data Studio](DATA%20STUDIO.md).

## Expansão por perfis

O NexoFlow já tem arquitetura organizada por perfis para inclusão de novos departamentos e segmentos. A habilitação inclui registrar o novo perfil nos seletores e configurar organização Weni, credenciais, API autorizada, destinos Sheets, campos, fluxos e regras próprias, com validação antes de ativar. Os perfis operacionais disponíveis nesta versão são **FARMA** e **PET**.

## Terminal e referências

No **NexoFlow Terminal**, `nexo` abre o menu e `nexo ajuda` lista os comandos. Referência completa: [docs/README TERMINAL.md](README%20TERMINAL.md).

[Instalação](README%20INSTALACAO.md) · [Weni](README%20WENI.md) · [Planilha](README%20DELIVERY.md) · [Recompra](README%20RECOMPRA.md) · [Proxy](README%20PROXY.md) · [Documentação por assunto](README.md)

O NexoFlow é distribuído sem chaves, tokens ou credenciais. Configure seus próprios acessos e mantenha-os privados. Veja [Segurança](../SECURITY.md).
