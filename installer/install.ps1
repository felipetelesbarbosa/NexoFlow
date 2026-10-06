[CmdletBinding()]
param(
    [switch]$NonInteractive
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$AppName = 'NexoFlow'
$AppVersion = '1.0'
$Publisher = 'Grupo Lider'
$InstallDir = 'C:\NexoFlow'
$DataDir = 'C:\NexoFlow Data'
$PackageRoot = Split-Path -Parent $PSScriptRoot
$PayloadDir = Join-Path $PackageRoot 'payload'
$ManifestPath = Join-Path $PayloadDir 'payload manifest.json'
$BundledPythonInstaller = Join-Path $PackageRoot 'prerequisites\python-3.14.8-amd64.exe'
$BundledPythonSha256 = '759be887b96e736a3ca886daf8d575f18fcae1a09efab6902f42d59e8999f8ef'
$UninstallKey = 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\NexoFlow'
$AppKey = 'HKLM:\Software\Grupo Lider\NexoFlow'
$script:OptionalUninstallerValidated = $true
$script:RollbackInstallDir = $null

# Caminhos da instalação anterior, usados somente para migração para a marca NexoFlow.
$LegacyInstallDir = 'C:\Weni\WeniWhatsAppAnalytics'
$LegacyDataDir = 'C:\Weni\WeniWhatsAppAnalytics_Data'
$LegacyUninstallKey = 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\WeniWhatsAppAnalytics'
$LegacyAppKey = 'HKLM:\Software\Grupo Lider\WeniWhatsAppAnalytics'

$SetupLogPath = Join-Path $env:TEMP 'NexoFlow-Setup.log'
try {
    Start-Transcript -LiteralPath $SetupLogPath -Append -Force | Out-Null
} catch { }

function Write-Step([string]$Text) { Write-Host "`n==> $Text" -ForegroundColor Cyan }

function Test-Admin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Ensure-Administrator {
    if (Test-Admin) { return }

    if ($NonInteractive) {
        throw 'O modo nao interativo precisa ser executado com privilegios de administrador.'
    }

    $powershellExe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    if (-not (Test-Path -LiteralPath $powershellExe -PathType Leaf)) {
        $powershellExe = 'powershell.exe'
    }

    $argumentLine = '-NoLogo -NoProfile -ExecutionPolicy Bypass -File "{0}"' -f $PSCommandPath
    try {
        $process = Start-Process -FilePath $powershellExe -ArgumentList $argumentLine -Verb RunAs -Wait -PassThru -ErrorAction Stop
        exit $process.ExitCode
    } catch {
        throw "A instalacao precisa de permissao de administrador. Operacao cancelada ou negada pelo Windows. $($_.Exception.Message)"
    }
}

function Show-Info([string]$Text, [string]$Title = $AppName) {
    if ($NonInteractive) {
        Write-Host "[$Title] $Text"
        return
    }

    try {
        Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop
        [System.Windows.Forms.MessageBox]::Show($Text, $Title, 'OK', 'Information') | Out-Null
    } catch { Write-Host $Text }
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


function Test-PythonInterpreter {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [string[]]$PrefixArguments = @()
    )

    if (-not $Executable) { return $null }
    try { $Executable = [Environment]::ExpandEnvironmentVariables($Executable).Trim().Trim('"') } catch { }
    if (-not $Executable) { return $null }
    if ($Executable -like '*\WindowsApps\python*.exe') { return $null }

    if ([IO.Path]::IsPathRooted($Executable) -and -not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
        return $null
    }

    # Valida por um arquivo .py temporario. Isto evita problemas de quoting de
    # "python -c ..." no Windows PowerShell 5.1 e retorna o sys.executable real.
    $probeId = [guid]::NewGuid().ToString('N')
    $probeFile = Join-Path $env:TEMP ("nexoflow-python-probe-$probeId.py")
    $stdoutFile = Join-Path $env:TEMP ("nexoflow-python-probe-$probeId.out")
    $stderrFile = Join-Path $env:TEMP ("nexoflow-python-probe-$probeId.err")

    try {
        $probeSource = @'
import struct
import sys

bits = struct.calcsize("P") * 8
version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
print(f"{sys.executable}|{version}|{bits}")
raise SystemExit(0 if sys.version_info >= (3, 11) and bits == 64 else 3)
'@
        [IO.File]::WriteAllText($probeFile, $probeSource, (New-Object System.Text.UTF8Encoding($false)))

        $arguments = New-Object System.Collections.Generic.List[string]
        foreach ($arg in $PrefixArguments) {
            if ($arg) { $arguments.Add([string]$arg) }
        }
        $arguments.Add('"' + $probeFile + '"')

        $process = Start-Process `
            -FilePath $Executable `
            -ArgumentList ($arguments.ToArray()) `
            -PassThru `
            -Wait `
            -NoNewWindow `
            -RedirectStandardOutput $stdoutFile `
            -RedirectStandardError $stderrFile `
            -ErrorAction Stop

        if ($process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $stdoutFile -PathType Leaf)) {
            return $null
        }

        $lines = Get-Content -LiteralPath $stdoutFile -ErrorAction SilentlyContinue
        if (-not $lines) { return $null }

        $line = ([string]($lines | Select-Object -Last 1)).Trim()
        $parts = $line.Split('|')
        if ($parts.Count -lt 3) { return $null }

        $resolvedPath = $parts[0].Trim().Trim('"')
        $version = [Version]($parts[1].Trim())
        $bits = [int]($parts[2].Trim())
        if ($version -lt [Version]'3.11' -or $bits -ne 64) { return $null }

        if ($resolvedPath -and (Test-Path -LiteralPath $resolvedPath -PathType Leaf)) {
            $finalPath = $resolvedPath
        } elseif ([IO.Path]::IsPathRooted($Executable) -and (Test-Path -LiteralPath $Executable -PathType Leaf)) {
            $finalPath = $Executable
        } else {
            $command = Get-Command $Executable -ErrorAction SilentlyContinue
            if ($command -and $command.Source) { $finalPath = $command.Source } else { return $null }
        }

        return [pscustomobject]@{
            Path = $finalPath
            Version = $version.ToString()
            Bits = $bits
        }
    } catch {
        return $null
    } finally {
        foreach ($tempFile in @($probeFile, $stdoutFile, $stderrFile)) {
            Remove-Item -LiteralPath $tempFile -Force -ErrorAction SilentlyContinue
        }
    }
}

