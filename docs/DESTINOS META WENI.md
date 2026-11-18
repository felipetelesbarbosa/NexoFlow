# Destinos Meta e Weni no PostgreSQL FARMA

## Corte e definições

Em 18/11/2026 o conector Weni confirmou o projeto CX Delivery FarmaLíder, a organização Flows vinculada e dois números no mesmo WABA. O token do perfil leu org.json e channels.json (cinco canais). A resposta inclui uuid, address e created_on. Nenhum endereço coincidiu com os dois números E.164. A credencial ads_read retornou 403 ao consultar os telefones empresariais do WABA. O cadastro atual e a data de criação de um canal não determinam o receptor em um dia passado. O conjunto de anúncios consultado pela Graph retornou MESSAGING_INSTAGRAM_DIRECT_WHATSAPP nos três casos. Falta o histórico dos receptores e da exclusividade do Instagram.

O controle de 01 a 18/11 do Work tem 5, 13 e 24 eventos por anúncio, 42 no total e 70 conversas iniciadas da Meta. A nova leitura direta de eventos por instante em Belém encontrou 4, 13 e 25 nos mesmos anúncios. Um UUID apareceu nos eventos e na pesquisa de canais por UUID. A origem da diferença por anúncio permanece em conferência. Preserve a READY que forneceu o controle. Compare a data no fuso da conta, o horário de corte do dia aberto, a correspondência com fatos diários e a cobertura das duas consultas. Mantenha as diferenças por anúncio no recibo. A soma geral isolada não aprova a aplicação.

| Campo ou fonte | Uso |
|---|---|
| Projeto CX / organização Flows | Dois UUIDs independentes. Obter o vínculo por get_user_projects. O nome e o UUID do org.json e o fuso devem coincidir. |
| WABA / telefone empresarial / phone_id | WABA identifica a conta WhatsApp. O endereço E.164 e o ID Graph do telefone identificam recursos distintos. A lista privada de dois números é a extração revisada de list_project_wabas. |
| canal / clique / evento / conversa | O canal identifica o receptor na API Flows. O coletor reaproveita a identidade CTWA nativa. Clique, número do contato e criativo ficam fora da prova de destino. Contar conversas Weni exige identidade de conversa em todos os eventos e dias completos. |
| WA_1 / WA_2 | Rótulos fixados no arquivo privado. Contadores somáveis no grão anúncio/dia. Vínculo oficial com início inclusivo e fim exclusivo deve cobrir o instante do evento. |
| Eventos pendentes | Inclui canal ausente, vigência desconhecida e conflito. A soma dos dois receptores e das pendências deve fechar com eventos_ctwa. Sem auditoria nova, todos os eventos já observados ficam em SEM_AUDITORIA. |
| Configuração / recepção | O catálogo Meta é observado no instante da coleta. Um extrato oficial cobrindo todos os destinos e o dia inteiro permite classificar até um anúncio sem conversas. Ausência, perfis não exclusivos e sobreposição conflitante mantêm o custo original e deixam o custo comprovado nulo. Evidência PET no mesmo anúncio prevalece sobre exclusividade FARMA. |
| Dinheiro / pedidos | O fato diário tem conta, anúncio, data, moeda, fuso e política. Um anúncio com investimento ou impressões positivos em qualquer dia entra com todos os dias selecionados. A tabela de receptores só carrega contagens de eventos. CPA = custo comprovado / pedidos. ROAS = receita BRL / custo comprovado BRL. Denominador zero ou componente desconhecido produz nulo. |
| Fuso e cobertura | Datas inclusivas no fuso IANA da conta. Eventos são instantes convertidos para esse fuso. A operação Weni usa America/Belem. Contagens de conversas Meta ficam no dia da Meta. O dia ainda aberto aparece como parcial. A API exige READY e devolve erro se a leitura falhar. |
| Publicação / agentes | A rotina nativa roda no Analytics e na etapa Analytics do Noturno. O publicador privado existente confirma o hash/recibo por lote e recupera a resposta perdida. Dados e cursor tornam-se visíveis juntos na READY. O documento de auditoria fica no fato privado. O agente futuro deverá receber acesso apenas à função agregada e ao catálogo abaixo, por um canal dedicado. |

O catálogo aditivo deste contrato chama-se farma.ds_catalogo_destinos_meta. A função versionada chama-se farma.ds_veiculacao_meta_v1(date,date,boolean). As duas convivem com o catálogo e a função experimentais do Work, que têm nomes diferentes. O código de implantação confere o banco, o perfil, a revisão e a ausência de WRITING sob a trava do publicador.

## Work na VPS de homologação

