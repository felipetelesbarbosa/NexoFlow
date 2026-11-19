# Operação do NexoFlow Windows com a VPS

Estado registrado em 19/11/2026. Use este guia para distinguir a versão do Windows, a publicação de dados e as fontes do Looker efetivamente ligadas ao PostgreSQL.

## Fluxo por perfil

| Etapa | Execução e destino |
| --- | --- |
| Weni | Windows consulta os contatos e a API FarmaLíder, reconcilia os pedidos e aplica as atualizações autorizadas na Weni. |
| Analytics | Windows consolida pedidos, itens e histórico. Com PostgreSQL ativo no perfil, publica pela API HTTPS privada. A VPS recebe os lotes e confirma a revisão READY após a conciliação. |
| Recompra | Windows calcula e aplica a elegibilidade aos grupos Weni (FARMA D+25, PET D+30). O armazenamento configurado no perfil controla o estado e a retomada. O envio da campanha é da Weni. |
| Noturno | Windows automatiza Weni → Analytics → Recompra no perfil selecionado. |
| Looker Studio | O conector privado Apps Script consulta a API leitora da VPS quando o gráfico está ligado à fonte PostgreSQL. Usa o segmento, o ambiente e a janela selecionados. |

O contrato `nexoflow_datastudio_1` usa os bancos `nexoflow_datastudio` (produção) e `nexoflow_datastudio_homologacao` (homologação), com schemas separados por segmento. O PostgreSQL fica na rede privada. O arquivo de credenciais do Windows é para publicação. O Apps Script configura separadamente a credencial da API leitora. Uma execução com PostgreSQL ativo reporta falhas nesse destino e conserva os recibos de retomada. Sheets permanece selecionável nos perfis legados.

## Estado da migração FARMA

- O Windows estável 1.5.45 foi publicado. O pacote 1.5.46 foi exercitado no Windows FARMA de homologação. A simulação de 01 a 18/11 protegeu a conversa histórica de 09/11 ausente na consulta nova e retornou `controle_por_anuncio_divergente` com `applied: false`. [Release estável](https://github.com/felipetelesbarbosa/NexoFlow/releases/tag/v1.5.45) · [Pacote de homologação](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/44438449987/artifacts/14491002371)
- A revisão comercial FARMA READY v2 tem a conciliação de vendas e pedidos documentada. Os 204 pedidos já recuperados não exigem reenvio. Use a revisão ativa e recalcule os controles se uma nova carga mudar o corte. [Inventário do relatório](ROTEIRO%20INVENTARIO%20FARMA%20POSTGRESQL.md)
- A página de ensaio de Anúncios mostrou três anúncios, R$ 251,02 e 70 conversas para 01 a 18/11. Em 09/11 mostrou uma conversa e em 11/11 mostrou “Não há dados”. Esses números vieram da fonte Sheets `ds133`. Na VPS de homologação, `Anuncios_Veiculados_FARMA` e `Resumo_Anuncios_Veiculados_FARMA` confirmaram os três anúncios, R$ 251,02 e 42 eventos CTWA. A métrica de conversas Meta saiu indisponível no período. A promoção depende de preservar a informação histórica exibida e indicar a cobertura da métrica no Looker. [Contrato Meta/Weni](DESTINOS%20META%20WENI.md)
- Público (`ds82`) migra por componente, conservando as métricas e os filtros. Compra identificada na base e comprador com pedido elegível são indicadores distintos. Weni (`ds136`) tem controle de seis dias em homologação, com 2.002 conversas, 465 resolvidas, 316 não resolvidas e 1.221 transferidas. Para produção, confira a visão, a origem, o fuso e a cobertura antes de trocar as fontes. PET segue o próprio roteiro. [Aceite e reversão no Looker oficial](IMPLANTACAO%20LEITOR%20FARMA%20OFICIAL.md)

## Conferir o Windows antes de uma carga

Abra o Terminal NexoFlow no perfil da execução. Para conferir versão, acesso e destino PostgreSQL:

```powershell
Set-Location C:\NexoFlow
nexo versao
nexo armazenamento postgres diagnosticar
```

Confira segmento, ambiente, revisão ativa e pendências. A credencial privada é indicada por `DATASTUDIO_CREDENTIALS_FILE` no perfil local. O caminho pode incluir uma subpasta específica do ambiente ou do ensaio. Guarde o arquivo fora do Git. Consulte os requisitos de ativação, importação de estado, preparo e retomada no [guia de migração](MIGRACAO%20WINDOWS%20POSTGRESQL%20DATA%20STUDIO.md).

Uma falha durante o envio pode acontecer depois de a VPS ter gravado o lote. Retome o plano e confirme seus recibos antes de iniciar outra revisão. Uma carga completa de Weni, Recompra e Analytics usa os atalhos normais com o perfil e o destino já conferidos. Registre no relatório de execução o ambiente, a versão Windows e a READY publicada. Só marque a troca do Looker como concluída após conferir a fonte efetiva, os totais e os filtros no endereço oficial.