function Get-CompatiblePython {
    $seen = @{}
    # Fallback de seguranca: se um python.exe real existir mas o probe do
    # PowerShell falhar por alguma particularidade do ambiente, o caminho ainda
    # pode ser entregue ao instalar.bat, que faz uma segunda validacao direta.
    $fallback = [pscustomobject]@{ Path = $null }

    function Try-Candidate([string]$Executable, [string[]]$PrefixArguments = @()) {
        if (-not $Executable) { return $null }
        try { $Executable = [Environment]::ExpandEnvironmentVariables($Executable).Trim().Trim('"') } catch { }
        $key = ($Executable + '|' + ($PrefixArguments -join ' ')).ToLowerInvariant()
        if ($seen.ContainsKey($key)) { return $null }
        $seen[$key] = $true

        # Guarda o primeiro python.exe real como fallback. Launchers (py.exe) e
        # aliases de WindowsApps nao entram aqui.
        if (-not $fallback.Path -and $PrefixArguments.Count -eq 0 -and [IO.Path]::IsPathRooted($Executable)) {
            $leaf = [IO.Path]::GetFileName($Executable)
            if (($leaf -match '(?i)^python(?:3(?:\.\d+)*)?\.exe$') -and ($Executable -notlike '*\WindowsApps\python*.exe') -and (Test-Path -LiteralPath $Executable -PathType Leaf)) {
                $fallback.Path = $Executable
            }
        }

        $validated = Test-PythonInterpreter -Executable $Executable -PrefixArguments $PrefixArguments
        if ($validated) {
            $validated | Add-Member -NotePropertyName Validated -NotePropertyValue $true -Force
            return $validated
        }
        return $null
    }

    # 0. Caminho já resolvido por uma etapa anterior.
    if ($env:NEXOFLOW_PYTHON_EXE -and (Test-Path -LiteralPath $env:NEXOFLOW_PYTHON_EXE -PathType Leaf)) {
        $result = Try-Candidate -Executable $env:NEXOFLOW_PYTHON_EXE
        if ($result) { return $result }
    }

    # 1. Atalhos oficiais do Python no Menu Iniciar. O instalador classico
    #    cria o atalho "Python X.Y.Z"; resolver o TargetPath obtem o python.exe
    #    real mesmo quando ele nao foi adicionado ao PATH.
    try {
        $shell = New-Object -ComObject WScript.Shell
        $startMenuRoots = New-Object System.Collections.Generic.List[string]

        foreach ($root in @(
            (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'),
            (Join-Path $env:ProgramData 'Microsoft\Windows\Start Menu\Programs')
        )) {
            if ($root -and (Test-Path -LiteralPath $root -PathType Container) -and -not $startMenuRoots.Contains($root)) {
                $startMenuRoots.Add($root)
            }
        }

        try {
            if (Test-Path -LiteralPath 'C:\Users' -PathType Container) {
                foreach ($profile in (Get-ChildItem -LiteralPath 'C:\Users' -Directory -ErrorAction SilentlyContinue)) {
                    $root = Join-Path $profile.FullName 'AppData\Roaming\Microsoft\Windows\Start Menu\Programs'
                    if ((Test-Path -LiteralPath $root -PathType Container) -and -not $startMenuRoots.Contains($root)) {
                        $startMenuRoots.Add($root)
                    }
                }
            }
        } catch { }

        foreach ($root in $startMenuRoots) {
            foreach ($pythonFolder in (Get-ChildItem -LiteralPath $root -Directory -Filter 'Python*' -ErrorAction SilentlyContinue)) {
                foreach ($shortcutFile in (Get-ChildItem -LiteralPath $pythonFolder.FullName -Filter '*.lnk' -File -ErrorAction SilentlyContinue | Sort-Object Name -Descending)) {
                    try {
                        if ($shortcutFile.BaseName -match '(?i)manual|module docs|idle|documentation|docs') { continue }
                        $shortcut = $shell.CreateShortcut($shortcutFile.FullName)
                        $target = ([string]$shortcut.TargetPath).Trim().Trim('"')
                        $leaf = [IO.Path]::GetFileName($target)
                        if ($target -and $leaf -match '(?i)^python(?:3(?:\.\d+)*)?\.exe$' -and (Test-Path -LiteralPath $target -PathType Leaf)) {
                            $result = Try-Candidate -Executable $target
                            if ($result) { return $result }
                        }
                    } catch { }
                }
            }
        }
    } catch { }

    # 2. PATH atual. Aliases de WindowsApps sao ignorados porque podem abrir a
    #    Microsoft Store em vez de representar um runtime instalado.
    foreach ($commandName in @('python.exe','python3.exe','python3.14.exe','python3.13.exe','python3.12.exe','python3.11.exe')) {
        foreach ($command in (Get-Command $commandName -All -ErrorAction SilentlyContinue)) {
            if (-not $command.Source) { continue }
            if ($command.Source -like '*\WindowsApps\python*.exe') { continue }
            $result = Try-Candidate -Executable $command.Source
            if ($result) { return $result }
        }
    }

    # 3. Perfis de usuário conhecidos. Isto é importante quando o Setup está
    #    elevado e o Python foi instalado somente para o usuário normal.
    $profilePaths = New-Object System.Collections.Generic.List[string]
    foreach ($candidateProfile in @($env:USERPROFILE, [Environment]::GetFolderPath('UserProfile'))) {
        if ($candidateProfile -and -not $profilePaths.Contains($candidateProfile)) { $profilePaths.Add($candidateProfile) }
    }
    try {
        $profileList = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList'
        foreach ($profileKey in (Get-ChildItem -LiteralPath $profileList -ErrorAction SilentlyContinue)) {
            try {
                $profilePath = (Get-ItemProperty -LiteralPath $profileKey.PSPath -Name ProfileImagePath -ErrorAction Stop).ProfileImagePath
                if ($profilePath) {
                    $profilePath = [Environment]::ExpandEnvironmentVariables([string]$profilePath)
                    if ((Test-Path -LiteralPath $profilePath -PathType Container) -and -not $profilePaths.Contains($profilePath)) {
                        $profilePaths.Add($profilePath)
                    }
                }
            } catch { }
        }
    } catch { }

    foreach ($profilePath in $profilePaths) {
        $patterns = @(
            (Join-Path $profilePath 'AppData\Local\Programs\Python\Python*\python.exe'),
            (Join-Path $profilePath 'AppData\Local\Python\pythoncore-*-64\python.exe'),
            (Join-Path $profilePath 'AppData\Local\Python\pythoncore-*\python.exe')
        )
        foreach ($pattern in $patterns) {
            foreach ($candidate in (Get-ChildItem -Path $pattern -File -ErrorAction SilentlyContinue | Sort-Object FullName -Descending)) {
                $result = Try-Candidate -Executable $candidate.FullName
                if ($result) { return $result }
            }
        }
    }

    # 4. Registro PEP 514: máquina, usuário atual e todos os hives de usuários
    #    carregados. O valor padrão de InstallPath aponta para a pasta do runtime.
    $registryBases = New-Object System.Collections.Generic.List[string]
    foreach ($baseKey in @(
        'HKLM:\SOFTWARE\Python\PythonCore',
        'HKCU:\SOFTWARE\Python\PythonCore',
        'HKLM:\SOFTWARE\WOW6432Node\Python\PythonCore'
    )) { $registryBases.Add($baseKey) }

    try {
        foreach ($userHive in (Get-ChildItem 'Registry::HKEY_USERS' -ErrorAction SilentlyContinue)) {
            $sid = Split-Path -Leaf $userHive.Name
            if ($sid -match '^S-1-5-21-' -and $sid -notmatch '_Classes$') {
                $registryBases.Add("Registry::HKEY_USERS\$sid\Software\Python\PythonCore")
            }
        }
    } catch { }

    foreach ($baseKey in ($registryBases | Select-Object -Unique)) {
        if (-not (Test-Path -LiteralPath $baseKey)) { continue }
        foreach ($versionKey in (Get-ChildItem -LiteralPath $baseKey -ErrorAction SilentlyContinue)) {
            $installPathKey = Join-Path $versionKey.PSPath 'InstallPath'
            if (-not (Test-Path -LiteralPath $installPathKey)) { continue }
            try {
                $key = Get-Item -LiteralPath $installPathKey -ErrorAction Stop
                $executablePath = [string]$key.GetValue('ExecutablePath', '')
                $installPath = [string]$key.GetValue('', '')
                foreach ($candidate in @(
                    $executablePath,
                    $(if ($installPath) { Join-Path $installPath 'python.exe' } else { $null })
                )) {
                    if (-not $candidate) { continue }
                    $result = Try-Candidate -Executable $candidate
                    if ($result) { return $result }
                }
            } catch { }
        }
    }

    # 5. Python Launcher / Python Install Manager. Não usamos python.exe de
    #    WindowsApps, mas py.exe/pymanager.exe podem listar o runtime real.
    $managerExecutables = New-Object System.Collections.Generic.List[string]
    foreach ($managerName in @('py.exe','pymanager.exe')) {
        foreach ($command in (Get-Command $managerName -All -ErrorAction SilentlyContinue)) {
            if ($command.Source -and -not $managerExecutables.Contains($command.Source)) { $managerExecutables.Add($command.Source) }
        }
    }
    foreach ($profilePath in $profilePaths) {
        foreach ($candidate in @(
            (Join-Path $profilePath 'AppData\Local\Microsoft\WindowsApps\py.exe'),
            (Join-Path $profilePath 'AppData\Local\Microsoft\WindowsApps\pymanager.exe')
        )) {
            if ((Test-Path -LiteralPath $candidate -PathType Leaf) -and -not $managerExecutables.Contains($candidate)) {
                $managerExecutables.Add($candidate)
            }
        }
    }

    foreach ($managerExe in $managerExecutables) {
        try {
            $listed = & $managerExe list --format=exe 2>$null
            foreach ($line in $listed) {
                $candidate = ([string]$line).Trim().Trim('"')
                if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
                    $result = Try-Candidate -Executable $candidate
                    if ($result) { return $result }
                }
            }
        } catch { }

        if ([IO.Path]::GetFileName($managerExe) -ieq 'py.exe') {
            $result = Try-Candidate -Executable $managerExe -PrefixArguments @('-3')
            if ($result) { return $result }
            try {
                $launcherList = & $managerExe -0p 2>$null
                foreach ($line in $launcherList) {
                    $match = [regex]::Match([string]$line, '([A-Za-z]:\\.*?python(?:\.exe)?)\s*$')
                    if ($match.Success) {
                        $result = Try-Candidate -Executable $match.Groups[1].Value
                        if ($result) { return $result }
                    }
                }
            } catch { }
        } elseif ([IO.Path]::GetFileName($managerExe) -ieq 'pymanager.exe') {
            $result = Try-Candidate -Executable $managerExe -PrefixArguments @('exec')
            if ($result) { return $result }
        }
    }

    # 6. Instalações globais tradicionais.
    foreach ($pattern in @(
        'C:\Program Files\Python*\python.exe',
        'C:\Program Files\Python*\*\python.exe',
        'C:\Python*\python.exe'
    )) {
        foreach ($candidate in (Get-ChildItem -Path $pattern -File -ErrorAction SilentlyContinue | Sort-Object FullName -Descending)) {
            $result = Try-Candidate -Executable $candidate.FullName
            if ($result) { return $result }
        }
    }


    # 7. Varredura recursiva restrita às pastas de Python. É um fallback para
    #    instalações que usam uma estrutura diferente da esperada, sem varrer o
    #    disco inteiro nem executar atalhos/documentação.
    foreach ($profilePath in $profilePaths) {
        foreach ($pythonRoot in @(
            (Join-Path $profilePath 'AppData\Local\Programs\Python'),
            (Join-Path $profilePath 'AppData\Local\Python')
        )) {
            if (-not (Test-Path -LiteralPath $pythonRoot -PathType Container)) { continue }
            foreach ($candidate in (Get-ChildItem -LiteralPath $pythonRoot -Filter 'python*.exe' -File -Recurse -ErrorAction SilentlyContinue | Sort-Object FullName -Descending)) {
                if ($candidate.Name -match '^pythonw') { continue }
                $result = Try-Candidate -Executable $candidate.FullName
                if ($result) { return $result }
            }
        }
    }

    foreach ($pythonRoot in @('C:\Program Files\Python', 'C:\Program Files')) {
        if (-not (Test-Path -LiteralPath $pythonRoot -PathType Container)) { continue }
        $searchRoot = $pythonRoot
        if ($pythonRoot -eq 'C:\Program Files') {
            foreach ($dir in (Get-ChildItem -LiteralPath $pythonRoot -Directory -Filter 'Python*' -ErrorAction SilentlyContinue)) {
                foreach ($candidate in (Get-ChildItem -LiteralPath $dir.FullName -Filter 'python*.exe' -File -Recurse -ErrorAction SilentlyContinue | Sort-Object FullName -Descending)) {
                    if ($candidate.Name -match '^pythonw') { continue }
                    $result = Try-Candidate -Executable $candidate.FullName
                    if ($result) { return $result }
                }
            }
        } else {
            foreach ($candidate in (Get-ChildItem -LiteralPath $searchRoot -Filter 'python*.exe' -File -Recurse -ErrorAction SilentlyContinue | Sort-Object FullName -Descending)) {
                if ($candidate.Name -match '^pythonw') { continue }
                $result = Try-Candidate -Executable $candidate.FullName
                if ($result) { return $result }
            }
        }
    }

    # 8. Atalhos do Menu Iniciar como último recurso. Só aceitamos atalhos cujo
    #    ALVO seja realmente python*.exe. Isso evita abrir Python Manuals/Module Docs.
    try {
        $shell = New-Object -ComObject WScript.Shell
        foreach ($profilePath in $profilePaths) {
            $shortcutRoot = Join-Path $profilePath 'AppData\Roaming\Microsoft\Windows\Start Menu\Programs'
            if (-not (Test-Path -LiteralPath $shortcutRoot -PathType Container)) { continue }
            foreach ($shortcutFile in (Get-ChildItem -LiteralPath $shortcutRoot -Filter '*.lnk' -File -Recurse -ErrorAction SilentlyContinue | Where-Object { $_.FullName -match '\\Python(?:\s|\\|$)' })) {
                try {
                    $shortcut = $shell.CreateShortcut($shortcutFile.FullName)
                    $target = [string]$shortcut.TargetPath
                    $leaf = [IO.Path]::GetFileName($target)
                    if ($target -and $leaf -match '^python(?:3(?:\.\d+)?)?(?:w)?\.exe$' -and (Test-Path -LiteralPath $target -PathType Leaf)) {
                        $result = Try-Candidate -Executable $target
                        if ($result) { return $result }
                    }
                } catch { }
            }
        }
    } catch { }

    if ($fallback.Path) {
        return [pscustomobject]@{
            Path = $fallback.Path
            Version = $null
            Bits = $null
            Validated = $false
        }
    }

    return $null
}

