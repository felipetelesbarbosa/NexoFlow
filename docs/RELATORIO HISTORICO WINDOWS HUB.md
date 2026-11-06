# Entrega: histórico paginado Windows e Hub

## Escopo e marcos

Implementação no repositório oficial `felipetelesbarbosa/NexoFlow`, branch `main`. Windows primeiro (`465ce50`), proteção de histórico remoto (`df686b2`), depois PostgreSQL/worker Hub (`794a1e9`). Correções finais e pacote Windows 1.5.16 seguem em commits próprios. O SHA publicado identifica o conjunto final; tags anteriores são preservadas. O Hub não recebe release operacional.

O Windows lê o histórico oficial pela seleção de rota direta/proxy já existente. A coleta é paginada, retomável, por segmento/período/limite e não exige vínculo Weni para reconhecer uma compra oficial. O Hub compartilha a normalização e o contrato, mas nesta fase só executa dados sintéticos em Docker/PostgreSQL isolados.

## Implementação

| Área | Arquivos principais | Resultado |
|---|---|---|
| API e regras | `app/farmalider_client.py`, `app/order_history.py` | GET com query serializada, sem redirects; envelope, identidade oficial, dinheiro, itens, cancelamentos, LTV e atribuição temporal pura |
| Estado Windows | `app/order_history_store.py` | Tabelas SQLite aditivas, páginas/checkpoints atômicos, revisões, pendências, deduplicação entre fontes e índice Weni |
| Operação | `app/run_order_history.py`, `app/nexo_cli.py`, `app/main.py` | Terminal opção 10, histórico sob demanda, incremental D−20 opt-in e incorporação pelo Analytics/Noturno |
| Saídas | `app/order_history_sheets.py`, `app/sheets_storage.py` | Revisão, backup e confirmação em abas novas dos destinos Histórico/Dashboard existentes |
| Anúncios | `app/meta_ads_model.py` | Não aplicar atribuição legada sem janela causal a novas compras históricas |
| Hub | `hub/nexoflow_hub/{api,store,worker,history}.py`, migração 002 | Entrada autenticada, fila, validação compartilhada, páginas e LTV em PostgreSQL, fencing de worker |
| Homologação | `tests/test_order_history.py`, `hub/tests/{test_history,run_docker_hml}.py`, workflow n8n histórico inativo | Fixtures sintéticas, APIs simuladas, banco/API/worker reais em contêineres locais |
| Distribuição | `VERSION`, `pyproject.toml`, scripts de build/checks, workflow Windows, documentação | Versão 1.5.16; inclusão pelo processo oficial, sem distribuir Hub ou dados privados |

O vínculo usa `codCliente` para obter o cadastro oficial no índice geral. CPF válido precisa de correspondência única. CPF inválido preenchido exige CPF concordante e **nome completo + telefone ou nome completo + e-mail**, sem ambiguidades. Não inventa CPF, não deduplica contatos destrutivamente e não faz consultas individuais em massa. FARMA/PET permanecem isolados.

## Demonstrações e testes

- **1.200 pedidos:** limites 500 e 1.000 produzem, respectivamente, três e duas páginas, com os mesmos IDs e valores. Uma página deixa cursor e cobertura parcial.
- **205 pedidos:** orçamento de duas páginas de 100 grava 200; retomada fecha em 205 sem duplicidade. No Hub, faturamento sintético final de R$ 16.400,00 persistido após reinício do PostgreSQL.
- **LTV:** compras elegíveis R$ 80 + R$ 50 e cancelada R$ 30 resultam em R$ 130, duas compras, ticket R$ 65; receita mensal R$ 50 não reduz o LTV.
- **Amostra privada PET:** inspeção local de 52 pedidos/73 itens; 40 válidos, 12 cancelados. Sem pendências financeiras nessa amostra. A amostra não foi copiada para Git, testes ou pacotes.
- **Regressão local:** 1.789 testes Python, 73 ignorados por ambiente; 20 testes JavaScript de conectores Data Studio aprovados. Testes sintéticos cobrem identidade, segmentos, valores, cancelamento, HTTP/timeout/429/TLS, paginação, orçamento, retomada e escrita Sheets idempotente.
- **Hub:** 46 casos com PostgreSQL temporário, migração v1→v2, rollback protegido, isolamento, idempotência, lease, retomada e invariantes. O ensaio inclui HTTP autenticado da API, processo worker e reinício de contêineres. Consultar o workflow do SHA final para a evidência publicada.
- **Qualidade:** Ruff, Pyright Windows/Hub, consistência, auditorias de dependências e Gitleaks. A URL interna `hub-api:8000/tarefas/historico` foi identificada pelo scanner como padrão de chave; exceção exata para porta/caminho sem segredo, sem ignorar arquivos ou regras.

