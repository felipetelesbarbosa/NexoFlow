param([string]$PackageDir = "dist/NexoFlow")
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$package = Join-Path $root $PackageDir
$source = Join-Path $package "NexoFlow Recompra.exe"
if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
    throw "NexoFlow Recompra.exe nao foi incluido no pacote."
}
$testDir = Join-Path $env:TEMP ("nexoflow-recompra-launcher-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $testDir | Out-Null
try {
    $exe = Join-Path $testDir "NexoFlow Recompra.exe"
    $bat = Join-Path $testDir "atualizar_recompra.bat"
    $signal = Join-Path $testDir "recompra-launcher-sinal.txt"
    Copy-Item -LiteralPath $source -Destination $exe -Force

    # Somente um BAT sintetico isolado. NAO acessa a Weni e NAO importa clientes.
    [IO.File]::WriteAllText($bat, "@echo off`r`necho BAT_RECOMPRA_CHAMADO> `"%~dp0recompra-launcher-sinal.txt`"`r`nexit /b 0`r`n", [Text.Encoding]::ASCII)
    $proc = Start-Process -FilePath $exe -WorkingDirectory $testDir -NoNewWindow -PassThru -Wait
    if ($proc.ExitCode -ne 0) { throw "Launcher sucesso: exit inesperado $($proc.ExitCode)" }
    if (-not (Test-Path -LiteralPath $signal -PathType Leaf)) { throw "O executavel NAO chamou atualizar_recompra.bat" }
    if (-not ((Get-Content -LiteralPath $signal -Raw) -match "BAT_RECOMPRA_CHAMADO")) { throw "BAT nao executado" }

    [IO.File]::WriteAllText($bat, "@echo off`r`nexit /b 7`r`n", [Text.Encoding]::ASCII)
    $proc = Start-Process -FilePath $exe -WorkingDirectory $testDir -NoNewWindow -PassThru -Wait
    if ($proc.ExitCode -ne 7) { throw "Launcher falha: exit $($proc.ExitCode) deveria ser 7" }
    Write-Host "[OK] NexoFlow Recompra.exe chama BAT real por nome e propaga erro; sem acesso a producao."
}
finally {
    Remove-Item -LiteralPath $testDir -Recurse -Force -ErrorAction SilentlyContinue
}