function Confirm-PythonInstall {
    if ($NonInteractive) { return $false }

    $message = @"
Nenhuma instalação compatível do Python foi localizada pelo NexoFlow.

O NexoFlow Analytics requer Python 3.11 ou superior, 64 bits.

Este pacote já inclui o instalador do Python 3.14.8 x64. Deseja abri-lo agora?

Se o Python 3.14.8 já estiver instalado, o próprio instalador poderá oferecer opções de manutenção/reparo. Enquanto você conclui a instalação ou o reparo, o NexoFlow verificará o interpretador em segundo plano e continuará assim que ele estiver disponível.

O NexoFlow NÃO instalará Python 3.12 e NÃO usará WinGet.
"@
    try {
        Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop
        $result = [System.Windows.Forms.MessageBox]::Show(
            $message,
            "$AppName - Python necessário",
            'YesNo',
            'Question'
        )
        return ($result -eq [System.Windows.Forms.DialogResult]::Yes)
    } catch {
        Write-Host $message
        $answer = Read-Host 'Deseja abrir o instalador do Python 3.14.8 x64 agora? (S/N)'
        return ($answer -match '^[Ss]')
    }
}

function Install-PythonIfNeeded {
    $python = Get-CompatiblePython
    if ($python) {
        if ($python.Validated -eq $false) {
            Write-Host ("[OK] Executavel Python localizado: {0}" -f $python.Path) -ForegroundColor Green
            Write-Host '[INFO] A validacao final de versao e arquitetura sera feita pelo preparar ambiente.' -ForegroundColor DarkYellow
        } else {
            Write-Host ("[OK] Python {0} x{1} encontrado: {2}" -f $python.Version, $python.Bits, $python.Path) -ForegroundColor Green
        }
        return $python.Path
    }

    if (-not (Confirm-PythonInstall)) {
        throw 'O Python 3.11 ou superior, 64 bits, é necessário para executar o NexoFlow Analytics. A instalação foi cancelada pelo usuário.'
    }

    if (-not (Test-Path -LiteralPath $BundledPythonInstaller -PathType Leaf)) {
        throw "O instalador incluído do Python 3.14.8 não foi encontrado em: $BundledPythonInstaller"
    }

    $actualHash = Get-Sha256File -Path $BundledPythonInstaller
    if ($actualHash -ne $BundledPythonSha256) {
        throw 'Falha de integridade no instalador incluído do Python 3.14.8.'
    }

    Write-Step 'Abrindo Python 3.14.8 x64 incluído no pacote'
    Write-Host '[INFO] Conclua a instalação ou o reparo do Python na janela que será aberta.' -ForegroundColor Yellow
    Write-Host '[INFO] O NexoFlow verificará o Python em segundo plano e continuará assim que ele estiver disponível.' -ForegroundColor Yellow

    # IMPORTANTE: não usamos Start-Process -Wait. O instalador oficial do Python
    # é um bootstrapper e pode manter/substituir processos auxiliares depois que a
    # janela principal fecha. Em alguns PCs isso faz o PowerShell aguardar para
    # sempre. Aqui o NexoFlow acompanha a instalação pela disponibilidade real do
    # interpretador, não pelo ciclo de vida do bootstrapper.
    $process = Start-Process -FilePath $BundledPythonInstaller -PassThru
    $deadline = (Get-Date).AddMinutes(20)
    $lastStatus = Get-Date
    $parentExitObservedAt = $null
    $pythonInstallerExitCode = $null

    while ((Get-Date) -lt $deadline) {
        # Recarrega o PATH porque o instalador pode alterá-lo durante a execução.
        try {
            $machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
            $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
            $env:Path = "$machinePath;$userPath"
        } catch { }

        $python = Get-CompatiblePython
        if ($python) {
            if ($python.Validated -eq $false) {
                Write-Host ("[OK] Executavel Python localizado: {0}" -f $python.Path) -ForegroundColor Green
                Write-Host '[INFO] A validacao final de versao e arquitetura sera feita pelo preparar ambiente.' -ForegroundColor DarkYellow
            } else {
                Write-Host ("[OK] Python {0} x{1} localizado e validado: {2}" -f $python.Version, $python.Bits, $python.Path) -ForegroundColor Green
            }
            return $python.Path
        }

        # O processo inicial pode terminar antes dos processos filhos. Portanto,
        # a saída do bootstrapper é apenas um sinal; ainda damos tempo para o
        # runtime aparecer e ser validado.
        if (-not $parentExitObservedAt) {
            try {
                $process.Refresh()
                if ($process.HasExited) {
                    $parentExitObservedAt = Get-Date
                    try { $pythonInstallerExitCode = $process.ExitCode } catch { }
                }
            } catch { }
        }

        if ($parentExitObservedAt -and ((Get-Date) - $parentExitObservedAt).TotalSeconds -ge 90) {
            break
        }

        if (((Get-Date) - $lastStatus).TotalSeconds -ge 15) {
            Write-Host '[INFO] Aguardando o Python 3.14.8 ficar disponível...' -ForegroundColor DarkYellow
            $lastStatus = Get-Date
        }

        Start-Sleep -Seconds 2
    }

    # Última varredura antes de reportar erro.
    $python = Get-CompatiblePython
    if ($python) {
        if ($python.Validated -eq $false) {
            Write-Host ("[OK] Executavel Python localizado: {0}" -f $python.Path) -ForegroundColor Green
            Write-Host '[INFO] A validacao final de versao e arquitetura sera feita pelo preparar ambiente.' -ForegroundColor DarkYellow
        } else {
            Write-Host ("[OK] Python {0} x{1} localizado e validado: {2}" -f $python.Version, $python.Bits, $python.Path) -ForegroundColor Green
        }
        return $python.Path
    }

    if ($null -ne $pythonInstallerExitCode -and $pythonInstallerExitCode -notin @(0, 1641, 3010)) {
        throw "O instalador do Python foi encerrado com o código $pythonInstallerExitCode e nenhum Python compatível foi localizado."
    }

    throw @"
O instalador do Python foi concluído, mas o NexoFlow ainda não conseguiu validar o interpretador.

O Setup procurou no PATH, Registro do Windows, Python Launcher, pastas padrão e nos atalhos oficiais do Menu Iniciar.

Abra o atalho "Python 3.14.8" uma vez para confirmar que o interpretador inicia normalmente e execute o NexoFlow Setup novamente.
"@

}

