[CmdletBinding()]
param(
    [switch]$NonInteractive,
    [ValidateSet('Preserve', 'Clean', 'Cancel')][string]$InstallMode = 'Preserve'
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$AppName = 'NexoFlow'
$AppVersion = '1.5.2'
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
$script:RollbackUsesExistingRoot = $false

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
        throw 'O modo não interativo precisa ser executado com privilégios de administrador.'
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
        throw "A instalação precisa de permissão de administrador. Operação cancelada ou negada pelo Windows. $($_.Exception.Message)"
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

function Get-Sha256File {
    param(
        [string]$Path,
        [ValidateRange(0, 60)][double]$RetryTimeoutSeconds = 30,
        [ValidateRange(1, 1000)][int]$RetryDelayMilliseconds = 500
    )

    # Uma leitura síncrona retida por um filtro do Windows não permite conferir
    # o relógio. O worker mantém todo I/O fora do controle do prazo e do console.
    if (-not ('NexoFlowHashJob' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Security.Cryptography;
using System.Threading;
public sealed class NexoFlowHashJob {
    private readonly ManualResetEventSlim completed = new ManualResetEventSlim(false);
    private volatile bool cancelled;
    private volatile bool sharingBlocked;
    public string Hash { get; private set; }
    public Exception Error { get; private set; }
    public bool SharingBlocked { get { return sharingBlocked; } }
    public bool Wait(int milliseconds) { return completed.Wait(milliseconds); }
    public void Cancel() { cancelled = true; }
    public static NexoFlowHashJob Start(string path, int delay) {
        NexoFlowHashJob job = new NexoFlowHashJob();
        Thread worker = new Thread(delegate() { job.Run(path, delay); });
        worker.IsBackground = true;
        worker.Start();
        return job;
    }
    private void Run(string path, int delay) {
        try {
            while (!cancelled) {
                try {
                    // Aceita handles que permitem leitura. Não escreve nem
                    // desbloqueia arquivos; o manifesto continua obrigatório.
                    using (FileStream stream = File.Open(path, FileMode.Open,
                        FileAccess.Read, FileShare.ReadWrite | FileShare.Delete)) {
                        long length = stream.Length;
                        DateTime stamp = File.GetLastWriteTimeUtc(path);
                        using (SHA256 sha = SHA256.Create()) {
                            byte[] buffer = new byte[65536];
                            int read;
                            while ((read = stream.Read(buffer, 0, buffer.Length)) > 0) {
                                if (cancelled) return;
                                sha.TransformBlock(buffer, 0, read, buffer, 0);
                            }
                            if (cancelled) return;
                            sha.TransformFinalBlock(buffer, 0, 0);
                            if (stream.Length != length || File.GetLastWriteTimeUtc(path) != stamp)
                                throw new IOException("O arquivo mudou durante a validação de integridade: " + path);
                            Hash = BitConverter.ToString(sha.Hash).Replace("-", "").ToLowerInvariant();
                        }
                    }
                    return;
                } catch (IOException failure) {
                    int code = failure.HResult & 0xffff;
                    if (code != 32 && code != 33) throw;
                    sharingBlocked = true;
                    Thread.Sleep(delay);
                }
            }
        } catch (Exception failure) {
            Error = failure;
        } finally { completed.Set(); }
    }
}
'@
    }

    $job = [NexoFlowHashJob]::Start($Path, $RetryDelayMilliseconds)
    $watch = [Diagnostics.Stopwatch]::StartNew()
    $waitingReported = $false
    $lastReport = 0.0
    try {
        while ($true) {
            $remainingMs = ($RetryTimeoutSeconds - $watch.Elapsed.TotalSeconds) * 1000
            $waitMs = [int][Math]::Max(0, [Math]::Min(200, [Math]::Ceiling($remainingMs)))
            if ($job.Wait($waitMs)) {
                if ($job.Error) { throw $job.Error }
                if ($job.Hash -notmatch '^[a-f0-9]{64}$') { throw "Leitura de integridade incompleta: $Path" }
                return $job.Hash
            }
            if ($watch.Elapsed.TotalSeconds -ge $RetryTimeoutSeconds) {
                if ($job.SharingBlocked) { $reason = 'o arquivo continua em uso' }
                else { $reason = 'a leitura do arquivo não respondeu' }
                throw [TimeoutException]::new("Não foi possível verificar a integridade de '$Path': $reason no prazo de $RetryTimeoutSeconds segundo(s). Aguarde a liberação do arquivo pelo Windows e tente novamente. A instalação não pode continuar sem validar esse componente.")
            }
            if ($job.SharingBlocked -and -not $waitingReported) {
                Write-Host "[AVISO] Arquivo em uso; aguardando liberação para validar a integridade: $Path (até $RetryTimeoutSeconds s)." -ForegroundColor Yellow
                $waitingReported = $true
            }
            if (($watch.Elapsed.TotalSeconds - $lastReport) -ge 5) {
                $elapsed = [int]$watch.Elapsed.TotalSeconds
                $remaining = [int][Math]::Ceiling($RetryTimeoutSeconds - $watch.Elapsed.TotalSeconds)
                Write-Host "[INFO] Validando integridade: $Path | espera: $elapsed s | prazo restante: $remaining s."
                $lastReport = $watch.Elapsed.TotalSeconds
            }
        }
    } finally { $job.Cancel() }
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
    # Fallback de segurança: se um python.exe real existir mas o probe do
    # PowerShell falhar por alguma particularidade do ambiente, o caminho ainda
    # pode ser entregue ao instalar.bat, que faz uma segunda validação direta.
    $fallback = [pscustomobject]@{ Path = $null }

    function Try-Candidate([string]$Executable, [string[]]$PrefixArguments = @()) {
        if (-not $Executable) { return $null }
        try { $Executable = [Environment]::ExpandEnvironmentVariables($Executable).Trim().Trim('"') } catch { }
        $key = ($Executable + '|' + ($PrefixArguments -join ' ')).ToLowerInvariant()
        if ($seen.ContainsKey($key)) { return $null }
        $seen[$key] = $true

        # Guarda o primeiro python.exe real como fallback. Launchers (py.exe) e
        # aliases de WindowsApps não entram aqui.
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

    # 1. Atalhos oficiais do Python no Menu Iniciar. O instalador clássico
    #    cria o atalho "Python X.Y.Z"; resolver o TargetPath obtém o python.exe
    #    real mesmo quando ele não foi adicionado ao PATH.
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

    # 2. PATH atual. Aliases de WindowsApps são ignorados porque podem abrir a
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
            Write-Host ("[OK] Executável Python localizado: {0}" -f $python.Path) -ForegroundColor Green
            Write-Host '[INFO] A validação final de versão e arquitetura será feita pelo preparar ambiente.' -ForegroundColor DarkYellow
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
                Write-Host ("[OK] Executável Python localizado: {0}" -f $python.Path) -ForegroundColor Green
                Write-Host '[INFO] A validação final de versão e arquitetura será feita pelo preparar ambiente.' -ForegroundColor DarkYellow
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
            Write-Host ("[OK] Executável Python localizado: {0}" -f $python.Path) -ForegroundColor Green
            Write-Host '[INFO] A validação final de versão e arquitetura será feita pelo preparar ambiente.' -ForegroundColor DarkYellow
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

function Show-InstallModeDialog {
    Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop
    $form = New-Object System.Windows.Forms.Form
    try {
        $form.Name = 'NexoFlowInstallMode'
        $form.Text = 'NexoFlow — Instalação'
        $form.ClientSize = New-Object System.Drawing.Size(660, 285)
        $form.StartPosition = 'CenterScreen'
        $form.FormBorderStyle = 'FixedDialog'
        $form.MaximizeBox = $false
        $form.MinimizeBox = $false
        $form.AutoScaleMode = 'Font'
        $form.Font = [Drawing.SystemFonts]::MessageBoxFont

        $label = New-Object System.Windows.Forms.Label
        $label.Location = New-Object System.Drawing.Point(20, 20)
        $label.Size = New-Object System.Drawing.Size(620, 185)
        $label.Text = "Já existem arquivos do NexoFlow neste computador.`n`nAtualizar mantendo dados: mantém configurações, credenciais, logs e estado local.`n`nInstalação limpa: reinicia esses dados para FarmaLíder e Pets Líder. Será necessário configurar os acessos novamente.`n`nOs arquivos de importacoes são preservados nas duas opções."
        $form.Controls.Add($label)

        foreach ($choice in @(
            @{ Name = 'Preserve'; Text = 'Atualizar mantendo dados'; X = 20; Width = 260; Result = [Windows.Forms.DialogResult]::Yes },
            @{ Name = 'Clean'; Text = 'Instalação limpa'; X = 295; Width = 200; Result = [Windows.Forms.DialogResult]::No },
            @{ Name = 'Cancel'; Text = 'Cancelar'; X = 510; Width = 130; Result = [Windows.Forms.DialogResult]::Cancel }
        )) {
            $button = New-Object System.Windows.Forms.Button
            $button.Name = $choice.Name
            $button.Text = $choice.Text
            $button.Location = New-Object System.Drawing.Point($choice.X, 230)
            $button.Size = New-Object System.Drawing.Size($choice.Width, 35)
            $button.DialogResult = $choice.Result
            $form.Controls.Add($button)
            if ($choice.Name -eq 'Preserve') { $form.AcceptButton = $button }
            if ($choice.Name -eq 'Cancel') { $form.CancelButton = $button }
        }
        switch ($form.ShowDialog()) {
            ([Windows.Forms.DialogResult]::Yes) { return 'Preserve' }
            ([Windows.Forms.DialogResult]::No) { return 'Clean' }
            default { return 'Cancel' }
        }
    } finally { $form.Dispose() }
}

function Read-InstallModeFromConsole {
    while ($true) {
        Write-Host '[1] Atualizar mantendo configurações, credenciais, logs e estado local'
        Write-Host '[2] Instalação limpa — reiniciar esses dados nos dois segmentos'
        Write-Host '[0] Cancelar'
        Write-Host 'Os arquivos de importacoes serão preservados.'
        switch ((Read-Host 'Escolha uma opção')) {
            '1' { return 'Preserve' }
            '2' { return 'Clean' }
            '0' { return 'Cancel' }
            '' { return 'Cancel' }
            default { Write-Host '[AVISO] Opção inválida. Tente novamente.' }
        }
    }
}

function Select-InstallMode {
    if ($NonInteractive) { return $InstallMode }
    try { return Show-InstallModeDialog }
    catch { return Read-InstallModeFromConsole }
}

function Validate-Payload {
    if (-not (Test-Path -LiteralPath $PayloadDir -PathType Container)) { throw "Pasta payload não encontrada em: $PayloadDir" }
    if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) { throw "Manifesto de integridade não encontrado: $ManifestPath" }

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
                Write-Warning "$optionalRelative foi removido ou bloqueado antes da instalação. Como ele é opcional, o Setup continuará normalmente."
                continue
            }
            throw "Arquivo ausente no pacote: $relative"
        }

        try {
            $hash = Get-Sha256File -Path $file
        } catch {
            if ($relative -eq $optionalRelative) {
                $script:OptionalUninstallerValidated = $false
                Write-Warning "Não foi possível validar $optionalRelative. O componente será ignorado e o Setup continuará."
                continue
            }
            throw
        }

        if ($hash -ne ([string]$entry.sha256).ToLowerInvariant()) {
            if ($relative -eq $optionalRelative) {
                $script:OptionalUninstallerValidated = $false
                Write-Warning "$optionalRelative divergiu do manifesto. Por segurança ele não será instalado, mas o Setup continuará."
                continue
            }
            throw "Falha de integridade no arquivo: $relative"
        }

        $count++
    }

    Write-Host "[OK] Integridade dos componentes obrigatórios validada ($count arquivos)." -ForegroundColor Green
}

