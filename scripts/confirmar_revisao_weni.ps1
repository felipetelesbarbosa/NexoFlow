[CmdletBinding()]
param(
    [string]$Part = ""
)

$ErrorActionPreference = "Stop"
$Expected = "CARGA COMPLETA REVISADA"
$title = "NexoFlow Weni - Revisao Humana"

try {
    Add-Type -AssemblyName Microsoft.VisualBasic

    $partText = ""
    if ($Part) {
        $partText = " da Parte $Part/4"
    }

    $message = @"
Revise o relatorio aberto no Bloco de Notas$partText.

Depois de concluir a revisao, digite exatamente:

$Expected

Fechar ou cancelar esta janela NAO aplica nenhuma alteracao.
"@

    $response = [Microsoft.VisualBasic.Interaction]::InputBox(
        $message,
        $title,
        ""
    )

    if ($response.Trim().Equals($Expected, [System.StringComparison]::OrdinalIgnoreCase)) {
        Write-Host "[OK] Revisao humana confirmada."
        exit 0
    }

    Write-Host "[INFO] Confirmacao humana nao recebida. Nenhuma alteracao sera aplicada."
    exit 2
}
catch {
    Write-Host "[ERRO] Nao foi possivel abrir a confirmacao humana grafica."
    Write-Host "[ERRO] Nenhuma alteracao sera aplicada."
    exit 3
}