function Confirm-Update {
    if ($NonInteractive) { return $true }

    try {
        Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop
        $result = [System.Windows.Forms.MessageBox]::Show(
            "Uma instalacao do $AppName ja existe.`n`nDeseja atualizar/reinstalar mantendo configuracoes, credenciais e logs?",
            "$AppName - Atualizacao", 'OKCancel', 'Question')
        return ($result -eq [System.Windows.Forms.DialogResult]::OK)
    } catch {
        $answer = Read-Host 'Instalacao existente encontrada. Atualizar/reinstalar? (S/N)'
        return ($answer -match '^[Ss]')
    }
}

function Validate-Payload {
    if (-not (Test-Path -LiteralPath $PayloadDir -PathType Container)) { throw "Pasta payload nao encontrada em: $PayloadDir" }
    if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) { throw "Manifesto de integridade nao encontrado: $ManifestPath" }

    $script:OptionalUninstallerValidated = $true
    $optionalRelative = 'NexoFlow Uninstall.exe'
    $manifest = Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $count = 0

    foreach ($entry in $manifest.files) {
        $relative = [string]$entry.path
        if ($relative -eq 'payload manifest.json') { continue }

        $file = Join-Path $PayloadDir $relative
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
            if ($relative -eq $optionalRelative) {
                $script:OptionalUninstallerValidated = $false
                Write-Warning "$optionalRelative foi removido ou bloqueado antes da instalacao. Como ele e opcional, o Setup continuara normalmente."
                continue
            }
            throw "Arquivo ausente no pacote: $relative"
        }

        try {
            $hash = Get-Sha256File -Path $file
        } catch {
            if ($relative -eq $optionalRelative) {
                $script:OptionalUninstallerValidated = $false
                Write-Warning "Nao foi possivel validar $optionalRelative. O componente sera ignorado e o Setup continuara."
                continue
            }
            throw
        }

        if ($hash -ne ([string]$entry.sha256).ToLowerInvariant()) {
            if ($relative -eq $optionalRelative) {
                $script:OptionalUninstallerValidated = $false
                Write-Warning "$optionalRelative divergiu do manifesto. Por seguranca ele nao sera instalado, mas o Setup continuara."
                continue
            }
            throw "Falha de integridade no arquivo: $relative"
        }

        $count++
    }

    Write-Host "[OK] Integridade dos componentes obrigatorios validada ($count arquivos)." -ForegroundColor Green
}

