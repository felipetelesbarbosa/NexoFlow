# Exportação PostgreSQL — cabeçalhos físicos reordenados

Ocorrência informada pelo operador na revisão FARMA `665b492dcc1f4c61838a869a190fbe57`: cinco abas possuem os campos canônicos em outra ordem. A causa foi reproduzida com dados sintéticos; não houve leitura ou alteração das planilhas comerciais nesta correção.

## Causa e correção

`app/ds_backend/sheets_export.py` comparava o hash de cada parte diretamente ao hash da ordem canônica e exigia igualdade posicional do cabeçalho. Isso rejeitava schemas físicos válidos registrados no manifesto.

O exportador agora lê a primeira linha inteira da grade, desconsidera somente células vazias reservadas no final, confere hash e largura do cabeçalho físico contra a parte registrada e exige exatamente o conjunto de campos canônicos, sem faltas, extras, nomes vazios ou duplicatas. Cada linha é associada aos nomes na ordem física antes da normalização canônica; células finais omitidas pelo Sheets são preenchidas com vazio nessa mesma ordem. Abas legadas sem parte registrada também exigem o conjunto exato de campos; não se inventa hash de manifesto para elas.

O registro canônico e seu hash, as assinaturas do publicador, os manifestos existentes e as planilhas são preservados. Permanecem as guardas de origem/segmento, revisão histórica READY, outras publicações READY, lease, consistência dos schemas entre continuações, versões Drive antes/depois e hash do manifesto ao fechar. Falha não sela o corte como READY. Não ordenar colunas no Sheets nem editar o manifesto para contornar o erro.

## Validação

Regressão de reordenação falhou antes da correção com DS_SCHEMA_ORIGEM_DIVERGENTE. Cobertura: cinco tabelas históricas e múltiplas partes, comparação integral dos hashes/contagens canônicos e centavos/LTV, grade de 500 mil linhas com blocos de até mil, cabeçalhos ausentes/extras/duplicados/vazios/desconhecidos, hash físico divergente em uma continuação, tabela legada reordenada com linha curta, alteração Drive/revisão/manifesto e CLI real sobre serviços simulados. O teste da CLI conserva o exclusoes.json original.

Resultados locais: 47 testes da suíte Data Studio aprovados, incluindo os 13 testes de migração; um smoke HTTP de imagem Docker ignorado nesta rodada. Regressão do transporte histórico/continuações: 35 testes e 19 subtestes aprovados. Ruff, Pyright do módulo alterado, consistência, documentação e diff aprovados. CI/CodeQL do commit devem ser conferidos no GitHub; estes resultados não são homologação comercial.

## Atualização Windows

A correção altera código operacional e exige **nova release/Setup** para chegar ao Windows instalado. A 1.5.37 publicada não contém este ajuste. A distribuição corretiva 1.5.38 está em preparação autorizada; aguardar sua publicação comprovada antes de atualizar. Depois de disponibilizado o Setup validado que inclua o commit, encerrar as rotinas, instalar em Preserve, preservar configuração/credenciais/SQLite/journals e conferir `nexo versao`. Não copiar módulo avulso sobre C:\NexoFlow.

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