Execute em Bash, a partir do checkout do SHA entregue. Use os caminhos privados, a rede e o projeto Compose **de homologação** já conferidos. DSN_ADMIN é o caminho de arquivo do administrador, legível pelo UID do contêiner. O PostgreSQL continua sem porta publicada. Guarde a imagem e o Compose anteriores do leitor.

```bash
set -euo pipefail
: "${SHA:?SHA completo da entrega}" "${DSN_ADMIN:?arquivo privado de homologação}" "${REDE_PG:?rede privada do teste}"
test "$(git rev-parse HEAD)" = "$SHA"
img="nexoflow-datastudio:destinos-$SHA"
docker build --build-arg NEXOFLOW_SOURCE_SHA="$SHA" -t "$img" -f integrations/datastudio/Dockerfile .
test "$(docker image inspect -f '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$img")" = "$SHA"
ready=0f53a255-3129-4afb-858f-f48f960c1098
docker run --rm --network "$REDE_PG" -v "$DSN_ADMIN:/run/secrets/admin:ro" "$img" \
  python -m integrations.datastudio.admin --dsn-file /run/secrets/admin --ambiente homologacao \
  --segmento FARMA --instalar-destinos-farma "$ready"
```

Se a revisão tiver mudado, confira o novo corte antes de qualquer instalação. A operação pode ser repetida no mesmo corte. No diretório do Compose do leitor de homologação, exporte COMPOSE_FILE e COMPOSE_PROJECT_NAME para o conjunto real já conferido. Aplique o overlay ao leitor existente. Confira que o modelo renderizado preserva rede e credenciais privadas de homologação.

```bash
: "${COMPOSE_FILE:?arquivos de homologação separados por dois-pontos}" "${COMPOSE_PROJECT_NAME:?projeto de homologação}"
: "${CHECKOUT:?caminho absoluto do checkout validado}"
anterior="$(docker compose ps -q datastudio-farma-read)"
test -n "$anterior"
export IMAGEM_ANTERIOR="$(docker inspect -f '{{.Image}}' "$anterior")"
export NEXOFLOW_FARMA_READER_IMAGE="$img"
export COMPOSE_FILE="$COMPOSE_FILE:$CHECKOUT/integrations/datastudio/compose.farma-reader-tuning.yaml"
docker compose config --quiet
docker compose up -d --no-deps --pull never datastudio-farma-read
docker compose ps datastudio-farma-read
```

O publicador existente aceita o contrato de lotes original. Mantenha a credencial de leitura do Apps Script separada da de publicação Windows. Para conferir SQL em sessão somente leitura usando o papel FARMA, selecione o ambiente de teste e execute:

```sql
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SELECT current_database(), current_user;
SELECT * FROM farma.ds_veiculacao_meta_v1('2026-11-01','2026-11-18',false);
SELECT * FROM farma.ds_veiculacao_meta_v1('2026-11-01','2026-11-18',true);
SELECT anuncio_id,destino,situacao,sum(eventos_ctwa)
FROM farma.ds_destinos_ctwa_diarios WHERE data BETWEEN '2026-11-01' AND '2026-11-18'
GROUP BY 1,2,3 ORDER BY 1,2,3;
SELECT * FROM farma.ds_catalogo_destinos_meta ORDER BY campo;
COMMIT;
```

O detalhe diário inclui anúncios FARMA sem entrega. Para comparar com o painel, restrinja os IDs e as contas aos devolvidos pela função no mesmo intervalo. Registre a versão READY juntamente com o resultado. Um período válido vazio devolve zero linhas. Um erro da função ou da API bloqueia a comparação.

Para a futura interface de consulta, o administrador pode criar um papel **dedicado de homologação** na sessão do banco correto. A criação abaixo falha se já existir um papel com o nome. Confira os privilégios antes de qualquer reaproveitamento. Nenhum login, token ou serviço de agente é necessário nesta etapa.

```sql
BEGIN;
CREATE ROLE nf_ds_hml_farma_anuncios_agregados NOLOGIN;
GRANT CONNECT ON DATABASE nexoflow_datastudio_homologacao TO nf_ds_hml_farma_anuncios_agregados;
GRANT USAGE ON SCHEMA farma TO nf_ds_hml_farma_anuncios_agregados;
GRANT SELECT ON farma.ds_catalogo_destinos_meta TO nf_ds_hml_farma_anuncios_agregados;
GRANT EXECUTE ON FUNCTION farma.ds_veiculacao_meta_v1(date,date,boolean) TO nf_ds_hml_farma_anuncios_agregados;
COMMIT;
```

## Terminal FARMA