function Ensure-InstalledPayloadFile([string]$RelativePath) {
    $source = Join-Path $PayloadDir $RelativePath
    $target = Join-Path $InstallDir $RelativePath

    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "Arquivo obrigatório ausente no payload: $RelativePath"
    }

    $needsRestore = -not (Test-Path -LiteralPath $target -PathType Leaf)
    if (-not $needsRestore) {
        try {
            $sourceHash = Get-Sha256File -Path $source
            $targetHash = Get-Sha256File -Path $target
            $needsRestore = ($sourceHash -ne $targetHash)
        } catch {
            $needsRestore = $true
        }
    }

    if ($needsRestore) {
        Write-Warning "$RelativePath não foi encontrado ou divergiu após a cópia. Restaurando a partir do payload validado."
        $parent = Split-Path -Parent $target
        if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
        Copy-Item -LiteralPath $source -Destination $target -Force
        Start-Sleep -Milliseconds 250
    }

    if (-not (Test-Path -LiteralPath $target -PathType Leaf)) {
        throw "$RelativePath não permaneceu em $InstallDir após a instalação. Verifique antivírus/EDR e tente novamente."
    }

    $sourceHash = Get-Sha256File -Path $source
    $targetHash = Get-Sha256File -Path $target
    if ($sourceHash -ne $targetHash) {
        throw "Falha de integridade no arquivo instalado: $RelativePath"
    }

    Write-Host "[OK] $RelativePath validado no destino." -ForegroundColor Green
}

function Install-OptionalUninstaller {
    $relative = 'NexoFlow Uninstall.exe'

    if (-not $script:OptionalUninstallerValidated) {
        Write-Warning "$relative nao sera instalado porque nao passou pela validacao opcional do pacote. A desinstalacao por script permanece funcional."
        return
    }
    $source = Join-Path $PayloadDir $relative
    $target = Join-Path $InstallDir $relative

    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        Write-Warning "$relative não está disponível no pacote. A instalação continuará; a desinstalação por script permanece funcional."
        return
    }

    try {
        Copy-Item -LiteralPath $source -Destination $target -Force -ErrorAction Stop
        Start-Sleep -Milliseconds 350
    } catch {
        Write-Warning "Não foi possível copiar $relative. Um antivírus/EDR pode ter bloqueado o arquivo. A instalação continuará normalmente."
        return
    }

    if (-not (Test-Path -LiteralPath $target -PathType Leaf)) {
        Write-Warning "$relative foi copiado, mas não permaneceu no destino. Um antivírus/EDR pode tê-lo removido. A instalação continuará normalmente."
        return
    }

    try {
        $sourceHash = Get-Sha256File -Path $source
        $targetHash = Get-Sha256File -Path $target
        if ($sourceHash -ne $targetHash) {
            Write-Warning "$relative está presente, mas diverge do pacote. Ele será tratado como indisponível; a instalação continuará normalmente."
            return
        }
    } catch {
        Write-Warning "Não foi possível verificar a integridade de $relative. A instalação continuará normalmente."
        return
    }

    Write-Host "[OK] $relative disponível no destino (componente opcional)." -ForegroundColor Green
}

function Backup-PrivateData([string]$Source, [string]$Backup) {
    if (-not (Test-Path -LiteralPath $Source -PathType Container)) { return }
    New-Item -ItemType Directory -Force -Path $Backup | Out-Null
    $secret = Join-Path $Source 'secrets_config.py'
    if (Test-Path -LiteralPath $secret -PathType Leaf) { Copy-Item -LiteralPath $secret -Destination (Join-Path $Backup 'secrets_config.py') -Force }
    foreach ($dirName in @('credentials','logs')) {
        $srcDir = Join-Path $Source $dirName
        if (Test-Path -LiteralPath $srcDir -PathType Container) { Copy-Item -LiteralPath $srcDir -Destination (Join-Path $Backup $dirName) -Recurse -Force }
    }
}

function Restore-PrivateData([string]$Backup, [string]$Target) {
    if (-not (Test-Path -LiteralPath $Backup -PathType Container)) { return }
    $secret = Join-Path $Backup 'secrets_config.py'
    if (Test-Path -LiteralPath $secret -PathType Leaf) { Copy-Item -LiteralPath $secret -Destination (Join-Path $Target 'secrets_config.py') -Force }
    foreach ($dirName in @('credentials','logs')) {
        $srcDir = Join-Path $Backup $dirName
        if (Test-Path -LiteralPath $srcDir -PathType Container) {
            $dstDir = Join-Path $Target $dirName
            if (Test-Path -LiteralPath $dstDir) { Remove-Item -LiteralPath $dstDir -Recurse -Force }
            Copy-Item -LiteralPath $srcDir -Destination $dstDir -Recurse -Force
        }
    }
}

function Stop-InstalledNexoFlowProcesses {
    if (-not (Test-Path -LiteralPath $InstallDir -PathType Container)) { return }

    $prefix = ([IO.Path]::GetFullPath($InstallDir)).TrimEnd('\\') + '\\'
    $targets = @()
    foreach ($process in (Get-Process -ErrorAction SilentlyContinue)) {
        try {
            $path = [string]$process.Path
            if ($path -and $path.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
                $targets += $process
            }
        } catch { }
    }

    if (-not $targets) { return }

    Write-Host '[INFO] Fechando processos da instalacao anterior antes da atualizacao:' -ForegroundColor DarkYellow
    $taskkill = Join-Path $env:SystemRoot 'System32\taskkill.exe'
    foreach ($process in ($targets | Sort-Object Id -Unique)) {
        try {
            Write-Host ("  - {0} (PID {1})" -f $process.ProcessName, $process.Id) -ForegroundColor DarkYellow
            if (Test-Path -LiteralPath $taskkill -PathType Leaf) {
                & $taskkill /PID $process.Id /T /F 2>$null | Out-Null
            } else {
                Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
            }
        } catch { }
    }
    Start-Sleep -Milliseconds 700
}

