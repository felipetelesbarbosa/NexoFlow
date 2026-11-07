# E. Arquitetura dos produtos web
Especificação de 07/11/2026. Nenhum frontend, domínio ou conta de usuário final foi publicado.

## Produtos e limites
| Produto | Público | Dados disponíveis | Escrita inicial |
| --- | --- | --- | --- |
| Central de Operações, painel.nexoflowhub.com.br planejado | Admin, desenvolvedor, leitor técnico autorizado | Infra, tarefas, integração, erros saneados, capacidade e backups | Somente consulta |
| NexoFlow Métricas, metricas.nexoflowhub.com.br planejado | Gestor FARMA/PET, visualizador e administrador com escopo explícito | Relatórios BI autorizados | Somente consulta |
| Hub Python | n8n e serviços internos | Fatos/regras/tarefas | Comercial bloqueada |
| Grafana opcional | Equipe técnica restrita | Telemetria agregada | Consulta técnica; não substitui Métricas |

Não haverá acesso de usuário Métricas a n8n, PostgreSQL, SQL livre, logs brutos, segredos, Prometheus ou Docker. Ser admin técnico não concede automaticamente dados pessoais de BI. Navegação entre produtos depende de permissão explícita; sessões distintas.

## Componentes e fluxos
Frontend React/TypeScript responsivo servido por contêiner estático sem privilégios. APIs de consulta FastAPI separadas, uma de operações e outra de BI; contratos OpenAPI privados/versionados. Mesma origem de UI/API por produto evita CORS amplo. Não inserir tokens de segmento Hub no JavaScript.

Central: navegador → Cloudflare Access adicional → BFF/API de operações → views agregadas/telemetria saneada. Métricas: navegador → autenticação própria → API BI → views/agregações PostgreSQL com filtro de permissão. Workers consolidam fatos aprovados em tabelas de leitura; n8n orquestra, sem regras financeiras.

Banco de identidade separado por schema/credencial das tabelas de negócio; não reutilizar o banco interno n8n. Papéis runtime de consulta sem ownership, sem superuser/BYPASSRLS; migrador separado. Usar pools limitados, consultas parametrizadas, statement_timeout, paginação e índices. RLS por segmento/relatório como defesa adicional, FORCE RLS e SET LOCAL dentro da transação; o serviço não pode ser dono das tabelas protegidas. Limpar contexto ao devolver conexão ao pool.

Consultas BI e exportações devem usar o mesmo escopo do backend. Cache inclui usuário/política, organização, segmento, relatório, período, versão dos dados e moeda. Revogação de permissão invalida sessões/cache; nunca confiar apenas no seletor de marca do frontend.

## Autenticação e ciclo de vida
Cadastro fechado: administrador cria usuário individual e escopo; convite de ativação com token aleatório, hash no banco, uso único e prazo. O usuário define sua senha por canal HTTPS. Não enviar senha fixa por e-mail nem registrar valores em logs.

Hash Argon2id com salt único e parâmetros calibrados no servidor; referência mínima inicial OWASP: 19 MiB, 2 iterações, paralelismo 1. Parametrização precisa ser medida sob tentativas concorrentes e protegida por rate limit. Bibliotecas maduras, atualização controlada; sem criptografia reversível de senha.

Sessão opaca aleatória no servidor; só hash do token persistido. Cookies host-only Secure/HttpOnly/SameSite=Lax, nomes diferentes por produto, sem Domain=.nexoflowhub.com.br. Sem token persistente em localStorage. Renovação do ID após login/elevação, CSRF nos endpoints que mudam estado e validação de Origin. Logout, senha trocada, bloqueio ou remoção de escopo revogam sessões.

Proposta: expiração inativa 30 min, absoluta 12h; sessão administrativa de 15 min inativa/8h absoluta; confirmar com o responsável antes de uso final. MFA obrigatório para admin e desenvolvimento. Aplicar autenticação forte também atrás do Access; validar JWT Access, assinatura, issuer, audience, expiração e identidade, sem confiar em header e-mail não assinado.

Recuperação de acesso com resposta uniforme para evitar enumeração; token uso único/curto, armazenado com hash, sessão revogada após troca. Limites por conta e origem, backoff, alertas de abuso e canal de recuperação aprovado. Auditoria registra ator opaco, ação, escopo, horário, resultado e versão de política, sem senha/token/PII.

## Autorização no backend
Permissão é produto + organização + segmento + relatório + ação + classificação do dado. Deny por padrão em cada request, inclusive filtros, detalhe, download e links salvos. IDs opacos não substituem autorização.