Instale o Setup 1.5.45 em Preserve na instalação de homologação. Confira o backend PostgreSQL FARMA, as credenciais do destino de **homologação**, a READY e ambas as credenciais Weni. Em secrets_config.py do perfil FARMA, configure META_ADS_ENABLED=True e META_ADS_DESTINOS_FILE com o caminho privado credentials/datastudio/FARMA/destinos.json. WENI_INSIGHTS_PROJECT_UUID deve conter o UUID CX do projeto conferido. Mantenha em branco o novo caminho nos outros ambientes. O JSON de destinos contém metadados de autoridade e nenhuma credencial. Exemplo estrutural com identificadores fictícios:

```json
{"segment":"FARMA","source":"WENI_CX_PROJECT_WABAS","observed":"2026-11-18T12:00:00-03:00","cx_project":"00000000-0000-4000-8000-000000000001","flows_org":"00000000-0000-4000-8000-000000000002","waba":"001","phones":{"+550000000001":"WA_1","+550000000002":"WA_2"},"bindings":[],"controle":{"inicio":"2026-11-01","fim":"2026-11-18","conta_id":"001","moeda":"BRL","eventos_por_anuncio":{"001":2},"conversas_meta":3}}
```

Use bindings vazio para a evidência atual. Um futuro extrato revisado de canal usa kind=channel, source=WENI_META_CHANNEL_HISTORY, channel, waba, phone, phone_id, ref, observed, from e until. Um extrato do destino completo usa kind=ad, source=META_AD_DESTINATION_HISTORY, account, ad, adset, receivers, ref e os mesmos três instantes com fuso. Receivers aceita os números autorizados, OUTRO ou DESCONHECIDO. DIRECT_FARMA exige exclusive_ig_id e documento que comprove a exclusividade e todos os receptores no período. Feed, mensagem, telefone do cliente e texto da peça não são fontes para esses campos. Não invente as datas. A coleta atual registra o destino do conjunto separadamente.

No Terminal do NexoFlow FARMA, rode a simulação. A pasta privada deve ser nova.

```powershell
Set-Location C:\NexoFlow
if ("$(nexo versao)".Trim() -ne 'NexoFlow 1.5.45') { throw 'Confira o Setup instalado.' }
$py = '.\.venv\Scripts\python.exe'
$p = Join-Path 'logs\privado' ('destinos-farma-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $p -ErrorAction Stop | Out-Null
$janela = @('--perfil','FARMA','--start','2026-11-01','--end','2026-11-18','--review',"$p\revisao.json")
& $py -B app/run_meta_ads.py @janela --dry-run
if ($LASTEXITCODE -ne 0 -or !(Test-Path "$p\revisao.json")) { throw 'Controle pendente. Preserve a saída agregada e a READY.' }
```

Compare controle_referencia por anúncio com a origem da mesma revisão e o mesmo corte. Uma divergência mantém a etapa em simulação. Só após essa conferência, no Terminal de homologação e na mesma sessão:

```powershell
& $py -B app/run_meta_ads.py @janela --apply --confirm-schema
if ($LASTEXITCODE -ne 0) { throw 'Verifique o estado da revisão e seus recibos antes de retomar.' }
```

Confirme pela API e pela cópia a nova versão READY. Reenvio verifica o recibo da mesma solicitação após resposta perdida. Uma revisão ainda WRITING exige consultar seu estado antes de iniciar outra. O controle histórico no arquivo é conferido também pela rotina automática em períodos sobrepostos.

## Looker e reversão

No projeto Apps Script de teste, implante Code.js, Schemas.js, AbcCore.js e appsscript.json de connectors/datastudio_api. Selecione FARMA e homologacao. Para a tabela use Anuncios_Veiculados_FARMA. Para os cartões use Resumo_Anuncios_Veiculados_FARMA com a mesma janela, conta, moeda, fuso e política. Mantenha um único grupo dessas dimensões nos cartões de razão. Destinos_CTWA_Diarios e Catalogo_Destinos_Meta são fontes separadas de inspeção. Confira os cinco períodos do ensaio, o dia sem entrega com conversão posterior, período vazio e falha de acesso. Registre os totais por ID para 01 a 18/11, distinguindo o corte READY de um novo pull. Solicite apenas as colunas autorizadas. Uma única imagem da peça não identifica anúncio nem receptor.

Para reverter o leitor na sessão Bash acima, execute:

```bash
: "${IMAGEM_ANTERIOR:?imagem registrada antes da troca}"
export NEXOFLOW_FARMA_READER_IMAGE="$IMAGEM_ANTERIOR"
docker compose config --quiet
docker compose up -d --no-deps --pull never datastudio-farma-read
docker compose ps datastudio-farma-read
```

Restaure a implantação Apps Script e os vínculos anteriores na cópia. Pause o ensaio Meta no perfil de homologação e restaure a configuração privada preservada pelo operador. A reversão do leitor conserva as revisões e os recibos. O relatório oficial, PET, a aba legada e o banco comercial não participam deste procedimento.