function Remove-DirectoryWithRetry {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [int]$Attempts = 20
    )

    if (-not (Test-Path -LiteralPath $Path)) { return $true }

    $lastError = $null
    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        try {
            Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
            return $true
        } catch {
            $lastError = $_.Exception.Message
            Start-Sleep -Milliseconds 500
        }
    }

    Write-Warning "Nao foi possivel remover completamente: $Path. Detalhe: $lastError"
    return $false
}

function Stage-ExistingInstall {
    if (-not (Test-Path -LiteralPath $InstallDir -PathType Container)) { return $null }

    $rollback = "$InstallDir.__rollback__.$([guid]::NewGuid().ToString('N'))"
    $lastError = $null

    for ($attempt = 1; $attempt -le 20; $attempt++) {
        try {
            Move-Item -LiteralPath $InstallDir -Destination $rollback -Force -ErrorAction Stop
            Write-Host "[OK] Instalacao anterior preservada para rollback seguro." -ForegroundColor Green
            return $rollback
        } catch {
            $lastError = $_.Exception.Message
            Start-Sleep -Milliseconds 500
        }
    }

    throw "Nao foi possivel preparar a atualizacao segura de $InstallDir. A instalacao anterior foi mantida intacta. Feche terminais/Explorer nessa pasta e tente novamente. Detalhe: $lastError"
}

function Restore-PreviousInstall {
    param([string]$RollbackPath)

    if (-not $RollbackPath -or -not (Test-Path -LiteralPath $RollbackPath -PathType Container)) {
        return $false
    }

    Stop-InstalledNexoFlowProcesses

    if (Test-Path -LiteralPath $InstallDir) {
        if (-not (Remove-DirectoryWithRetry -Path $InstallDir -Attempts 20)) {
            return $false
        }
    }

    try {
        Move-Item -LiteralPath $RollbackPath -Destination $InstallDir -Force -ErrorAction Stop
        Write-Host "[OK] Instalacao anterior restaurada automaticamente." -ForegroundColor Green
        return $true
    } catch {
        Write-Warning "Falha ao restaurar automaticamente a instalacao anterior: $($_.Exception.Message)"
        return $false
    }
}

function Refresh-NexoFlowIconCache([string[]]$Executables) {
    # O Explorer pode manter ícones antigos mesmo após substituir/renomear EXEs.
    # Atualiza os timestamps dos executáveis e notifica o Shell para nova leitura dos recursos PE.
    foreach ($exePath in $Executables) {
        try {
            if ($exePath -and (Test-Path -LiteralPath $exePath -PathType Leaf)) {
                (Get-Item -LiteralPath $exePath).LastWriteTime = Get-Date
            }
        } catch {
            Write-Warning "Nao foi possivel atualizar o timestamp de ${exePath}: $($_.Exception.Message)"
        }
    }

    try {
        $source = @'
using System;
using System.Runtime.InteropServices;
public static class NexoFlowShellIconRefresh {
    [DllImport("shell32.dll")]
    public static extern void SHChangeNotify(uint wEventId, uint uFlags, IntPtr dwItem1, IntPtr dwItem2);
}
'@
        if (-not ('NexoFlowShellIconRefresh' -as [type])) {
            Add-Type -TypeDefinition $source -ErrorAction Stop
        }
        # SHCNE_ASSOCCHANGED = 0x08000000; SHCNF_IDLIST = 0
        [NexoFlowShellIconRefresh]::SHChangeNotify(0x08000000, 0, [IntPtr]::Zero, [IntPtr]::Zero)
    } catch {
        Write-Warning "Nao foi possivel notificar o Explorer sobre os novos icones: $($_.Exception.Message)"
    }

    $ie4uinit = Join-Path $env:SystemRoot 'System32\ie4uinit.exe'
    if (Test-Path -LiteralPath $ie4uinit -PathType Leaf) {
        try { & $ie4uinit -ClearIconCache | Out-Null } catch { }
        try { & $ie4uinit -show | Out-Null } catch { }
    }
}

function Create-Shortcut([string]$ShortcutPath,[string]$TargetPath,[string]$WorkingDirectory,[string]$Description,[string]$IconPath) {
    $parent = Split-Path -Parent $ShortcutPath
    if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($ShortcutPath)
    $shortcut.TargetPath = $TargetPath
    $shortcut.WorkingDirectory = $WorkingDirectory
    $shortcut.Description = $Description
    if (Test-Path -LiteralPath $IconPath) { $shortcut.IconLocation = "$IconPath,0" }
    $shortcut.Save()
}

function Register-Uninstaller {
    New-Item -Path $UninstallKey -Force | Out-Null
    New-ItemProperty -Path $UninstallKey -Name 'DisplayName' -Value $AppName -PropertyType String -Force | Out-Null
    New-ItemProperty -Path $UninstallKey -Name 'DisplayVersion' -Value $AppVersion -PropertyType String -Force | Out-Null
    New-ItemProperty -Path $UninstallKey -Name 'Publisher' -Value $Publisher -PropertyType String -Force | Out-Null
    New-ItemProperty -Path $UninstallKey -Name 'InstallLocation' -Value $InstallDir -PropertyType String -Force | Out-Null
    New-ItemProperty -Path $UninstallKey -Name 'DisplayIcon' -Value (Join-Path $InstallDir 'assets\NexoFlow.ico') -PropertyType String -Force | Out-Null
    $uninstallScript = Join-Path $InstallDir 'installer\uninstall.ps1'
    $powershellExe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    if (-not (Test-Path -LiteralPath $powershellExe -PathType Leaf)) { $powershellExe = 'powershell.exe' }
    # Registro padrão do Windows: chama o script local auditável. O próprio script solicita elevação via UAC.
    $uninstallCommand = '"' + $powershellExe + '" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "' + $uninstallScript + '"'
    New-ItemProperty -Path $UninstallKey -Name 'UninstallString' -Value $uninstallCommand -PropertyType String -Force | Out-Null
    New-ItemProperty -Path $UninstallKey -Name 'NoModify' -Value 1 -PropertyType DWord -Force | Out-Null
    New-ItemProperty -Path $UninstallKey -Name 'NoRepair' -Value 1 -PropertyType DWord -Force | Out-Null
    New-Item -Path $AppKey -Force | Out-Null
    New-ItemProperty -Path $AppKey -Name 'InstallPath' -Value $InstallDir -PropertyType String -Force | Out-Null
    New-ItemProperty -Path $AppKey -Name 'Version' -Value $AppVersion -PropertyType String -Force | Out-Null
}

