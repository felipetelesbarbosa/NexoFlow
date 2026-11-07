# Origens Google Sheets: correção após a 1.5.22

## Ocorrência e evidência — 07/11/2026

Base analisada: tag `v1.5.22` / `cfb382e`, comparada à main `6b56573`.
O commit do Work adicionou somente documentação; a validação permaneceu igual.
A mensagem «A origem do arquivo diverge do segmento ou papel configurado» vinha
exatamente de `app/sheets_continuation.py::verify_book_stamp`, chamada pelo
pré-voo de `StorageSetup.configure`. Não era diagnóstico de CPF/pedido nem quota.

Foram executados GETs de metadados, mapa e índice nos três destinos FARMA
informados pelo usuário. Não foram lidas linhas comerciais, alterados metadados,
executados publicadores nem consultas à FarmaLíder/Weni. Credenciais locais
existentes foram utilizadas com escopos de leitura; não foram copiadas/expostas.
O relatório sanitizado completo permanece privado, fora do Git.

| Arquivo esperado | Classe no mapa/índice | Marcadores | Evidência observada |
|---|---|---:|---|
| Dashboard | principal | 1 | hub correto, segment FARMA, role dashboard, DOCUMENT, spreadsheet=true; Google devolve também locationType=SPREADSHEET |
| Operação | principal | 0 | origem ausente, não conflitante |
| Histórico | principal | 0 | origem ausente, não conflitante |

O índice foi validado, sem arquivos de continuação registrados e com zero fontes
Data Studio autorizadas. A conta de serviço conseguiu ler os três arquivos e
apresentou capacidade de edição. Não retornou as pastas nessa identidade; isso
não foi interpretado como inexistência de pasta. Pelo Drive conectado ao usuário,
os três arquivos estão na mesma pasta **NexoFlow/FarmaLíder**, com permissões do
tipo user (owner/writer); a pasta FARMA apresenta owner. Essa consulta não
comprova qual usuário será autorizado no OAuth do Windows: o provisionador
continua exigindo a conferência local dessa identidade e da pasta.

**Causa comprovada:** o código comparava `location` por igualdade com
`{"spreadsheet": true}`. A API devolveu
`{"locationType": "SPREADSHEET", "spreadsheet": true}`. O campo de saída
`locationType` é legítimo. O marcador existente não precisa ser apagado, editado
ou recriado. Não há evidência de marcador duplicado, PET ou papel trocado nesses
três arquivos no corte examinado.

A 1.5.22 valida todos os marcadores antes de criar índice/marcar origens. Nesta
ocorrência a rejeição acontece no Dashboard, o primeiro arquivo. Portanto esse
caminho não chega a marcar Operação/Histórico. A versão anterior podia adquirir e
liberar o lease remoto antes da rejeição e a autorização no navegador podia
atualizar a credencial OAuth local. A existência atual do índice/marcador não
permite datar sua criação sem um snapshot anterior; não atribuí-la artificialmente
à tentativa que falhou.

## Correção e guardas

- Aceitar `locationType=SPREADSHEET` opcional no GET, mantendo `spreadsheet=true`
  e recusando sheetId/dimensionRange/localizações conflitantes.
- Comparar os campos JSON tipados, não ordem/espaçamento da serialização. JSON
  inválido, chaves repetidas, campos extras, duplicidade de marcadores, hub/papel/
  segmento divergentes e visibility diferente de DOCUMENT continuam bloqueantes.
- Erro acionável com ID do arquivo, papel e nomes dos campos divergentes; valores
  remotos livres são omitidos ou identificados por hash, nunca ecoados como log.
- Pré-voo dos três marcadores e permissões antes de qualquer escrita, inclusive
  aquisição do lease. Repetir os marcadores sob lease antes das origens.
- Um principal com propriedade Drive de intenção de continuação ou outro contexto
  é recusado, sem remover essas propriedades. Continuação legítima mantém seu
  marcador e o mesmo contrato de leitura/manifesto.
- Nenhum reparo destrutivo de metadados é necessário neste caso. O `configurar`
  corrigido preserva o Dashboard e cria somente as duas origens ausentes após
  comprovação dos destinos. Prévia: Dashboard 1→1 preservado; Operação 0→1 FARMA/
  operacao; Histórico 0→1 FARMA/historico; hub esperado é o Dashboard do mapa.
  Cada criação é relida; nova execução não duplica marcadores.

Não há transação atômica entre arquivos Google. Falha de rede **durante** criação
pode deixar configuração parcial confirmada: preservar lease incerto, esperar a
expiração e reler na retomada. Não prometer ausência de estado parcial após POST
incerto. Conflitos/permissões já detectáveis no pré-voo bloqueiam sem escrever.

## Diagnóstico novo

No código corrigido:

```text
nexo armazenamento diagnosticar-origens
```

Só GETs, escopos `spreadsheets.readonly` e `drive.metadata.readonly`, sem novo
OAuth, lease remoto ou fatos. Relata mapa/índice, tipo principal/continuação,
papel, ID, quantidade de marcadores, campos permitidos, divergências e leitura de
permissões. Continua nos outros destinos após falha individual. Leitura negada,
falha de transporte e configuração incompatível são distintas; nenhum erro vira
«marcador ausente». Retorno 0 = origens compatíveis, 3 = impedimento; isso não
libera carga comercial nem confirma fontes Data Studio. Falha no mapa impede
inferir destinos e é explicitada. `origens_compativeis` não comprova OAuth/pasta
no Windows; `pasta_e_permissoes_oauth` registra essa limitação.

