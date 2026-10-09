[CmdletBinding()]
param(
    [switch]$Stage2,
    [string]$InstallDir = 'C:\NexoFlow',
    [string]$DataDir = 'C:\NexoFlow Data',
    [int]$KeepDataFlag = 1
)

$ErrorActionPreference = 'Stop'
$AppName = 'NexoFlow'
$UninstallKey = 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\NexoFlow'
$AppKey = 'HKLM:\Software\Grupo Lider\NexoFlow'

function Show-Message([string]$Text, [string]$Title = $AppName, [string]$Icon = 'Information') {
    try {
        Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop
        [System.Windows.Forms.MessageBox]::Show($Text, $Title, 'OK', $Icon) | Out-Null
    } catch {
        Write-Host $Text
    }
}


function Test-Admin {
    try {
        $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
        $principal = New-Object Security.Principal.WindowsPrincipal($identity)
        return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    } catch {
        return $false
    }
}

function Get-WindowsPowerShellPath {
    $candidate = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    return 'powershell.exe'
}

function Ensure-Administrator {
    if ($Stage2 -or (Test-Admin)) { return }

    $powershell = Get-WindowsPowerShellPath
    $args = @(
        '-NoLogo',
        '-NoProfile',
        '-ExecutionPolicy', 'Bypass',
        '-File', ('"' + $PSCommandPath + '"'),
        '-InstallDir', ('"' + $InstallDir + '"'),
        '-DataDir', ('"' + $DataDir + '"')
    )

    try {
        $process = Start-Process -FilePath $powershell -ArgumentList $args -Verb RunAs -Wait -PassThru -ErrorAction Stop
        exit $process.ExitCode
    } catch {
        Show-Message "A desinstalação precisa de permissão de administrador.`n`n$($_.Exception.Message)" "$AppName - Permissão necessária" 'Warning'
        exit 1
    }
}

function Remove-Shortcuts {
    $desktop = [Environment]::GetFolderPath('CommonDesktopDirectory')
    $userDesktop = [Environment]::GetFolderPath('Desktop')
    foreach ($path in @(
        (Join-Path $desktop 'NexoFlow Analytics.lnk'),
        (Join-Path $userDesktop 'NexoFlow Analytics.lnk'),
        (Join-Path $desktop 'NexoFlow Weni.lnk'),
        (Join-Path $userDesktop 'NexoFlow Weni.lnk'),
        (Join-Path $desktop 'NexoFlow Planilha.lnk'),
        (Join-Path $userDesktop 'NexoFlow Planilha.lnk'),
        (Join-Path $desktop 'NexoFlow Terminal.lnk'),
        (Join-Path $userDesktop 'NexoFlow Terminal.lnk'),
        (Join-Path $desktop 'NexoFlow - Update Weni.lnk'),
        (Join-Path $userDesktop 'NexoFlow - Update Weni.lnk'),
        (Join-Path $desktop 'NexoFlow Console.lnk'),
        (Join-Path $userDesktop 'NexoFlow Console.lnk'),
        (Join-Path $desktop 'NexoFlow.lnk'),
        (Join-Path $userDesktop 'NexoFlow.lnk')
    )) {
        Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
    }

    $startMenu = Join-Path $env:ProgramData 'Microsoft\Windows\Start Menu\Programs\NexoFlow'
    Remove-Item -LiteralPath $startMenu -Recurse -Force -ErrorAction SilentlyContinue
}

function Remove-OptionalPrivateData {
    # importacoes nunca faz parte da limpeza opcional.
    foreach ($name in @('secrets_config.py', 'credentials', 'logs', 'DADOS PRESERVADOS.txt')) {
        $path = Join-Path $DataDir $name
        if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction Stop }
    }
}

function Get-Sha256File([string]$Path) {
    $stream = $null
    $sha = $null
    try {
        $stream = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
        $sha = [Security.Cryptography.SHA256]::Create()
        $bytes = $sha.ComputeHash($stream)
        return ([BitConverter]::ToString($bytes)).Replace('-', '').ToLowerInvariant()
    } finally {
        if ($sha) { $sha.Dispose() }
        if ($stream) { $stream.Dispose() }
    }
}


