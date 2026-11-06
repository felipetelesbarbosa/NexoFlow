# Relatório técnico — Hub Etapa 2

## Entrega e evidências

O Windows 1.5.15 foi publicado antes desta implementação, no commit `07dc391afff4e1dc0aad238224a2d0e2c99b75ca`, com CI, Setup/completo e hashes. O desenvolvimento Hub mantém `VERSION` e os releases Windows intactos; seus commits usam `[skip release]`. Não há release operacional do Hub.

O núcleo Linux implementa API, fila e worker sobre PostgreSQL **real**, com fontes comerciais **simuladas**. O ensaio Docker local construiu a imagem, subiu PostgreSQL 18.6 em rede interna sem portas, aplicou migrações, iniciou API/worker e confirmou resultados persistidos. Depois interrompeu um processo após checkpoint, aguardou a lease real, retomou sem repetir a etapa e reiniciou API/worker/PostgreSQL, comprovando persistência e novo processamento PET. Os três serviços passaram nos healthchecks; o papel da aplicação não tem superuser. Nenhuma chamada ou gravação comercial ocorreu.

A suíte de 38 testes de integração verifica concorrência de produtores/workers, payload conflitante com mesma chave, separação FARMA/PET, fencing do proprietário antigo, checkpoint idempotente, rollback transacional, recuperação, pendências, autenticação, proibição de escrita, API e exports n8n inativos. Variações do contrato normalizado incluem estados documentados, frete, valores divergentes, proprietário/CPF/identidade, itens ausentes e diferentes políticas de recompra por segmento.

A regressão Windows local manteve a suíte de **1.770 testes aprovada**, com 73 específicos de ambiente ignorados; três regressões adicionais protegem a extração de regras puras. A extração das funções puras preserva as interfaces de CPF e Recompra. Os testes Windows no GitHub e o workflow Hub ficam ligados ao SHA do commit, sem alterar o produto distribuído já publicado. O CI dedicado repete build, PostgreSQL, HTTP, interrupção e reinício, além de lint/tipos/auditoria. Consulte o resultado do workflow do commit final antes de homologar outra instalação.

## Arquivos e mudanças

| Área | Arquivos principais | Mudança |
| --- | --- | --- |
| Núcleo / serviços | `hub/nexoflow_hub/{api,store,worker,config,core,orders,migrate}.py` | API interna, configuração própria, decisões normalizadas, fila e estados duráveis |
| PostgreSQL | `hub/migrations/001_{up,down}.sql`, `hub/init-hml.sql` | Schema Hub, índices, chaves por segmento, migração explícita e reversão só vazia; bootstrap apenas no banco descartável |
| Docker | `hub/Dockerfile`, `hub/Dockerfile.dockerignore`, `hub/compose.homologacao.yaml` | Build com imagens por digest, contexto mínimo sem segredos, usuário sem root, read-only/capabilities limitadas; Compose isolado, sem portas/Tunnel |
| Testes | `hub/tests/{test_hub,test_orders,run_docker_hml}.py` | Decisões, persistência, concorrência e processos reais; limpeza limitada ao UUID local do ensaio |
| Reutilização | `app/business_identity.py`, `app/business_recompra.py`, `app/{analytics,recompra,recompra_profiles}.py`, `pyproject.toml` | Extração pequena de funções puras, preservando interfaces Windows; sem novos clientes/configuração no aplicativo |
| Distribuição | `scripts/build_release.ps1` | Exclui `hub/` dos futuros pacotes Windows; não gera release nesta etapa |
| n8n / CI | `hub/n8n/homologacao-{farma,pet}.json`, `.github/workflows/hub.yml` | Workflows manuais inativos com polling limitado; CI isolado sem credenciais de produção |
| Documentação | `hub/README.md`, escopo em `AGENTS.md`, `README.md`, `docs/planejamento/` | Operação Linux, segredos, banco, backup, reversão e limites |

## Falhas encontradas e corrigidas na homologação

- O primeiro bootstrap falhou por leitura do SQL de inicialização pelo UID do PostgreSQL. Preparados corretamente os arquivos públicos e a propriedade do código na imagem, mantendo os segredos externos em diretório privado.
- Nova linha no arquivo da senha sintética gerou autenticação divergente. O bootstrap agora remove explicitamente CR/LF/espaços das bordas, alinhado à leitura da configuração.
- Uma lista YAML de tmpfs interpretava a vírgula como outro mount. O ensaio real detectou o problema; o item foi cotado e o teste completo passou.
- Tipagem de rows/cursor e SQL de migração corrigida explicitamente. SQL vem de recursos versionados, nunca do corpo da API. O token de lease também é conferido na coordenação transacional para bloquear confirmações antigas.

- A revisão final também bloqueou cenários desconhecidos na fila interna e tornou a confirmação de fonte explicitamente obrigatória, com regressões reproduzidas antes da correção.

## Limitações e pendências

- Não houve acesso ou mudança na VPS 2132956. O PDF e os dez arquivos do ZIP foram inspecionados; scripts operacionais recebidos não foram executados. O ZIP não contém os seis Compose efetivos; não é possível afirmar compatibilidade de uma extensão de produção sem essa leitura real. Entregue projeto separado para ensaio, não alteração cega de `/usr/local/sbin/nexoflow-compose`.
- Motor n8n real/importação UI não executados aqui. Estrutura dos exports e contrato HTTP de criação/polling/resultado são testados; credenciais por segmento e rede interna devem ser configuradas pelo Work em homologação, sem ativar fluxos comerciais.
- PostgreSQL e locks do Hub não coordenam Win32. Nenhuma escrita concorrente Windows/VPS foi habilitada ou declarada resolvida.
- As portas dos conectores rejeitam produção. Histórico oficial, paginação, contratos de cobertura, coleta Google Ads e publicação Sheets/Data Studio aguardam integração gradual e autorização. O núcleo não substitui todas as guardas/enriquecimentos/revisões de escrita do Windows.
- O banco temporário usa papel de aplicação sem privilégios administrativos, dono somente do banco Hub de homologação. Antes de produção, separar migrador/runtime e aplicar grants mínimos; testar backups/restauração e coordenação de proprietário único.
- A suíte usa TestClient de Starlette com httpx; a versão atual emite aviso de depreciação em favor de httpx2. O aviso não é suprimido e não impediu os ensaios HTTP reais da API.
- As ressalvas da Etapa 1 (backup natural de 07/11, Monarx, kernel, retenção e webhooks) permanecem fora desta mudança.

Próxima etapa: o Work confere o SHA e a infraestrutura real, executa o ensaio isolado e registra evidências. Só depois conectar fontes gradualmente, em leitura primeiro, com contratos de identidade/cobertura e revisão de escrita. O [guia](README.md) detalha variáveis, endpoints, comandos, backup e rollback.
