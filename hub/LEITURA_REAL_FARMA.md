# Noturno FARMA HML: leitura real e planejamento em simulação

Esta entrega mantém a publicação oficial Windows e os cenários sintéticos.
Os dois cenários explícitos abaixo entram na fila existente e são executados
pelo mesmo worker que a Central monitora. Nunca aplicam planos nem publicam
Analytics, inclusive em homologação. Não criam checkpoint comercial nem READY.

| Cenário | Escopo | Resultado |
| --- | --- | --- |
| `leitura_real_amostral` | Weni, FarmaLíder e Meta independentes; Meta recupera a referência 07 e 09/11/2026 | Diagnóstico sanitizado, com cobertura amostral |
| `planejamento_real` | Diagnóstico + histórico paginado, estado FARMA verificado, Update Weni e Recompra D+25 | Propostas agregadas e totais financeiros confirmados; revisão necessária |

A identificação CTWA usa o módulo compartilhado `meta_events` e o planejador
Weni. A **atribuição comercial integral do Analytics** (classificações de
conversas, destinos históricos, cobertura de anúncios e histórico de
primeira compra) ainda exige integração e conciliação; não se infere venda
ou CAC de um clique. O Analytics financeiro usa `order_history.normalize_order`.
O recorte não substitui uma revisão congelada do Windows. Recompra é calculada
sobre o cadastro Weni observado, não sobre um Update hipoteticamente aplicado.

## Credenciais e rede

- Ambiente homologação, perfil FARMA, `HUB_ESCRITA_REAL=false` obrigatório.
- Adicione `compose.leitura-real-hml.yaml` somente ao Compose do worker HML.
- Preserve o complemento Meta já implantado: `HUB_META_TOKEN_FILE`,
  `HUB_META_PROXY_URL=http://farma-meta-egress:3128`,
  `HUB_META_ACCOUNT_ID=898435729140540` e `HUB_META_API_VERSION=v26.0`.
- Provisione o token existente de FarmaLíder do perfil FARMA Windows pelo
  canal privado da VPS, não no Git, chat, n8n, env com valor em texto, linha de
  comando ou URL de log. Diretório privado:
  `/srv/nexoflow/central-hml/secrets/farma_leitura`.
  Arquivo sugerido: `farmalider_api_token`, root:10001, modo 0440,
  montagem somente leitura em `/run/secrets/farmalider_api_token`,
  variável `HUB_FARMALIDER_TOKEN_FILE` com o caminho do arquivo montado.
- Para Weni, monte separadamente o token de leitura do projeto Flows Delivery
  FarmaLíder em `/run/secrets/weni_flows_read_token`; configure
  `HUB_WENI_FLOWS_READ_TOKEN_FILE`. **Não reutilize a chave de autenticação
  do webhook do Hub**.
- Ambos os conectores passam por `HUB_SOURCE_PROXY_URL=http://farma-fontes-egress:3128`.
  É um proxy de saída **na VPS**, não o proxy corporativo Windows. Provisione
  numa rede interna dedicada exclusivamente ao worker FARMA e a esse proxy,
  sem portas públicas e com saída somente para CONNECT
  `api.farmalider.net.br:3200` e `flows.weni.ai:443`. Restrinja o ACL de
  origem à rede interna, desabilite cache e logs de acesso, mantenha TLS
  ponta a ponta, verificação de certificado e bloqueio de todo outro destino.
  Não use uma faixa IP fixa sem verificar a disponibilidade na VPS.
  Não atribua a rede externa ao worker diretamente.
- O cliente FarmaLíder fixa a URL externa
  `https://api.farmalider.net.br:3200/farmalider` sem fallback, permite só GET
  nos caminhos `/api/Delivery/pedidos/farma`,
  `/api/Delivery/pedido/{codigo}` e `/api/Delivery/clientes/FARMA` (prefixo
  `/farmalider`). Token é query string **dentro de TLS** conforme o contrato
  da API. A consulta individual valida o identificador e o segmento explícito
  do cabeçalho e os vínculos dos itens; não publica identificadores.
- A listagem de cadastros é integral e não tem paginação no Swagger. Só
  habilite `HUB_FARMALIDER_DIRECTORY_PROBE=true` após verificar memória e
  tempo, porque a operação pode ser extensa. O diagnóstico usa
  `CustomerDirectory` do Windows e registra apenas contagens de recebidos,
  rejeitados e conflitos. A rota individual por CPF é reservada ao plano
  integrado, que deve aplicar as regras de identidade existentes.
- Se o token Farma ainda não existir, marque a fonte pendente, sem
  reutilizar tokens Weni/Meta/PET. Sem acesso necessário, confirmar com TI/API
  as permissões GET para os endpoints acima e `/api/Delivery/cliente/cpf/{cpf}`,
  e acesso pela rota externa TLS porta 3200 a partir da VPS.

## Preparar o planejamento (opcional após o diagnóstico)

O diagnóstico amostral independe do ZIP Windows. Para um planejamento com
estado real, use o complemento `compose.planejamento-real-hml.yaml` após
comprovar as três leituras e transferir os insumos privados FARMA:

- `farma_leitura/weni_update_state.json`: checkpoint existente com
  `last_success_utc` válido e pendências de compra do Update.
