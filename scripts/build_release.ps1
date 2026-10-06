param(
    [string]$Version = "1.0"
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$DistDir = Join-Path $RepoRoot "dist"
$SetupRoot = Join-Path $DistDir "NexoFlow Setup"
$PayloadDir = Join-Path $SetupRoot "payload"
$ProjectRoot = Join-Path $DistDir "NexoFlow"

if (Test-Path -LiteralPath $DistDir) {
    Remove-Item -LiteralPath $DistDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $PayloadDir | Out-Null
New-Item -ItemType Directory -Force -Path $ProjectRoot | Out-Null

function Copy-TrackedFiles {
    param([Parameter(Mandatory = $true)][string]$Destination)

    Push-Location $RepoRoot
    try {
        $tracked = & git ls-files
        if ($LASTEXITCODE -ne 0) { throw "git ls-files falhou." }

        foreach ($relative in $tracked) {
            if (-not $relative) { continue }
            if ($relative -like "releases/*") { continue }
            if ($relative -like ".github/*") { continue }
            if ($relative -like "scripts/*") { continue }

            $source = Join-Path $RepoRoot $relative
            if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { continue }

            $target = Join-Path $Destination $relative
            $targetDir = Split-Path -Parent $target
            if ($targetDir) { New-Item -ItemType Directory -Force -Path $targetDir | Out-Null }
            Copy-Item -LiteralPath $source -Destination $target -Force
        }
    }
    finally {
        Pop-Location
    }
}

function Write-PayloadManifest {
    param([Parameter(Mandatory = $true)][string]$Payload)

    $manifestPath = Join-Path $Payload "payload manifest.json"
    $entries = @()

    Get-ChildItem -LiteralPath $Payload -Recurse -File |
        Where-Object { $_.FullName -ne $manifestPath } |
        Sort-Object FullName |
        ForEach-Object {
            $relative = $_.FullName.Substring($Payload.Length).TrimStart("\","/").Replace("\","/")
            $entries += [ordered]@{
                path = $relative
                sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash.ToLowerInvariant()
                size = $_.Length
            }
        }

    $manifest = [ordered]@{
        version = $Version
        algorithm = "SHA256"
        files = $entries
    }

    $json = $manifest | ConvertTo-Json -Depth 8
    [IO.File]::WriteAllText($manifestPath, $json + [Environment]::NewLine, (New-Object Text.UTF8Encoding($false)))
}

function Write-Checksums {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$OutputFile
    )

    $lines = New-Object System.Collections.Generic.List[string]
    Get-ChildItem -LiteralPath $Root -Recurse -File |
        Where-Object { $_.FullName -ne $OutputFile } |
        Sort-Object FullName |
        ForEach-Object {
            $relative = $_.FullName.Substring($Root.Length).TrimStart("\","/").Replace("\","/")
            $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash.ToLowerInvariant()
            $lines.Add("$hash  $relative")
        }

    [IO.File]::WriteAllLines($OutputFile, $lines, (New-Object Text.UTF8Encoding($false)))
}

function Assert-ZipEntry {
    param(
        [Parameter(Mandatory = $true)][string]$ZipPath,
        [Parameter(Mandatory = $true)][string]$EntryName
    )

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [IO.Compression.ZipFile]::OpenRead($ZipPath)
    try {
        $found = $zip.Entries | Where-Object { $_.FullName -eq $EntryName }
        if (-not $found) { throw "Entrada obrigatoria ausente no ZIP: $EntryName" }
    }
    finally {
        $zip.Dispose()
    }
}

Write-Host "==> Montando projeto completo NexoFlow $Version"
Copy-TrackedFiles -Destination $ProjectRoot

Write-Host "==> Montando payload do Setup"
Copy-TrackedFiles -Destination $PayloadDir
Write-PayloadManifest -Payload $PayloadDir

New-Item -ItemType Directory -Force -Path (Join-Path $SetupRoot "installer") | Out-Null
Copy-Item -LiteralPath (Join-Path $RepoRoot "installer\install.ps1") -Destination (Join-Path $SetupRoot "installer\install.ps1") -Force

New-Item -ItemType Directory -Force -Path (Join-Path $SetupRoot "prerequisites") | Out-Null
Copy-Item -LiteralPath (Join-Path $RepoRoot "prerequisites\python-3.14.8-amd64.exe") -Destination (Join-Path $SetupRoot "prerequisites\python-3.14.8-amd64.exe") -Force

$readme = @"
NexoFlow $Version - SETUP INSTAVEL

Este pacote mantem a versao publica NexoFlow $Version.
O instalador esta marcado como INSTAVEL porque ainda precisa de validacao final
em Windows domestico e corporativo/EDR.

Extraia TODO o ZIP antes de executar.
Depois execute: NexoFlow Setup.exe

O launcher NexoFlow Uninstall.exe permanece opcional.
Se um antivirus corporativo remove-lo, a instalacao nao deve falhar.
A desinstalacao continua disponivel por installer\uninstall.ps1 e
desinstalar_nexoflow.cmd.

Nao coloque credenciais dentro deste pacote.
"@
[IO.File]::WriteAllText((Join-Path $SetupRoot "LEIA-ME INSTALACAO.txt"), $readme, (New-Object Text.UTF8Encoding($false)))
[IO.File]::WriteAllText((Join-Path $SetupRoot "SETUP INSTAVEL.txt"), "NexoFlow $Version - Setup instavel para validacao. A versao do produto continua 1.0.", (New-Object Text.UTF8Encoding($false)))

$signing = @'
param()
Write-Host "Assinatura Authenticode nao automatizada neste pacote instavel."
Write-Host "Assine os executaveis somente quando houver certificado corporativo confiavel."
'@
[IO.File]::WriteAllText((Join-Path $SetupRoot "Assinar Release.ps1"), $signing, (New-Object Text.UTF8Encoding($false)))

Write-Host "==> Compilando launcher do Setup"
Push-Location $RepoRoot
$oldGo111Module = $env:GO111MODULE
try {
    $env:GO111MODULE = "off"
    & go build -trimpath -tags setup -ldflags "-s -w" -o (Join-Path $SetupRoot "NexoFlow Setup.exe") ./native_launcher
    if ($LASTEXITCODE -ne 0) { throw "Falha ao compilar NexoFlow Setup.exe" }
}
finally {
    if ($null -eq $oldGo111Module) {
        Remove-Item Env:GO111MODULE -ErrorAction SilentlyContinue
    } else {
        $env:GO111MODULE = $oldGo111Module
    }
    Pop-Location
}

Write-Host "==> Gerando checksums internos do Setup"
Write-Checksums -Root $SetupRoot -OutputFile (Join-Path $SetupRoot "checksums SHA256.txt")

$SetupZip = Join-Path $DistDir "NexoFlow-Setup-$Version-Instavel.zip"
$ProjectZip = Join-Path $DistDir "NexoFlow-$Version.zip"
$ShaFile = Join-Path $DistDir "SHA256SUMS-$Version.txt"

Write-Host "==> Compactando Setup"
Compress-Archive -Path $SetupRoot -DestinationPath $SetupZip -CompressionLevel Optimal -Force

Write-Host "==> Compactando projeto completo"
Compress-Archive -Path $ProjectRoot -DestinationPath $ProjectZip -CompressionLevel Optimal -Force

Assert-ZipEntry -ZipPath $SetupZip -EntryName "NexoFlow Setup/NexoFlow Setup.exe"
Assert-ZipEntry -ZipPath $SetupZip -EntryName "NexoFlow Setup/payload/payload manifest.json"
Assert-ZipEntry -ZipPath $SetupZip -EntryName "NexoFlow Setup/payload/weni_update.py"
Assert-ZipEntry -ZipPath $SetupZip -EntryName "NexoFlow Setup/payload/analytics.py"

$setupHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $SetupZip).Hash.ToLowerInvariant()
$projectHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $ProjectZip).Hash.ToLowerInvariant()

$shaLines = @(
    "$setupHash  NexoFlow-Setup-$Version-Instavel.zip",
    "$projectHash  NexoFlow-$Version.zip"
)
[IO.File]::WriteAllLines($ShaFile, $shaLines, (New-Object Text.UTF8Encoding($false)))

$releaseNotes = @"
# NexoFlow $Version

## Setup 1.0 - INSTAVEL

A versao do produto continua NexoFlow 1.0. Nao houve alteracao para 1.1.

O arquivo NexoFlow-Setup-$Version-Instavel.zip contem o Setup mais recente,
incluindo as alteracoes atuais de pedidos, pedido_status, rechecagem de status
e integracao Weni/Analytics.

O Setup esta marcado como instavel porque a instalacao completa ainda precisa
ser validada em Windows domestico e em ambiente corporativo com antivirus/EDR.

Downloads:
- NexoFlow-Setup-$Version-Instavel.zip - instalador para validacao.
- NexoFlow-$Version.zip - projeto completo correspondente ao mesmo codigo.
- SHA256SUMS-$Version.txt - hashes SHA-256.

Regras atuais de pedidos:
- ultimo_pedido e a fonte prioritaria de ID, data, produtos, quantidades e valores;
- no Caminho 1 a API consulta somente o mesmo pedido_id para confirmar o status;
- pedido_status recebe Em processamento, Em transito, Concluido, Cancelado ou Pronto para rota;
- pedidos 0, 1, 2 e 4 contam como pedido feito;
- somente Cancelado fica fora;
- pedidos abertos sao rechecados ate Concluido ou Cancelado.

A versao publica, CLI, documentacao e metadados do produto permanecem 1.0.
"@
[IO.File]::WriteAllText((Join-Path $DistDir "release-notes.md"), $releaseNotes, (New-Object Text.UTF8Encoding($false)))

Write-Host "==> Artefatos gerados"
Get-ChildItem -LiteralPath $DistDir -File | Select-Object Name,Length