function Copy-ImportDirectory([string]$Source, [string]$Target, [string]$Relative = '', [string]$ArchiveRoot = '') {
    if (-not $ArchiveRoot) { $ArchiveRoot = Join-Path $Target 'historico_preservado' }
    $sourceItem = Get-Item -LiteralPath $Source -Force
    if ($sourceItem.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw 'A pasta importacoes contém um link/junção. A desinstalação foi interrompida para preservar os dados.'
    }
    New-Item -ItemType Directory -Force -Path $Target | Out-Null
    foreach ($item in (Get-ChildItem -LiteralPath $Source -Force)) {
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw 'A pasta importacoes contém um link/junção. A desinstalação foi interrompida para preservar os dados.'
        }
        $destination = Join-Path $Target $item.Name
        $relativePath = if ($Relative) { Join-Path $Relative $item.Name } else { $item.Name }
        if ($item.PSIsContainer) {
            Copy-ImportDirectory -Source $item.FullName -Target $destination -Relative $relativePath -ArchiveRoot $ArchiveRoot
            continue
        }
        $sourceHash = (Get-Sha256File -Path $item.FullName)
        if (Test-Path -LiteralPath $destination) {
            $existingHash = (Get-Sha256File -Path $destination)
            if ($existingHash -eq $sourceHash) { continue }
            # Um backup anterior com o mesmo nome é mantido antes da cópia
            # atual. A chave por conteúdo evita perder versões ou duplicá-las.
            $archive = Join-Path (Join-Path $ArchiveRoot $existingHash) $relativePath
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $archive) | Out-Null
            if (Test-Path -LiteralPath $archive) {
                if ((Get-Sha256File -Path $archive) -ne $existingHash) {
                    throw 'O histórico preservado está inconsistente. Nenhum arquivo instalado será removido.'
                }
            } else {
                Copy-Item -LiteralPath $destination -Destination $archive -Force -ErrorAction Stop
                if ((Get-Sha256File -Path $archive) -ne $existingHash) {
                    throw "Não foi possível verificar a cópia anterior de importacoes."
                }
            }
        }
        Copy-Item -LiteralPath $item.FullName -Destination $destination -Force -ErrorAction Stop
        if ((Get-Sha256File -Path $destination) -ne $sourceHash) {
            throw 'A cópia das importações não passou pela validação SHA-256. A desinstalação foi interrompida.'
        }
    }
}