Os resultados locais não substituem o teste dos executáveis instalados no Windows. O workflow oficial executa suíte Windows, launchers, Setup Preserve/Clean/rollback, integridade e varredura dos dois ZIPs antes de publicar. A confirmação final de aprovação, SHA e hashes fica no release e na execução Actions correspondente, não é antecipada por este relatório.

## Correções da revisão final

- Bloqueio de uma revisão Sheets quando há pedido ativo remoto ausente da base local; impede inativação indevida por uma instalação incompleta.
- Cache histórico antigo não desfaz confirmação/cancelamento mais recente do Analytics.
- Diretório cadastral de outro segmento é recusado antes do vínculo Weni.
- Incremental Hub reconsulta janela concluída, retoma incompleta e conserva a data de criação ao recuperar uma tarefa no dia seguinte.
- Isolamento entre a suíte PostgreSQL e o ensaio entre processos: fixtures de datas distintas não contaminam a prova seguinte. A limpeza ocorre somente no banco temporário criado com UUID pelo helper.

## Saídas e cálculos

`Historico_Pedidos` e `Historico_Itens` ficam no destino Histórico; `BI_LTV_Clientes` e `BI_Cobertura_Historica`, no Dashboard do mesmo segmento. Abas antigas e seus cabeçalhos são preservados. Chaves são oficiais e estáveis; IDs são texto; valores para agregação são numéricos. Linhas substituídas mantêm marcador `vigente`.

Faturamento observado = totais conciliados dos produtos + frete oficial uma vez. Status 3 ou pagamento 0 excluem a venda; lista explicitamente vazia não equivale a campo omitido. Descontos com semântica desconhecida ficam pendentes. LTV soma compras elegíveis deduplicadas por cliente/segmento, ticket divide por quantidade de compras. Não há comprovação de valor pago, cliente novo, CAC ou atribuição causal sem evidências suficientes.

A função temporal de atribuição é testada com anúncio A/pedido 1/anúncio B/pedido 2, mas não recebe uma janela comercial inventada. Todas as compras permanecem no histórico, inclusive as sem anúncio e sem conversa Weni.

## Ativação e reversão

Siga [Histórico de pedidos](HISTORICO%20PEDIDOS.md): atualizar pelo Setup Preserve, selecionar o segmento no Terminal e começar com um intervalo pequeno/uma página. Repetir os mesmos parâmetros retoma; mudar limite abre cursor novo com deduplicação. Confira resumo e pendências antes de aumentar o período.

A coleta automática pelo Analytics depende de `FARMALIDER_HISTORY_ENABLED=True` no perfil privado; padrão desativado. O Noturno não realiza backfill completo. Prepare e confira a revisão Sheets em destinos de teste antes de aplicar. Nenhum campo/grupo Weni ou Recompra é modificado pela importação histórica.

Rollback: guardar backup privado do SQLite/revisões, desativar coleta automática e voltar ao pacote Windows anterior preservando dados. Não apagar tabelas. Sheets exige restauração por lote após verificar mudanças posteriores. Hub: parar apenas serviços de homologação, preservar volume; rollback de schema recusa dados existentes. Restaurar em banco separado para ensaiar reversão.

## Limitações e próxima homologação

- Não foram consultadas APIs comerciais nem feitas escritas reais em Weni/Sheets/anúncios. Destinos Sheets são simulados; dashboards não foram editados.
- Validar nova rota FARMA e PET em conexão pessoal e proxy corporativo, sem desligar TLS/antivírus. Confirmar filtros temporais, ordenação durante mutação, inclusividade da data final e descontos/estornos com o fornecedor.
- Extração completa do envelope não prova cobertura temporal completa. O resultado continua “LTV observado”, nunca vida completa do cliente sem comprovação.
- Nenhuma VPS, serviço existente, volume ou porta pública foi alterado. n8n real, integração comercial Hub e coordenação de escrita Windows/VPS permanecem pendentes. O Hub só possui escritor interno protegido por PostgreSQL; isso não coordena o Windows.
- Kaspersky/SmartScreen e conectividade da máquina do usuário exigem homologação local; CI não certifica aprovação desses controles.

Guias: [Windows](HISTORICO%20PEDIDOS.md), [Hub](../hub/HISTORICO.md), [operação Docker/backup](../hub/README.md). Registrar SHA, segmento, parâmetros, contagens, código de saída e diagnósticos sanitizados ao homologar; não compartilhar tokens ou dados pessoais nos chamados públicos.