- `farma_leitura/recompra_state.json`: estado existente, schema 1, com mapa
  `contacts` e pendências de compra. Não use estado vazio inventado.
- `farma_leitura/farma-reservas.json`: manifesto FARMA original; deve ser
  legível pelo UID 10001 e montado somente leitura.
- Configure os SHA-256 respectivos em
  `HUB_PLAN_WENI_STATE_FILE_SHA256`, `HUB_PLAN_RECOMPRA_STATE_FILE_SHA256`
  e `NEXOFLOW_RESERVAS_FARMA_SHA256` no ambiente privado do Compose.
  Confirme a origem FARMA de cada arquivo. O código não altera esses hashes,
  arquivos ou checkpoints.
- `HUB_PLAN_HISTORY_START` e `HUB_PLAN_HISTORY_END` definem o recorte civil
  America/Belem (ex.: 2026-11-01 e 2026-11-26). O corte UTC é a criação da
  tarefa no Hub; o fim do período e o checkpoint anterior não podem
  ultrapassá-lo. Um cadastro observado depois do corte impede afirmar uma
  fotografia congelada. Use a mesma janela/corte para conciliar o Windows.
- Até 32 dias, 50 páginas de 500 pedidos, 50 mil cadastros, 5 mil contatos,
  30 mil mensagens e eventos CTWA. Cada sessão permite até 2 mil GETs e
  900 s, com corpo decodificado limitado a 64 MiB. Antes de habilitar a
  consulta integral, confira orçamento real de RAM e tempo do worker.
  Excesso de limite, paginação inconsistente, identidade ou reserva não
  confirmada ficam pendentes; não se substitui o restante por zero.

O transporte restringe método GET, destinos HTTPS, portas, rotas, proxy
privado e certificado; rejeita redirecionamentos. O resultado persiste
somente contagens, totais financeiros, origem, estados e códigos fechados.
Não envia cadastro, CPF, telefone ou token ao Hub/n8n/Central.

## Implantação e execução manual (somente HML)

1. Aguarde a aprovação do PR e a CI Hub com PostgreSQL temporário. Confira
   SHA, Compose ativo, imagens de reversão, backup recuperável e banco
   `nexoflow_hub_hml` na VPS. Não altere PET, Windows ou Produção.
2. Preserve perfis, convites, papéis, volume de perfis, credenciais,
   complementos de usuários/Métricas/Meta e domínio oficial. Construa as
   imagens do Hub, Central API e Central Web no SHA aprovado. Aplique a
   **migração 008 somente no banco HML**, pelo serviço `migracao` existente,
   e atualize API, worker, Central API e Central Web de forma coordenada.
   A migração acrescenta à view existente uma projeção de evidência com
   chaves/valores permitidos, sem conceder acesso à tabela de tarefas.
   Confirme saúde dos quatro serviços. Em rollback, preserve o backup
   recuperável e as imagens anteriores; não faça downgrade com tarefas
   gravadas nem restaure banco oficial. O código antigo exige schema 007;
   a reversão da migração deve ser planejada antes da mudança.
3. Importe o workflow `n8n/noturno-farma-leitura-real-hml.json`. Associe
   a credencial existente Hub HML FARMA aos dois nós HTTP. Deixe inativo
   (manual, sem Schedule Trigger). Rode sem aguardar o ZIP.
4. Registre ID n8n, ID Hub, três fontes, período, Meta 07 e 09/11, erros e
   pendências. Se não houver credencial FarmaLíder, confirme a pendência
   dessa fonte, sem bloquear Meta e Weni. As omissões da Meta são
   recuperadas pelo cliente compartilhado sem inventar impressões/CTR/CPM.
5. Quando os estados reais e reservas estiverem disponíveis, habilite o
   complemento de planejamento e importe
   `n8n/noturno-farma-planejamento-real-hml.json`. Também manual e inativo.
   Execute, compare os totais e propostas com a referência equivalente,
   e confira a primeira etapa pendente no detalhe da Central. Ausência
   de estado/checkpoint/reserva impede comprovar o plano, não fabrica um.
6. Reenvie a mesma chave (preserva ID, nenhuma reaplicação); nova chave
   produz novo diagnóstico. Confira zero escritas comerciais, zero
   publicações, nenhum READY criado, agendamentos desligados, PET e READY
   oficial intactos. Registre SHA efetivamente implantado e os IDs.
7. Só depois da conciliação preparar publicador de teste HML em entrega
   separada. Não habilitar Produção nesta etapa.

## Validação

As fixtures da suíte são exclusivamente sintéticas, sem rede comercial.
Os ensaios verificam recuperação Meta, limites, regras compartilhadas de
Update Weni e Recompra, normalização financeira, segregação FARMA/PET,
idempotência, fencing/renovação e o contrato visual. A confirmação de
acesso externo, credenciais e volumes privados só pode ocorrer na VPS.

### Monitoramento horário das fontes

`n8n/saude-fontes-farma-hml.json` é importável e vem desativado. Tem disparo manual e agendamento de uma hora. Usa a mesma credencial Hub HML FARMA e o cenário amostral de leitura; a chave é estável dentro da hora UTC. Confirme no modo manual que dois disparos na mesma hora retornam a mesma tarefa, com cobertura na Central e sem publicação. A escolha de ativar o timer de leitura em homologação é independente do agendamento comercial.
