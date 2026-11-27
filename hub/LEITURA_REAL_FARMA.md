# Noturno FARMA HML: aceite amostral das fontes reais

Esta entrega é um **diagnóstico inicial**, não a migração operacional do
Noturno. Mantém os fluxos sintéticos anteriores e a publicação oficial Windows.
O cenário explícito `leitura_real_amostral` entra na fila do Noturno existente e
é executado pelo mesmo worker. Nenhuma etapa comercial, reserva, planejamento
de compra ou publicação é confirmada por uma amostra. O resultado terminal é
`revisao_necessaria` com a primeira etapa pendente e as evidências agregadas
por fonte em `GET /tarefas/{id}/resultado`. Não há recibo READY artificial.

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

## Execução manual

1. Base `main`, sem release Windows, preserve imagens/Compose atuais. Valide
   a configuração e o build de API/worker; implante somente esses serviços em
   homologação após verificar o SHA e backup. Nenhuma migração adicional é
   necessária para **este diagnóstico**.
2. Importe `n8n/noturno-farma-leitura-real-hml.json`, vincule a credencial
   existente Hub HML FARMA aos dois nós HTTP. Não grave tokens de fontes
   comerciais nos nós. Deixe o fluxo inativo, sem Schedule Trigger.
3. Execute manualmente. O fluxo usa a API/worker padrão, com chave de
   idempotência derivada da execução n8n e consulta apenas o resultado
   sanitizado. A Central mostra o mesmo ID FARMA em Revisão necessária.
   Os detalhes por fonte são retornados pelo endpoint de resultado. A tela
   atual ainda não tem uma seção específica de evidências por fonte.
4. Meta: use a conta e anúncio de referência de 07 e 09/11/2026. A resposta
   por conta é real; se omitida, use a mesma recuperação direta da 1.5.64.
   A referência Windows é somente hipótese para localizar lacunas, jamais
   preenchimento de fatos. Métricas não retornadas permanecem indisponíveis.
5. Confirme resultado por fonte e ausência de publicação; teste nova chave,
   e reenvio com a mesma chave. Verifique agendamentos, serviços, READY
   oficial e PET intactos. Registre ID n8n/Hub e SHA implantado.

## Continuação obrigatória antes da paridade operacional

A amostra não demonstra cobertura do período de Analytics, nem produção
dos planos reais. Implementar adaptadores não comerciais com regras
compartilhadas de Update Weni, histórico, Analytics/atribuição e Recompra
(realidade de reservas, checkpoints e consentimentos). Definir corte e
limites, reconciliar com referência Windows, apresentar cobertura por fonte
na Central com projeção sanitizada e somente depois preparar publicação de
teste no PostgreSQL HML. Nunca conectar destino comercial de escrita.
