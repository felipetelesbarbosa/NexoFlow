# NexoFlow 1.5.5

Aplicativos para Windows que integram **Weni e a API FarmaLíder nos segmentos FarmaLíder e Pets Líder**, atualizam contatos e pedidos e organizam os dados no **Google Sheets** para análise no **Data Studio**.

O NexoFlow identifica pedidos registrados na API **independentemente de terem sido feitos por conversa na Weni, ligação telefônica ou outro atendimento externo**. A rotina Weni faz a correspondência com os contatos e retroalimenta a base com os dados disponíveis, propondo criar os cadastros ausentes com identidade e pedido validados. Nos aplicativos individuais, a aplicação segue a revisão solicitada; no Noturno, ela é automática. O canal específico da compra só é informado quando há evidência: estar na API não prova que o pedido veio da Weni ou de uma ligação.

[Baixar instalador](https://github.com/felipetelesbarbosa/NexoFlow/releases/download/v1.5.5/NexoFlow-Setup-1.5.5.zip) · [Documentação](docs/README.md) · [Histórico de mudanças](CHANGELOG.md)

## Componentes

| Aplicativo | Para que serve |
| --- | --- |
| **NexoFlow Noturno** | Executa Weni, Analytics e Recompra sem confirmação humana, com auditoria automática e relatório final. |
| **NexoFlow Weni** | Retroalimenta contatos e pedidos da API na Weni, incluindo compras externas; atualiza grupos e trata duplicados após revisão. |
| **NexoFlow Analytics** | Sincroniza a base, acumula o histórico de pedidos e atualiza as tabelas do Google Sheets. |
| **NexoFlow Planilha** | Revalida exports de contatos e conversas para atualizar Weni ou Analytics. |
| **NexoFlow Recompra** | Mantém a elegibilidade da Recompra FarmaLíder D+25 e Pets Líder D+30; os envios ficam na campanha Weni. |
| **NexoFlow Terminal** | Oferece comandos, consultas e diagnóstico pelo comando `nexo`. |

## Instalar e configurar

1. Baixe e extraia todo o ZIP do instalador. Execute **NexoFlow Setup.exe**.
2. Configure suas credenciais em `C:\NexoFlow\secrets_config.py`, usando [o modelo](configuracao/secrets_config.example.py). Salve a credencial Google em `C:\NexoFlow\credentials\google_credentials.json`.
3. Compartilhe as planilhas como **Editor** com a conta de serviço Google e configure seus destinos.
4. Abra **NexoFlow Terminal** e execute `nexo diagnostico` antes das cargas.

Requer Windows x64 e Python 3.11 ou superior, 64 bits. O Setup oferece o Python incluído quando necessário. Veja [instalação e primeira configuração](docs/README%20INSTALACAO.md).

## Escolher o segmento

Abra o mesmo executável Weni, Analytics, Recompra, Planilha ou Noturno e escolha **[1] FarmaLíder** ou **[2] Pets Líder**. No Noturno, depois escolha incremental ou completa. O Terminal também permite selecionar a marca. Ambos executam a mesma sequência de conexão, auditoria e aplicação; credenciais, planilhas, revisões e estado permanecem separados. Para agendamentos, use `--perfil FARMA` ou `--perfil PET`; o Noturno também aceita `--incremental` ou `--full`.

Preencha `PERFIS["FARMA"]` e `PERFIS["PET"]` no arquivo local, incluindo os três IDs de Sheets (Dashboard, Operação e Histórico). A credencial Google pode ser compartilhada; os arquivos de planilhas precisam ser distintos. Confira o [guia dos segmentos e fluxos](docs/SEGMENTOS%20E%20FLUXOS.md) e o mapa `NexoFlow_Arquivos` em cada Dashboard. O NexoFlow recusa destinos Pets divergentes e token de outra organização.

Pets usa `logs/PET/`, `importacoes/PET/`, `compra_recente` e `opt_in_marketing` com Sim/Não. Não exige maioridade. A Recompra usa **pedido_data D+30**; FarmaLíder usa **pedido_data D+25**. O filtro humano permanece exclusivo da FarmaLíder; pedidos Pets exigem segmento PET comprovado pela listagem ou pela consulta individual por CPF.

Para conferir apenas o grupo atual, execute `comandos/auditar_grupo_recompra.bat` no perfil desejado. A auditoria consulta a API sem modificar contatos e salva JSON/CSV privado. Consulta inconclusiva permanece pendente.

## Novos departamentos e segmentos

O NexoFlow já tem arquitetura organizada por perfis para inclusão de novos departamentos e segmentos. A habilitação inclui registrar o novo perfil nos seletores e configurar organização Weni, credenciais, API autorizada, destinos Sheets, campos, fluxos e regras próprias, com validação antes de ativar. Os perfis operacionais disponíveis nesta versão são **FARMA** e **PET**.

## Primeira carga e atualização completa

Execute nesta ordem, revisando e confirmando os relatórios solicitados:

1. **Weni:** carga completa em `comandos/atualizar_weni_carga_completa.bat`.
2. **Planilha, quando houver exports:** opção **[1] Atualizar Weni**, depois **[2] Atualizar Analytics e Google Sheets**.
3. **Analytics:** carga completa em `comandos/executar_carga_completa.bat`.
4. **Recompra:** gere a revisão, confira as pendências e confirme a aplicação.
5. **Analytics:** sincronização incremental; depois atualize os dados no Data Studio.

Para percorrer essa sequência com os exports, coloque `Conversas_Delivery.xlsx` e `Contatos_Delivery.xlsx` em `importacoes/` (Farma) ou `importacoes/PET/` (Pets) e execute `comandos/atualizar_tudo.bat`. As confirmações continuam sendo solicitadas durante o fluxo.

Para executar durante a madrugada, use **NexoFlow Noturno**. A partir da 1.5.5, FARMA e PET podem executar simultaneamente; duas cargas do mesmo segmento permanecem bloqueadas. Veja [execução automática e agendamento](docs/NOTURNO.md).

Na rotina diária, use os atalhos Weni, Recompra e Analytics conforme necessário. As cargas completas também podem ser divididas em quatro partes, executadas em ordem para cada componente. Consulte o [guia de operação](docs/Documentacao%20NexoFlow.md).

## O que considerar nos resultados

- Pedidos e valores dependem da confirmação na API FarmaLíder. Cancelados, inclusive pedidos oficialmente sem itens, ficam fora das vendas e da Recompra.
- No perfil FARMA, o recorte é da farmácia: pedidos mistos mantêm somente produtos humanos; pedidos apenas pet ou veterinários são excluídos.
- O histórico é acumulado nas coletas dos dois segmentos, inclusive pedidos de clientes ainda ausentes na Weni. Pedidos observados ficam guardados localmente até a entrega idempotente ao Analytics/Sheets. O último pedido da API não comprova todas as compras anteriores nem compras intermediárias não observadas.
- A rotina Weni propõe criar clientes da API com pedido validado e identidade única, preenchendo nome, telefone e campos disponíveis. Sem telefone, o cadastro pode ficar sem canal de contato. CPF inválido sem vínculo independente, conflito cadastral e resposta incerta ficam pendentes; não são criados consentimentos nem inclusões em grupos.
- A Weni mantém o pedido mais recente; o histórico de pedidos distintos fica nas planilhas e no dashboard. Um pedido vindo da API não comprova que foi feito pelo WhatsApp ou pela Weni.
- Operação, histórico e dashboard podem usar [três arquivos do Sheets](docs/planilhas_separadas.md). O Data Studio lê as fontes `BI_*`; confira seus destinos e atualize os campos quando houver novas colunas.
- Nos atalhos individuais, revise as propostas de Weni, Planilha e Recompra antes de aplicar. Carga parcial exige conferir o log e as pendências antes de prosseguir.

## Capacidade das planilhas

As continuações automáticas no Meu Drive exigem autorização Google local. O Data Studio precisa do conector privado e de uma troca inicial de fontes para somar as partes. Veja [configuração e limites](docs/CONTINUACOES.md); a instalação não muda o dashboard automaticamente.

## Versões e atualizações

A versão atual é **1.5.5**. As próximas correções seguem **1.5.6, 1.5.7, ... 1.5.99; depois 1.6**. A numeração muda por publicação, sem saltos por commit ou nova tentativa de build. Veja a [política de versionamento](docs/VERSIONAMENTO.md).

## Referências

O código fica em [app/](app/README.md), os comandos Windows em [comandos/](comandos/README.md) e os modelos em [configuracao/](configuracao/README.md). Os guias por assunto estão em [docs/](docs/README.md).

[Weni](docs/README%20WENI.md) · [Planilha](docs/README%20DELIVERY.md) · [Recompra](docs/README%20RECOMPRA.md) · [Terminal](<docs/README TERMINAL.md>) · [Google Sheets](docs/GOOGLE%20SETUP.md) · [Data Studio](docs/DATA%20STUDIO.md)

O projeto é distribuído sem chaves, tokens ou credenciais. Use os seus próprios acessos e mantenha-os privados. Consulte [Segurança](SECURITY.md).

## Organização do repositório

Os executáveis de referência ficam em `native_launcher/prebuilt/`; os pacotes oficiais recompilam os aplicativos e mantêm os caminhos de instalação. Dependências opcionais e de desenvolvimento ficam em `dependencias/`. `pyproject.toml`, `pyrightconfig.json` e `requirements.txt` permanecem na raiz para as ferramentas Python.

A integração dos dois segmentos usa produção. A leitura da base completa pode aguardar até 10 minutos por tentativa; consultas individuais mantêm 90 segundos. Quando necessário, o NexoFlow consulta o CPF e exige confirmação do segmento antes de usar os dados.

Os três IDs de planilha podem ser configurados em cada perfil do `secrets_config.py`: Dashboard, Operação e Histórico. O mapa `NexoFlow_Arquivos`, quando existir, deve coincidir com esses IDs. Consulte o relatório de cada execução: HTTP 200 não dispensa a validação do conteúdo e do segmento.
