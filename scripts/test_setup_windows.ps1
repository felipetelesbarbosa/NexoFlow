param(
    [Parameter(Mandatory = $true)][string]$SetupZip
)

$ErrorActionPreference = "Stop"
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
        (Join-Path ([Environment]::GetFolderPath("CommonDesktopDirectory")) "NexoFlow Planilha.lnk"),
        (Join-Path ([Environment]::GetFolderPath("CommonDesktopDirectory")) "NexoFlow Terminal.lnk"),
        (Join-Path $env:ProgramData "Microsoft\Windows\Start Menu\Programs\NexoFlow")
    )) {
        Remove-Item -LiteralPath $shortcut -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Invoke-Setup {
    param([string]$Label)

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

    if ($process.ExitCode -ne 0) {
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
    foreach ($relative in @(
        "NexoFlow Analytics.exe",
        "NexoFlow Weni.exe",
        "NexoFlow Recompra.exe",
        "NexoFlow Terminal.exe",
        "NexoFlow Planilha.exe",
        "executar_planilha.bat",
        "assets\NexoFlow_Planilha.ico",
        "installer\install.ps1",
        "installer\uninstall.ps1",
        "scripts\confirmar_revisao_weni.ps1",
        "scripts\resultado_carga_weni.ps1",
        "desinstalar_nexoflow.cmd",
        ".venv\Scripts\python.exe"
    )) {
        $path = Join-Path $InstallDir $relative
        Assert-True (Test-Path -LiteralPath $path -PathType Leaf) "Arquivo instalado ausente: $relative"
    }

    Assert-True (Test-Path -LiteralPath (Join-Path $InstallDir "importacoes") -PathType Container) "A pasta importacoes não foi instalada."

    $shortcutPath = Join-Path ([Environment]::GetFolderPath("CommonDesktopDirectory")) "NexoFlow Planilha.lnk"
    Assert-True (Test-Path -LiteralPath $shortcutPath) "Atalho NexoFlow Planilha ausente."
    $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($shortcutPath)
    Assert-True ($shortcut.TargetPath -eq (Join-Path $InstallDir "NexoFlow Planilha.exe")) "Destino do atalho de planilha incorreto."
    Assert-True ($shortcut.IconLocation.StartsWith((Join-Path $InstallDir "assets\NexoFlow_Planilha.ico"))) "Ícone do atalho de planilha incorreto."

    Assert-True (Test-Path -LiteralPath $UninstallKey) "Registro de desinstalação não foi criado."
    $displayVersion = (Get-ItemProperty -LiteralPath $UninstallKey -Name DisplayVersion -ErrorAction Stop).DisplayVersion
    Assert-True ($displayVersion -eq "1.0") "DisplayVersion inesperada: $displayVersion"
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
    $projectZip = Join-Path (Split-Path -Parent $resolvedZip) 'NexoFlow-1.0.zip'
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $projectArchive = [IO.Compression.ZipFile]::OpenRead($projectZip)
    try {
        Assert-True ($null -ne $projectArchive.GetEntry('NexoFlow/importacoes/')) 'Pasta importacoes ausente no projeto completo.'
        Assert-True (@($projectArchive.Entries | Where-Object { $_.FullName.StartsWith('NexoFlow/importacoes/') -and -not $_.FullName.EndsWith('/') }).Count -eq 0) 'O projeto completo não deve incluir arquivos privados em importacoes.'
    } finally { $projectArchive.Dispose() }


    $python = (Get-Command python.exe -ErrorAction Stop).Source
    $env:NEXOFLOW_SETUP_NONINTERACTIVE = "1"
    $env:NEXOFLOW_PYTHON_EXE = $python

    Invoke-Setup "Primeira instalação"
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

    Invoke-Setup "Atualização sobre instalação existente"
    Assert-Installed
    Assert-True ((Get-Content -LiteralPath (Join-Path $InstallDir "logs\setup-smoke-marker.txt") -Raw).Trim() -eq "preservar") "Logs não foram preservados na atualização."
    Assert-True ((Get-Content -LiteralPath (Join-Path $InstallDir "credentials\google_credentials.json") -Raw) -match "smoke_test") "Credenciais não foram preservadas na atualização."
    Assert-True ((Get-Content -LiteralPath (Join-Path $InstallDir "secrets_config.py") -Raw) -match "TOKEN_TESTE_WENI") "secrets_config.py não foi preservado."
    Assert-True ((Get-Content -LiteralPath (Join-Path $InstallDir 'importacoes\planilha-teste.txt') -Raw) -eq 'export privado sintético') 'Importações não foram preservadas na atualização.'

    Write-Host "==> Simulando antivírus/EDR removendo o launcher opcional Uninstall"
    $optionalSource = Join-Path $SetupDir "payload\NexoFlow Uninstall.exe"
    Remove-Item -LiteralPath $optionalSource -Force -ErrorAction SilentlyContinue
    Assert-True (-not (Test-Path -LiteralPath $optionalSource)) "Não foi possível simular a remoção do Uninstall opcional."

    Invoke-Setup "Atualização sem NexoFlow Uninstall.exe no pacote extraido"
    Assert-Installed
    Assert-True ((Get-Content -LiteralPath (Join-Path $InstallDir "logs\setup-smoke-marker.txt") -Raw).Trim() -eq "preservar") "Dados privados foram perdidos sem o launcher opcional."

    Write-Host "==> Executando check-up da instalação real"
    $oldLauncher = $env:NEXOFLOW_LAUNCHER
    $env:NEXOFLOW_LAUNCHER = "1"
    try {
        $checkOutput = Join-Path $TempRoot "checkup-stdout.txt"
        $checkError = Join-Path $TempRoot "checkup-stderr.txt"
        $check = Start-Process -FilePath (Join-Path $env:SystemRoot "System32\cmd.exe") -ArgumentList '/d','/c','check-up.bat' -WorkingDirectory $InstallDir -RedirectStandardOutput $checkOutput -RedirectStandardError $checkError -PassThru
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
        Assert-True ($check.ExitCode -eq 0) "check-up.bat instalado falhou com código $($check.ExitCode)."
    }
    finally {
        if ($null -eq $oldLauncher) {
            Remove-Item Env:NEXOFLOW_LAUNCHER -ErrorAction SilentlyContinue
        } else {
            $env:NEXOFLOW_LAUNCHER = $oldLauncher
        }
    }

    Write-Host "[OK] Smoke test do NexoFlow Setup 1.0 concluído."
}
finally {
    Remove-Item Env:NEXOFLOW_SETUP_NONINTERACTIVE -ErrorAction SilentlyContinue
    Remove-Item Env:NEXOFLOW_PYTHON_EXE -ErrorAction SilentlyContinue
    Remove-TestArtifacts
    Remove-Item -LiteralPath $TempRoot -Recurse -Force -ErrorAction SilentlyContinue
}
# NexoFlow 1.0
