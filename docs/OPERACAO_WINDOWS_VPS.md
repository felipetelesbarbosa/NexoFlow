# Operação do NexoFlow Windows com a VPS

Estado registrado em 19/11/2026. Use este guia para distinguir a versão do Windows, a publicação de dados e as fontes do Looker efetivamente ligadas ao PostgreSQL.

## Fluxo por perfil

| Etapa | Execução e destino |
| --- | --- |
| Weni | Windows consulta os contatos e a API FarmaLíder, reconcilia os pedidos e aplica as atualizações autorizadas na Weni. |
| Analytics | Windows consolida pedidos, itens e histórico. No perfil FARMA com Meta Ads e o XLSX de Salas configurados, cruza o pedido oficial com eventos CTWA, Weni Flows e a tag Pedido Finalizado. Calcula pedidos na conversa, pedidos até sete dias depois e novos clientes. Com PostgreSQL ativo, publica pela API HTTPS privada. A VPS confirma os lotes na revisão READY. |
| Recompra | Windows calcula e aplica a elegibilidade aos grupos Weni (FARMA D+25, PET D+30). O armazenamento configurado no perfil controla o estado e a retomada. O envio da campanha é da Weni. |
| Noturno | Windows automatiza Weni → Analytics → Recompra no perfil selecionado. |
| Looker Studio | O conector privado Apps Script consulta a API leitora da VPS quando o gráfico está ligado à fonte PostgreSQL. Usa o segmento, o ambiente e a janela selecionados. |

O contrato `nexoflow_datastudio_1` usa os bancos `nexoflow_datastudio` (produção) e `nexoflow_datastudio_homologacao` (homologação), com schemas separados por segmento. O PostgreSQL fica na rede privada. O arquivo de credenciais do Windows é para publicação. O Apps Script configura separadamente a credencial da API leitora. Uma execução com PostgreSQL ativo reporta falhas nesse destino e conserva os recibos de retomada. Sheets permanece selecionável nos perfis legados.

## Estado da migração FARMA

