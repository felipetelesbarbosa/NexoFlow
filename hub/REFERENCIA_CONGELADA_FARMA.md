# FARMA HML: replay privado de uma referência Windows 1.5.64

O cenário `referencia_congelada` usa exclusivamente o ZIP validado e lacrado
pelo operador, com READY v15. Não usa clientes comerciais, não atualiza
estados operacionais, não gera READY e não publica. O cenário
`referencia_congelada_retomada` força uma pausa **após** o commit do primeiro
lote Weni quando a habilitação de teste está presente. A mesma tarefa é
reclamada pelo worker após a espera. Não interrompe o serviço inteiro nem
PET. A perda do processo/lease também se recupera pelos checkpoints.

## Implantação privada

1. Confirmar o projeto Compose HML ativo, banco `nexoflow_hub_hml`, backup
   recuperável da Central/perfis/convites, imagens de reversão e RAM/espaço.
   Não usar a raiz de publicação oficial.
2. Transferir o ZIP original pelo canal privado autorizado da VPS, para
   diretório de segredos específico FARMA (fora do contexto de build).
   Proteger o diretório 0750, arquivo 0440, root e grupo GID 10001. Confirmar
   o SHA-256 esperado em ambos os lados. Nenhuma extração do ZIP na VPS.
3. Configurar privadamente o caminho `HUB_FROZEN_REPLAY_PRIVATE_FILE`,
   SHA-256 `HUB_FROZEN_REPLAY_SHA256` e UUID da READY
   `HUB_FROZEN_REPLAY_REVISION`. Acrescentar
   `compose.referencia-congelada-hml.yaml` ao worker de homologação,
   preservando complementos existentes. O estado offline é limitado a
   128 MiB; orçamento de RAM do ensaio 1536 MiB. JSONL lidos em streaming,
   lotes de até mil linhas. Limites HTTP reais não mudam.
4. Após CI no SHA exato, construir API/worker/Central API/Central Web com
   a mesma revisão. Aplicar migração 009 exclusivamente na base HML pelo
   mecanismo vigente. Substitui a projeção da fila, sem conceder leitura
   das tabelas de tarefas. Preservar volumes, perfis, convites e domínio.
5. Importar os dois JSON em `hub/n8n/noturno-farma-referencia-congelada*-hml.json`.
   Usar o endereço interno confirmado do Hub HML e vincular Hub HML FARMA
   aos dois nós HTTP. **Não publicar/ativar workflow**; ambos têm apenas
   gatilho manual. n8n recebe somente agregados.
6. Executar o ensaio de retomada, conferir Aguardando após lote 1 Weni,
   confirmar mesmo ID e início pelo lote 2, sem recontagem. Executar caso
   normal separadamente. Reenviar mesma chave conserva o ID. Desabilitar
   a habilitação de interrupção após o aceite.

## Aceite

- Verificar hash da captura, arquivos, revisões, reservas, estado e corte
  original. Comparar todas as decisões por contato, por conteúdo canônico;
  validar agregados contra os planos Windows lacrados.
- Os checkpoints contêm só contagens, protocolo, hash e posição do último
  lote. Fencing da fila protege o commit. A retomada percorre as linhas
  anteriores para chegar ao cursor, sem recalcular as decisões confirmadas.
- Descoberta de novos cadastros e deduplicação não devem ser declaradas
  equivalentes quando falta a base cadastral integral e seus insumos no
  mesmo corte. Recalcular os campos da proposta de criação com o cadastro
  selecionado e o pedido normalizado, mantendo a descoberta e a prova do
  hash do snapshot bruto pendentes. Validar a revisão sem usar o resultado
  esperado como insumo circular.
- Analytics compara os totais da READY com o histórico vigente e o
  operacional, registra divergências dos pedidos/itens em centavos e
  distingue `BI_Vendas` armazenada da visão `farma.ds_bi_vendas`.
  Não publicar a comparação. A atribuição comercial Meta permanece parcial
  se faltam evidências da Weni; nunca atribuir lacunas a PET.
- IDs e números comerciais, UUID e SHA da captura, evidências do aceite
  real são tratados em relatório privado, nunca em Git ou nós do n8n
  que contenham dados de clientes. Sem escritas comerciais/publicações.
  Preservar a produção, PET, READY oficial e agendamentos.

Rollback: guardar as imagens anteriores e backup recuperável. Não
reverter schema com tarefas existentes. Avaliar a reversão em banco
isolado, sem apagar dados. Não lançar versão Windows.
