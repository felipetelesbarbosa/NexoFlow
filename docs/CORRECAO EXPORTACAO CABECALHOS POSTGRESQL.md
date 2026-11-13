# Exportação PostgreSQL — cabeçalhos físicos reordenados

Ocorrência informada pelo operador na revisão FARMA `665b492dcc1f4c61838a869a190fbe57`: cinco abas possuem os campos canônicos em outra ordem. A causa foi reproduzida com dados sintéticos; não houve leitura ou alteração das planilhas comerciais nesta correção.

## Causa e correção

`app/ds_backend/sheets_export.py` comparava o hash de cada parte diretamente ao hash da ordem canônica e exigia igualdade posicional do cabeçalho. Isso rejeitava schemas físicos válidos registrados no manifesto.

O exportador agora lê a primeira linha inteira da grade, desconsidera somente células vazias reservadas no final, confere hash e largura do cabeçalho físico contra a parte registrada e exige exatamente o conjunto de campos canônicos, sem faltas, extras, nomes vazios ou duplicatas. Cada linha é associada aos nomes na ordem física antes da normalização canônica; células finais omitidas pelo Sheets são preenchidas com vazio nessa mesma ordem. Abas legadas sem parte registrada também exigem o conjunto exato de campos; não se inventa hash de manifesto para elas.

O registro canônico e seu hash, as assinaturas do publicador, os manifestos existentes e as planilhas são preservados. Permanecem as guardas de origem/segmento, revisão histórica READY, outras publicações READY, lease, consistência dos schemas entre continuações, versões Drive antes/depois e hash do manifesto ao fechar. Falha não sela o corte como READY. Não ordenar colunas no Sheets nem editar o manifesto para contornar o erro.

## Validação

Regressão de reordenação falhou antes da correção com DS_SCHEMA_ORIGEM_DIVERGENTE. Cobertura: cinco tabelas históricas e múltiplas partes, comparação integral dos hashes/contagens canônicos e centavos/LTV, grade de 500 mil linhas com blocos de até mil, cabeçalhos ausentes/extras/duplicados/vazios/desconhecidos, hash físico divergente em uma continuação, tabela legada reordenada com linha curta, alteração Drive/revisão/manifesto e CLI real sobre serviços simulados. O teste da CLI conserva o exclusoes.json original.

Resultados locais: 47 testes da suíte Data Studio aprovados, incluindo os 13 testes de migração; um smoke HTTP de imagem Docker ignorado nesta rodada. Regressão do transporte histórico/continuações: 35 testes e 19 subtestes aprovados. Ruff, Pyright do módulo alterado, consistência, documentação e diff aprovados. CI, CodeQL, Meta e PostgreSQL/Docker do SHA distribuído aprovados. Matriz Windows Python 3.11/3.14 nas duas codificações, executáveis, Setup Preserve/Clean/rollback e pacote instalado aprovados. Estes resultados não são homologação comercial.

## Atualização Windows