function Remove-LegacyBrand {
    $desktop = [Environment]::GetFolderPath('CommonDesktopDirectory')
    $userDesktop = [Environment]::GetFolderPath('Desktop')
    foreach ($shortcut in @(
        (Join-Path $desktop 'Weni WhatsApp Analytics.lnk'),
        (Join-Path $desktop 'Weni WhatsApp Analytics - Sincronizar.lnk'),
        (Join-Path $userDesktop 'Weni WhatsApp Analytics.lnk'),
        (Join-Path $userDesktop 'Weni WhatsApp Analytics - Sincronizar.lnk')
    )) { if (Test-Path -LiteralPath $shortcut) { Remove-Item -LiteralPath $shortcut -Force -ErrorAction SilentlyContinue } }
    $oldMenu = Join-Path $env:ProgramData 'Microsoft\Windows\Start Menu\Programs\Weni WhatsApp Analytics'
    if (Test-Path -LiteralPath $oldMenu) { Remove-Item -LiteralPath $oldMenu -Recurse -Force -ErrorAction SilentlyContinue }
    Remove-Item -LiteralPath $LegacyUninstallKey -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $LegacyAppKey -Recurse -Force -ErrorAction SilentlyContinue
    # A pasta antiga só é removida depois que o NexoFlow terminou de instalar com sucesso.
    if (Test-Path -LiteralPath $LegacyInstallDir) { Remove-Item -LiteralPath $LegacyInstallDir -Recurse -Force -ErrorAction SilentlyContinue }
    if (Test-Path -LiteralPath $LegacyDataDir) { Remove-Item -LiteralPath $LegacyDataDir -Recurse -Force -ErrorAction SilentlyContinue }
}