Devolver somente esse JSON sanitizado e eventual mensagem de erro do auxiliar.
Não enviar credenciais, dumps, journals, SQLite ou respostas HTTP brutas.

## Disponibilização sem release e sem sobrescrever C:\NexoFlow

A tag, a versão e os pacotes **1.5.22 continuam intactos**. Não se distribui um
novo Setup com o número já publicado. O comando novo não existe no executável
original 1.5.22. O código corrigido fica na main, com commit `[skip release]`.

Para diagnóstico/retomada da configuração antes de uma futura distribuição,
utilizar `scripts/armazenamento_1_5_22.py` do **checkout oficial no SHA validado**,
extraído fora da instalação, por exemplo `C:\NexoFlow-Correcao`. A pasta deve
conter diretamente `app` e `scripts`. Pode baixar o ZIP de código no GitHub pelo
SHA informado na entrega; não extrair sobre `C:\NexoFlow`.

Esse auxiliar verifica VERSION e os hashes normalizados dos três módulos
originais 1.5.22. Usa o Python, configuração, credenciais, seleção de rede e
travas locais da instalação; carrega somente os três módulos corrigidos em
memória nesta execução. Não instala dependências, não copia credenciais, não
substitui executáveis/arquivos, não ativa fontes nem publica pedidos. Recusa
outras versões ou módulos locais divergentes. Esse é um auxiliar pontual,
não uma atualização da instalação nem requisito permanente de operação.

No NexoFlow Terminal, perfil FARMA e rede já escolhidos:

```powershell
& C:\NexoFlow\.venv\Scripts\python.exe C:\NexoFlow-Correcao\scripts\armazenamento_1_5_22.py --instalacao C:\NexoFlow diagnosticar-origens
```

Se os resultados corresponderem à prévia acima (sem conflito, arquivos/papéis
corretos), fechar outras cargas e executar somente a configuração dos metadados:

```powershell
& C:\NexoFlow\.venv\Scripts\python.exe C:\NexoFlow-Correcao\scripts\armazenamento_1_5_22.py --instalacao C:\NexoFlow configurar
& C:\NexoFlow\.venv\Scripts\python.exe C:\NexoFlow-Correcao\scripts\armazenamento_1_5_22.py --instalacao C:\NexoFlow diagnosticar-origens
& C:\NexoFlow\.venv\Scripts\python.exe C:\NexoFlow-Correcao\scripts\armazenamento_1_5_22.py --instalacao C:\NexoFlow configurar
nexo armazenamento status
```

O segundo diagnóstico deve aprovar as três origens. A segunda configuração
reconfirma permissões e não duplica origens/índice; pode pedir OAuth novamente.
Conflito, permissão ou resposta incerta: parar e conservar o diagnóstico, sem
apagar marcadores ou travas. Não há comando de sobrescrita de marcador.

`fontes_data_studio: []` permanece uma pendência separada. O Work deve comprovar
as conexões reais e permissões das cinco fontes antes de autorizar sua ativação;
esta entrega não executou nem presume essa conferência. Não usar
`--confirmar-fontes` como correção de origem.

Somente quando origens, OAuth/pasta, fontes, backup consistente com WAL e snapshot
FARMA estiverem comprovados, o preparo sem escrita comercial é:

```text
nexo historico --planilhas capacidade --banco C:\NexoFlow\logs\privado\farma-copia.sqlite --revisao C:\NexoFlow\logs\privado\farma-plano-origens.json --resumo-mensal C:\NexoFlow\logs\privado\farma-esperado-origens.json
```

Usar caminhos novos para não sobrescrever revisões/journals existentes. A capacidade
não exige recolher a base. Se fontes/conexões não estiverem comprovadas, manter
esse passo pendente. **Nenhuma aplicação comercial está autorizada nesta tarefa.**
O auxiliar não corrige o processo de publicação iniciado separadamente pelo
executável antigo: a validação compartilhada também é usada ao marcar novas
continuações. Uma futura aplicação deve usar o publicador integralmente corrigido,
validado e distribuído; revisões vinculadas a código antigo precisam ser
repreparadas/reconciliadas, nunca forçadas. PET continua intacto.

## Validação e limites

A regressão com resposta oficial Google falhou antes da correção. Uma segunda
regressão mostrou a escrita do lease antes de detectar conflito no terceiro
arquivo. Ambas passam com a correção. Fixtures agora reproduzem locationType no
GET. Cobertura inclui JSON equivalente, hub/papel/segmento incompatíveis, marcador
duplicado/localização inválida, continuação preservada, recusa de intenção de
continuação como principal, leitura 403/timeout sanitizada, diagnóstico sem POST,
CLI real, configuração idempotente e publicador/capacidade/rollback sintéticos.

O auxiliar foi executado localmente com os módulos extraídos do pacote público
1.5.22, configuração/Sheets sintéticos e rede externa bloqueada: hashes instalados
preservados, credenciais resolvidas no caminho instalado, nenhuma escrita. Isso
não equivale à execução no Windows do usuário. Testes Windows/CI e SHA exato são
informados na entrega. Leituras comerciais comprovam o marcador encontrado,
não autorização OAuth no PC nem sucesso da configuração após instalar/executar
o código corrigido. Nenhuma publicação comercial, alteração de fontes, release
ou implantação do Hub foi executada.

Validação local: suíte completa com 1.874 testes (73 dependentes de ambiente
ignorados no Linux), seguida da regressão adicional para intenção vazia de
continuação; 30 testes Node, Ruff, Pyright (zero erros), consistência e HTML
aprovados. A contagem final do CI inclui essa regressão adicional.
