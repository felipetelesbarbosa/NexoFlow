# Criação e retomada de continuações vazias

Correção distribuída na release NexoFlow 1.5.26, publicada em 08/11/2026. A versão
1.5.25 já foi publicada e seus pacotes, tag e release devem ser preservados.

## Causa e comportamento

O `gspread` 6.2.1 transforma respostas de Values API sem `values`, ou com
`values=[]`, em `[[]]` no método `Worksheet.get_all_values()`. Essa lista é
verdadeira em uma condição Python. A guarda anterior usava `not values` para a
aba inicial e aceitava apenas `[]` ou o cabeçalho exato para uma aba já renomeada.
Assim, podia interromper a criação de um arquivo efetivamente vazio antes do
primeiro lote, preservando a intenção durável e o estado WRITING.

A correção aceita somente matrizes vazias ou compostas exclusivamente por
strings vazias, incluindo `[]`, `[[]]` e `[[""]]`. Zero, falso, `None`, espaços,
outros tipos e conteúdo preenchido não representam ausência de dados. A leitura
usa `FORMULA`, para que uma fórmula que calcula `""` permaneça visível e bloqueie
o redimensionamento. Uma única aba com o título esperado e somente o cabeçalho
exato continua sendo uma retomada válida.

Arquivos com mais de uma aba são bloqueados, inclusive quando uma delas tem o
título esperado. Antes de renomear ou reduzir a grade, a rotina também confere
a estrutura nativa de toda a área existente: notas, validações, formatação
explícita, texto enriquecido, chips, tabelas dinâmicas e estruturas vinculadas,
além de mesclagens, proteções, filtros, gráficos, formatação condicional, cores
alternadas, grupos de linhas/colunas, segmentações de dados e tabelas.
Qualquer uma dessas estruturas exige revisão, preservando a aba.

Depois da leitura de células limitada à grade conhecida, uma consulta de
metadados sem `ranges` e sem dados de grade reconfere todas as abas do arquivo,
identidade, título, dimensões e estruturas. Isso valida o estado observado antes
da alteração; a API não oferece aqui atomicidade contra edições humanas
posteriores. O lease continua serializando as cargas NexoFlow.

A criação continua vinculada à mesma intenção, ao arquivo comprovado e ao
schema aprovado. Uma perda de resposta após renomear ou gravar o cabeçalho pode
ser retomada sem criar outro arquivo ou outra parte. Não são alteradas as
guardas de propriedade, segmento, pasta, permissões, lease e persistência do
índice. A conferência adicional é de leitura, antes do redimensionamento.

Uma segunda falha foi comprovada por resposta HTTP 400 do próprio Google:
congelar uma linha em uma aba com grade de uma única linha é inválido, pois
congelaria todas as linhas visíveis. As chamadas anteriores de resize e cabeçalho
já haviam sido aplicadas. A criação agora mantém a reserva aprovada de uma linha
e não tenta congelá-la. O bootstrap das abas-raiz também omite o congelamento
quando há somente uma linha. Grades maiores preservam o comportamento usual.
Não há ampliação implícita da capacidade nem mudança de política financeira.

## Revisão em andamento sob 1.5.25

Uma revisão WRITING exige manter os comprovantes originais e retomar a mesma
revisão. Não replanejar por cima dela, converter seu formato ou editar assinaturas,
journals ou índices. A recuperação limitada ao cabeçalho sob 1.5.25 não resolve o
erro de congelamento: essa versão tenta congelar novamente a grade de uma linha.

O commit posterior à release 1.5.25 preservou a privacidade do resumo das
exclusões, mas alterou `history_exclusions.py`, um dos módulos cobertos por
`publisher_signature`. Portanto uma instalação baseada nessa main não tem a
mesma assinatura da revisão preparada pela release 1.5.25. A semântica financeira
preservada não autoriza ignorar essa guarda. Na 1.5.25 a assinatura não cobria
`sheets_partitions.py`, `sheets_provisioning.py` e `google_sheets.py`. Na 1.5.26
esses módulos e o validador de reconciliação também ficam vinculados à assinatura.

Após a aprovação e disponibilização do pacote 1.5.26, o caso estrito de uma
revisão 1.5.25 interrompida **antes do primeiro lote** dispõe do comando oficial
abaixo. Preserve a revisão, o diretório privado completo e a cópia SQLite; faça
a atualização por **Preserve** e execute no mesmo perfil e nos mesmos destinos:

