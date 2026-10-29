param([string]$PackageDir = "dist/NexoFlow")
$ErrorActionPreference = 'Stop'
$env:NEXOFLOW_PERFIL = 'FARMA'
$root = Split-Path -Parent $PSScriptRoot
$temp = Join-Path $env:TEMP ("nexoflow-noturno-" + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path (Join-Path $temp 'app') | Out-Null
try {
    Copy-Item -LiteralPath (Join-Path $root "$PackageDir/NexoFlow Noturno.exe") -Destination $temp
    & python -m venv --without-pip (Join-Path $temp '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Falha na preparação do ambiente sintético.' }
    $script = Join-Path $temp 'app/run_noturno.py'
    $synthetic = @'
import os,sys
from pathlib import Path
Path('modo.txt').write_text(sys.argv[1], encoding='utf-8')
raise SystemExit(int(os.environ.get('NEXOFLOW_SYNTHETIC_EXIT', '0')))
'@
    [IO.File]::WriteAllText($script, $synthetic, [Text.UTF8Encoding]::new($false))
    function Invoke-NightCase {
        param([string]$Argument = '', [string]$InputText = '', [string]$ExpectedMode = '', [int]$ExpectedExit = 0, [string]$ExpectedLogs = 'logs\noturno\')
        $signal = Join-Path $temp 'modo.txt'
        Remove-Item -LiteralPath $signal -ErrorAction SilentlyContinue
        $info = [Diagnostics.ProcessStartInfo]::new()
        $info.FileName = Join-Path $temp 'NexoFlow Noturno.exe'
        $info.Arguments = $Argument
        $info.WorkingDirectory = $temp
        $info.UseShellExecute = $false
        $info.CreateNoWindow = $true
        $info.RedirectStandardInput = $true
        $info.RedirectStandardOutput = $true
        $info.RedirectStandardError = $true
        $process = [Diagnostics.Process]::new()
        $process.StartInfo = $info
        try {
            [void]$process.Start()
            if ($InputText) { $process.StandardInput.WriteLine($InputText) }
            $process.StandardInput.Close()
            if (-not $process.WaitForExit(15000)) {
                $process.Kill($true)
                $process.WaitForExit()
                throw "O launcher ficou aguardando interação inesperada. Saída: $($process.StandardOutput.ReadToEnd()) $($process.StandardError.ReadToEnd())"
            }
            if ($process.ExitCode -ne $ExpectedExit) { throw "Retorno incorreto: $($process.ExitCode); esperado $ExpectedExit" }
            $output = $process.StandardOutput.ReadToEnd()
            if ($InputText -ne '0') {
                if (-not $output.Contains("Código de saída: $ExpectedExit")) { throw 'O resumo final não informou o código de saída.' }
                if (-not $output.Contains($ExpectedLogs)) { throw 'O resumo final não informou o caminho dos relatórios.' }
                if ($output.Contains('Pressione ENTER')) { throw 'A execução sem console solicitou uma tecla.' }
            }
            if ($ExpectedMode) {
                if (-not (Test-Path -LiteralPath $signal)) { throw 'O processo filho não foi iniciado.' }
                if ((Get-Content -LiteralPath $signal -Raw) -cne $ExpectedMode) { throw 'Modo incorreto passado ao Python.' }
            } elseif (Test-Path -LiteralPath $signal) { throw 'Iniciou carga sem selecionar um modo válido.' }
        } finally { $process.Dispose() }
    }
    Remove-Item Env:NEXOFLOW_PERFIL -ErrorAction SilentlyContinue
    Invoke-NightCase -InputText "2`n1" -ExpectedMode '--incremental' -ExpectedLogs 'logs\PET\noturno\'
    $env:NEXOFLOW_PERFIL = 'FARMA'
    Invoke-NightCase -InputText '1' -ExpectedMode '--incremental'
    Invoke-NightCase -InputText '2' -ExpectedMode '--full'
    Invoke-NightCase -InputText '0'
    Invoke-NightCase -Argument '--incremental' -ExpectedMode '--incremental'
    Invoke-NightCase -Argument '--full' -ExpectedMode '--full'
    Invoke-NightCase -ExpectedExit 2
    $env:NEXOFLOW_SYNTHETIC_EXIT = '7'
    Invoke-NightCase -Argument '--full' -ExpectedMode '--full' -ExpectedExit 7
    $env:NEXOFLOW_SYNTHETIC_EXIT = '3'
    Invoke-NightCase -Argument '--incremental' -ExpectedMode '--incremental' -ExpectedExit 3
    Remove-Item Env:NEXOFLOW_SYNTHETIC_EXIT
    Remove-Item -LiteralPath $script
    Invoke-NightCase -Argument '--incremental' -ExpectedExit 2
    Write-Host '[OK] Noturno: menu, resumo de sucesso/parcial/falha e encerramento sem console; sem APIs reais.'
} finally {
    Remove-Item Env:NEXOFLOW_SYNTHETIC_EXIT -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue
}
