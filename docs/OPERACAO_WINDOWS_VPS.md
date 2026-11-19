# Operação do NexoFlow Windows com a VPS

Estado registrado em 19/11/2026. Use este guia para distinguir a versão do Windows, a publicação de dados e as fontes do Looker efetivamente ligadas ao PostgreSQL.

## Fluxo por perfil

| Etapa | Execução e destino |
| --- | --- |
| Weni | Windows consulta os contatos e a API FarmaLíder, reconcilia os pedidos e aplica as atualizações autorizadas na Weni. |
| Analytics | Windows consolida pedidos, itens e histórico. No perfil FARMA com Meta Ads ativo, cruza eventos CTWA da Weni com os pedidos e gera o diagnóstico por pedido. Com PostgreSQL ativo no perfil, publica pela API HTTPS privada. A VPS recebe os lotes e confirma a revisão READY após a conciliação. |
| Recompra | Windows calcula e aplica a elegibilidade aos grupos Weni (FARMA D+25, PET D+30). O armazenamento configurado no perfil controla o estado e a retomada. O envio da campanha é da Weni. |
| Noturno | Windows automatiza Weni → Analytics → Recompra no perfil selecionado. |
| Looker Studio | O conector privado Apps Script consulta a API leitora da VPS quando o gráfico está ligado à fonte PostgreSQL. Usa o segmento, o ambiente e a janela selecionados. |

O contrato `nexoflow_datastudio_1` usa os bancos `nexoflow_datastudio` (produção) e `nexoflow_datastudio_homologacao` (homologação), com schemas separados por segmento. O PostgreSQL fica na rede privada. O arquivo de credenciais do Windows é para publicação. O Apps Script configura separadamente a credencial da API leitora. Uma execução com PostgreSQL ativo reporta falhas nesse destino e conserva os recibos de retomada. Sheets permanece selecionável nos perfis legados.

## Estado da migração FARMA

- O Windows estável 1.5.45 foi publicado. O pacote 1.5.46 foi exercitado no Windows FARMA de homologação. A simulação de 01 a 18/11 protegeu a conversa histórica de 09/11 ausente na consulta nova e retornou `controle_por_anuncio_divergente` com `applied: false`. [Release estável](https://github.com/felipetelesbarbosa/NexoFlow/releases/tag/v1.5.45) · [Pacote de homologação](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/44438449987/artifacts/14491002371)
- A revisão comercial FARMA READY v2 tem a conciliação de vendas e pedidos documentada. Os 204 pedidos já recuperados não exigem reenvio. Use a revisão ativa e recalcule os controles se uma nova carga mudar o corte. [Inventário do relatório](ROTEIRO%20INVENTARIO%20FARMA%20POSTGRESQL.md)
- Na cópia do Looker, `Anuncios_Veiculados_FARMA` e `Resumo_Anuncios_Veiculados_FARMA` leram o PostgreSQL de homologação de 01 a 18/11. O controle fechou em três anúncios com nomes de campanha, R$ 251,02 e 70 conversas informadas. Três dos 15 fatos diários não informam a métrica. A consulta comercial também confirmou 42 eventos CTWA, métrica de origem própria. [Contrato Meta/Weni](DESTINOS%20META%20WENI.md) · [Alteração validada](https://github.com/felipetelesbarbosa/NexoFlow/pull/15)
- Público (`ds82`) migra por componente. A projeção comercial conferiu 48.843 contatos, 30.939 com compra identificada, 17.904 sem compra identificada, 2.184 com idade informada e 6.174 sem cidade. Compra identificada e comprador com pedido elegível são indicadores distintos. Weni (`ds136`) tem seis dias em homologação, com 2.002 conversas, 465 resolvidas, 316 não resolvidas e 1.221 transferidas. [Aceite e reversão no Looker oficial](IMPLANTACAO%20LEITOR%20FARMA%20OFICIAL.md)

### Produção FARMA em 19/11/2026

As visões de Público, Anúncios e Weni foram instaladas na VPS. Leitor e publicador rodaram saudáveis com a imagem do commit `574e70254fb18c63791d679f06a2944845cd9584` e a READY v2 permaneceu ativa. O leitor usa um processo Uvicorn, limite HTTP 48 e `max_parallel_workers_per_gather=0` na sessão. A rota comercial de Weni aceitou a autenticação e rejeitou a solicitação de teste vazia com `DS_PARAMETROS_INVALIDOS`, sem gravar dias. A visão comercial de Weni retornou `DS_INSIGHTS_COBERTURA_INCOMPLETA` para a amostra, ainda aguardando publicação Windows nesse destino.

O Apps Script comercial está na versão 7. A versão 6 e as definições Compose anteriores ficaram disponíveis para reversão. Para reoperar os serviços, use nesta ordem `compose.yaml`, `compose.tunnel.yaml` e `compose.farma-v146-validado.yaml`. O backup operacional guarda as definições anteriores da FARMA, as imagens e os hashes. PET segue o próprio roteiro.

| Uso comercial | Estado verificado |
| --- | --- |
| Anúncios | A página principal usa `Anuncios_Veiculados_FARMA` para a tabela e `Resumo_Anuncios_Veiculados_FARMA` para os cartões de veiculação e resultados. A fonte dos detalhes de pedidos por anúncio tem aceite próprio. |
| Público | Os 12 componentes antes vinculados à `ds82` na Base de clientes usam `BI_Publico_Resumo` no Looker oficial. São seis cartões, três tabelas e três controles. Os componentes de bairro e LTV têm fontes e aceite próprios. |
| Weni | A visão comercial está instalada. O leitor retornou `DS_INSIGHTS_COBERTURA_INCOMPLETA` ao consultar 01–06/11 pelo papel de leitura. O vínculo comercial da `ds136` depende dos recibos da publicação Windows e da validação do período efetivo. |

No cartão e na tabela de Anúncios, o campo calculado `nxf_roas_meta` divide a soma de `receita_confirmada` pela soma de `investimento_original` da Meta no recorte FARMA. O resultado é exibido em porcentagem. O cálculo exige dados de receita e investimento em BRL e gasto positivo. Receita zero com gasto positivo produz 0%. O campo SQL `roas` da função de destinos registra a metodologia de custo exclusivo. O CPA do painel ainda lê o campo `cpa` desse contrato.

De 01 a 18/11/2026, o painel oficial apresentou três anúncios, R$ 251,02 de gasto Meta, 70 conversas informadas, zero pedidos e R$ 0,00 de receita na fonte de veiculação. `fatos_sem_metrica_meta` sinaliza três fatos sem contagem. Os 42 eventos CTWA têm origem e métrica próprias.

A revalidação no mesmo recorte encontrou dois registros na página oficial de Pedidos dos anúncios por meio da mesclagem legada. Na cópia PostgreSQL de homologação, a mesclagem `FARMA QA14 | Pedidos dos anúncios` devolveu três pedidos válidos de contatos com origem Meta Ads na Weni, posteriores ao primeiro anúncio. A soma foi R$ 322,69, incluindo frete. O período da mesclagem seleciona a chegada dos contatos. A conciliação dos eventos CTWA individuais e da receita com a fonte comercial de veiculação permanece pendente. A rotina no código Windows pode conferir cada pedido em modo somente leitura no perfil comercial. Use um pacote que inclua a alteração e registre o ambiente e a versão READY da execução. [Como executar a conferência](META%20ADS%20NATIVO.md#concilia%C3%A7%C3%A3o-de-pedidos-da-weni-no-windows)

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