```powershell
nexo historico --planilhas reconciliar --revisao logs\privado\historico_revisao.json
nexo historico --planilhas aplicar --revisao logs\privado\historico_revisao.json --max-lotes 1
nexo historico --planilhas conferir --revisao logs\privado\historico_revisao.json
```

O primeiro comando não envia fatos. Ele aceita apenas as assinaturas oficiais
1.5.25 conhecidas, em LF ou CRLF. Confere integridade da revisão/journal, fonte
SQLite, perfil, schema, evidências estáveis, recebimentos e exclusões; retransforma
a mesma fonte com o código instalado e exige igualdade exata de linhas, hashes de
entrada/projeção, baseline e lotes aprovados. Só o horário de geração
`conferido_em` é retirado da comparação da conferência recalculada.

Todos os lotes devem estar `pending`, sem backup de lote, finalização, manifesto
incerto ou partes novas já ativadas. Origens, pastas, permissões privadas, acesso
de serviço, inventário das raízes e baseline remoto são relidos. Cada intenção
deve corresponder à capacidade e apontar para um único arquivo da mesma operação,
com uma aba vazia ou somente seu cabeçalho exato. Fórmulas, notas, validações,
formatação explícita, dados, abas extras e estruturas inesperadas bloqueiam.
O lease é conferido antes e depois das leituras, assim como manifesto e destinos.

Somente após essas provas é inserido um recibo de compatibilidade, em transação
única no journal. A revisão JSON e `meta.review` permanecem integrais. A cópia
legível privada `compatibilidade_codigo_v1.json` pode ser reexportada repetindo o
comando se o processo parar após o commit. Recibo inválido ou código posterior
com outra assinatura é recusado. O recibo aprovado continua válido no piloto e na
retomada normal, sem exigir novamente que todos os lotes estejam pendentes nem
fixar o manifesto no estado anterior à aplicação.

O piloto e a conferência são etapas separadas. Depois de avaliá-los, retome com
`--planilhas aplicar` e a mesma revisão, sem `--max-lotes`, e faça a conferência
integral. Os controles usuais de capacidade, hashes, manifesto, backup, lote
incerto e fechamento financeiro continuam ativos. Casos fora desse protocolo
estreito são bloqueados e precisam de diagnóstico próprio, sem contornar guardas.

## Validação e limites

As regressões executam o método real `Worksheet.get_all_values()` do gspread
6.2.1 com apenas HTTP simulado. Cobrem as representações vazias, o título já
renomeado, conteúdo inesperado, fórmula que exibe vazio, abas extras e estruturas
invisíveis na Values API. O fluxo real de configuração, preparação, piloto,
retomada, releitura, rollback e idempotência do publicador é exercitado com
Sheets/Drive em memória e fatos exclusivamente sintéticos.

Testes Linux, lint, tipos e consistência não substituem CI Windows, construção e
inspeção dos pacotes, instalação Preserve ou homologação comercial. Nenhuma
planilha comercial, instalação Windows, assinatura ou journal operacional foi
modificado por esta implementação.

## Referências oficiais

- [gspread 6.2.1, Worksheet](https://docs.gspread.org/en/v6.2.1/api/models/worksheet.html): contrato de leitura da biblioteca usada.
- [ValueRenderOption](https://developers.google.com/workspace/sheets/api/reference/rest/v4/ValueRenderOption): `FORMULA` lê a fórmula sem calcular seu resultado.
- [CellData](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/cells#CellData): estruturas invisíveis na Values API.
- [batchUpdate](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/batchUpdate): atomicidade vale para os subrequests da mesma chamada; resize, cabeçalho e freeze em chamadas separadas podem deixar etapas anteriores aplicadas.
- [GridProperties](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/sheets#GridProperties): define os campos de grade e congelamento. A restrição de congelar todas as linhas foi comprovada pela resposta real do Google, não por uma desigualdade publicada nessa referência.
- [Erros da Sheets API](https://developers.google.com/workspace/sheets/api/troubleshoot-api-errors): argumento inválido em HTTP 400 exige corrigir a solicitação; repetir ou reautorizar não corrige o argumento.
- [Limites de arquivos do Google Drive](https://support.google.com/drive/answer/37603): limites publicados para arquivos, incluindo planilhas.

## Ajuste posterior das tabelas-raiz

A validação de cabeçalhos em arquivos principais exigiu outro ajuste após a
1.5.26. Para o erro `ABA_CRIADA_COM_CONTEUDO_DIVERGENTE` e a revisão já reconciliada
antes do primeiro lote, consulte [a correção específica](CORRECAO%20ABA%20RAIZ%20HISTORICO.md).
