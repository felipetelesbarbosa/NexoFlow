# NexoFlow 1.0

Aplicativos para Windows que integram **Weni e a API FarmaLíder nos segmentos FarmaLíder e Pets Líder**, atualizam contatos e pedidos e organizam os dados no **Google Sheets** para análise no **Looker Studio**.

[Baixar instalador](https://github.com/felipetelesbarbosa/NexoFlow/releases/download/v1.0/NexoFlow-Setup-1.0.zip) · [Documentação](docs/README.md) · [Histórico de mudanças](CHANGELOG.md)

## Componentes

| Aplicativo | Para que serve |
| --- | --- |
| **NexoFlow Noturno** | Executa Weni, Analytics e Recompra sem confirmação humana, com auditoria automática e relatório final. |
| **NexoFlow Weni** | Atualiza cadastros, pedidos e grupos na Weni; exclui duplicados confirmados após revisão. |
| **NexoFlow Analytics** | Sincroniza a base, acumula o histórico de pedidos e atualiza as tabelas do Google Sheets. |
| **NexoFlow Planilha** | Revalida exports de contatos e conversas para atualizar Weni ou Analytics. |
| **NexoFlow Recompra** | Mantém a elegibilidade da Recompra FarmaLíder D+25; os envios ficam na campanha Weni. |
| **NexoFlow Terminal** | Oferece comandos, consultas e diagnóstico pelo comando `nexo`. |

## Instalar e configurar

1. Baixe e extraia todo o ZIP do instalador. Execute **NexoFlow Setup.exe**.
2. Configure suas credenciais em `C:\NexoFlow\secrets_config.py`, usando [o modelo](configuracao/secrets_config.example.py). Salve a credencial Google em `C:\NexoFlow\credentials\google_credentials.json`.
3. Compartilhe as planilhas como **Editor** com a conta de serviço Google e configure seus destinos.
4. Abra **NexoFlow Terminal** e execute `nexo diagnostico` antes das cargas.

Requer Windows x64 e Python 3.11 ou superior, 64 bits. O Setup oferece o Python incluído quando necessário. Veja [instalação e primeira configuração](docs/README%20INSTALACAO.md).

## Escolher o segmento

Os atalhos **NexoFlow Pets Weni/Analytics/Planilha/Recompra/Noturno/Terminal** usam o perfil PET. Os atalhos tradicionais continuam FARMA. Ambos executam a mesma sequência de conexão, auditoria e aplicação; credenciais, planilhas, revisões e estado permanecem separados.

Preencha `PERFIS["FARMA"]` e `PERFIS["PET"]` no arquivo local, incluindo os três IDs de Sheets (Dashboard, Operação e Histórico). A credencial Google pode ser compartilhada; os arquivos de planilhas precisam ser distintos. Confira o mapa `NexoFlow_Arquivos` em cada Dashboard. O NexoFlow recusa destinos Pets divergentes e token de outra organização.

Pets usa `logs/PET/`, `importacoes/PET/`, `compra_recente` e `opt_in_marketing` com Sim/Não. Não exige maioridade. A Recompra usa **pedido_data D+30**; FarmaLíder usa **pedido_data D+25**. O filtro humano permanece exclusivo da FarmaLíder; pedidos Pets exigem vínculo com `clientes/PET`.

Para conferir apenas o grupo atual, execute `comandos/auditar_grupo_recompra.bat` no perfil desejado. A auditoria consulta a API sem modificar contatos e salva JSON/CSV privado. Consulta inconclusiva permanece pendente.

## Primeira carga e atualização completa

Execute nesta ordem, revisando e confirmando os relatórios solicitados:

1. **Weni:** carga completa em `comandos/atualizar_weni_carga_completa.bat`.
2. **Planilha, quando houver exports:** opção **[1] Atualizar Weni**, depois **[2] Atualizar Analytics e Google Sheets**.
3. **Analytics:** carga completa em `comandos/executar_carga_completa.bat`.
4. **Recompra:** gere a revisão, confira as pendências e confirme a aplicação.
5. **Analytics:** sincronização incremental; depois atualize os dados no Looker Studio.

Para percorrer essa sequência com os exports, coloque `Conversas_Delivery.xlsx` e `Contatos_Delivery.xlsx` em `importacoes/` e execute `comandos/atualizar_tudo.bat`. As confirmações continuam sendo solicitadas durante o fluxo.

Para executar durante a madrugada, use **NexoFlow Noturno**. Veja [execução automática e agendamento](docs/NOTURNO.md).

Na rotina diária, use os atalhos Weni, Recompra e Analytics conforme necessário. As cargas completas também podem ser divididas em quatro partes, executadas em ordem para cada componente. Consulte o [guia de operação](docs/Documentacao%20NexoFlow.md).

## O que considerar nos resultados

- Pedidos e valores dependem da confirmação na API FarmaLíder. Cancelados, inclusive pedidos oficialmente sem itens, ficam fora das vendas e da Recompra.
- No perfil FARMA, o recorte é da farmácia: pedidos mistos mantêm somente produtos humanos; pedidos apenas pet ou veterinários são excluídos.
- O histórico é acumulado nas coletas. O último pedido da API não comprova todas as compras anteriores de um cliente.
- Operação, histórico e dashboard podem usar [três arquivos do Sheets](docs/planilhas_separadas.md). O Looker lê as fontes `BI_*`; confira seus destinos e atualize os campos quando houver novas colunas.
- Nos atalhos individuais, revise as propostas de Weni, Planilha e Recompra antes de aplicar. Carga parcial exige conferir o log e as pendências antes de prosseguir.

## Referências

O código fica em [app/](app/README.md), os comandos Windows em [comandos/](comandos/README.md) e os modelos em [configuracao/](configuracao/README.md). Os guias por assunto estão em [docs/](docs/README.md).

[Weni](docs/README%20WENI.md) · [Planilha](docs/README%20DELIVERY.md) · [Recompra](docs/README%20RECOMPRA.md) · [Terminal](<docs/README TERMINAL.md>) · [Google Sheets](docs/GOOGLE%20SETUP.md) · [Looker Studio](docs/LOOKER%20STUDIO.md)

O projeto é distribuído sem chaves, tokens ou credenciais. Use os seus próprios acessos e mantenha-os privados. Consulte [Segurança](SECURITY.md).

## Organização do repositório

Os executáveis de referência ficam em `native_launcher/prebuilt/`; os pacotes oficiais recompilam os aplicativos e mantêm os caminhos de instalação. Dependências opcionais e de desenvolvimento ficam em `dependencias/`. `pyproject.toml`, `pyrightconfig.json` e `requirements.txt` permanecem na raiz para as ferramentas Python.
