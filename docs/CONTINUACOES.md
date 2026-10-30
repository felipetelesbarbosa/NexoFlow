# Continuações de planilhas — NexoFlow

A partir da 1.5.5, Operação, Histórico e tabelas BI podem continuar em novos arquivos do Meu Drive. Os três arquivos configurados em cada perfil continuam sendo as origens; o NexoFlow registra suas continuações na aba `NexoFlow_Continuidade` do Dashboard.

## Capacidade e histórico

A reserva considera células **alocadas**, inclusive grades vazias de todas as abas. O padrão abre uma continuação antes de ultrapassar **18 milhões de células por arquivo** ou **500 mil linhas por parte**, contando o cabeçalho. O limite configurado é 20 milhões de células por arquivo; o número de linhas depende da quantidade de colunas. A margem não é uma garantia contra edições simultâneas feitas manualmente.

As leituras e os upserts percorrem as partes registradas. Uma atualização de status pode corrigir o pedido na parte antiga, sem copiá-lo para a atual. O histórico existente é preservado. Isso acumula o histórico observado pelo NexoFlow; não recupera compras anteriores que a API nunca entregou.

Não apague, renomeie ou mova manualmente as continuações, suas abas ou o índice. Preserve os logs privados e comprovantes no computador da carga. O índice não deve ser editado para forçar uma retomada.

## Autorizar criação no Meu Drive

A conta de serviço de `credentials/google_credentials.json` continua lendo e gravando as planilhas. Para **criar** arquivos no Meu Drive, é necessária uma autorização do usuário Google no computador onde as cargas serão executadas. Não é preciso criar outra conta de serviço para Pets.

1. Encerre as cargas. Instale a 1.5.6 ou superior preservando credenciais, configurações e logs.
2. No Google Cloud, habilite Google Drive API e Google Sheets API. Configure a tela de consentimento OAuth e crie um cliente **Aplicativo para computador**. A conta autorizada precisa editar as três origens e acessar suas pastas no Meu Drive.
3. Baixe o JSON oficial desse cliente para `credentials/google_oauth_client.json`. Não envie pelo chat, não inclua no Git e não substitua `google_credentials.json`.
4. Execute `comandos/configurar_continuacoes.bat`, escolha FarmaLíder ou Pets Líder e a opção de autorizar/configurar. Conclua a autorização no navegador local.
5. O acesso offline é salvo privadamente em `credentials/google_oauth_user.json`. Configure o outro perfil no mesmo computador. Cada perfil mantém seu índice e destinos separados; a autorização pode ser a mesma se a conta tiver acesso a ambos.
6. Consulte a capacidade pela opção de consulta desse BAT, ou no Terminal: `nexo armazenamento status`.

Em aplicativos OAuth externos no modo **Teste**, o Google pode expirar a autorização offline após sete dias. Use a configuração interna/produção adequada à organização ou reautorize quando necessário. Não coloque tokens nem arquivos OAuth no pacote público.

O NexoFlow cria a continuação na mesma pasta da origem e reproduz os acessos individuais/grupos permitidos, incluindo edição para a conta de serviço. Origens ou pastas com acesso público ou por domínio exigem revisão antes da criação automática. O recurso destina-se ao Meu Drive; não configura Drive compartilhado.

## Preparar o Data Studio uma vez

Uma fonte nativa Google Sheets lê uma aba de um arquivo. Ela **não passa automaticamente** a unir as continuações. Por isso, a criação de partes BI fica bloqueada até a confirmação das fontes que já usam o conector NexoFlow.

O Setup e o GitHub não implantam um Apps Script nem substituem fontes do relatório. Faça esta configuração no Google com a conta responsável pelo dashboard:

1. Faça uma cópia de segurança do relatório e anote suas fontes, filtros e campos calculados.
2. Crie um projeto privado Google Apps Script. Copie `Code.js`, `Tables.js` e `Schemas.js` de `connectors/continuacoes/` para arquivos de script com os mesmos nomes. Copie também `appsscript.json` para o manifesto do projeto.
3. Habilite o serviço avançado **Google Sheets API v4**, símbolo `Sheets`. O conector usa somente leitura e a autorização Google do usuário; não recebe tokens Weni/FarmaLíder ou credenciais da conta de serviço.
4. Em **Implantar → Testar implantações**, selecione o tipo conector do Data Studio. Use uma implantação privada, sem publicar em galeria.
5. Crie uma fonte para cada tabela BI usada no dashboard. Informe o ID do **Dashboard** do segmento, selecione FARMA/PET e a tabela correspondente. O usuário Google precisa ler também as continuações.
6. No relatório, substitua cada fonte pela correspondente, conferindo campos calculados, agregações, filtros e estilos. Os identificadores dos campos são os cabeçalhos originais. Não misture segmentos.
7. Compare total de pedidos, produtos, faturamento, clientes e período completo com as tabelas. Confira também um único dia e um intervalo vazio. Não conclua a migração apenas porque o gráfico abriu.
8. Somente após a conferência, no Terminal do perfil correto, confirme as tabelas substituídas. Exemplo:

```text
nexo armazenamento ativar-data-studio --abas BI_Itens BI_Publico BI_Vendas --confirmar-fontes
```

Repita com as demais tabelas usadas. `BI_Delivery_Pedidos` aparece como opção se sua rotina já a utiliza; esta versão não cria essa tabela opcional durante a configuração.

### Curva ABC

Atualize o projeto Apps Script da Curva ABC com os **três** arquivos `AbcCore.js`, `Code.js` e `Tables.js` de `connectors/looker_abc/`, mantendo seu manifesto. Atualize a implantação existente, valide dois períodos e confirme `BI_Itens` e `BI_Clientes_Vendas` somente quando esse leitor estiver em uso. Uma implantação antiga com apenas dois arquivos não lê continuações.

### Limites das consultas

O conector confere cabeçalhos, segmento, origem e contagens de todas as partes. Se uma tabela estiver em gravação ou o índice mudar durante a leitura, ele retorna erro para nova tentativa; não mostra uma soma parcial como total.

Cada consulta pode examinar até 1 milhão de linhas e retornar até 200 mil, com orçamento de 240 segundos. Não há amostragem ou corte silencioso. Para detalhes volumosos, restrinja o período ou use tabelas de resumo; se ultrapassar esses limites, planeje um armazenamento analítico adequado. O Apps Script/Google também pode impor quotas menores.

O conector geral não impõe uma janela automática de 30 dias. Tabelas de clientes sem coluna `data` permanecem completas; tabelas com data respeitam o período solicitado pelo relatório. As agregações dos gráficos e o período escolhido continuam exigindo conferência.

## Falhas e retomada

Uma resposta perdida após gravar não autoriza repetir uma inserção às cegas. O NexoFlow preserva a intenção e verifica coordenadas, chaves e hashes antes de retomar. A proteção remota pode permanecer por até cinco minutos após uma gravação sem confirmação. Aguarde e execute novamente; não apague a trava, o índice ou os comprovantes para acelerar.

Uma criação de arquivo indeterminada fica pendente até ser localizada; não cria outro arquivo automaticamente. Um histórico parcialmente entregue precisa do comprovante local da carga original. Se mudar de computador nessa situação, preserve os dados para revisão.

Falhas isoladas de consulta de contatos/pedidos mantêm o comportamento das rotinas: registros inconclusivos ficam pendentes e os demais podem prosseguir. Uma falha estrutural de armazenamento exige interromper as gravações afetadas para não publicar dados incompletos.
