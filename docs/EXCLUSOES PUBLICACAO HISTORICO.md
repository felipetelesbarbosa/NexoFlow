# Exclusões autorizadas numa cópia de publicação

Disponível na 1.5.25. Uma venda informada como erro operacional pode ser retirada
de uma cópia para publicação sem apagar o backup bruto ou alterar a resposta
oficial. Esta rotina não corrige a API nem configura uma exclusão global em Weni,
Analytics legado ou no banco operacional. Não deduzir exclusões por valores altos,
coincidência de campos ou ausência de resposta. Exigir autorização por ID.

## Criar a cópia

Fechar outras rotinas do segmento e obter um backup consistente pelo mecanismo
`history_snapshot.snapshot`, incluindo o WAL confirmado. Conferir caminho, tamanho
e SHA-256. Abrir o Terminal no segmento correto antes de carregar módulos.

Exemplo com IDs sintéticos, a substituir pelos IDs realmente autorizados:

```text
nexo historico --excluir-pedidos 111 222 --motivo-exclusao "Pedidos criados por engano, exclusão autorizada pelo operador" --responsavel-exclusao "Operador responsável" --banco CAMINHO_DO_BACKUP_BRUTO.sqlite --sha256-banco SHA256_DO_BACKUP
```

O comando exige motivo e responsável, valida hash, integridade, perfil e presença
dos IDs. Só aceita compras válidas sem pendência própria; bloqueia IDs duplicados,
outra projeção como fonte e backup com WAL externo não vazio. Não combina com
coleta, auditoria ou aplicação no mesmo comando. Não consulta APIs.

O resultado informa `banco_publicacao`, novo hash, tamanho, comprovante e resumo.
Os arquivos ficam em `logs/privado/exclusoes-publicacao` ou no diretório PET
equivalente. Não copiar apenas o SQLite operacional aberto para obter o backup.

A fonte continua idêntica. Somente a cópia tem os IDs removidos de `history_orders`.
Uma tabela privada conserva integralmente as linhas originais, motivo, responsável,
instante e hash da fonte. Um fingerprint verifica todas as demais tabelas e todos
os fatos não excluídos. Falha conserva a evidência; só utilizar a cópia cujo comando
terminou com sucesso. Não apagar cópia parcial para repetir sem diagnosticar.

Janelas, recibos e revisões permanecem como evidência da coleta bruta antes das
exclusões. Suas contagens não devem ser apresentadas como vendas após exclusões.
O novo resumo recalcula compradores distintos, pedidos válidos e valores.

## Preparar e publicar pelo mecanismo oficial

```text
nexo historico --planilhas capacidade --banco CAMINHO_RETORNADO_EM_BANCO_PUBLICACAO.sqlite --revisao CAMINHO_INEDITO_DA_REVISAO.json --resumo-mensal CAMINHO_INEDITO_DO_ESPERADO.json
```

Usar exatamente a cópia retornada, não o backup bruto ou o banco operacional.
A revisão contém a auditoria das exclusões e o hash da cópia. A preparação e o
fechamento continuam conferindo todas as tabelas, períodos, TOTAL e LTV.

Se um pedido já estava publicado, a inativação exige que segmento, ID, cliente,
data, estado e valores remotos correspondam exatamente à evidência autorizada.
Outro pedido ausente ou valor remoto divergente mantém
`BASE_LOCAL_INCOMPLETA_RECONCILIAR`. Não mudar assinaturas para contornar esse erro.

Seguir o piloto `--max-lotes 1`, conferir o subconjunto confirmado e retomar a
mesma revisão até READY integral, zero lotes restantes e diferenças zero. Provar
idempotência com novo preparo e zero deltas; preservar rollback e comprovantes.
Atualizar o painel somente depois do fechamento, mantendo as fontes corretas.

Toda nova coleta operacional pode voltar a receber os pedidos da API. Para uma
publicação futura, corrigir a origem ou criar outra cópia com as exclusões
expressamente autorizadas. A versão não traz lista comercial embutida nem aplica
automaticamente exclusões de um segmento no outro.

## Validação

Os testes usam SQLite real e transporte Sheets simulado: origem preservada,
hash divergente, autorização ausente, perfil incorreto, pendências, WAL, proteção
de saída, piloto, retomada, LTV, inativação autorizada, bloqueio de outras ausências
e idempotência. A distribuição ainda exige os checks Windows e conferência dos
pacotes do mesmo commit. Esses testes não representam publicação comercial.
