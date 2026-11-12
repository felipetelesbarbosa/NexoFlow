# Estrutura PostgreSQL e mapa de armazenamento Data Studio

Catálogo fechado: `app/ds_backend/registry.json`. Os campos completos, tipos e chaves estão nesse arquivo versionado; `connectors/datastudio_api/Schemas.js` é gerado a partir dele e dos tipos legados. Não confundir a quantidade de tabelas do catálogo com as 37 fontes observadas no relatório comercial.

| Tabela lógica | Origem | Chave / grão | Leitura Data Studio |
| --- | --- | --- | --- |
| `Base_Contatos` | Analytics/integração oficial | `contact_uuid` | Visão autorizada; 55 campos |
| `Historico_Alteracoes` | Analytics/integração oficial | `contact_uuid + sincronizado_em + acao` | Privada; não descoberta pelo conector |
| `Metricas_Diarias` | Analytics/integração oficial | `data + tipo_atribuicao + anuncio_id` | Privada; não descoberta pelo conector |
| `Eventos_Anuncios` | Analytics/integração oficial | `event_id` | Privada; não descoberta pelo conector |
| `Campanhas_Meta` | Analytics/integração oficial | `anuncio_id` | Privada; não descoberta pelo conector |
| `Pedidos_FarmaLider` | Analytics/integração oficial | `pedido_chave` | Privada; não descoberta pelo conector |
| `Itens_Pedidos_FarmaLider` | Analytics/integração oficial | `item_chave` | Privada; não descoberta pelo conector |
| `Metricas_Vendas` | Analytics/integração oficial | `data` | Privada; não descoberta pelo conector |
| `BI_Resumo_Diario` | Analytics/integração oficial | `data` | Visão autorizada; 35 campos |
| `BI_Canais` | Analytics/integração oficial | `chave` | Visão autorizada; 9 campos |
| `BI_Conversao` | Analytics/integração oficial | `chave` | Visão autorizada; 8 campos |
| `BI_Vendas` | Analytics/integração oficial | `data` | Visão autorizada; 13 campos |
| `BI_Ads` | Analytics/integração oficial | `data_snapshot + tipo_atribuicao + origem + tipo_campanha + canal_destino + anuncio_id` | Visão autorizada; 13 campos |
| `BI_Pedidos` | Analytics/integração oficial | `pedido_chave` | Visão autorizada; 29 campos |
| `BI_Status` | Analytics/integração oficial | `atualizado_em` | Visão autorizada; 18 campos |
| `Controle` | Analytics/integração oficial | `chave` | Privada; não descoberta pelo conector |
| `BI_Publico` | Analytics/integração oficial | `contato_chave` | Visão autorizada; 14 campos |
| `BI_Clientes` | Analytics/integração oficial | `cliente_chave` | Visão autorizada; 7 campos |
| `BI_Clientes_Vendas` | Analytics/integração oficial | `venda_chave` | Visão autorizada; 9 campos |
| `BI_Itens` | Analytics/integração oficial | `item_chave` | Visão autorizada; 12 campos |
| `BI_Produtos_ABC` | Analytics/integração oficial | `periodo_inicio + periodo_fim + produto_codigo + produto_nome` | Visão autorizada; 15 campos |
| `BI_Produtos_Juntos` | Analytics/integração oficial | `periodo_inicio + periodo_fim + produto_a_codigo + produto_b_codigo` | Visão autorizada; 8 campos |
| `BI_KPIs_Periodo` | Analytics/integração oficial | `periodo_inicio + periodo_fim` | Visão autorizada; 19 campos |
| `BI_Qualidade` | Analytics/integração oficial | `motivo_historico` | Visão autorizada; 21 campos |
| `Historico_Pedidos` | historico_publicado_READY | `chave` | Visão autorizada; 15 campos |
| `Historico_Itens` | historico_publicado_READY | `chave` | Visão autorizada; 11 campos |
| `BI_LTV_Clientes` | historico_publicado_READY | `chave` | Visão autorizada; 10 campos |
| `BI_Cobertura_Historica` | historico_publicado_READY | `chave` | Visão autorizada; 14 campos |
| `BI_Historico_Resumo` | historico_publicado_READY | `chave` | Visão autorizada; 19 campos |
| `Meta_Ads_Diario` | Analytics/integração oficial | `chave` | Privada; não descoberta pelo conector |
| `Meta_Ads_Campanhas` | Analytics/integração oficial | `chave` | Privada; não descoberta pelo conector |
| `Meta_Ads_Anuncios` | Analytics/integração oficial | `chave` | Privada; não descoberta pelo conector |
| `BI_Meta_Resultados` | Analytics/integração oficial | `chave` | Visão autorizada; 37 campos |
| `BI_Meta_Conversoes` | Analytics/integração oficial | `chave` | Visão autorizada; 21 campos |
| `Tickets_Delivery_Weni` | Analytics/integração oficial | `ticket_uuid` | Privada; não descoberta pelo conector |
| `BI_Delivery_Pedidos` | Analytics/integração oficial | `pedido_chave` | Visão autorizada; 12 campos |
| `Conversas_Diarias` | insumo manual Weni; confirmar mapeamento na migração | `projeto + data` | Visão autorizada; 3 campos |
| `Cache_profile` | cache privado reconstruível; fonte PostgreSQL | `segment` | Privada; não descoberta pelo conector |
| `Cache_orders` | cache privado reconstruível; fonte PostgreSQL | `id` | Privada; não descoberta pelo conector |
| `Cache_creations` | cache privado reconstruível; fonte PostgreSQL | `id` | Privada; não descoberta pelo conector |
| `Cache_history_run_receipts` | cache privado reconstruível; fonte PostgreSQL | `run + segment + id` | Privada; não descoberta pelo conector |
| `Cache_history_windows` | cache privado reconstruível; fonte PostgreSQL | `key` | Privada; não descoberta pelo conector |
| `Cache_history_seen` | cache privado reconstruível; fonte PostgreSQL | `window_key + id` | Privada; não descoberta pelo conector |
| `Cache_history_orders` | cache privado reconstruível; fonte PostgreSQL | `segment + id` | Privada; não descoberta pelo conector |
| `Cache_history_issues` | cache privado reconstruível; fonte PostgreSQL | `segment + id` | Privada; não descoberta pelo conector |
| `Cache_history_revisions` | cache privado reconstruível; fonte PostgreSQL | `segment + id + old_digest + new_digest` | Privada; não descoberta pelo conector |
| `Exclusoes_Publicacao` | auditoria privada da revisão READY | `segmento + pedido_id` | Privada; não descoberta pelo conector |