A correção altera código operacional e exige **nova release/Setup** para chegar ao Windows instalado. A 1.5.37 publicada não contém este ajuste. A distribuição corretiva **1.5.38 está publicada**. Encerrar as rotinas, instalar o [Setup oficial](https://github.com/felipetelesbarbosa/NexoFlow/releases/download/v1.5.38/NexoFlow-Setup-1.5.38.zip) em Preserve, preservar configuração/credenciais/SQLite/journals e conferir `nexo versao` (1.5.38). Não copiar módulo avulso sobre C:\NexoFlow.

## Repetir a exportação

Selecionar FARMA no Terminal atualizado. Encerrar as rotinas que possam gravar nos arquivos de origem durante a exportação. Reutilizar o **exclusoes.json já conferido dessa mesma revisão**, sem regenerar a partir de outro SQLite. Manter os arquivos da tentativa interrompida como evidência. O comando exporta o corte completo atual sob as guardas; não retoma um corte incompleto e não recoleta pedidos na API.

```powershell
& {
    $ErrorActionPreference = 'Stop'
    $exclusoes = Read-Host 'Caminho completo do exclusoes.json já conferido'
    if (-not (Test-Path -LiteralPath $exclusoes -PathType Leaf)) {
        throw 'Arquivo de exclusões não encontrado.'
    }
    $prova = Get-Content -LiteralPath $exclusoes -Raw | ConvertFrom-Json
    $revisao = '665b492dcc1f4c61838a869a190fbe57'
    if ($prova.segment -ne 'FARMA' -or $prova.revision -ne $revisao) {
        throw 'Exclusões pertencem a outro segmento ou revisão.'
    }
    $p = Join-Path 'C:\NexoFlow\logs\privado\migracao-postgres' ('exportacao-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
    New-Item -ItemType Directory -Path $p | Out-Null
    nexo armazenamento postgres exportar-sheets `
        --origem-revisao $revisao --exclusoes $exclusoes `
        --exportacao "$p\corte.sqlite" --saida "$p\corte-manifesto.json"
    if ($LASTEXITCODE -ne 0) { throw 'Exportação falhou. Preserve a pasta para diagnóstico.' }
    nexo armazenamento postgres auditar-exportacao `
        --exportacao "$p\corte.sqlite" --saida "$p\corte-conferencia.json"
    if ($LASTEXITCODE -ne 0) { throw 'Auditoria falhou. Não publicar este corte.' }
    Write-Host "Corte e conferência concluídos em: $p"
}
```

A exportação exige credenciais Google existentes, mas não publicacao.json. Depois do corte e da auditoria aprovados, usar o novo caminho no recorte de um pedido completo e gerar o piloto-manifesto.json para o Work. A simulação/publicação posterior na API exige credenciais e aprovação da origem em homologação; não é executada por estes comandos.

## Evidência da distribuição

Publicação: 12/11/2026, 22:39:37 (America/Fortaleza). Tag v1.5.38 no SHA `ace7c8f12361fe2bc0256323cb59f3b56b55cd0d`. [Preparação validada](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/43343660933), [CodeQL](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/43343660702) e [publicação sem recompilar](https://github.com/felipetelesbarbosa/NexoFlow/actions/runs/43346458099).

Os dois downloads públicos passaram em CRC e comparação com o commit (normalização CRLF apenas para texto): 123 módulos Python e 572 arquivos versionados por pacote, 579 entradas no manifesto do Setup, sete executáveis x64 do aplicativo e o Setup 1.5.38.0.

SHA-256 recalculado dos downloads:

- Setup: `a1d29adcad9940efe5bbf151f1c642dbdb249008e6eea383dbd2a1b5be679b1d`.
- Projeto: `9928d5b110719ded704e40dabeb5029569f4c70ba9936b7105b1e8b22f734c7a`.

Não houve leitura das planilhas comerciais nem confirmação da exportação real. O operador deve repetir exportação e auditoria conforme o roteiro acima; publicação de software não aprova automaticamente o corte comercial.

## Bloqueio posterior: chave divergente

O operador relatou `DS_ORIGEM_CHAVE_DIVERGENTE` após retentativas HTTP 429 na 1.5.38. A condição no código é duas linhas normalizadas com a mesma chave canônica e conteúdos distintos. Os logs fornecidos não identificam a tabela, a parte ou os campos; não permitem concluir duplicidade comercial nem erro no contrato da chave. O corte interrompido não é uma exportação READY e não deve ser enviado.

O diagnóstico posterior à 1.5.38 identifica tabela e nomes dos campos na exceção. Durante exportação Sheets, grava ao lado do corte `corte.diagnostico.json`, com segmento, revisão, nomes dos campos da chave, campos divergentes e posições físicas das duas ocorrências (parte, ID numérico da aba e linha). Não inclui valores de células, IDs de pedidos/clientes, tokens ou hashes de identidade. A consistência final da origem aparece como `NAO_CONCLUIDA`: o conflito é detectado antes da reconferência final de versões Drive/manifesto. Posições são evidência daquela tentativa, não autorização para editar a origem.

O índice de posições é temporário no SQLite durante a exportação; não muda o schema canônico ou o pacote definitivo. Duplicatas idênticas continuam idempotentes. Divergências continuam bloqueando o corte e não são resolvidas escolhendo a última linha nem descartando revisões.

Testes sintéticos cobrem conflito entre partes, posição das duas ocorrências, ausência de valores privados no diagnóstico, corte sem READY e repetição idêntica sem duplicação. O diagnóstico exige nova distribuição Windows; não substituir módulos avulsos. A causa da ocorrência comercial permanece pendente de evidência. Manter a pasta interrompida e o exclusoes.json; não repetir a carga somente para reproduzir o mesmo erro genérico.