| Perfil | Operações | BI | Exportação / PII |
| --- | --- | --- | --- |
| Admin | Consulta técnica e gestão de acessos quando implementada | Todos os relatórios somente se concedidos | Escopo explícito e auditoria |
| Desenvolvedor | Saúde, jobs e diagnósticos saneados | Nenhum por padrão | Sem PII por padrão |
| Gestor FARMA | Nenhum | FARMA e relatórios autorizados | Agregado por padrão |
| Gestor PET | Nenhum | PET e relatórios autorizados | Agregado por padrão |
| Visualizador | Nenhum | Marcas/relatórios concedidos, leitura | Exportação desabilitada por padrão |

Administração de usuários é função de identidade isolada e auditada. Ações operacionais de executar/reprocessar/cancelar/configurar integrações não fazem parte da primeira Central de consulta. Nenhum endpoint de comando deve existir apenas oculto no menu.

## Central: módulos e dependências
Dashboard geral; Infraestrutura; Aplicações; Integrações; APIs/requisições; Execuções; Filas/checkpoints; Logs; Erros/diagnóstico; PostgreSQL/capacidade; Backups; Alertas; Usuários/permissões.

Fontes: telemetria instalada, estado do monitor, jobs e tentativas Hub, metadados PostgreSQL, resultados de backup/check/restore e adaptadores n8n read-only. A API Central oferece visões saneadas, sem SQL arbitrário, download de backup ou acesso ao socket Docker. Detalhe de erro contém código classificado e correlação, sem header/token/corpo externo.

Dependências Codex: autenticação/RBAC, adaptador SQLite/textfile ou Prometheus, endpoints read-only, contrato de eventos, paginação e filtros, cobertura de dados e sanitização testada. Fonte indisponível retorna estado de coleta atrasada, nunca zero fabricado.

## Métricas: modelos e semântica
Fatos oficiais por (segmento,pedido_id); itens por identidade estável do item; cliente oficial por (segmento,codCliente). Contatos Weni são outra entidade, vinculada somente por evidência. Não usar CPF/telefone como chave pública ou somar contatos como pessoas distintas.

Separar fatos de pedidos de itens para não multiplicar frete/faturamento em joins. Preservar cancelamentos/estornos, valores oficiais em centavos e política versionada. Deduplicação, LTV e regras permanecem no Python. Views/materializadas incrementais evitam JSON bruto a cada abertura.

A mesma estrutura de páginas será oferecida a FARMA e PET, conforme a orientação complementar, incluindo Pedidos dos anúncios. Anúncios terá definições aprimoradas e KPIs ainda ausentes nas fontes atuais. Os Data Studio permanecem inalterados como referência.

LTV observado é o acumulado das compras válidas conhecidas por cliente oficial e data de corte; mostrar início/fim da cobertura e incompletude. Receita média por cliente no mês não é LTV. Recorrência e cliente novo dependem de cobertura anterior, com estado indeterminado quando ela falta.

ROAS requer gasto e receita atribuída sob política comprovada; CAC requer novos compradores atribuídos, não todos os contatos/compradores. Conversas com venda requerem IDs/eventos de conversas e vínculo temporal válido. Payback usa margem de contribuição acumulada da coorte versus CAC, não faturamento bruto. Exibir “Aguardando fonte/atribuição/margem” em vez de zero ou estimativa sem base.

## Interface
pt-BR, dark padrão/grafite, claro opcional, navegação lateral recolhível, cards compactos, gráficos com unidades, tabelas pesquisáveis/ordenáveis/paginadas e filtros por período. Detalhes em painel lateral; sucesso/erro com ícone e texto, sem depender só de cor. Mobile com navegação e tabelas adaptadas; teclado, contraste e leitores de tela.

Preservar logos sem deformação. PET usa azul #20AFE9 e laranja #F69F11. FARMA usa identidade própria verificada no material de marca. Referência Iota.hub é conceitual/funcional; não copiar código, marca ou layout proprietário. As imagens originais não foram recuperadas como arquivos nesta execução; o desenho usa os requisitos textuais do responsável e deverá receber validação visual posterior.

## Critérios para publicar
Testes automatizados de login, recuperação, revogação, CSRF, sessão, IDOR, cache e exportação; usuários FARMA não podem consultar PET nem por URL/API; sem rotas técnicas para usuários BI. Testes de carga e acessibilidade; paridade da matriz no mesmo período/cobertura; dados reais somente com autorização própria. DNS/ingress novos exigem autorização específica. Rollback mantém Data Studio e aplicação anterior disponíveis.

Referências técnicas: [OWASP Password Storage](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html), [Session Management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html), [Authorization](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html).

