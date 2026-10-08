[CmdletBinding()]
param(
    [string]$Part = ""
)

$ErrorActionPreference = "Stop"

function Show-WeniReviewDialog {
    param([string]$Message, [string]$Title)

    Add-Type -AssemblyName Microsoft.VisualBasic
    return [Microsoft.VisualBasic.Interaction]::InputBox($Message, $Title, "")
}

function Confirm-WeniReview {
    param([string]$Part = "")

    $expected = "CARGA COMPLETA REVISADA"
    $title = "NexoFlow Weni - Revisao Humana"
    try {
        $partText = ""
        if ($Part) { $partText = " da Parte $Part/4" }
        $message = @"
Revise o relatorio aberto no Bloco de Notas$partText.

Depois de concluir a revisao, digite exatamente:

$expected

Fechar ou cancelar esta janela NAO aplica nenhuma alteracao.
"@
        $response = [string](Show-WeniReviewDialog -Message $message -Title $title)
        if ($response.Trim().Equals($expected, [System.StringComparison]::OrdinalIgnoreCase)) {
            Write-Host "[OK] Revisao humana confirmada."
            return 0
        }
        Write-Host "[INFO] Confirmacao humana nao recebida. Nenhuma alteracao sera aplicada."
        return 2
    }
    catch {
        Write-Host "[ERRO] Nao foi possivel abrir a confirmacao humana grafica."
        Write-Host "[ERRO] Nenhuma alteracao sera aplicada."
        return 3
    }
}

if ($MyInvocation.InvocationName -ne '.') {
    exit (Confirm-WeniReview -Part $Part)
}