function Validate-InstalledPayload {
    # A origem pode ter sido alterada após o primeiro hash. Confere a cópia
    # final com o manifesto antes de executar BAT/Python ou restaurar dados.
    $manifest = Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($entry in $manifest.files) {
        $relative = [string]$entry.path
        if ($relative -in @('payload manifest.json', 'NexoFlow Uninstall.exe')) { continue }
        $target = Join-Path $InstallDir $relative
        if (-not (Test-Path -LiteralPath $target -PathType Leaf)) {
            throw "Arquivo obrigatório ausente após a cópia: $relative"
        }
        if ((Get-Sha256File -Path $target) -cne ([string]$entry.sha256).ToLowerInvariant()) {
            throw "Falha de integridade no arquivo instalado: $relative"
        }
    }
    Write-Host '[OK] Cópia instalada validada antes da execução.' -ForegroundColor Green
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
        Write-Warning "$relative não será instalado porque não passou pela validação opcional do pacote. A desinstalação por script permanece funcional."
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


function Backup-PrivateData([string]$Source, [string]$Backup) {
    if (-not (Test-Path -LiteralPath $Source -PathType Container)) { return }
    New-Item -ItemType Directory -Force -Path $Backup | Out-Null
    $secret = Join-Path $Source 'secrets_config.py'
    if (Test-Path -LiteralPath $secret -PathType Leaf) { Copy-Item -LiteralPath $secret -Destination (Join-Path $Backup 'secrets_config.py') -Force }
    foreach ($dirName in @('credentials','logs','importacoes')) {
        $srcDir = Join-Path $Source $dirName
        if (Test-Path -LiteralPath $srcDir -PathType Container) { Copy-Item -LiteralPath $srcDir -Destination (Join-Path $Backup $dirName) -Recurse -Force }
    }
}

function Restore-PrivateData([string]$Backup, [string]$Target) {
    if (-not (Test-Path -LiteralPath $Backup -PathType Container)) { return }
    $secret = Join-Path $Backup 'secrets_config.py'
    if (Test-Path -LiteralPath $secret -PathType Leaf) { Copy-Item -LiteralPath $secret -Destination (Join-Path $Target 'secrets_config.py') -Force }
    foreach ($dirName in @('credentials','logs','importacoes')) {
        $srcDir = Join-Path $Backup $dirName
        if (Test-Path -LiteralPath $srcDir -PathType Container) {
            $dstDir = Join-Path $Target $dirName
            if ($dirName -eq 'importacoes') {
                Copy-ImportDirectory -Source $srcDir -Target $dstDir
                continue
            }
            if (Test-Path -LiteralPath $dstDir) { Remove-Item -LiteralPath $dstDir -Recurse -Force }
            Copy-Item -LiteralPath $srcDir -Destination $dstDir -Recurse -Force
        }
    }
}

function Restore-SetupData {
    param(
        [string]$BackupRoot,
        [string]$Target,
        [ValidateSet('Preserve', 'Clean')][string]$Mode
    )
    foreach ($name in @('legacy preserved', 'legacy installed', 'preserved', 'installed')) {
        $backup = Join-Path $BackupRoot $name
        if ($Mode -eq 'Preserve') {
            Restore-PrivateData -Backup $backup -Target $Target
        } else {
            # Exports do usuário são documentos, não configuração ou estado da aplicação.
            $imports = Join-Path $backup 'importacoes'
            if (Test-Path -LiteralPath $imports -PathType Container) {
                Copy-ImportDirectory -Source $imports -Target (Join-Path $Target 'importacoes')
            }
        }
    }
}

function Get-SetupNetworkSettingsDirectory([string]$BackupRoot) {
    foreach ($name in @('installed', 'preserved', 'legacy installed', 'legacy preserved')) {
        $directory = Join-Path $BackupRoot $name
        if (Test-Path -LiteralPath (Join-Path $directory 'secrets_config.py') -PathType Leaf) {
            return $directory
        }
    }
    return $null
}

function Test-InstalledProcessPath([string]$Path) {
    if (-not $Path) { return $false }
    try {
        $prefix = ([IO.Path]::GetFullPath($InstallDir)).TrimEnd('\') + '\'
        return ([IO.Path]::GetFullPath($Path)).StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)
    } catch { return $false }
}

function Stop-InstalledNexoFlowProcesses {
    if (-not (Test-Path -LiteralPath $InstallDir -PathType Container)) { return }

    $targets = @()
    foreach ($process in (Get-Process -ErrorAction SilentlyContinue)) {
        try {
            $path = [string]$process.Path
            if (Test-InstalledProcessPath $path) {
                $targets += $process
            }
        } catch { }
    }

    if (-not $targets) { return }

    Write-Host '[INFO] Fechando processos da instalação anterior antes da atualização:' -ForegroundColor DarkYellow
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

    Write-Warning "Não foi possível remover completamente: $Path. Detalhe: $lastError"
    return $false
}

function Move-InstallEntry([string]$Source, [string]$Destination) {
    # Origem e rollback são irmãos no mesmo volume: não copiar/remover parcialmente.
    $entry = Get-Item -LiteralPath $Source -Force -ErrorAction Stop
    if ($entry.PSIsContainer) {
        [IO.Directory]::Move($Source, $Destination)
    } else {
        [IO.File]::Move($Source, $Destination)
    }
}

function Stage-ExistingInstall {
    if (-not (Test-Path -LiteralPath $InstallDir -PathType Container)) { return $null }

    $rollback = "$InstallDir.__rollback__.$([guid]::NewGuid().ToString('N'))"
    $lastError = $null
    $script:RollbackUsesExistingRoot = $false

    for ($attempt = 1; $attempt -le 3; $attempt++) {
        try {
            [IO.Directory]::Move($InstallDir, $rollback)
            Write-Host "[OK] Instalação anterior preservada para rollback seguro." -ForegroundColor Green
            return $rollback
        } catch {
            $lastError = $_.Exception.Message
            Start-Sleep -Milliseconds 300
        }
    }

    # Um terminal/Explorer pode manter um handle na raiz, sem bloquear os arquivos.
    # Preservar a raiz evita exigir sua renomeação, mantendo rollback completo.
    Write-Host '[INFO] A pasta principal não pode ser renomeada. Preparando atualização sem movê-la.' -ForegroundColor DarkYellow
    $moved = New-Object 'System.Collections.Generic.List[string]'
    $probe = Join-Path $InstallDir ('.nexoflow-write-probe-' + [guid]::NewGuid().ToString('N'))
    try {
        $rootEntry = Get-Item -LiteralPath $InstallDir -Force -ErrorAction Stop
        if ($rootEntry.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw 'A pasta da instalação é um link/junção e não pode ser atualizada por este modo.'
        }
        [IO.File]::WriteAllText($probe, '')
        [IO.File]::Delete($probe)
        New-Item -ItemType Directory -Path $rollback -ErrorAction Stop | Out-Null
        foreach ($entry in (Get-ChildItem -LiteralPath $InstallDir -Force | Sort-Object Name)) {
            Move-InstallEntry -Source $entry.FullName -Destination (Join-Path $rollback $entry.Name)
            $moved.Add($entry.Name)
        }
        $script:RollbackUsesExistingRoot = $true
        Write-Host '[OK] Conteúdo anterior preservado para rollback; pasta principal mantida.' -ForegroundColor Green
        return $rollback
    } catch {
        $lastError = $_.Exception.Message
        $restored = $true
        for ($index = $moved.Count - 1; $index -ge 0; $index--) {
            $name = $moved[$index]
            try {
                Move-InstallEntry -Source (Join-Path $rollback $name) -Destination (Join-Path $InstallDir $name)
            } catch { $restored = $false }
        }
        if ($restored) {
            if (Test-Path -LiteralPath $rollback) { [IO.Directory]::Delete($rollback) }
            throw "Não foi possível preparar a atualização segura de $InstallDir. Os arquivos anteriores foram preservados. Feche as rotinas do NexoFlow e tente novamente. Se persistir, verifique o acesso à pasta com o suporte de TI. Detalhe: $lastError"
        }
        throw "A atualização não foi iniciada. Alguns arquivos anteriores permanecem preservados em $rollback; mantenha essa pasta para recuperação. Detalhe: $lastError"
    } finally {
        if (Test-Path -LiteralPath $probe) { Remove-Item -LiteralPath $probe -Force -ErrorAction SilentlyContinue }
    }
}

function Restore-PreviousInstall {
    param([string]$RollbackPath)

    if (-not $RollbackPath -or -not (Test-Path -LiteralPath $RollbackPath -PathType Container)) {
        return $false
    }

    Stop-InstalledNexoFlowProcesses

    if ($script:RollbackUsesExistingRoot) {
        try {
            New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
            foreach ($entry in (Get-ChildItem -LiteralPath $InstallDir -Force)) {
                if (-not (Remove-DirectoryWithRetry -Path $entry.FullName -Attempts 3)) { return $false }
            }
            foreach ($entry in (Get-ChildItem -LiteralPath $RollbackPath -Force)) {
                Move-InstallEntry -Source $entry.FullName -Destination (Join-Path $InstallDir $entry.Name)
            }
            [IO.Directory]::Delete($RollbackPath)
            $script:RollbackUsesExistingRoot = $false
            Write-Host '[OK] Instalação anterior restaurada; pasta principal mantida.' -ForegroundColor Green
            return $true
        } catch {
            Write-Warning "Não foi possível concluir o rollback. Preserve $RollbackPath para recuperação. Detalhe: $($_.Exception.Message)"
            return $false
        }
    }

    if (Test-Path -LiteralPath $InstallDir) {
        if (-not (Remove-DirectoryWithRetry -Path $InstallDir -Attempts 20)) {
            return $false
        }
    }

    try {
        Move-Item -LiteralPath $RollbackPath -Destination $InstallDir -Force -ErrorAction Stop
        Write-Host "[OK] Instalação anterior restaurada automaticamente." -ForegroundColor Green
        return $true
    } catch {
        Write-Warning "Falha ao restaurar automaticamente a instalação anterior: $($_.Exception.Message)"
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
            Write-Warning "Não foi possível atualizar o timestamp de ${exePath}: $($_.Exception.Message)"
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
        Write-Warning "Não foi possível notificar o Explorer sobre os novos ícones: $($_.Exception.Message)"
    }

    $ie4uinit = Join-Path $env:SystemRoot 'System32\ie4uinit.exe'
    if (Test-Path -LiteralPath $ie4uinit -PathType Leaf) {
        try { & $ie4uinit -ClearIconCache | Out-Null } catch { }
        try { & $ie4uinit -show | Out-Null } catch { }
    }
}

function Create-Shortcut([string]$ShortcutPath,[string]$TargetPath,[string]$WorkingDirectory,[string]$Description,[string]$IconPath,[string]$Arguments = "") {
    $parent = Split-Path -Parent $ShortcutPath
    if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($ShortcutPath)
    $shortcut.TargetPath = $TargetPath
    $shortcut.Arguments = $Arguments
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

    $selectedMode = $InstallMode
    $hasPreviousData = @($InstallDir, $DataDir, $LegacyInstallDir, $LegacyDataDir) | Where-Object { Test-Path -LiteralPath $_ -PathType Container }
    if ($hasPreviousData) { $selectedMode = Select-InstallMode }
    if ($selectedMode -eq 'Cancel') {
        Write-Host '[INFO] Instalação cancelada pelo usuário. Nenhum arquivo instalado foi alterado.'
        try { Stop-Transcript | Out-Null } catch { }
        exit 2
    }
    if ($selectedMode -eq 'Clean') {
        Write-Host '[INFO] Instalação limpa: configurações, credenciais, logs e estado local serão reiniciados; importacoes será preservada.'
    } else {
        Write-Host '[INFO] Atualização mantendo configurações, credenciais, logs e estado local.'
    }

    Write-Step 'Verificando requisito Python'
    $pythonExe = Install-PythonIfNeeded
    $pythonDir = Split-Path -Parent $pythonExe
    $pythonScripts = Join-Path $pythonDir 'Scripts'
    $env:Path = "$pythonDir;$pythonScripts;$env:Path"
    if (Test-Path -LiteralPath $InstallDir -PathType Container) {
        Write-Step 'Fechando processos da instalação anterior'
        Stop-InstalledNexoFlowProcesses
    }

    $backupDir = Join-Path $env:TEMP ('NexoFlow Setup ' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Force -Path $backupDir | Out-Null

    Write-Step 'Preparando recuperação dos dados existentes em caso de falha'
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

    Write-Step 'Conferindo integridade dos arquivos copiados'
    Validate-InstalledPayload

    Restore-SetupData -BackupRoot $backupDir -Target $InstallDir -Mode $selectedMode
    New-Item -ItemType Directory -Force -Path (Join-Path $InstallDir 'importacoes') | Out-Null

    Write-Step 'Preparando ambiente Python e dependências'
    $oldInstaller = $env:NEXOFLOW_INSTALLER
    $oldPythonExe = $env:NEXOFLOW_PYTHON_EXE
    $oldSetupPythonPath = $env:PYTHONPATH
    $oldSetupNetworkConfig = $env:NEXOFLOW_SETUP_NETWORK_CONFIG
    $oldSetupProfile = $env:NEXOFLOW_PERFIL
    $env:NEXOFLOW_PERFIL = 'FARMA'
    if ($selectedMode -eq 'Clean') {
        $networkSettings = Get-SetupNetworkSettingsDirectory -BackupRoot $backupDir
        if ($networkSettings) {
            # A configuração permanece no backup privado, fora da instalação limpa.
            $env:PYTHONPATH = "$networkSettings;$oldSetupPythonPath"
            $env:NEXOFLOW_SETUP_NETWORK_CONFIG = '1'
            Write-Host '[INFO] Configuração de rede anterior disponível somente durante a preparação das dependências.'
        }
    }
    $env:NEXOFLOW_INSTALLER = '1'
    $env:NEXOFLOW_PYTHON_EXE = $pythonExe
    Push-Location $InstallDir
    try { & (Join-Path $InstallDir 'instalar.bat'); $installRc = $LASTEXITCODE }
    finally {
        Pop-Location
        if ($null -eq $oldInstaller) { Remove-Item Env:NEXOFLOW_INSTALLER -ErrorAction SilentlyContinue } else { $env:NEXOFLOW_INSTALLER = $oldInstaller }
        if ($null -eq $oldPythonExe) { Remove-Item Env:NEXOFLOW_PYTHON_EXE -ErrorAction SilentlyContinue } else { $env:NEXOFLOW_PYTHON_EXE = $oldPythonExe }
        if ($null -eq $oldSetupPythonPath) { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue } else { $env:PYTHONPATH = $oldSetupPythonPath }
        if ($null -eq $oldSetupNetworkConfig) { Remove-Item Env:NEXOFLOW_SETUP_NETWORK_CONFIG -ErrorAction SilentlyContinue } else { $env:NEXOFLOW_SETUP_NETWORK_CONFIG = $oldSetupNetworkConfig }
        if ($null -eq $oldSetupProfile) { Remove-Item Env:NEXOFLOW_PERFIL -ErrorAction SilentlyContinue } else { $env:NEXOFLOW_PERFIL = $oldSetupProfile }
    }
    if ($installRc -ne 0) { throw "A preparação do ambiente Python falhou (código $installRc). Os arquivos e dados privados foram preservados." }

    Write-Step 'Validando componentes instalados'
    foreach ($requiredFile in @('app/looker_bi.py','app/run_looker.py','NexoFlow Analytics.exe','NexoFlow Weni.exe','NexoFlow Recompra.exe','NexoFlow Terminal.exe','NexoFlow Planilha.exe','comandos/executar_planilha.bat','assets\NexoFlow_Planilha.ico','assets\NexoFlow_Recompra.ico','installer\uninstall.ps1','desinstalar_nexoflow.cmd','scripts\confirmar_revisao_weni.ps1','scripts\resultado_carga_weni.ps1')) {
        Ensure-InstalledPayloadFile -RelativePath $requiredFile
    }

    foreach ($nightFile in @('NexoFlow Noturno.exe', 'app/run_noturno.py', 'assets\NexoFlow_Noturno.ico')) {
        Ensure-InstalledPayloadFile -RelativePath $nightFile
    }

    Write-Step 'Verificando launcher opcional de desinstalação'
    Install-OptionalUninstaller

    Write-Step 'Criando atalhos do NexoFlow na Área de Trabalho'
    $nightExe = Join-Path $InstallDir 'NexoFlow Noturno.exe'
    $nightIcon = Join-Path $InstallDir 'assets\NexoFlow_Noturno.ico'
    $appExe = Join-Path $InstallDir 'NexoFlow Analytics.exe'
    $updateExe = Join-Path $InstallDir 'NexoFlow Weni.exe'
    $recompraExe = Join-Path $InstallDir 'NexoFlow Recompra.exe'
    $appIcon = Join-Path $InstallDir 'assets\NexoFlow.ico'
    $updateIcon = Join-Path $InstallDir 'assets\NexoFlow_Weni.ico'
    $recompraIcon = Join-Path $InstallDir 'assets\NexoFlow_Recompra.ico'
    $terminalIcon = Join-Path $InstallDir 'assets\NexoFlow_Terminal.ico'
    $uninstallCmd = Join-Path $InstallDir 'desinstalar_nexoflow.cmd'
    $terminalExe = Join-Path $InstallDir 'NexoFlow Terminal.exe'
    $planilhaExe = Join-Path $InstallDir 'NexoFlow Planilha.exe'
    $planilhaIcon = Join-Path $InstallDir 'assets\NexoFlow_Planilha.ico'
    $desktop = [Environment]::GetFolderPath('CommonDesktopDirectory')
    $userDesktop = [Environment]::GetFolderPath('Desktop')
    foreach ($old in @(
        (Join-Path $desktop 'NexoFlow Noturno.lnk'),
        (Join-Path $userDesktop 'NexoFlow Noturno.lnk'),
        (Join-Path $desktop 'NexoFlow.lnk'),
        (Join-Path $userDesktop 'NexoFlow.lnk'),
        (Join-Path $userDesktop 'NexoFlow Analytics.lnk'),
        (Join-Path $desktop 'NexoFlow Weni.lnk'),
        (Join-Path $userDesktop 'NexoFlow Weni.lnk'),
        (Join-Path $desktop 'NexoFlow Recompra.lnk'),
        (Join-Path $userDesktop 'NexoFlow Recompra.lnk'),
        (Join-Path $desktop 'NexoFlow Planilha.lnk'),
        (Join-Path $userDesktop 'NexoFlow Planilha.lnk'),
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
    Create-Shortcut -ShortcutPath (Join-Path $desktop 'NexoFlow Noturno.lnk') -TargetPath $nightExe -WorkingDirectory $InstallDir -Description 'Weni, Analytics e Recompra automáticos, sem confirmação humana' -IconPath $nightIcon
    Create-Shortcut -ShortcutPath (Join-Path $desktop 'NexoFlow Analytics.lnk') -TargetPath $appExe -WorkingDirectory $InstallDir -Description 'Valida o ambiente e executa uma sincronização incremental do NexoFlow' -IconPath $appIcon
    Create-Shortcut -ShortcutPath (Join-Path $desktop 'NexoFlow Weni.lnk') -TargetPath $updateExe -WorkingDirectory $InstallDir -Description 'Audita e atualiza contatos e campos da Weni' -IconPath $updateIcon
    Create-Shortcut -ShortcutPath (Join-Path $desktop 'NexoFlow Recompra.lnk') -TargetPath $recompraExe -WorkingDirectory $InstallDir -Description 'Recompra FarmaLíder D+25 e Pets Líder D+30 com revisão' -IconPath $recompraIcon
    Create-Shortcut -ShortcutPath (Join-Path $desktop 'NexoFlow Planilha.lnk') -TargetPath $planilhaExe -WorkingDirectory $InstallDir -Description 'Cargas por planilhas para Weni e Analytics, com revisão humana' -IconPath $planilhaIcon
    Create-Shortcut -ShortcutPath (Join-Path $desktop 'NexoFlow Terminal.lnk') -TargetPath $terminalExe -WorkingDirectory $InstallDir -Description 'Terminal NexoFlow com ambiente e proxy preparados para a sessao' -IconPath $terminalIcon
    Create-Shortcut -ShortcutPath (Join-Path $startMenu 'NexoFlow Noturno.lnk') -TargetPath $nightExe -WorkingDirectory $InstallDir -Description 'Weni, Analytics e Recompra automáticos, sem confirmação humana' -IconPath $nightIcon
    Create-Shortcut -ShortcutPath (Join-Path $startMenu 'NexoFlow Analytics.lnk') -TargetPath $appExe -WorkingDirectory $InstallDir -Description 'Sincronização manual segura do NexoFlow' -IconPath $appIcon
    Create-Shortcut -ShortcutPath (Join-Path $startMenu 'NexoFlow Weni.lnk') -TargetPath $updateExe -WorkingDirectory $InstallDir -Description 'Atualização segura de contatos e campos da Weni' -IconPath $updateIcon
    Create-Shortcut -ShortcutPath (Join-Path $startMenu 'NexoFlow Recompra.lnk') -TargetPath $recompraExe -WorkingDirectory $InstallDir -Description 'Recompra FarmaLíder D+25 e Pets Líder D+30 com revisão' -IconPath $recompraIcon
    Create-Shortcut -ShortcutPath (Join-Path $startMenu 'NexoFlow Planilha.lnk') -TargetPath $planilhaExe -WorkingDirectory $InstallDir -Description 'Cargas por planilhas para Weni e Analytics, com revisão humana' -IconPath $planilhaIcon
    Create-Shortcut -ShortcutPath (Join-Path $startMenu 'NexoFlow Terminal.lnk') -TargetPath $terminalExe -WorkingDirectory $InstallDir -Description 'Terminal NexoFlow com ambiente e proxy preparados para a sessao' -IconPath $terminalIcon
    New-Item -ItemType Directory -Force -Path (Join-Path $InstallDir 'logs/PET'),(Join-Path $InstallDir 'importacoes/PET') | Out-Null
    Create-Shortcut -ShortcutPath (Join-Path $startMenu 'Desinstalar NexoFlow.lnk') -TargetPath $uninstallCmd -WorkingDirectory $InstallDir -Description 'Desinstala o NexoFlow' -IconPath (Join-Path $InstallDir 'assets\uninstaller.ico')
    $documentation = Join-Path $InstallDir 'docs/Documentacao NexoFlow.html'
    if (Test-Path -LiteralPath $documentation -PathType Leaf) {
        Create-Shortcut -ShortcutPath (Join-Path $startMenu 'Documentacao NexoFlow.lnk') -TargetPath $documentation -WorkingDirectory $InstallDir -Description 'Abre a documentação operacional do NexoFlow' -IconPath $appIcon
    }
    Write-Host '[OK] Atalhos "NexoFlow Analytics", "NexoFlow Weni", "NexoFlow Terminal" e "NexoFlow Planilha" criados na Área de Trabalho.' -ForegroundColor Green

    Write-Step 'Atualizando cache de ícones do Windows'
    $uninstallExe = Join-Path $InstallDir 'NexoFlow Uninstall.exe'
    Refresh-NexoFlowIconCache -Executables @($appExe, $updateExe, $recompraExe, $terminalExe, $planilhaExe, $uninstallExe, $nightExe)
    Write-Host '[OK] Explorer notificado para reler os ícones internos dos executáveis do NexoFlow.' -ForegroundColor Green

    Write-Step 'Registrando NexoFlow no Windows'
    Register-Uninstaller
    Remove-LegacyBrand

    if ($script:RollbackInstallDir -and (Test-Path -LiteralPath $script:RollbackInstallDir -PathType Container)) {
        if (-not (Remove-DirectoryWithRetry -Path $script:RollbackInstallDir -Attempts 20)) {
            Write-Warning "A atualização foi concluída, mas a copia de rollback antiga permaneceu em: $script:RollbackInstallDir"
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
        Show-Info "NexoFlow foi instalado/atualizado com sucesso.`n`nOs atalhos NexoFlow Analytics, NexoFlow Weni, NexoFlow Terminal, NexoFlow Planilha e NexoFlow Noturno foram criados na Área de Trabalho.`n`nNexoFlow Weni executa check-up, teste de conexões, dry-run/auditoria obrigatória e somente depois permite aplicar as alterações."
    } else {
        Show-Info "NexoFlow foi instalado.`n`nOs atalhos NexoFlow Analytics, NexoFlow Weni, NexoFlow Terminal, NexoFlow Planilha e NexoFlow Noturno foram criados na Área de Trabalho.`n`nAntes da primeira execução, configure:`n- secrets_config.py`n- credentials\google_credentials.json"
    }
    try { Stop-Transcript | Out-Null } catch { }
    exit 0
}
catch {
    $errorMessage = $_.Exception.Message
    $rollbackRestored = $false

    if ($script:RollbackInstallDir) {
        Write-Host "`n[INFO] A instalação falhou. Tentando restaurar automaticamente a versão anterior..." -ForegroundColor DarkYellow
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
        Write-Host "[OK] A instalação anterior foi restaurada; o NexoFlow não ficou parcialmente atualizado." -ForegroundColor Green
    }
    Write-Host "[INFO] Log do Setup: $SetupLogPath" -ForegroundColor DarkYellow

    $rollbackMessage = if ($rollbackRestored) {
        "`n`nA instalação anterior foi restaurada automaticamente."
    } else {
        "`n`nDados privados existentes foram preservados sempre que possível."
    }
    Show-Info "A instalação não foi concluída.`n`n$errorMessage`n`nLog: $SetupLogPath$rollbackMessage" "$AppName - Erro"
    try { Stop-Transcript | Out-Null } catch { }
    exit 1
}
# NexoFlow 1.5.2
