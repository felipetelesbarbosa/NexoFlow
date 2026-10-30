param([string]$PackageDir = 'dist/NexoFlow')
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$temporary = Join-Path $env:TEMP ('nexoflow-weni-smoke-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path (Join-Path $temporary 'comandos') -Force | Out-Null
$oldProfile = $env:NEXOFLOW_PERFIL
$oldUnattended = $env:NEXOFLOW_UNATTENDED
try {
    Copy-Item -LiteralPath (Join-Path $repo "$PackageDir/NexoFlow Weni.exe") -Destination $temporary
    $exe = Join-Path $temporary 'NexoFlow Weni.exe'
    $signal = Join-Path $temporary 'child.txt'
    $bat = Join-Path $temporary 'comandos/atualizar_weni.bat'
    [IO.File]::WriteAllText($bat, "@echo off`r`necho %NEXOFLOW_PERFIL%> `"%~dp0..\child.txt`"`r`nexit /b 0`r`n", [Text.Encoding]::ASCII)
    $env:NEXOFLOW_UNATTENDED = '1'
    foreach ($profile in @('FARMA', 'PET')) {
        $env:NEXOFLOW_PERFIL = $profile
        Remove-Item -LiteralPath $signal -ErrorAction SilentlyContinue
        $process = Start-Process -FilePath $exe -WorkingDirectory $temporary -NoNewWindow -PassThru -Wait
        if ($process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $signal) -or (Get-Content -LiteralPath $signal -Raw).Trim() -cne $profile) {
            throw "O launcher Weni não executou o BAT sintético de $profile."
        }
    }
    $env:NEXOFLOW_PERFIL = 'FARMA'
    $created = $false
    $active = New-Object Threading.Mutex($false, 'Local\NexoFlowOperationLock_FARMA', [ref]$created)
    try {
        Remove-Item -LiteralPath $signal -ErrorAction SilentlyContinue
        $output = Join-Path $temporary 'inspection.txt'
        $inspect = Start-Process -FilePath $exe -ArgumentList '--build-info' -WorkingDirectory $temporary -NoNewWindow -RedirectStandardOutput $output -PassThru -Wait
        if ($inspect.ExitCode -ne 0 -or (Test-Path -LiteralPath $signal) -or (Get-Content -LiteralPath $output -Raw) -notmatch 'NexoFlowWeniIconRevision=1.5') {
            throw 'Inspeção iniciou uma carga ou não respondeu com carga ativa.'
        }
        $blocked = Start-Process -FilePath $exe -WorkingDirectory $temporary -NoNewWindow -PassThru -Wait
        if ($blocked.ExitCode -ne 2 -or (Test-Path -LiteralPath $signal)) { throw 'A inspeção enfraqueceu a trava operacional.' }
    } finally { $active.Dispose() }
    [IO.File]::WriteAllText($bat, "@echo off`r`nexit /b 7`r`n", [Text.Encoding]::ASCII)
    $failure = Start-Process -FilePath $exe -WorkingDirectory $temporary -NoNewWindow -PassThru -Wait
    if ($failure.ExitCode -ne 7) { throw 'O launcher não propagou a falha sintética.' }
    Write-Host '[OK] Weni instalado: BAT sintético FARMA/PET, inspeção sem carga, trava e códigos de saída.'
} finally {
    if ($null -eq $oldProfile) { Remove-Item Env:NEXOFLOW_PERFIL -ErrorAction SilentlyContinue } else { $env:NEXOFLOW_PERFIL = $oldProfile }
    if ($null -eq $oldUnattended) { Remove-Item Env:NEXOFLOW_UNATTENDED -ErrorAction SilentlyContinue } else { $env:NEXOFLOW_UNATTENDED = $oldUnattended }
    Remove-Item -LiteralPath $temporary -Recurse -Force -ErrorAction SilentlyContinue
}
