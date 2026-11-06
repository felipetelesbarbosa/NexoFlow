param(
    [int]$ResultCode = 0,
    [string]$Stage = 'RESULTADO',
    [string]$Snapshot = '',
    [switch]$RecordOnly
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$log = Join-Path $root 'logs\weni_full_launcher.log'

function Show-WeniResult {
    param([string]$Message)
    Add-Type -AssemblyName System.Windows.Forms
    [void][Windows.Forms.MessageBox]::Show($Message, 'NexoFlow Weni — Resultado da carga',
        [Windows.Forms.MessageBoxButtons]::OK, [Windows.Forms.MessageBoxIcon]::Information,
        [Windows.Forms.MessageBoxDefaultButton]::Button1, [Windows.Forms.MessageBoxOptions]::DefaultDesktopOnly)
}

function Complete-WeniResult {
    try {
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $log) | Out-Null
        $zone = [TimeZoneInfo]::FindSystemTimeZoneById('SA Eastern Standard Time')
        $when = [TimeZoneInfo]::ConvertTime([DateTimeOffset]::UtcNow, $zone).ToString('yyyy-MM-ddTHH:mm:sszzz')
        Add-Content -LiteralPath $log -Encoding UTF8 -Value "$when | etapa=$Stage | código=$ResultCode | snapshot=$Snapshot"
        if ($RecordOnly) { return 0 }
        $status = if ($Stage -eq 'CANCELADO') { 'Operação cancelada.' }
                  elseif ($ResultCode -eq 0) { 'Carga concluída.' }
                  elseif ($ResultCode -eq 3 -and $Stage -eq 'PARCIAL') { 'Carga concluída com pendências. As alterações confirmadas foram preservadas. Consulte o resumo de cada etapa para revalidar as pendências na próxima carga.' }
                  else { "Carga interrompida. Código: $ResultCode. Não presuma conclusão." }
        $nextAction = if ($Stage -eq 'PARCIAL' -and $ResultCode -eq 3) { 'Gere uma nova revisão na próxima carga para revalidar as pendências; não reaplique a revisão antiga.' }
                      else { 'Confira o estado e a auditoria antes de retomar uma aplicação interrompida.' }
        Show-WeniResult "$status`n`nConfira o resultado no CMD antes de fechar esta janela.`n`nLogs:`n$log`n$(Join-Path $root 'logs\nexoflow_update_weni.log')`n`nSnapshot preservado: $Snapshot`n$nextAction"
        return 0
    }
    catch {
        Write-Host '[ERRO] Não foi possível registrar ou apresentar o resultado da carga.'
        return 3
    }
}

if ($MyInvocation.InvocationName -ne '.') { exit (Complete-WeniResult) }