$backupDir = $null
try {
    Write-Host '==========================================================' -ForegroundColor DarkCyan
    Write-Host ' NexoFlow - Instalador' -ForegroundColor Cyan
    Write-Host '==========================================================' -ForegroundColor DarkCyan
    Ensure-Administrator

    Write-Step 'Validando integridade do pacote'
    Validate-Payload

    Write-Step 'Verificando requisito Python'
    $pythonExe = Install-PythonIfNeeded
    $pythonDir = Split-Path -Parent $pythonExe
    $pythonScripts = Join-Path $pythonDir 'Scripts'
    $env:Path = "$pythonDir;$pythonScripts;$env:Path"
    if (Test-Path -LiteralPath $InstallDir -PathType Container) {
        if (-not (Confirm-Update)) { Write-Host '[INFO] Instalacao cancelada pelo usuario.'; try { Stop-Transcript | Out-Null } catch { }; exit 2 }
        Write-Step 'Fechando processos da instalacao anterior'
        Stop-InstalledNexoFlowProcesses
    }

    $backupDir = Join-Path $env:TEMP ('NexoFlow Setup ' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Force -Path $backupDir | Out-Null

    Write-Step 'Preservando configuracoes, credenciais e logs existentes'
    Backup-PrivateData -Source $LegacyDataDir -Backup (Join-Path $backupDir 'legacy preserved')
    Backup-PrivateData -Source $LegacyInstallDir -Backup (Join-Path $backupDir 'legacy installed')
    Backup-PrivateData -Source $DataDir -Backup (Join-Path $backupDir 'preserved')
    Backup-PrivateData -Source $InstallDir -Backup (Join-Path $backupDir 'installed')

    Write-Step "Instalando arquivos em $InstallDir"
    $script:RollbackInstallDir = Stage-ExistingInstall
    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    # O launcher NexoFlow Uninstall.exe é opcional e pode ser bloqueado por EDR/antivírus.
    # Ele é copiado separadamente em modo tolerante para nunca reprovar o Setup.
    Get-ChildItem -LiteralPath $PayloadDir -Force | Where-Object { $_.Name -notin @('payload manifest.json','NexoFlow Uninstall.exe') } | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $InstallDir -Recurse -Force
    }

    # Ordem: legado primeiro; dados de uma instalação NexoFlow existente prevalecem.
    Restore-PrivateData -Backup (Join-Path $backupDir 'legacy preserved') -Target $InstallDir
    Restore-PrivateData -Backup (Join-Path $backupDir 'legacy installed') -Target $InstallDir
    Restore-PrivateData -Backup (Join-Path $backupDir 'preserved') -Target $InstallDir
    Restore-PrivateData -Backup (Join-Path $backupDir 'installed') -Target $InstallDir

    Write-Step 'Preparando ambiente Python e dependencias'
    $oldInstaller = $env:NEXOFLOW_INSTALLER
    $oldPythonExe = $env:NEXOFLOW_PYTHON_EXE
    $env:NEXOFLOW_INSTALLER = '1'
    $env:NEXOFLOW_PYTHON_EXE = $pythonExe
    Push-Location $InstallDir
    try { & (Join-Path $InstallDir 'instalar.bat'); $installRc = $LASTEXITCODE }
    finally {
        Pop-Location
        if ($null -eq $oldInstaller) { Remove-Item Env:NEXOFLOW_INSTALLER -ErrorAction SilentlyContinue } else { $env:NEXOFLOW_INSTALLER = $oldInstaller }
        if ($null -eq $oldPythonExe) { Remove-Item Env:NEXOFLOW_PYTHON_EXE -ErrorAction SilentlyContinue } else { $env:NEXOFLOW_PYTHON_EXE = $oldPythonExe }
    }
    if ($installRc -ne 0) { throw "A preparacao do ambiente Python falhou (codigo $installRc). Os arquivos e dados privados foram preservados." }

    Write-Step 'Validando componentes instalados'
    foreach ($requiredFile in @('NexoFlow Analytics.exe','NexoFlow Weni.exe','NexoFlow Terminal.exe','installer\uninstall.ps1','desinstalar_nexoflow.cmd')) {
        Ensure-InstalledPayloadFile -RelativePath $requiredFile
    }

    Write-Step 'Verificando launcher opcional de desinstalação'
    Install-OptionalUninstaller

    Write-Step 'Criando atalhos do NexoFlow na Area de Trabalho'
    $appExe = Join-Path $InstallDir 'NexoFlow Analytics.exe'
    $updateExe = Join-Path $InstallDir 'NexoFlow Weni.exe'
    $appIcon = Join-Path $InstallDir 'assets\NexoFlow.ico'
    $updateIcon = Join-Path $InstallDir 'assets\NexoFlow_Weni.ico'
    $terminalIcon = Join-Path $InstallDir 'assets\NexoFlow_Terminal.ico'
    $uninstallCmd = Join-Path $InstallDir 'desinstalar_nexoflow.cmd'
    $terminalExe = Join-Path $InstallDir 'NexoFlow Terminal.exe'
    $desktop = [Environment]::GetFolderPath('CommonDesktopDirectory')
    $userDesktop = [Environment]::GetFolderPath('Desktop')
    foreach ($old in @(
        (Join-Path $desktop 'NexoFlow.lnk'),
        (Join-Path $userDesktop 'NexoFlow.lnk'),
        (Join-Path $userDesktop 'NexoFlow Analytics.lnk'),
        (Join-Path $desktop 'NexoFlow Weni.lnk'),
        (Join-Path $userDesktop 'NexoFlow Weni.lnk'),
        (Join-Path $desktop 'NexoFlow Terminal.lnk'),
        (Join-Path $userDesktop 'NexoFlow Terminal.lnk'),
        (Join-Path $desktop 'NexoFlow - Update Weni.lnk'),
        (Join-Path $userDesktop 'NexoFlow - Update Weni.lnk'),
        (Join-Path $desktop 'NexoFlow Console.lnk'),
        (Join-Path $userDesktop 'NexoFlow Console.lnk')
    )) {
        if (Test-Path -LiteralPath $old) { Remove-Item -LiteralPath $old -Force -ErrorAction SilentlyContinue }
    }
    if (-not (Test-Path -LiteralPath $updateExe -PathType Leaf)) {
        throw 'NexoFlow Weni.exe não foi encontrado no payload.'
    }
    if (-not (Test-Path -LiteralPath $terminalExe -PathType Leaf)) {
        throw 'NexoFlow Terminal.exe não foi encontrado no payload.'
    }
    $startMenu = Join-Path $env:ProgramData 'Microsoft\Windows\Start Menu\Programs\NexoFlow'
    if (Test-Path -LiteralPath $startMenu) { Remove-Item -LiteralPath $startMenu -Recurse -Force -ErrorAction SilentlyContinue }
    Create-Shortcut -ShortcutPath (Join-Path $desktop 'NexoFlow Analytics.lnk') -TargetPath $appExe -WorkingDirectory $InstallDir -Description 'Valida o ambiente e executa uma sincronizacao incremental do NexoFlow' -IconPath $appIcon
    Create-Shortcut -ShortcutPath (Join-Path $desktop 'NexoFlow Weni.lnk') -TargetPath $updateExe -WorkingDirectory $InstallDir -Description 'Audita e atualiza contatos e campos da Weni' -IconPath $updateIcon
    Create-Shortcut -ShortcutPath (Join-Path $desktop 'NexoFlow Terminal.lnk') -TargetPath $terminalExe -WorkingDirectory $InstallDir -Description 'Terminal NexoFlow com ambiente e proxy preparados para a sessao' -IconPath $terminalIcon
    Create-Shortcut -ShortcutPath (Join-Path $startMenu 'NexoFlow Analytics.lnk') -TargetPath $appExe -WorkingDirectory $InstallDir -Description 'Sincronizacao manual segura do NexoFlow' -IconPath $appIcon
    Create-Shortcut -ShortcutPath (Join-Path $startMenu 'NexoFlow Weni.lnk') -TargetPath $updateExe -WorkingDirectory $InstallDir -Description 'Atualizacao segura de contatos e campos da Weni' -IconPath $updateIcon
    Create-Shortcut -ShortcutPath (Join-Path $startMenu 'NexoFlow Terminal.lnk') -TargetPath $terminalExe -WorkingDirectory $InstallDir -Description 'Terminal NexoFlow com ambiente e proxy preparados para a sessao' -IconPath $terminalIcon
    Create-Shortcut -ShortcutPath (Join-Path $startMenu 'Desinstalar NexoFlow.lnk') -TargetPath $uninstallCmd -WorkingDirectory $InstallDir -Description 'Desinstala o NexoFlow' -IconPath (Join-Path $InstallDir 'assets\uninstaller.ico')
    $documentation = Join-Path $InstallDir 'Documentacao NexoFlow.html'
    if (Test-Path -LiteralPath $documentation -PathType Leaf) {
        Create-Shortcut -ShortcutPath (Join-Path $startMenu 'Documentacao NexoFlow.lnk') -TargetPath $documentation -WorkingDirectory $InstallDir -Description 'Abre a documentação operacional do NexoFlow' -IconPath $appIcon
    }
    Write-Host '[OK] Atalhos "NexoFlow Analytics", "NexoFlow Weni" e "NexoFlow Terminal" criados na Area de Trabalho.' -ForegroundColor Green

    Write-Step 'Atualizando cache de icones do Windows'
    Refresh-NexoFlowIconCache -Executables @($updateExe, $terminalExe)
    Write-Host '[OK] Explorer notificado para reler os icones internos do NexoFlow Weni e NexoFlow Terminal.' -ForegroundColor Green

    Write-Step 'Registrando NexoFlow no Windows'
    Register-Uninstaller
    Remove-LegacyBrand

    if ($script:RollbackInstallDir -and (Test-Path -LiteralPath $script:RollbackInstallDir -PathType Container)) {
        if (-not (Remove-DirectoryWithRetry -Path $script:RollbackInstallDir -Attempts 20)) {
            Write-Warning "A atualizacao foi concluida, mas a copia de rollback antiga permaneceu em: $script:RollbackInstallDir"
        } else {
            $script:RollbackInstallDir = $null
        }
    }

    if (Test-Path -LiteralPath $DataDir) { Remove-Item -LiteralPath $DataDir -Recurse -Force }
    Remove-Item -LiteralPath $backupDir -Recurse -Force -ErrorAction SilentlyContinue

    $hasSecrets = Test-Path -LiteralPath (Join-Path $InstallDir 'secrets_config.py') -PathType Leaf
    $hasGoogle = Test-Path -LiteralPath (Join-Path $InstallDir 'credentials\google_credentials.json') -PathType Leaf
    Write-Host "`n[OK] $AppName instalado com sucesso." -ForegroundColor Green
    if ($hasSecrets -and $hasGoogle) {
        Show-Info "NexoFlow foi instalado/atualizado com sucesso.`n`nOs atalhos NexoFlow Analytics, NexoFlow Weni e NexoFlow Terminal foram criados na Area de Trabalho.`n`nNexoFlow Weni executa check-up, teste de conexoes, dry-run/auditoria obrigatoria e somente depois permite aplicar as alteracoes."
    } else {
        Show-Info "NexoFlow foi instalado.`n`nOs atalhos NexoFlow Analytics, NexoFlow Weni e NexoFlow Terminal foram criados na Area de Trabalho.`n`nAntes da primeira execucao, configure:`n- secrets_config.py`n- credentials\google_credentials.json"
    }
    try { Stop-Transcript | Out-Null } catch { }
    exit 0
}
catch {
    $errorMessage = $_.Exception.Message
    $rollbackRestored = $false

    if ($script:RollbackInstallDir) {
        Write-Host "`n[INFO] A instalacao falhou. Tentando restaurar automaticamente a versao anterior..." -ForegroundColor DarkYellow
        $rollbackRestored = Restore-PreviousInstall -RollbackPath $script:RollbackInstallDir
        if ($rollbackRestored) {
            $script:RollbackInstallDir = $null
        }
    }

    if (-not $rollbackRestored -and $backupDir -and (Test-Path -LiteralPath $backupDir -PathType Container)) {
        try {
            New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
            foreach ($name in @('legacy preserved','legacy installed','preserved','installed')) {
                Restore-PrivateData -Backup (Join-Path $backupDir $name) -Target $DataDir
            }
        } catch { }
    }

    Write-Host "`n[ERRO] $errorMessage" -ForegroundColor Red
    if ($rollbackRestored) {
        Write-Host "[OK] A instalacao anterior foi restaurada; o NexoFlow nao ficou parcialmente atualizado." -ForegroundColor Green
    }
    Write-Host "[INFO] Log do Setup: $SetupLogPath" -ForegroundColor DarkYellow

    $rollbackMessage = if ($rollbackRestored) {
        "`n`nA instalacao anterior foi restaurada automaticamente."
    } else {
        "`n`nDados privados existentes foram preservados sempre que possivel."
    }
    Show-Info "A instalacao nao foi concluida.`n`n$errorMessage`n`nLog: $SetupLogPath$rollbackMessage" "$AppName - Erro"
    try { Stop-Transcript | Out-Null } catch { }
    exit 1
}
