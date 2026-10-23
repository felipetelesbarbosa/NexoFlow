param([string]$PackageDir = "dist/NexoFlow")
$ErrorActionPreference = 'Stop'
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
        param([string]$Argument = '', [string]$InputText = '', [string]$ExpectedMode = '', [int]$ExpectedExit = 0)
        $signal = Join-Path $temp 'modo.txt'
        Remove-Item -LiteralPath $signal -ErrorAction SilentlyContinue
        $info = [Diagnostics.ProcessStartInfo]::new()
        $info.FileName = Join-Path $temp 'NexoFlow Noturno.exe'
        $info.Arguments = $Argument
        $info.WorkingDirectory = $temp
        $info.UseShellExecute = $false
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
                throw 'O launcher ficou aguardando interação inesperada.'
            }
            if ($process.ExitCode -ne $ExpectedExit) { throw "Retorno incorreto: $($process.ExitCode); esperado $ExpectedExit" }
            if ($ExpectedMode) {
                if (-not (Test-Path -LiteralPath $signal)) { throw 'O processo filho não foi iniciado.' }
                if ((Get-Content -LiteralPath $signal -Raw) -cne $ExpectedMode) { throw 'Modo incorreto passado ao Python.' }
            } elseif (Test-Path -LiteralPath $signal) { throw 'Iniciou carga sem selecionar um modo válido.' }
        } finally { $process.Dispose() }
    }
    Invoke-NightCase -InputText '1' -ExpectedMode '--incremental'
    Invoke-NightCase -InputText '2' -ExpectedMode '--full'
    Invoke-NightCase -InputText '0'
    Invoke-NightCase -Argument '--incremental' -ExpectedMode '--incremental'
    Invoke-NightCase -Argument '--full' -ExpectedMode '--full'
    Invoke-NightCase -ExpectedExit 2
    $env:NEXOFLOW_SYNTHETIC_EXIT = '7'
    Invoke-NightCase -Argument '--full' -ExpectedMode '--full' -ExpectedExit 7
    Remove-Item Env:NEXOFLOW_SYNTHETIC_EXIT
    Remove-Item -LiteralPath $script
    Invoke-NightCase -Argument '--incremental' -ExpectedExit 2
    Write-Host '[OK] Noturno: menu, agendamento, cancelamento e falhas sem pausas; sem APIs reais.'
} finally {
    Remove-Item Env:NEXOFLOW_SYNTHETIC_EXIT -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue
}