- O Windows estável 1.5.46 inclui o diagnóstico dos eventos CTWA de pedidos paginados FARMA. Uma prévia da 1.5.46 foi exercitada no Windows FARMA de homologação. Na simulação de 01 a 18/11, ela protegeu a conversa histórica de 09/11 ausente na consulta nova e retornou `controle_por_anuncio_divergente` com `applied: false`. [Release estável](https://github.com/felipetelesbarbosa/NexoFlow/releases/tag/v1.5.46) · [Pacote usado na homologação anterior](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/44438449987/artifacts/14491002371)
- A revisão comercial FARMA READY v2 tem a conciliação de vendas e pedidos documentada. Os 204 pedidos já recuperados não exigem reenvio. Use a revisão ativa e recalcule os controles se uma nova carga mudar o corte. [Inventário do relatório](ROTEIRO%20INVENTARIO%20FARMA%20POSTGRESQL.md)
- Na cópia do Looker, `Anuncios_Veiculados_FARMA` e `Resumo_Anuncios_Veiculados_FARMA` leram o PostgreSQL de homologação de 01 a 18/11. O controle fechou em três anúncios com nomes de campanha, R$ 251,02 e 70 conversas informadas. Três dos 15 fatos diários não informam a métrica. A consulta comercial também confirmou 42 eventos CTWA, métrica de origem própria. [Contrato Meta/Weni](DESTINOS%20META%20WENI.md) · [Alteração validada](https://github.com/felipetelesbarbosa/NexoFlow/pull/15)
- Público (`ds82`) migra por componente. A projeção comercial conferiu 48.843 contatos, 30.939 com compra identificada, 17.904 sem compra identificada, 2.184 com idade informada e 6.174 sem cidade. Compra identificada e comprador com pedido elegível são indicadores distintos. Weni (`ds136`) tem seis dias em homologação, com 2.002 conversas, 465 resolvidas, 316 não resolvidas e 1.221 transferidas. [Aceite e reversão no Looker oficial](IMPLANTACAO%20LEITOR%20FARMA%20OFICIAL.md)

### Produção FARMA em 19/11/2026

As visões de Público, Anúncios e Weni estão instaladas. O leitor usa a imagem do commit `2d9332010e26839774da33fe91ccf33dd2c95594` e o publicador usa `574e70254fb18c63791d679f06a2944845cd9584`. Ambos estavam saudáveis após a troca do leitor. A READY v2 continuou ativa. A função `farma.ds_veiculacao_meta_v4` expõe o cálculo comercial no contrato existente. A visão diária de Weni retornou `DS_INSIGHTS_COBERTURA_INCOMPLETA` para a amostra e aguarda publicação Windows nesse destino.

O Apps Script comercial está na versão 8 da mesma implantação. As fontes `ds176` e `ds177` foram atualizadas no relatório oficial. Para reoperar os serviços, use nesta ordem `compose.yaml`, `compose.tunnel.yaml`, `compose.farma-v146-validado.yaml` e `compose.farma-v147-comercial.yaml`. O último arquivo troca somente a imagem do leitor. Para reversão do conector e do leitor, use a versão 7 do Apps Script e os três primeiros arquivos Compose. O backup guarda as definições anteriores da FARMA. PET segue o próprio roteiro.

| Uso comercial | Estado verificado |
| --- | --- |
| Anúncios | A página principal usa `Anuncios_Veiculados_FARMA` para a tabela e `Resumo_Anuncios_Veiculados_FARMA` para os cartões de veiculação e resultados. A fonte dos detalhes de pedidos por anúncio tem aceite próprio. |
| Público | Os 12 componentes antes vinculados à `ds82` na Base de clientes usam `BI_Publico_Resumo` no Looker oficial. São seis cartões, três tabelas e três controles. Os componentes de bairro e LTV têm fontes e aceite próprios. |
| Weni | A visão comercial está instalada. O leitor retornou `DS_INSIGHTS_COBERTURA_INCOMPLETA` ao consultar 01–06/11 pelo papel de leitura. O vínculo comercial da `ds136` depende dos recibos da publicação Windows e da validação do período efetivo. |

Para os novos campos, o ROAS divide a receita na conversa do anúncio pelo investimento FARMA informado pela Meta e é exibido em porcentagem. O CPA divide esse investimento pelos pedidos dessa conversa. O CAC divide o mesmo investimento pelos clientes cuja primeira compra válida, considerando o histórico oficial desde 2020, ocorreu na conversa do anúncio. A compra em outro atendimento em até sete dias entra em um indicador próprio, sem duplicar pedidos. [Regra e configuração](META%20ADS%20NATIVO.md#m%C3%A9tricas-da-p%C3%A1gina-an%C3%BAncios-em-produ%C3%A7%C3%A3o)

Na página **Anúncios**, **Pedidos** e **Receita** se referem ao atendimento original. **Pedidos no ciclo de 7 dias** é o nome do cartão e **Pedidos (7D)** é o cabeçalho na tabela. Ambos contam pedidos em outro atendimento dentro da janela. **Conversas** soma os valores informados. A tabela mostra os dados em uma linha por célula e conserva os valores completos na fonte.

De 01 a 18/11/2026, a leitura autenticada da v4 retornou três anúncios, R$ 251,02 de investimento Meta e 70 conversas informadas em 12 dos 15 fatos. Os 15 fatos ainda estavam sem atribuição comercial do Windows. Os novos campos de pedidos e CAC retornaram indisponíveis. Os 42 eventos CTWA têm origem e métrica próprias.

A revalidação no mesmo recorte encontrou dois registros na página oficial de Pedidos dos anúncios por meio da mesclagem legada. Na cópia PostgreSQL de homologação, a mesclagem `FARMA QA14 | Pedidos dos anúncios` devolveu três pedidos válidos de contatos com origem Meta Ads na Weni, posteriores ao primeiro anúncio. A soma foi R$ 322,69, incluindo frete. O período da mesclagem seleciona a chegada dos contatos. A conciliação dos eventos CTWA individuais e da receita com a fonte comercial de veiculação permanece pendente. A rotina no código Windows pode conferir cada pedido em modo somente leitura no perfil comercial. Use um pacote que inclua a alteração e registre o ambiente e a versão READY da execução. [Como executar a conferência](META%20ADS%20NATIVO.md#concilia%C3%A7%C3%A3o-de-pedidos-da-weni-no-windows)

A auditoria anterior do Windows FARMA sobre a READY v2 confirmou três pedidos válidos e R$ 322,69 na coorte. Registrou `conversas_meta_pendentes` quando a Meta omitiu um fato cujo histórico informava uma conversa. O resultado foi gravado localmente com `applied: false`. A atribuição comercial 1.5.47 usa a evidência por atendimento descrita no guia, com deduplicação por pedido oficial. Os resultados da coorte anterior continuam disponíveis para auditoria.

Público reproduziu os seis cartões da cópia na READY v2. As dimensões de cidade, canal e faixa etária são compartilhadas pela fonte comercial. A participação por linha usa o total da seleção, e o percentual de compra usa a razão entre as somas de compra identificada e de contatos. O filtro Instagram retornou 147 contatos. Belém retornou 33.451 e o cruzamento Belém com 35–44 anos retornou 322 nos cartões e nas tabelas. A página Base de clientes usa a revisão ativa e seus controles de público.

## Conferir o Windows antes de uma carga

Abra o Terminal NexoFlow no perfil da execução. Para conferir versão, acesso e destino PostgreSQL:

```powershell
Set-Location C:\NexoFlow
nexo versao
nexo armazenamento postgres diagnosticar
```

Para a carga comercial FARMA, confira `ARMAZENAMENTO_BACKEND = "postgres"`, `DATASTUDIO_AMBIENTE = "producao"`, segmento `FARMA`, revisão ativa e pendências. A credencial privada da API publicadora é indicada por `DATASTUDIO_CREDENTIALS_FILE` no perfil local. O caminho pode incluir uma subpasta específica do ambiente ou do ensaio. Guarde o arquivo fora do Git. Consulte os requisitos de ativação, importação de estado, preparo e retomada no [guia de migração](MIGRACAO%20WINDOWS%20POSTGRESQL%20DATA%20STUDIO.md).

Uma falha durante o envio pode acontecer depois de a VPS ter gravado o lote. Retome o plano e confirme seus recibos antes de iniciar outra revisão. Uma carga completa de Weni, Recompra e Analytics usa os atalhos normais com o perfil e o destino já conferidos. Registre no relatório de execução o ambiente, a versão Windows e a READY publicada. Só marque a troca do Looker como concluída após conferir a fonte efetiva, os totais e os filtros no endereço oficial.

Na 1.5.48, o perfil FARMA detecta o XLSX opcional em Downloads ou em `importacoes`, lê as datas do arquivo e usa o Flows v2 quando a planilha está indisponível. Janelas de atribuição ainda abertas e lacunas de evidência aparecem como cobertura parcial. Confira no diagnóstico `atribuicao_comercial_weni` e no Looker a revisão e os dias parciais. [Guia de configuração](META%20ADS%20NATIVO.md#m%C3%A9tricas-da-p%C3%A1gina-an%C3%BAncios-em-produ%C3%A7%C3%A3o)

## Recuperação FARMA após simulação Weni interrompida

Em 20/11/2026, o servidor confirmou o aborto da v3 vazia. A v2 permaneceu READY com o mesmo recibo. O papel da API publicadora recebeu erro de permissão na leitura das exclusões durante a guarda financeira. A aplicação das permissões e a retomada comercial têm conferências independentes.

1. Na VPS, usar a sessão administrativa privada do banco dedicado. No checkout revisado, executar `psql -X -v ON_ERROR_STOP=1 --single-transaction -d nexoflow_datastudio -f integrations/datastudio/grants_conferencia_farma.sql`. O SQL concede ao publicador SELECT nas colunas usadas nas três visões e prepara a tabela privada de partes descrita abaixo. Os papéis do painel e PET conservam seus privilégios. Para verificar, usar o mesmo DSN do publicador, no contêiner do serviço, e executar a função `assert_financial(conn, "farma")` numa transação somente leitura sobre a READY vigente. Guardar o código de saída. A ausência de registros no resultado de uma consulta que falhou não comprova conciliação.
2. Instalar o Setup 1.5.49 em **Atualizar mantendo dados**. Abrir o Terminal FARMA. Conferir `nexo versao` e `nexo armazenamento postgres diagnosticar`. Identificar a produção, a READY e a ausência de revisão concorrente.
3. Recuperar os documentos privados da última instalação ou backup com procedência, inclusive pendências e admissões anteriores. Com rotinas paradas, usar o procedimento de [importação de estado](MIGRACAO%20WINDOWS%20POSTGRESQL%20DATA%20STUDIO.md). Uma campanha fracionada comprovadamente inexistente pode usar o procedimento documentado. Um checkpoint perdido de Weni/Recompra exige reconstrução e conferência operacional antes de aplicar. O histórico comercial e uma lista atual de contatos não reconstituem as ações anteriores.
4. Após liberar os estados, executar a simulação Weni. Conferir que a revisão comercial permanece a mesma. Para verificar a publicação do Analytics, escolher incremental no Terminal FARMA; preservar o recibo, comparar o indicador afetado pelo mesmo período na VPS e na página oficial e verificar as chaves e totais após repetição. A existência da release não substitui essa conferência.

### Importação seletiva do backup do Windows

Recuperar exclusivamente o estado FARMA da raiz de logs, identificando a última aplicação Weni e Recompra por segmento e data. Conferir integridade do ZIP e dos membros selecionados. O histórico de relatórios, arquivos de atendimento e logs integrais pode permanecer arquivado. Validar a ausência de uma campanha fracionada ativa com o operador antes de importar seu estado inicial.

Para estados grandes de Recompra, implantar primeiro o SQL acima e a imagem do **publicador** desta versão no serviço FARMA, conservando as configurações privadas, limites HTTP e o leitor. A migração cria uma tabela privada de partes apenas no schema FARMA. Conferir a integridade e a READY no serviço. O comando `importar-estado` e as gravações posteriores usam o formato compactado do checkpoint. O cliente divide o documento grande em partes e mantém uma chave de recibo determinística para o mesmo destino, nome, versão e conteúdo. Uma interrupção antes da última parte mantém o estado anterior; a última transação confere o hash, aplica o controle de concorrência e grava o recibo. Repetir o mesmo arquivo permite recuperar o recibo após perda da resposta. O leitor do painel não tem acesso às partes.

Reversão do publicador: aguardar a conclusão de um envio em andamento, manter a API sem escritores e restabelecer a imagem anterior com o mesmo Compose. Preservar checkpoints, recibos e a tabela de partes. O formato armazenado é legível pela versão anterior; o envio de novos estados grandes requer a versão com transporte em partes.

O operador da VPS deve registrar o SHA da imagem FARMA anterior e aplicar o SQL revisado em uma transação antes da troca do serviço. Usar um overlay com a imagem nova apenas para `datastudio-farma-publish`; manter leitor, túnel e demais serviços com suas imagens efetivas. Se os arquivos Compose comerciais estiverem em outro diretório, usar o projeto e os arquivos já auditados. No contêiner atualizado, este comando Python confere o papel dedicado, a transação de leitura e a guarda usada por `/v1/confirmar`. Não imprimir a configuração ou o DSN.

```python
import json, os
from pathlib import Path
from integrations.datastudio.store import Store
from integrations.datastudio.financial_views import assert_financial

cfg = json.loads(Path(os.environ["DATASTUDIO_CONFIG_FILE"]).read_text(encoding="utf-8-sig"))
if (cfg["mode"], cfg["environment"], cfg["segment"]) != ("publish", "producao", "FARMA"):
    raise SystemExit("Serviço ou destino divergente")
store = Store(Path(cfg["dsn_file"]).read_text(encoding="utf-8-sig").strip(),
              "producao", "FARMA", require_dedicated_role=True)
with store.connect(readonly=True) as conn:
    assert_financial(conn, store.schema)
    print("Conferência financeira aprovada na READY", store.active(conn))
```

O checkpoint grande usa até oito partes de quatro milhões de caracteres base64. Acima desse volume a execução informa erro e conserva a versão anterior. Uma revisão do histórico ou um arquivo `.lock` não substituem o documento de estado da Weni, da Recompra ou de uma campanha.

### Conferência financeira do publicador FARMA em volume

Em 20/11/2026, na READY v2, o Work confirmou as permissões da 1.5.49. Com o planejador padrão, a consulta de itens operacionais expirou aos 50 e aos 180 segundos. Na mesma base e com o mesmo papel, a conferência completa passou com `enable_nestloop=off`, `jit=off` e `work_mem=64MB` locais à transação, conservando o limite original de 50 segundos por instrução. O publicador corrigido aplica esses valores ao entrar em `assert_financial` da FARMA, depois de preparar a revisão candidata e antes de verificar itens, pedidos e LTV. Uma divergência financeira ou um timeout ainda reverte a transação de confirmação.

Para implantar a correção, use a imagem do commit corrigido somente em `datastudio-farma-publish`, com os mesmos arquivos Compose e a mesma configuração privada em uso. Confira o SHA em `/v1/destino`, a READY esperada e `pending` vazio. No contêiner atualizado execute o teste de leitura da seção anterior, como `nf_ds_farma_publish`, sem passar opções de planejador na conexão, no ambiente ou no comando. Registre duração, revisão e código de saída. O aceite exige a conclusão de todas as verificações nesse caminho padrão. A homologação sintética cobre a rota de confirmação, a releitura do recibo e o retorno dos parâmetros de sessão após o fim da transação.

Se o teste padrão falhar, conserve a READY e a saída de erro e mantenha a carga pausada. Para reverter o serviço, retorne o publicador à imagem anterior à correção de desempenho (1.5.49, `3e72ea40887142e4ac22e08449b65c60424888f0`). O próximo passo após o aceite é o incremental isolado abaixo.

### Conferir o Analytics enquanto se recuperam os estados de ações Weni

Em uma instalação FARMA já configurada para PostgreSQL de produção, o comando `nexo analytics` abre o executável Analytics. O fluxo incremental faz o check-up, testa as conexões e executa a sincronização. Ele abre o armazenamento com a finalidade `analytics`. A aplicação de mudanças de campos ou grupos por Update Weni e Recompra tem executáveis e checkpoints próprios. Uma ativação nova do backend continua exigindo o procedimento de migração dos estados.

Após o Work confirmar a versão do publicador FARMA, a guarda financeira com seu papel de produção e a ausência de gravação pendente, o operador pode conferir uma atualização pelo Analytics no PC. Se aparecer uma revisão pendente, investigue o recibo antes de iniciar outra execução. No Terminal FARMA, execute um comando de cada vez.

```powershell
Set-Location C:\NexoFlow
nexo versao
nexo armazenamento postgres diagnosticar
nexo analytics
nexo armazenamento postgres diagnosticar
```

Guarde o horário de Belém, o resultado da sincronização, a READY e o recibo confirmado. Escolha um indicador cujo período coincida com a carga. Compare o valor do Windows com a API da VPS e com o componente atualizado do relatório oficial, usando a mesma fonte, filtro e granularidade. Para faturamento histórico mensal, use a linha do mês em `nexo armazenamento postgres conferir --saida "$env:TEMP\nexoflow-farma-conferencia-$([guid]::NewGuid()).json"` e a página de histórico com o mesmo recorte. Verifique as chaves e os totais em uma repetição sem mudança de origem. Registre separadamente dados novos coletados entre as duas execuções.

Um ZIP de logs com Weni e Recompra de datas diferentes pode servir de referência privada. Quando houver dúvida sobre aplicações posteriores, compare cada documento com a última aplicação confirmada, o respectivo `weni_update_audit.jsonl` ou `recompra_audit.jsonl` e os resultados do Noturno na máquina que executou a rotina. Conserve pendências e admissões. A ausência de linhas de estado em backups do servidor não comprova ausência de ações Weni iniciadas em outro PC. Retome o Noturno após validar e importar os estados operacionais correspondentes.

### Destino nos relatórios do Windows

A partir da 1.5.50, confira o perfil e o armazenamento em `nexo status --local`. No modo PostgreSQL, `nexo armazenamento postgres diagnosticar` consulta a API e informa o destino, a versão disponível e as revisões pendentes. O Analytics identifica o transporte das quatro etapas e da camada BI. O processamento de uma tabela pode ocorrer enquanto a revisão está em preparação. A mensagem de confirmação READY é emitida após a resposta do publicador.

O Noturno identifica em seu resultado o armazenamento configurado para as etapas. As alterações de contatos e grupos continuam sendo operações da Weni. A rotina Planilha usa o XLSX como entrada e informa o destino autorizado para a aplicação. A verificação de código no check-up inclui o conector Google Sheets nos dois modos. Exportações explícitas de uma planilha ainda identificam o Google como origem.

Conclua a execução em andamento antes de atualizar com **Atualizar mantendo dados**. No Terminal do mesmo perfil, confira `nexo versao` e o destino. Consulte o log da próxima execução regular para conferir as mensagens e a revisão confirmada.

### Progresso dos contatos e do histórico no Analytics (próximo Setup)

O tempo de “contatos + histórico” abrange toda a primeira das quatro etapas. Na leitura paginada da VPS, o Windows mostra a tabela, as linhas recebidas e o tempo decorrido. O total de páginas não é fornecido pela API. Na conferência local do histórico, o contador soma registros existentes indexados e alterações examinadas. No envio, o progresso avança por lote com recibo da VPS. Durante uma espera, o log volta a informar a operação em andamento a cada 15 segundos.

O tempo restante estimado vale para a operação identificada na linha. A leitura de tamanho desconhecido indica “indisponível”. O recibo de um lote atesta a gravação na revisão em preparo. A atualização do painel depende da confirmação final READY.

### Pendências históricas acumuladas no Analytics FARMA

Na 1.5.55, `Histórico paginado: ... pendências=...` inclui todas as pendências do segmento no cache. Mesmo uma extração completa pode terminar com `DS_FONTES_INCOMPLETAS_RETOMAR` se a READY já continha alertas de fechamentos antigos.

A correção posterior à 1.5.55 confere os alertas de fechamento antigo que já existiam na base com uma venda válida antes da coleta. Para tratá-los como preservados, exige pedido fora da coleta corrente, extração completa, cabeçalhos equivalentes, itens vigentes com chaves únicas correspondentes e diferença apenas na descrição. Mantém o alerta, a descrição publicada, os itens e os valores financeiros. O log informa quantas pendências acumuladas atenderam a esses critérios. Divergência nova, observação conflitante e evidência insuficiente continuam pendentes.

Para uma revisão já em `WRITING`, consulte o estado antes de retomar. A correção se aplica a novas execuções e não produz o manifesto nem o recibo final de uma revisão anterior.

### Resposta incerta durante o envio do Analytics

Na 1.5.50, se o Windows perder a resposta de um lote, ele consulta o recibo pelo UUID. Se a API devolver `DS_LOTE_AUSENTE`, repete o POST uma única vez com os mesmos dados, revisão e UUID. Se a segunda resposta também se perder, consulta o recibo mais uma vez. Só prossegue com ID, hash, revisão e estado comprovados. Permissão negada, divergência ou ausência persistente interrompem a etapa. A simulação exige um resultado SIMULADO.

Na 1.5.53, o cliente Windows aguarda até 120 segundos pela leitura da resposta do fechamento. Se a resposta de `POST /v1/confirmar` se perder, o Analytics consulta automaticamente a própria revisão até três vezes, com cinco segundos entre consultas. Ele confere o manifesto selado, o estado READY e o recibo final com a mesma revisão, versão e hash do manifesto. Com a confirmação, o fluxo normal retorna 0 se as demais etapas também tiverem sucesso. Se a confirmação continuar incerta ou houver outra pendência, retorna 3. A consulta usa somente leitura, sem repetir a carga nem o POST de fechamento.

Se uma execução anterior já encerrou com código 3, consulte `nexo armazenamento postgres diagnosticar` e `nexo armazenamento postgres status --id-revisao <UUID>`. Uma atualização do Setup não reconstrói o lote em memória da execução anterior. Para uma revisão Analytics WRITING sem selo, o Work deve conferir heartbeat, gravador, quantidade e horário dos recibos, linhas de staging por tabela e publicações posteriores com o administrador, em leitura. Preserve evidências. O comando de retomada de uma exportação exige seu plano de migração e o fechamento de revisão selada exige o manifesto previamente selado. Antes de decidir o destino de uma revisão operacional interrompida, registre os resultados e confirme o procedimento com o operador.

### Analytics interrompido na etapa 2/4 com DS_OPERACAO_SHEETS_NAO_PERMITIDA

No backend PostgreSQL, uma correção de pedido pode trazer um snapshot com menos itens que o anterior. O adaptador deve remover as chaves obsoletas daquele pedido pelo publicador da revisão e conferir o recibo. Na 1.5.51, essa operação podia alcançar a limpeza de linhas do adaptador de planilhas e parar na proteção de transporte. A linha de log dos cancelamentos anteriores, por si só, não identifica o pedido que acionou a proteção.

Consulte o estado pelo UUID mostrado pelo próprio Analytics. Uma revisão em WRITING sem selo após a saída do processo não contém a prova de conclusão das quatro etapas. Preserve a revisão e seus recibos para a conferência descrita acima. Para uma nova execução, a instalação Windows precisa conter a correção e o destino da revisão interrompida precisa estar resolvido. A conferência do relatório usa a última publicação READY.

### Setup e publicador 1.5.52

Instale o Setup em modo Preserve. Em Auto, uma nova sessão testa HTTPS direto, sem proxy, credenciais ou redirecionamento. Uma sessão filha reutiliza a rota escolhida. Se a direta falhar, o modo interativo oferece a escolha de proxy; sem console, a rede corporativa previamente reconhecida ou explicitamente configurada pode usar o proxy. Os modos explícitos continuam disponíveis.

Para habilitar o aborto automático, o Work deve atualizar somente a imagem do publicador FARMA pelo procedimento de implantação deste guia, usando o commit da tag v1.5.52, preservar a imagem anterior para reversão e conferir o SHA em /v1/destino. A rota autenticada POST /v1/analytics/abortar-incompleta recebe o UUID da revisão. O cliente a usa ao tratar erros definitivos de validação local ou de chaves/schema que interrompem o Analytics, antes do selo e somente se o processo abriu a revisão. O servidor confere finalidade, base, estado, selo e recibo sob trava. As pendências informativas, erros de rede, respostas incertas e revisões anteriores continuam sujeitos aos mecanismos de conferência existentes. Um publicador anterior não oferece essa rota; o Windows informa a ausência de confirmação e preserva a revisão para conferência. Uma queda do processo ou do PC pode impedir a execução do tratador de erros.

## Noturno FARMA com reservas do operador

Na instalação Windows, guarde o manifesto privado em `credentials\farma-reservas.json`. Ele deve conter exatamente os campos `segmento` (texto `FARMA`), `adiar_exclusoes` (booleano `true`) e `contatos_recompra` (lista dos UUIDs Weni canônicos, minúsculos e distintos). O Work deve montar a lista a partir do cruzamento dos 21 contatos de inclusão e três de troca, conferir os UUIDs contra a revisão e fornecer o SHA-256 do arquivo final pelo canal privado. O manifesto vale nas próximas execuções desse PC enquanto estiver instalado. Use o mesmo arquivo nos demais PCs que possam executar essas rotinas.

No Terminal FARMA da instalação atualizada, estes comandos conferem a identidade do arquivo e a quantidade de contatos antes da carga. Compare o hash exibido com o informado pelo Work.

```powershell
Set-Location C:\NexoFlow
nexo versao
Get-FileHash -Algorithm SHA256 -LiteralPath '.\credentials\farma-reservas.json'
& '.\.venv\Scripts\python.exe' -B app/reservas_farma.py --esperados 24
```

Após a conferência, no mesmo Terminal FARMA, rode a carga usando a quantidade exigida. A rotina valida o manifesto antes de iniciar as etapas. Alterar ou retirar o arquivo invalida a revisão. Esta forma também bloqueia o início se o arquivo estiver ausente.

```powershell
& '.\.venv\Scripts\python.exe' -B app/run_noturno.py --full --reservas-farma 24
```

O Update Weni adia as exclusões novas e os lotes de exclusão interrompidos, mantém os planos de contatos reservados para reavaliar e grava a contagem no arquivo privado de reservas ao lado da revisão de duplicados. A Recompra preserva os grupos e os campos dos contatos reservados, inclusive nas trocas, e registra a decisão RESERVADO na auditoria. O relatório Noturno registra o hash e o total de reservas. A campanha que já estiver agendada na própria Weni continua com suas regras. Para liberar casos, atualize a lista fora de uma execução e gere nova simulação. Os recibos anteriores e a lista de reservas têm finalidades independentes. O perfil PET continua com sua configuração própria.

### Aplicação Weni com reservas e revisão pendente

No Windows 1.5.54, uma aplicação FARMA que gravou seu checkpoint e terminou com reservas pode retornar 3 e deixar a revisão Weni aberta no PostgreSQL. O checkpoint operacional e o recibo READY da revisão são comprovantes distintos. Para diagnosticar, use `nexo armazenamento postgres diagnosticar` e `nexo armazenamento postgres status --id-revisao UUID`. Compare o hash do plano no checkpoint com `plan_sha256` da revisão Weni e confira os recibos dos lotes antes de escolher uma recuperação. Uma revisão sem selo exige comprovar o manifesto completo antes da confirmação. A repetição da carga Weni pode atingir contatos já atualizados.

A partir da 1.5.55, o Update Weni fecha a revisão quando a aplicação conclui a parte autorizada e retorna o resultado específico de reservas. A rotina continua informando código 3 ao operador. Em FARMA/PostgreSQL, após uma etapa com código 3, o Noturno consulta o destino e interrompe a sequência se houver publicação pendente ou se a consulta falhar. O relatório conserva o código original da etapa.
