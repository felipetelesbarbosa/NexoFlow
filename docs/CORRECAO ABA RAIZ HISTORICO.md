# Cabeçalho vazio nos arquivos principais do histórico

## Incidente e causa

A release 1.5.26 corrigiu a validação da primeira aba de uma continuação e o
congelamento inválido da grade de uma linha. A tentativa posterior encontrou
`ABA_CRIADA_COM_CONTEUDO_DIVERGENTE` ao inicializar uma tabela em um arquivo
principal. Esse caminho chama `Worksheet.get()` e ainda aceitava somente `[]`
ou `[cabecalho]`. O gspread 6.2.1 retorna `[[]]` quando a Values API não informa
valores. A fixture anterior exercitava o método real `get_all_values()`, mas seu
`get()` era uma implementação simplificada que retornava `[]`.

A regressão de configuração, preparo e piloto falhou com o código 1.5.26 quando
passou a usar também o `Worksheet.get()` real, com apenas HTTP simulado. Isso
reproduz o erro observado, sem acesso ao SQLite ou às planilhas comerciais.

## Correção

A inicialização das tabelas-raiz usa a mesma validação estrita de matriz vazia:
`[]`, `[[]]` e strings vazias. Zero, falso, espaços, fórmulas e conteúdo diferente
do cabeçalho não são aceitos como vazio. A leitura é `FORMULA`. A grade precisa
ser a reserva de uma linha e a largura do schema. Notas, validações e estruturas
inesperadas bloqueiam antes de qualquer escrita de cabeçalho. O cabeçalho completo
é relido antes do registro no manifesto. Perda de resposta reaproveita a mesma
aba, sem criar outra ou substituir fatos.

A guarda de estrutura pode conferir uma aba específica da raiz, preservando as
outras abas e reconferindo o inventário completo. Continuações continuam exigindo
uma única aba. Não há redimensionamento implícito de dados existentes.

## Recuperação de revisão reconciliada na 1.5.26

O publicador cria as partes antes de iniciar os lotes. Portanto esse erro pode
ocorrer após registrar continuações e cabeçalhos, embora todos os lotes ainda
estejam `pending`. Isso precisa ser comprovado pelo journal e pelos destinos;
a mensagem de erro isoladamente não substitui essa conferência.

O comando `--planilhas reconciliar` aceita atualizar um recibo anterior somente
quando ele corresponde exatamente ao publicador oficial 1.5.26, commit
`a62a707aeb9b50c8bef28229aae3b77830050d4c`, em LF ou CRLF, para uma revisão
oficial 1.5.25 já reconhecida pelo protocolo. Ele exige novamente:

- fonte, revisão, projeção financeira, hashes e baseline íntegros;
- todos os lotes pendentes, sem backups de lote, finalização ou manifesto incerto;
- mesmo segmento, destinos, manifesto e estado WRITING da mesma revisão;
- partes originais preservadas e novas partes correspondentes à capacidade e às
  coordenadas registradas no journal e no manifesto;
- novas grades com uma linha e largura exata, contendo apenas cabeçalho ou vazio;
- origens, pastas, permissões privadas e acesso de serviço comprovados;
- ausência de fórmulas, fatos, notas, estruturas inesperadas e abas não planejadas.

A reconciliação não cria partes, não envia fatos, não reescreve a revisão e não
altera a fonte. O recibo anterior permanece dentro da nova evidência privada.
Qualquer alteração posterior do código invalida a compatibilidade. Estados com
lotes já enviados, respostas de escrita incertas, recibos desconhecidos ou fatos
inesperados exigem outro diagnóstico; não editar assinaturas ou journals.

## Operação Windows

Depois que o pacote corretivo for validado e publicado, encerrar as rotinas e
atualizar por **Preserve**. Não copiar módulos avulsos. Manter a revisão antiga,
a fonte derivada, exclusões, journals e evidências completas.

No Terminal, selecionar FARMA, conferir `nexo versao` e usar o caminho do mesmo
plano privado (o nome do arquivo pode continuar contendo 1.5.25):

```powershell
$planoFarma = "C:\NexoFlow\logs\privado\revisao-farma-existente.json"
nexo historico --planilhas reconciliar --revisao $planoFarma
```

Somente após `[OK]`, executar separadamente:

```powershell
nexo historico --planilhas aplicar --revisao $planoFarma --max-lotes 1
nexo historico --planilhas conferir --revisao $planoFarma --resumo-mensal "C:\NexoFlow\logs\privado\conferencia-piloto-corrigido.json"
```

Pausa do piloto com lotes restantes retorna código 3. Não é autorização para
ignorar uma divergência. Conferir o subconjunto antes de retomar a mesma revisão
sem `--max-lotes`. O fechamento integral e o total de LTV só são comprovados ao
final, com releitura e diferenças financeiras nulas. Não replanejar sobre uma
publicação WRITING nem recolher novamente pedidos para resolver este erro.

## Evidências e limites

Os testes sintéticos cobrem o gspread real, perda da resposta de cabeçalho,
reconciliação anterior, partes já criadas sem fatos, piloto, retomada e fechamento;
cobrem também bloqueios por fórmulas, dados, notas, abas extras, lote `sending` e
recibo adulterado/desconhecido. As mesmas decisões são executadas pela CLI usada
no Windows. CI Windows, pacote instalado e hashes precisam ser conferidos no SHA
distribuído. Aprovação desses testes não comprova publicação comercial, conciliação
da base FARMA ou aprovação do antivírus no PC do operador. Nenhum fato real foi
alterado nesta correção; a homologação operacional cabe ao operador/Work.
