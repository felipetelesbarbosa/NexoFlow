# Relatório técnico — BI_Itens FARMA PostgreSQL 1.5.36

Data de implementação: 12/11/2026 (America/Fortaleza). Publicação ainda depende dos checks e dos pacotes do mesmo SHA. A evidência factual de distribuição será registrada após conferência dos downloads públicos.

## Resultado implementado

O Analytics reutiliza exatamente as linhas de `build_looker_tables()["BI_Itens"]`, com o mesmo parser, grão, chaves, identidade e política comercial. Um destino opt-in FARMA encaminha essa tabela ao piloto PostgreSQL por API HTTPS autenticada. As demais tabelas e PET conservam o fluxo anterior. O destino padrão permanece Sheets, sem dependência obrigatória da VPS.

A chave do item deriva da posição produzida pelo parser oficial, posteriormente opacificada pelo builder BI. Uma correção pode alterar conteúdo/chaves ou remover itens: o publicador trata o conjunto explícito de vendas inteiras, com reconciliação por `venda_chave`. Só uma extração marcada completa permite remover itens anteriores dessas vendas. Não há exclusão global por ausência numa extração.

Outbox imutável, lock local do SO, sessão reservada antes da coleta, revisão do servidor, plano de lotes e recibos duráveis protegem retomada e ordenação. Staging, conferência de precisão, upsert somente do conteúdo alterado, auditoria antes/depois e recibo ocorrem numa transação PostgreSQL. O checkpoint Windows só avança após confirmar digest e commit. Rollback de lote recusa alterações posteriores.

O serviço separado de leitura usa SELECT na visão existente `farma.produtos_itens`, outro login e outros segredos. O conector privado do Data Studio recebe período/filtros, agrega no PostgreSQL e oferece distintos globais do período. Publicação incompleta, esquema/origem/grão incompatível, limites ou falhas geram indisponibilidade explícita, sem totais parciais. Não altera o manifesto Sheets nem o relatório comercial.

## Arquivos e componentes

| Área | Arquivos principais |
| --- | --- |
| Contrato, cliente e recuperação Windows | `app/bi_postgres_contract.py`, `app/bi_postgres_client.py`, `app/run_bi_postgres.py` |
| Integração Analytics/CLI/preflight | `app/main.py`, `app/nexo_cli.py`, `app/bi_preflight.py` |
| APIs, persistência, leitura, migração e administração | `integrations/bi_itens_publisher/` |
| Conector privado de leitura | `connectors/bi_itens_api/` |
| Regressões | `tests/test_bi_postgres_client.py`, `tests/publisher/test_postgres.py`, `tests/test_postgres_connector.cjs` |
| Homologação descartável | `scripts/test_postgres_publisher.py` |
| CI e validação de evidências | `.github/workflows/release-v1.yml`, `scripts/validate_release_run.py` |
| Distribuição e operação | VERSION, instalador, versionamento, changelog, exemplo público de configuração e documentação vinculada |

Os dez módulos de assinatura do histórico permanecem byte a byte preservados. O novo roteamento evita alterar o gravador assinado `google_sheets.py`. Dependências da API ficam isoladas do requirements Windows; o Hub e seus serviços não foram modificados.

## Evidências locais

- Suíte Python Linux: **2.017 testes, 95 ignorados, zero falhas**. Inclui integração real da CLI/Analytics com serviços simulados.
- Node: **90 testes aprovados**, incluindo seis casos do novo conector com SDK/UrlFetch simulados.
- PostgreSQL 18.6 temporário: 26 casos de staging, persistência, reaplicação, correção, cancelamento, perdas antes/depois do commit, recuperação, concorrência, autorização, parcial, revisão antiga, rollback, leitura e limites. Docker e HTTP são reais; dados são sintéticos.
- Regressão adicional: disputa local da outbox reproduzida antes da proteção e aprovada após o lock do SO. A retomada simula encerramento do processo anterior e usa uma nova sessão HTTP.
- Leitura volumosa: 200.001 linhas sintéticas; detalhe acima do limite é recusado e resumo agregado fecha sem truncamento. Códigos com zeros, quantidade e dinheiro são preservados.
- Ruff, Pyright, consistência e auditorias de dependências Windows/API aprovados. O CI do SHA final ainda precisa confirmar Windows 3.11/3.14 nas duas codificações, executáveis, Setup Preserve/Clean/rollback, pacote instalado, CodeQL e segredos.

Uma repetição local do smoke Docker encontrou `no space left on device`; o cache exclusivamente desta tarefa foi removido e o teste foi repetido. Esse diagnóstico é do ambiente descartável, não uma falha atribuída à VPS ou ao PostgreSQL comercial. Há aviso não bloqueante de depreciação do TestClient/HTTPX na suíte.

## Limites e próximos passos

Não foram lidos os fatos comerciais do PostgreSQL, alterados a VPS/Cloudflare, emitidos Service Tokens, implantados os serviços ou migradas fontes do Data Studio. Hostinger disponível não oferece terminal. **68.273 itens e o período informado são referências do usuário, não uma nova conciliação executada nesta entrega.**

O Work deve inspecionar schema/PK, origem e cabeçalhos da visão real antes da migração aditiva. A guarda recusa visões agregadas/incompatíveis, dependências adicionais, RLS/triggers não avaliados e logins administrativos. Não mudar contratos ou permissões às cegas para liberar. Banco Métricas, Hub, n8n e configuração do Metabase permanecem fora do destino.

A configuração privada preserva os tokens anteriores e contém Bearers novos separados. Hostnames e credenciais Cloudflare Access só podem ser preenchidos após emissão real; DSNs permanecem exclusivamente no servidor. Nenhum segredo particular entra no Git ou release.

Ver [guia técnico e operacional](BI%20ITENS%20POSTGRESQL%20FARMA.md) e [prompt do Work](PROMPT%20WORK%20BI%20ITENS%20POSTGRESQL.md). A cópia do Data Studio deve ser comparada ao Metabase, incluindo datas, rankings, vazio, nove usos e mesclagens. Migrar produção só após envio homologado, plano READY e resultados aprovados. A correção Windows exige instalar o Setup novo em Preserve.