## Caminhos de execução

| Fluxo | Coleta | Persistência no modo PostgreSQL |
| --- | --- | --- |
| Analytics `main.py` | Weni, FarmaLíder e Meta pelos clientes existentes | `ds_backend.runtime`/`adapter`; comparação/delta, BI, Controle e histórico na revisão atômica |
| Noturno | Orquestra as etapas existentes; não duplica regras | Cada aplicativo usa a configuração do perfil; não exige credencial Sheets no backend novo |
| Update Weni / deduplicação | Mesmas revisões/guardas de identidade, consentimento e POST | Estado remoto CAS, cache observado; `ds_backend.dedup` reaproveita `requests_for` e validação financeira de `dedup_bi` |
| Recompra | Mesmos critérios FARMA D+25/PET D+30 e reconferência antes do POST | Estado remoto confirmado, inclusive intenção/recusas; não utiliza BI para admitir contatos |
| Terminal histórico | GET paginado oficial, período explícito; incremental D−20 | Cache/janelas/recibos remotos. `--somente-resumo` consulta a base financeira PostgreSQL, não o cache parcial |
| Data Studio/Looker local | Recalcula dos fatos acumulados existentes | `run_looker.py` usa fábrica; nenhuma gravação prévia em Sheets |
| Meta nativo independente | Coleta autenticada existente | `run_meta_ads.py` usa o mesmo contexto por perfil; simulação apenas lê |
| Delivery/webhooks opcionais | Clientes e autenticação existentes | Fábrica explícita; instalação não habilita webhooks nem integrações |
| Armazenamento/diagnóstico | Conexão privada de publicação | Verifica protocolo/target/segmento/schema; não faz fallback |
| Exportação inicial | Leitura controlada dos três Sheets/continuações | Única ponte de corte, com hashes, capacidade e exclusões da revisão READY |

Os dez módulos de assinatura do publicador histórico/Sheets permanecem byte a byte na base. As mudanças de transporte ficam em módulos novos e chamadores. Os comandos Sheets e as credenciais anteriores são mantidos para reversão explícita.

## Grãos e qualidade

Pedidos únicos por segmento/ID oficial; itens distintos mesmo com SKU repetido; cliente oficial distinto de contato Weni. Datas civis usam America/Belem. Dinheiro permanece Decimal/centavos. Técnicos de frete não entram em produtos/unidades. O resumo TOTAL conta clientes diretamente, sem somar compradores mensais. Meta/Google mantêm origem comprovada, sem inventar gasto nem crédito para interação posterior ao pedido.

Base_Contatos é autorizada para as mesclagens privadas existentes, com exclusão dos campos individuais de clique na API leitora. Histórico de alterações, Controle, cache, estados e exclusões são privados. Uma tabela fora do catálogo exige revisão/versionamento; não há descoberta ampla de abas.

## Conferência do ambiente comercial

O Work informou três mesclagens ativas e 37 fontes Sheets/Apps Script. Os nomes/campos de todas elas ainda precisam ser comparados ao catálogo. Entradas manuais dentro das abas não foram descartadas como hipótese. Nenhuma remoção de fonte é autorizada apenas por zero gráficos diretos. Ver o guia de migração para os comandos e os critérios do corte.
