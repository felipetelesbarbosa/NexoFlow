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
        (Join-Path ([Environment]::GetFolderPath("CommonDesktopDirectory")) "NexoFlow Terminal.lnk"),
        (Join-Path $env:ProgramData "Microsoft\Windows\Start Menu\Programs\NexoFlow")
    )) {
        Remove-Item -LiteralPath $shortcut -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Invoke-Setup {
    param([string]$Label)

    Write-Host "==> $Label"
    $process = Start-Process -FilePath (Join-Path $SetupDir "NexoFlow Setup.exe") -WorkingDirectory $SetupDir -PassThru -Wait

    if ($process.ExitCode -ne 0) {
        $log = Join-Path $env:TEMP "NexoFlow-Setup.log"
        if (Test-Path -LiteralPath $log) {
            Write-Host "----- NexoFlow-Setup.log -----"
            Get-Content -LiteralPath $log -Tail 250
            Write-Host "------------------------------"
        }
        throw "$Label falhou com codigo $($process.ExitCode)."
    }
}

function Assert-Installed {
    foreach ($relative in @(
        "NexoFlow Analytics.exe",
        "NexoFlow Weni.exe",
        "NexoFlow Terminal.exe",
        "installer\install.ps1",
        "installer\uninstall.ps1",
        "desinstalar_nexoflow.cmd",
        ".venv\Scripts\python.exe"
    )) {
        $path = Join-Path $InstallDir $relative
        Assert-True (Test-Path -LiteralPath $path -PathType Leaf) "Arquivo instalado ausente: $relative"
    }

    Assert-True (Test-Path -LiteralPath $UninstallKey) "Registro de desinstalacao nao foi criado."
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

    $python = (Get-Command python.exe -ErrorAction Stop).Source
    $env:NEXOFLOW_SETUP_NONINTERACTIVE = "1"
    $env:NEXOFLOW_PYTHON_EXE = $python

    Invoke-Setup "Primeira instalacao"
    Assert-Installed

    Write-Host "==> Criando dados privados para testar preservacao"
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

    Invoke-Setup "Atualizacao sobre instalacao existente"
    Assert-Installed
    Assert-True ((Get-Content -LiteralPath (Join-Path $InstallDir "logs\setup-smoke-marker.txt") -Raw).Trim() -eq "preservar") "Logs nao foram preservados na atualizacao."
    Assert-True ((Get-Content -LiteralPath (Join-Path $InstallDir "credentials\google_credentials.json") -Raw) -match "smoke_test") "Credenciais nao foram preservadas na atualizacao."
    Assert-True ((Get-Content -LiteralPath (Join-Path $InstallDir "secrets_config.py") -Raw) -match "TOKEN_TESTE_WENI") "secrets_config.py nao foi preservado."

    Write-Host "==> Simulando antivirus/EDR removendo o launcher opcional Uninstall"
    $optionalSource = Join-Path $SetupDir "payload\NexoFlow Uninstall.exe"
    Remove-Item -LiteralPath $optionalSource -Force -ErrorAction SilentlyContinue
    Assert-True (-not (Test-Path -LiteralPath $optionalSource)) "Nao foi possivel simular a remocao do Uninstall opcional."

    Invoke-Setup "Atualizacao sem NexoFlow Uninstall.exe no pacote extraido"
    Assert-Installed
    Assert-True ((Get-Content -LiteralPath (Join-Path $InstallDir "logs\setup-smoke-marker.txt") -Raw).Trim() -eq "preservar") "Dados privados foram perdidos sem o launcher opcional."

    Write-Host "==> Executando check-up da instalacao real"
    $oldLauncher = $env:NEXOFLOW_LAUNCHER
    $env:NEXOFLOW_LAUNCHER = "1"
    try {
        $check = Start-Process -FilePath (Join-Path $env:SystemRoot "System32\cmd.exe") -ArgumentList '/d','/c','check-up.bat' -WorkingDirectory $InstallDir -PassThru -Wait
        Assert-True ($check.ExitCode -eq 0) "check-up.bat instalado falhou com codigo $($check.ExitCode)."
    }
    finally {
        if ($null -eq $oldLauncher) {
            Remove-Item Env:NEXOFLOW_LAUNCHER -ErrorAction SilentlyContinue
        } else {
            $env:NEXOFLOW_LAUNCHER = $oldLauncher
        }
    }

    Write-Host "[OK] Smoke test do NexoFlow Setup 1.0 concluido."
}
finally {
    Remove-Item Env:NEXOFLOW_SETUP_NONINTERACTIVE -ErrorAction SilentlyContinue
    Remove-Item Env:NEXOFLOW_PYTHON_EXE -ErrorAction SilentlyContinue
    Remove-TestArtifacts
    Remove-Item -LiteralPath $TempRoot -Recurse -Force -ErrorAction SilentlyContinue
}
# NexoFlow 1.0
