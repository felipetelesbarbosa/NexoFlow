param(
    [Parameter(Mandatory = $true)][string]$SetupZip
)

$ErrorActionPreference = "Stop"
$env:NEXOFLOW_PERFIL = "FARMA"
$ProgressPreference = "SilentlyContinue"

$InstallDir = "C:\NexoFlow"
$UninstallKey = "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\NexoFlow"
$AppKey = "HKLM:\Software\Grupo Lider\NexoFlow"
$TempRoot = Join-Path $env:RUNNER_TEMP ("nexoflow-setup-smoke-" + [guid]::NewGuid().ToString("N"))
$Expanded = Join-Path $TempRoot "expanded"
$SetupDir = Join-Path $Expanded "NexoFlow Setup"

function Assert-True([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}

function Remove-TestArtifacts {
    try {
        Get-Process -ErrorAction SilentlyContinue | Where-Object {
            try {
                $_.Path -and ([IO.Path]::GetFullPath($_.Path)).StartsWith(
                    ([IO.Path]::GetFullPath($InstallDir)).TrimEnd("\") + "\",
                    [StringComparison]::OrdinalIgnoreCase
                )
            } catch { $false }
        } | Stop-Process -Force -ErrorAction SilentlyContinue
    } catch { }

    try {
        if (Test-Path -LiteralPath $InstallDir) {
            Remove-Item -LiteralPath $InstallDir -Recurse -Force -ErrorAction SilentlyContinue
        }
        Get-ChildItem -LiteralPath "C:\" -Directory -Filter "NexoFlow.__rollback__.*" -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    } catch { }

    Remove-Item -LiteralPath $UninstallKey -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $AppKey -Recurse -Force -ErrorAction SilentlyContinue

    foreach ($shortcut in @(
        (Join-Path ([Environment]::GetFolderPath("CommonDesktopDirectory")) "NexoFlow Analytics.lnk"),
        (Join-Path ([Environment]::GetFolderPath("CommonDesktopDirectory")) "NexoFlow Weni.lnk"),
        (Join-Path ([Environment]::GetFolderPath("CommonDesktopDirectory")) "NexoFlow Noturno.lnk"),
        (Join-Path ([Environment]::GetFolderPath("CommonDesktopDirectory")) "NexoFlow Recompra.lnk"),
        (Join-Path ([Environment]::GetFolderPath("CommonDesktopDirectory")) "NexoFlow Planilha.lnk"),
        (Join-Path ([Environment]::GetFolderPath("CommonDesktopDirectory")) "NexoFlow Terminal.lnk"),
        (Join-Path $env:ProgramData "Microsoft\Windows\Start Menu\Programs\NexoFlow")
    )) {
        Remove-Item -LiteralPath $shortcut -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Invoke-Setup {
    param([string]$Label, [int]$ExpectedExitCode = 0)

    Write-Host "==> $Label"
    $outputLog = Join-Path $TempRoot "setup-stdout.txt"
    $errorLog = Join-Path $TempRoot "setup-stderr.txt"
    $process = Start-Process -FilePath (Join-Path $SetupDir "NexoFlow Setup.exe") -WorkingDirectory $SetupDir -RedirectStandardOutput $outputLog -RedirectStandardError $errorLog -PassThru
    if (-not $process.WaitForExit(240000)) {
        & taskkill.exe /PID $process.Id /T /F | Out-Null
        foreach ($path in @($outputLog, $errorLog, (Join-Path $env:TEMP "NexoFlow-Setup.log"))) {
            if (Test-Path -LiteralPath $path) { Get-Content -LiteralPath $path -Encoding UTF8 -Tail 100 }
        }
        throw "O teste de instalação excedeu quatro minutos: $Label"
    }

    if ($process.ExitCode -ne $ExpectedExitCode) {
        $log = Join-Path $env:TEMP "NexoFlow-Setup.log"
        if (Test-Path -LiteralPath $log) {
            Write-Host "----- NexoFlow-Setup.log -----"
            Get-Content -LiteralPath $log -Tail 250
            Write-Host "------------------------------"
        }
        throw "$Label falhou com código $($process.ExitCode)."
    }
}

function Assert-Installed {
    param([bool]$ExpectNightExe = $true)
    foreach ($relative in @(
        "app/recompra_profiles.py", "app/recompra_cleanup.py", "app/runtime_profile.py",
        "comandos/limpar_cancelados_recompra.bat", "comandos/atualizar_recompra_pets.bat",
        "app/run_noturno_console.py",
        "comandos/executar_noturno.bat",
        "assets\NexoFlow_Noturno.ico",
        "app\run_noturno.py",
        "NexoFlow Analytics.exe",
        "NexoFlow Weni.exe",
        "NexoFlow Recompra.exe",
        "NexoFlow Terminal.exe",
        "NexoFlow Planilha.exe",
        "comandos/executar_planilha.bat",
        "assets\NexoFlow_Planilha.ico",
        "assets\NexoFlow_Recompra.ico",
        "installer\install.ps1",
        "installer\uninstall.ps1",
        "scripts\confirmar_revisao_weni.ps1",
        "scripts\resultado_carga_weni.ps1",
        "scripts\build_documentation.py",
        "desinstalar_nexoflow.cmd",
        ".venv\Scripts\python.exe"
    )) {
        $path = Join-Path $InstallDir $relative
        Assert-True (Test-Path -LiteralPath $path -PathType Leaf) "Arquivo instalado ausente: $relative"
    }

    Assert-True (Test-Path -LiteralPath (Join-Path $InstallDir "importacoes") -PathType Container) "A pasta importacoes não foi instalada."

    $nightLink = Join-Path ([Environment]::GetFolderPath("CommonDesktopDirectory")) "NexoFlow Noturno.lnk"
    Assert-True (Test-Path -LiteralPath $nightLink) "Atalho Noturno ausente."
    $nightShortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($nightLink)
    $nightTarget = if ($ExpectNightExe) { 'NexoFlow Noturno.exe' } else { 'comandos\executar_noturno.bat' }
    Assert-True ($nightShortcut.TargetPath -eq (Join-Path $InstallDir $nightTarget)) 'Destino do atalho Noturno incorreto.'
    Assert-True ((Test-Path -LiteralPath (Join-Path $InstallDir 'NexoFlow Noturno.exe')) -eq $ExpectNightExe) 'O launcher indisponível não deve ficar na instalação.'

    foreach ($nightShortcutRoot in @([Environment]::GetFolderPath("CommonDesktopDirectory"), (Join-Path $env:ProgramData 'Microsoft\Windows\Start Menu\Programs\NexoFlow'))) {
        $nightIconLink = Join-Path $nightShortcutRoot 'NexoFlow Noturno.lnk'
        $nightIconShortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($nightIconLink)
        Assert-True ($nightIconShortcut.IconLocation.StartsWith((Join-Path $InstallDir "assets\NexoFlow_Noturno.ico"))) "Ícone dedicado do Noturno incorreto: $nightIconLink"
    }

    $recompraLink = Join-Path ([Environment]::GetFolderPath("CommonDesktopDirectory")) "NexoFlow Recompra.lnk"
    Assert-True (Test-Path -LiteralPath $recompraLink) "Atalho Recompra ausente."
    $recompraShortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($recompraLink)
    Assert-True ($recompraShortcut.TargetPath -eq (Join-Path $InstallDir "NexoFlow Recompra.exe")) "Destino do atalho Recompra incorreto."
    Assert-True ($recompraShortcut.IconLocation.StartsWith((Join-Path $InstallDir "assets\NexoFlow_Recompra.ico"))) "Ícone dedicado do atalho Recompra incorreto."
    $shortcutPath = Join-Path ([Environment]::GetFolderPath("CommonDesktopDirectory")) "NexoFlow Planilha.lnk"
    Assert-True (Test-Path -LiteralPath $shortcutPath) "Atalho NexoFlow Planilha ausente."
    $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($shortcutPath)
    Assert-True ($shortcut.TargetPath -eq (Join-Path $InstallDir "NexoFlow Planilha.exe")) "Destino do atalho de planilha incorreto."
    Assert-True ($shortcut.IconLocation.StartsWith((Join-Path $InstallDir "assets\NexoFlow_Planilha.ico"))) "Ícone do atalho de planilha incorreto."

    foreach ($component in @('Recompra', 'Planilha')) {
        $link = Join-Path $env:ProgramData "Microsoft\Windows\Start Menu\Programs\NexoFlow\NexoFlow $component.lnk"
        Assert-True (Test-Path -LiteralPath $link) "Atalho do Menu Iniciar ausente: $component"
        $menuShortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($link)
        Assert-True ($menuShortcut.IconLocation.StartsWith((Join-Path $InstallDir "assets\NexoFlow_$component.ico"))) "Ícone do Menu Iniciar incorreto: $component"
    }

    Assert-True (Test-Path -LiteralPath $UninstallKey) "Registro de desinstalação não foi criado."
    $installedVersion = (Get-Content -Raw -LiteralPath (Join-Path $InstallDir "VERSION")).Trim()
    Assert-True ($installedVersion -eq "1.5.4") "Versão instalada inesperada: $installedVersion"
    $displayVersion = (Get-ItemProperty -LiteralPath $UninstallKey -Name DisplayVersion -ErrorAction Stop).DisplayVersion
    Assert-True ($displayVersion -eq "1.5.4") "DisplayVersion inesperada: $displayVersion"
}

Remove-TestArtifacts
New-Item -ItemType Directory -Force -Path $Expanded | Out-Null

try {
    $resolvedZip = (Resolve-Path -LiteralPath $SetupZip).Path
    Expand-Archive -LiteralPath $resolvedZip -DestinationPath $Expanded -Force

    Assert-True (Test-Path -LiteralPath (Join-Path $SetupDir "NexoFlow Setup.exe") -PathType Leaf) "NexoFlow Setup.exe ausente no ZIP."
    Assert-True (Test-Path -LiteralPath (Join-Path $SetupDir "payload\payload manifest.json") -PathType Leaf) "Manifesto do payload ausente."
    $importsPayload = Join-Path $SetupDir 'payload\importacoes'
    Assert-True (Test-Path -LiteralPath $importsPayload -PathType Container) 'Pasta importacoes ausente no ZIP do Setup.'
    Assert-True (@(Get-ChildItem -LiteralPath $importsPayload -Force -Recurse).Count -eq 0) 'O pacote deve conter importacoes vazia, sem exports.'
    $projectZip = Join-Path (Split-Path -Parent $resolvedZip) 'NexoFlow-1.5.4.zip'
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $projectArchive = [IO.Compression.ZipFile]::OpenRead($projectZip)
    try {
        Assert-True ($null -ne $projectArchive.GetEntry('NexoFlow/importacoes/')) 'Pasta importacoes ausente no projeto completo.'
        Assert-True ($null -ne $projectArchive.GetEntry('NexoFlow/scripts/build_documentation.py')) 'Verificador da documentação ausente no projeto completo.'
        Assert-True (@($projectArchive.Entries | Where-Object { $_.FullName.StartsWith('NexoFlow/importacoes/') -and -not $_.FullName.EndsWith('/') }).Count -eq 0) 'O projeto completo não deve incluir arquivos privados em importacoes.'
    } finally { $projectArchive.Dispose() }


    $python = (Get-Command python.exe -ErrorAction Stop).Source
    $env:NEXOFLOW_SETUP_NONINTERACTIVE = "1"
    $env:NEXOFLOW_PYTHON_EXE = $python

    # Reproduz o bloqueio transitório do payload no Setup real, sem relaxar o hash.
    Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Threading;
public static class NexoFlowPayloadTestLock {
    public static FileStream Hold(string path) {
        FileStream handle = File.Open(path, FileMode.Open, FileAccess.Read, FileShare.None);
        Thread worker = new Thread(delegate() { Thread.Sleep(10000); handle.Dispose(); });
        worker.IsBackground = true;
        worker.Start();
        return handle;
    }
}
'@
    Remove-Item Env:NEXOFLOW_PERFIL -ErrorAction SilentlyContinue
    $payloadLock = [NexoFlowPayloadTestLock]::Hold((Join-Path $SetupDir 'payload\NexoFlow Noturno.exe'))
    try { Invoke-Setup "Primeira instalação com arquivo do payload temporariamente em uso" }
    finally { $payloadLock.Dispose() }
    $firstOutput = [IO.File]::ReadAllText((Join-Path $TempRoot 'setup-stdout.txt'), [Text.Encoding]::UTF8)
    Assert-True ($firstOutput -match 'aguardando .* para validar a integridade') 'O teste nao exercitou a espera pelo arquivo do payload.'
    Assert-True ($firstOutput -notmatch '\[1\] Farma') 'O Setup exibiu indevidamente a selecao de segmento.'
    $env:NEXOFLOW_PERFIL = 'FARMA'
    Assert-Installed

    Write-Host "==> Criando dados privados para testar preservação"
    $secretText = @'
WENI_API_TOKEN = "TOKEN_TESTE_WENI"
GOOGLE_SPREADSHEET_ID = "PLANILHA_TESTE"
FARMALIDER_API_ENABLED = False
FARMALIDER_API_TOKEN = ""
FARMALIDER_USE_HML = False
PROXY_MODE = "off"
PROXY_HOST = ""
PROXY_PORT = 0
PROXY_USER = ""
PROXY_PASSWORD = ""
PROXY_BYPASS = "localhost,127.0.0.1"
PROXY_DETECTION_TIMEOUT = 1.0
'@
    [IO.File]::WriteAllText((Join-Path $InstallDir "secrets_config.py"), $secretText, (New-Object Text.UTF8Encoding($false)))
    New-Item -ItemType Directory -Force -Path (Join-Path $InstallDir "credentials") | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $InstallDir "logs") | Out-Null
    [IO.File]::WriteAllText((Join-Path $InstallDir "credentials\google_credentials.json"), '{"smoke_test":true}', (New-Object Text.UTF8Encoding($false)))
    [IO.File]::WriteAllText((Join-Path $InstallDir "logs\setup-smoke-marker.txt"), "preservar", (New-Object Text.UTF8Encoding($false)))
    [IO.File]::WriteAllText((Join-Path $InstallDir 'importacoes\planilha-teste.txt'), 'export privado sintético', (New-Object Text.UTF8Encoding($false)))

    # Simular sobras da estrutura anterior; a atualização deve substituí-las.
    [IO.File]::WriteAllText((Join-Path $InstallDir 'main.py'), '# código antigo sintético', [Text.Encoding]::UTF8)
    [IO.File]::WriteAllText((Join-Path $InstallDir 'executar_manual.bat'), '@echo off', [Text.Encoding]::ASCII)
    # Mantém a raiz aberta sem FILE_SHARE_DELETE, como um terminal/Explorer.
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
public static class NexoFlowSetupRootLock {
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern SafeFileHandle CreateFile(string name, uint access, uint share,
        IntPtr security, uint creation, uint flags, IntPtr template);
    public static SafeFileHandle Open(string path) {
        SafeFileHandle handle = CreateFile(path, 0x80000000, 3, IntPtr.Zero, 3, 0x02000000, IntPtr.Zero);
        if (handle.IsInvalid) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
        return handle;
    }
}
'@
    $rootLock = [NexoFlowSetupRootLock]::Open($InstallDir)
    $compatibleLock = [IO.File]::Open((Join-Path $SetupDir 'payload\NexoFlow Noturno.exe'), 'Open', 'ReadWrite', 'Read')
    try {
        Invoke-Setup "Atualização com raiz bloqueada e payload aberto com compartilhamento de leitura"
    } finally { $compatibleLock.Dispose(); $rootLock.Dispose() }
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $InstallDir 'main.py'))) 'Módulo antigo permaneceu na raiz.'
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $InstallDir 'executar_manual.bat'))) 'Comando antigo permaneceu na raiz.'
    Assert-True (Test-Path -LiteralPath (Join-Path $InstallDir 'app\main.py')) 'Módulo organizado ausente.'
    Assert-True (Test-Path -LiteralPath (Join-Path $InstallDir 'comandos\executar_manual.bat')) 'Comando organizado ausente.'

    Assert-Installed
    Assert-True ((Get-Content -LiteralPath (Join-Path $InstallDir "logs\setup-smoke-marker.txt") -Raw).Trim() -eq "preservar") "Logs não foram preservados na atualização."
    Assert-True ((Get-Content -LiteralPath (Join-Path $InstallDir "credentials\google_credentials.json") -Raw) -match "smoke_test") "Credenciais não foram preservadas na atualização."
    Assert-True ((Get-Content -LiteralPath (Join-Path $InstallDir "secrets_config.py") -Raw) -match "TOKEN_TESTE_WENI") "secrets_config.py não foi preservado."
    Assert-True ((Get-Content -LiteralPath (Join-Path $InstallDir 'importacoes\planilha-teste.txt') -Raw) -eq 'export privado sintético') 'Importações não foram preservadas na atualização.'

    Write-Host '==> Reproduzindo acesso negado real ao launcher Noturno no payload'
    $nightSource = Join-Path $SetupDir 'payload\NexoFlow Noturno.exe'
    $nightAcl = Get-Acl -LiteralPath $nightSource
    $deniedAcl = Get-Acl -LiteralPath $nightSource
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User
    $denyRead = New-Object Security.AccessControl.FileSystemAccessRule($sid, [Security.AccessControl.FileSystemRights]::ReadData, [Security.AccessControl.AccessControlType]::Deny)
    $deniedAcl.AddAccessRule($denyRead)
    Set-Acl -LiteralPath $nightSource -AclObject $deniedAcl
    try {
        Invoke-Setup 'Atualização com acesso negado ao EXE Noturno e atalho para script validado'
        Assert-Installed -ExpectNightExe $false
        Assert-True ((Get-Content -Raw -LiteralPath (Join-Path $InstallDir 'logs\setup-smoke-marker.txt')).Trim() -eq 'preservar') 'Dados privados foram perdidos na instalação com entrada em script.'
    } finally { Set-Acl -LiteralPath $nightSource -AclObject $nightAcl }

    Write-Host "==> Simulando antivírus/EDR removendo o launcher opcional Uninstall"
    $optionalSource = Join-Path $SetupDir "payload\NexoFlow Uninstall.exe"
    Remove-Item -LiteralPath $optionalSource -Force -ErrorAction SilentlyContinue
    Assert-True (-not (Test-Path -LiteralPath $optionalSource)) "Não foi possível simular a remoção do Uninstall opcional."

    Invoke-Setup "Atualização sem NexoFlow Uninstall.exe no pacote extraido"
    Assert-Installed
    Assert-True ((Get-Content -LiteralPath (Join-Path $InstallDir "logs\setup-smoke-marker.txt") -Raw).Trim() -eq "preservar") "Dados privados foram perdidos sem o launcher opcional."

    $env:NEXOFLOW_SETUP_INSTALL_MODE = 'Cancel'
    Invoke-Setup 'Cancelamento sem alterar a instalação existente' -ExpectedExitCode 2
    Assert-True ((Get-Content -LiteralPath (Join-Path $InstallDir 'secrets_config.py') -Raw) -match 'TOKEN_TESTE_WENI') 'Cancelar alterou a configuração.'
    Assert-True ((Get-Content -LiteralPath (Join-Path $InstallDir 'logs\setup-smoke-marker.txt') -Raw).Trim() -eq 'preservar') 'Cancelar alterou os logs.'

    # Falha sintética após preparar a instalação limpa: o rollback precisa devolver tudo.
    $payloadBat = Join-Path $SetupDir 'payload\instalar.bat'
    $payloadManifest = Join-Path $SetupDir 'payload\payload manifest.json'
    $savedBat = [IO.File]::ReadAllBytes($payloadBat)
    $savedManifest = [IO.File]::ReadAllBytes($payloadManifest)
    try {
        [IO.File]::WriteAllText($payloadBat, "@echo off`r`nexit /b 1`r`n", [Text.Encoding]::ASCII)
        $sha = [Security.Cryptography.SHA256]::Create()
        try { $changedHash = ([BitConverter]::ToString($sha.ComputeHash([IO.File]::ReadAllBytes($payloadBat)))).Replace('-', '').ToLowerInvariant() }
        finally { $sha.Dispose() }
        $manifest = [IO.File]::ReadAllText($payloadManifest, [Text.Encoding]::UTF8) | ConvertFrom-Json
        $entry = @($manifest.files | Where-Object { $_.path -eq 'instalar.bat' })
        Assert-True ($entry.Count -eq 1) 'instalar.bat não está no manifesto de teste.'
        $entry[0].sha256 = $changedHash
        [IO.File]::WriteAllText($payloadManifest, ($manifest | ConvertTo-Json -Depth 8), (New-Object Text.UTF8Encoding($false)))
        $env:NEXOFLOW_SETUP_INSTALL_MODE = 'Clean'
        Invoke-Setup 'Instalação limpa com falha sintética e recuperação' -ExpectedExitCode 1
    } finally {
        [IO.File]::WriteAllBytes($payloadBat, $savedBat)
        [IO.File]::WriteAllBytes($payloadManifest, $savedManifest)
    }
    Assert-Installed
    Assert-True ((Get-Content -LiteralPath (Join-Path $InstallDir 'secrets_config.py') -Raw) -match 'TOKEN_TESTE_WENI') 'Falha da instalação limpa perdeu a configuração anterior.'
    Assert-True ((Get-Content -LiteralPath (Join-Path $InstallDir 'logs\setup-smoke-marker.txt') -Raw).Trim() -eq 'preservar') 'Falha da instalação limpa perdeu os logs.'
    Assert-True ((Get-Content -LiteralPath (Join-Path $InstallDir 'credentials\google_credentials.json') -Raw) -match 'smoke_test') 'Falha da instalação limpa perdeu credenciais.'

    $env:NEXOFLOW_PERFIL = 'PET'
    Invoke-Setup 'Instalação limpa bem-sucedida mantendo somente importações'
    $env:NEXOFLOW_PERFIL = 'FARMA'
    Assert-Installed
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $InstallDir 'secrets_config.py'))) 'A instalação limpa restaurou a configuração anterior.'
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $InstallDir 'credentials\google_credentials.json'))) 'A instalação limpa restaurou credenciais anteriores.'
    Assert-True (@(Get-ChildItem -LiteralPath (Join-Path $InstallDir '__pycache__') -Filter 'secrets_config*.pyc' -ErrorAction SilentlyContinue).Count -eq 0) 'A instalação limpa reteve bytecode da configuração anterior.'
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $InstallDir 'logs\setup-smoke-marker.txt'))) 'A instalação limpa restaurou logs anteriores.'
    Assert-True ((Get-Content -LiteralPath (Join-Path $InstallDir 'importacoes\planilha-teste.txt') -Raw) -eq 'export privado sintético') 'A instalação limpa perdeu as importações.'
    Remove-Item Env:NEXOFLOW_SETUP_INSTALL_MODE -ErrorAction SilentlyContinue

    Write-Host "==> Executando check-up da instalação real"
    $oldLauncher = $env:NEXOFLOW_LAUNCHER
    $env:NEXOFLOW_LAUNCHER = "1"
    try {
        $checkOutput = Join-Path $TempRoot "checkup-stdout.txt"
        $checkError = Join-Path $TempRoot "checkup-stderr.txt"
        $check = Start-Process -FilePath (Join-Path $env:SystemRoot "System32\cmd.exe") -ArgumentList '/d','/c','comandos\check-up.bat' -WorkingDirectory $InstallDir -RedirectStandardOutput $checkOutput -RedirectStandardError $checkError -PassThru
        if (-not $check.WaitForExit(120000)) {
            & taskkill.exe /PID $check.Id /T /F | Out-Null
            Get-Content -LiteralPath $checkOutput -Encoding UTF8 -Tail 150
            Get-Content -LiteralPath $checkError -Encoding UTF8 -Tail 150
            throw "O check-up instalado excedeu dois minutos."
        }
        if ($check.ExitCode -ne 0) {
            Get-Content -LiteralPath $checkOutput -Encoding UTF8 -Tail 150
            Get-Content -LiteralPath $checkError -Encoding UTF8 -Tail 150
        }
        Assert-True ($check.ExitCode -eq 0) "comandos/check-up.bat instalado falhou com código $($check.ExitCode)."
    }
    finally {
        if ($null -eq $oldLauncher) {
            Remove-Item Env:NEXOFLOW_LAUNCHER -ErrorAction SilentlyContinue
        } else {
            $env:NEXOFLOW_LAUNCHER = $oldLauncher
        }
    }

    Write-Host "[OK] Smoke test do NexoFlow Setup 1.5.4 concluído."
}
finally {
    Remove-Item Env:NEXOFLOW_SETUP_INSTALL_MODE -ErrorAction SilentlyContinue
    Remove-Item Env:NEXOFLOW_SETUP_NONINTERACTIVE -ErrorAction SilentlyContinue
    Remove-Item Env:NEXOFLOW_PYTHON_EXE -ErrorAction SilentlyContinue
    Remove-TestArtifacts
    Remove-Item -LiteralPath $TempRoot -Recurse -Force -ErrorAction SilentlyContinue
}
# NexoFlow 1.5.4