function Preserve-Imports {
    $installed = [IO.Path]::GetFullPath($InstallDir).TrimEnd('\')
    $preserved = [IO.Path]::GetFullPath($DataDir).TrimEnd('\')
    if ($preserved.Equals($installed, [StringComparison]::OrdinalIgnoreCase) -or
        $preserved.StartsWith($installed + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'A pasta de preservação deve ficar fora da instalação do NexoFlow.'
    }
    $source = Join-Path $InstallDir 'importacoes'
    $target = Join-Path $DataDir 'importacoes'
    New-Item -ItemType Directory -Force -Path $target | Out-Null
    if (Test-Path -LiteralPath $source -PathType Container) {
        Copy-ImportDirectory -Source $source -Target $target
    }
}

function Preserve-PrivateData {
    Preserve-Imports
    Remove-OptionalPrivateData
    New-Item -ItemType Directory -Force -Path $DataDir | Out-Null

    $secret = Join-Path $InstallDir 'secrets_config.py'
    if (Test-Path -LiteralPath $secret -PathType Leaf) {
        Copy-Item -LiteralPath $secret -Destination (Join-Path $DataDir 'secrets_config.py') -Force
    }
    foreach ($name in @('credentials', 'logs')) {
        $source = Join-Path $InstallDir $name
        if (Test-Path -LiteralPath $source -PathType Container) {
            Copy-Item -LiteralPath $source -Destination (Join-Path $DataDir $name) -Recurse -Force
        }
    }
    @"
Dados preservados pelo desinstalador do NexoFlow.
Uma futura instalação restaurará automaticamente:
- secrets_config.py
- credentials\
- logs\
- importacoes\
As importações são sempre preservadas, independentemente da escolha para os demais dados.
"@ | Set-Content -LiteralPath (Join-Path $DataDir 'DADOS PRESERVADOS.txt') -Encoding UTF8
}

function Get-NexoFlowProcesses {
    $items = New-Object System.Collections.Generic.List[object]
    if (-not $InstallDir) { return $items }

    try {
        $root = [IO.Path]::GetFullPath($InstallDir).TrimEnd('\') + '\'
    } catch {
        return $items
    }

    try {
        foreach ($process in (Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)) {
            $pidValue = [int]$process.ProcessId
            if ($pidValue -eq $PID) { continue }

            $path = [string]$process.ExecutablePath
            $commandLine = [string]$process.CommandLine
            $matches = $false

            if ($path) {
                try {
                    $fullPath = [IO.Path]::GetFullPath($path)
                    if ($fullPath.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) {
                        $matches = $true
                    }
                } catch { }
            }

            # Fora da pasta de instalação, encerramos somente Python/PythonW
            # quando a própria linha de comando referencia explicitamente um
            # arquivo dentro do NexoFlow. Não encerramos cmd.exe/PowerShell
            # genéricos: terminais abertos devem ser fechados pelo usuário.
            if (-not $matches -and $commandLine -and $commandLine.IndexOf($root, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
                $name = [string]$process.Name
                if ($name -match '(?i)^pythonw?\.exe$') {
                    $matches = $true
                }
            }

            if ($matches) {
                $items.Add([pscustomobject]@{
                    ProcessId = $pidValue
                    Name = [string]$process.Name
                    Path = $path
                    CommandLine = $commandLine
                })
            }
        }
    } catch { }

    return $items
}

function Stop-NexoFlowProcesses {
    $stopped = @()
    foreach ($process in (Get-NexoFlowProcesses)) {
        try {
            Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
            $stopped += $process.Name
        } catch { }
    }
    return $stopped
}

function Remove-InstallDirectory {
    # O Stage2 executa a partir de %TEMP%. Durante a janela de encerramento do
    # launcher original, repetimos a limpeza para evitar corrida com handles que
    # ainda estejam sendo liberados pelo Windows.
    Start-Sleep -Seconds 2

    $removed = $false
    for ($attempt = 1; $attempt -le 60; $attempt++) {
        Stop-NexoFlowProcesses | Out-Null

        try {
            if (Test-Path -LiteralPath $InstallDir) {
                # Remove atributos somente-leitura/sistema/oculto antes da
                # tentativa de exclusão. Falha aqui não interrompe o retry.
                & attrib.exe -R -S -H (Join-Path $InstallDir '*') /S /D 2>$null | Out-Null
            }
        } catch { }

        Start-Sleep -Milliseconds 500

        try {
            if (Test-Path -LiteralPath $InstallDir) {
                Remove-Item -LiteralPath $InstallDir -Recurse -Force -ErrorAction Stop
            }
        } catch { }

        $removed = -not (Test-Path -LiteralPath $InstallDir)
        if ($removed) { break }
        Start-Sleep -Milliseconds 750
    }

    return $removed
}

if ($Stage2) {
    # Fundamental: copiar o script para %TEMP% não basta. O processo também
    # precisa trocar explicitamente seu diretório atual, pois um CWD herdado em
    # C:\NexoFlow pode impedir a remoção da própria pasta.
    try {
        $tempWorkingDir = [IO.Path]::GetFullPath($env:TEMP)
        Set-Location -LiteralPath $tempWorkingDir
    } catch {
        try { Set-Location -LiteralPath ([IO.Path]::GetTempPath()) } catch { }
    }

    $KeepData = ($KeepDataFlag -eq 1)
    try {
        Stop-NexoFlowProcesses | Out-Null
        Preserve-Imports
    } catch {
        Show-Message "Não foi possível preservar importacoes. A instalação não será removida.`n`n$($_.Exception.Message)" "$AppName - Erro" 'Error'
        exit 1
    }
    $removed = Remove-InstallDirectory

    if ($removed) {
        Remove-Shortcuts
        Remove-Item -LiteralPath $UninstallKey -Recurse -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $AppKey -Recurse -Force -ErrorAction SilentlyContinue

        if (-not $KeepData) { Remove-OptionalPrivateData }

        try { Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue } catch { }

        if ($KeepData) {
            Show-Message "$AppName foi desinstalado.`n`nConfigurações, credenciais, logs e importacoes foram preservados em:`n$DataDir"
        } else {
            Show-Message "$AppName foi desinstalado. Configurações, credenciais e logs foram removidos.`n`nA pasta importacoes e seus arquivos foram preservados em:`n$(Join-Path $DataDir 'importacoes')"
        }
        exit 0
    }

    $remainingProcesses = @(Get-NexoFlowProcesses)
    $remainingFiles = @()
    try {
        if (Test-Path -LiteralPath $InstallDir) {
            $remainingFiles = @(Get-ChildItem -LiteralPath $InstallDir -Force -Recurse -ErrorAction SilentlyContinue | Select-Object -First 12 -ExpandProperty FullName)
        }
    } catch { }

    $details = ''
    if ($remainingProcesses.Count -gt 0) {
        $details += "`n`nProcessos ainda ativos:`n" + (($remainingProcesses | ForEach-Object { "- $($_.Name) (PID $($_.ProcessId))" }) -join "`n")
    }
    if ($remainingFiles.Count -gt 0) {
        $details += "`n`nAlguns itens ainda presentes:`n" + ($remainingFiles -join "`n")
    }

    Show-Message "Não foi possível remover completamente a pasta:`n$InstallDir$details`n`nFeche terminais ou janelas do Explorer posicionados nessa pasta e tente novamente." "$AppName - Erro" 'Error'
    exit 1
}

Ensure-Administrator

try {
    Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop
    $result = [System.Windows.Forms.MessageBox]::Show(
        "Deseja manter configurações, credenciais e logs para uma futura reinstalação?`n`nSIM (recomendado): preserva secrets_config.py, credentials e logs.`nNÃO: remove configurações, credenciais e logs.`nCANCELAR: não desinstala.`n`nA pasta importacoes e seus arquivos SEMPRE serão preservados em $DataDir\importacoes.`n`nProcessos do NexoFlow que estiverem em execução serão encerrados para permitir a remoção segura.",
        "$AppName - Desinstalar",
        'YesNoCancel',
        'Warning'
    )
    if ($result -eq [System.Windows.Forms.DialogResult]::Cancel) { exit 2 }
    $keep = ($result -eq [System.Windows.Forms.DialogResult]::Yes)

    Preserve-Imports
    if ($keep) { Preserve-PrivateData }

    # O Stage2 precisa executar fora de C:\NexoFlow para que o Windows possa
    # remover a pasta instalada, .venv, Analytics, Weni e Terminal.
    # Nome determinístico: evita gerar scripts aleatórios a cada desinstalação
    # e facilita auditoria por ferramentas de segurança.
    $tempScript = Join-Path $env:TEMP 'NexoFlow-Uninstall-Stage2.ps1'
    Remove-Item -LiteralPath $tempScript -Force -ErrorAction SilentlyContinue
    Copy-Item -LiteralPath $PSCommandPath -Destination $tempScript -Force
    $keepFlag = if ($keep) { 1 } else { 0 }
    $argLine = '-NoLogo -NoProfile -ExecutionPolicy Bypass -File "{0}" -Stage2 -InstallDir "{1}" -DataDir "{2}" -KeepDataFlag {3}' -f $tempScript, $InstallDir, $DataDir, $keepFlag

    $tempWorkingDir = [IO.Path]::GetTempPath()
    # Mantemos a janela visível. A release não oculta PowerShell no Stage2.
    Start-Process -FilePath (Get-WindowsPowerShellPath) -ArgumentList $argLine -WorkingDirectory $tempWorkingDir
    exit 0
} catch {
    Show-Message "A desinstalação não foi concluída.`n`n$($_.Exception.Message)" "$AppName - Erro" 'Error'
    exit 1
}
