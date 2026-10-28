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

function Assert-PublicTrackedFiles {
    param([Parameter(Mandatory = $true)][string[]]$Paths)

    # A lista do Git pode conter arquivos adicionados com --force. Falhe antes
    # de copiar qualquer arquivo privado; nunca leia seu conteúdo no build.
    $publicPlaceholders = @(
        "configuracao/secrets_config.example.py",
        "configuracao/secrets_config.example_webhook.txt",
        "app/secrets_config.pyi",
        "credentials/coloque_a_credencial_google_aqui.txt",
        "logs/.gitkeep"
    )
    $privatePatterns = @(
        '(^|/)(\.git|\.venv|venv|__pycache__)(/|$)',
        '(^|/)(credentials|secrets|logs)(/|$)',
        '(^|/)(diagnosticos_privados|importacoes)(/|$)',
        '(^|/)(Conversas_Delivery|Contatos_Delivery)\.xlsx$',
        '(^|/)farmalider_falhas_[^/]*\.jsonl$',
        '(^|/)secrets_config\.py($|\.)',
        '(^|/)\.env($|\.)',
        '(^|/)(google[-_]?credentials|service[-_]?account|credentials|secrets|tokens?)([-_.][^/]*)?\.json$',
        '(^|/)(id_rsa|id_dsa|id_ecdsa|id_ed25519)($|\.)',
        '\.(pem|key|p12|pfx|jks|keystore|ppk|log)(\.[^/]*)?$'
    )
    $unsafe = @()
    foreach ($relative in $Paths) {
        if (-not $relative) { continue }
        $normalized = $relative.Replace("\", "/").ToLowerInvariant()
        if ($normalized -in $publicPlaceholders) { continue }
        foreach ($pattern in $privatePatterns) {
            if ($normalized -match $pattern) {
                $unsafe += $relative
                break
            }
        }
    }
    if ($unsafe.Count -gt 0) {
        throw ("Build bloqueado: arquivos privados estão rastreados no Git. " +
            "Remova-os do índice antes de publicar: " + ($unsafe -join ", "))
    }
}

function Copy-TrackedFiles {
    param([Parameter(Mandatory = $true)][string]$Destination)

    Push-Location $RepoRoot
    try {
        $tracked = & git ls-files
        if ($LASTEXITCODE -ne 0) { throw "git ls-files falhou." }
        Assert-PublicTrackedFiles -Paths $tracked

        foreach ($relative in $tracked) {
            if (-not $relative) { continue }
            if ($relative -like "releases/*") { continue }
            if ($relative -like "native_launcher/prebuilt/*") { continue }
            if ($relative -like ".github/*") { continue }
            if ($relative -like "scripts/*" -and $relative -notin @("scripts/confirmar_revisao_weni.ps1", "scripts/resultado_carga_weni.ps1", "scripts/check_release_secrets.py", "scripts/build_documentation.py")) { continue }

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
        if (-not $found) { throw "Entrada obrigatória ausente no ZIP: $EntryName" }
    }
    finally {
        $zip.Dispose()
    }
}

Write-Host "==> Compilando launchers com textos em português brasileiro"
$LauncherDir = Join-Path $DistDir "launchers"
New-Item -ItemType Directory -Force -Path $LauncherDir | Out-Null
$launcherTargets = @(
    @{ Name = "NexoFlow Noturno.exe"; Tag = "noturno"; Description = "NexoFlow Noturno — Weni, Analytics e Recompra sem confirmação humana" },
    @{ Name = "NexoFlow Analytics.exe"; Tag = "analytics"; Description = "NexoFlow Analytics — análise de dados" },
    @{ Name = "NexoFlow Weni.exe"; Tag = "updateweni"; Description = "NexoFlow Weni — atualização de contatos" },
    @{ Name = "NexoFlow Recompra.exe"; Tag = "recompra"; Description = "NexoFlow Recompra — grupo FarmaLíder D+25" },
    @{ Name = "NexoFlow Planilha.exe"; Tag = "planilha"; Description = "NexoFlow Planilha — cargas por planilhas" },
    @{ Name = "NexoFlow Terminal.exe"; Tag = "terminal"; Description = "NexoFlow Terminal — consultas e diagnóstico" },
    @{ Name = "NexoFlow Uninstall.exe"; Tag = "uninstall"; Description = "NexoFlow — desinstalação" }
)
Push-Location $RepoRoot
$previousGoModule = $env:GO111MODULE
try {
    $env:GO111MODULE = "off"
    foreach ($target in $launcherTargets) {
        $output = Join-Path $LauncherDir $target.Name
        & go build -trimpath -tags $target.Tag -ldflags "-s -w" -o $output ./native_launcher
        if ($LASTEXITCODE -ne 0) { throw "Falha ao compilar $($target.Name)" }
        & (Join-Path $PSScriptRoot "embed_windows_version.ps1") -ExecutablePath $output -Description $target.Description
    }
}
finally {
    if ($null -eq $previousGoModule) { Remove-Item Env:GO111MODULE -ErrorAction SilentlyContinue }
    else { $env:GO111MODULE = $previousGoModule }
    Pop-Location
}

Write-Host "==> Montando projeto completo NexoFlow $Version"
Copy-TrackedFiles -Destination $ProjectRoot

Write-Host "==> Montando payload do Setup"
Copy-TrackedFiles -Destination $PayloadDir

foreach ($folder in @($ProjectRoot, $PayloadDir)) {
    New-Item -ItemType Directory -Force -Path (Join-Path $folder 'importacoes') | Out-Null
    foreach ($target in $launcherTargets) {
        Copy-Item -LiteralPath (Join-Path $LauncherDir $target.Name) -Destination (Join-Path $folder $target.Name) -Force
    }
}

# Um .ico ao lado do EXE não altera o ícone exibido pelo Explorer.
# Cada launcher deve incorporar seu próprio RT_ICON + RT_GROUP_ICON.
$launcherIcons = @(
    @{ Executable = "NexoFlow Noturno.exe"; Icon = "NexoFlow_Noturno.ico" },
    @{ Executable = "NexoFlow Analytics.exe"; Icon = "NexoFlow.ico" },
    @{ Executable = "NexoFlow Weni.exe"; Icon = "NexoFlow_Weni.ico" },
    @{ Executable = "NexoFlow Recompra.exe"; Icon = "NexoFlow_Recompra.ico" },
    @{ Executable = "NexoFlow Planilha.exe"; Icon = "NexoFlow_Planilha.ico" },
    @{ Executable = "NexoFlow Terminal.exe"; Icon = "NexoFlow_Terminal.ico" },
    @{ Executable = "NexoFlow Uninstall.exe"; Icon = "uninstaller.ico" }
)
Write-Host "==> Incorporando ícones PE dos executáveis no projeto e no payload"
foreach ($folder in @($ProjectRoot, $PayloadDir)) {
    foreach ($item in $launcherIcons) {
        & (Join-Path $PSScriptRoot "embed_windows_icon.ps1") `
            -ExecutablePath (Join-Path $folder $item.Executable) `
            -IconPath (Join-Path (Join-Path $RepoRoot "assets") $item.Icon)
    }
}

# O manifest deve refletir os EXEs depois da incorporação dos ícones.
Write-Host "==> Auditando os executáveis recompilados no projeto completo"
Push-Location $ProjectRoot
try {
    & python app/auditar_consistencia.py
    if ($LASTEXITCODE -ne 0) { throw "A auditoria dos arquivos empacotados falhou." }
}
finally { Pop-Location }
Write-PayloadManifest -Payload $PayloadDir

New-Item -ItemType Directory -Force -Path (Join-Path $SetupRoot "installer") | Out-Null
Copy-Item -LiteralPath (Join-Path $RepoRoot "installer\install.ps1") -Destination (Join-Path $SetupRoot "installer\install.ps1") -Force

New-Item -ItemType Directory -Force -Path (Join-Path $SetupRoot "prerequisites") | Out-Null
Copy-Item -LiteralPath (Join-Path $RepoRoot "prerequisites\python-3.14.8-amd64.exe") -Destination (Join-Path $SetupRoot "prerequisites\python-3.14.8-amd64.exe") -Force

$readme = @"
NexoFlow $Version - SETUP

Este pacote corresponde ao NexoFlow $Version.

Extraia TODO o ZIP antes de executar.
Depois execute: NexoFlow Setup.exe

O Setup solicita elevação do Windows automaticamente quando necessário.
Atualizações preservam a instalação anterior para rollback automático se houver falha.

O launcher NexoFlow Uninstall.exe permanece opcional.
Se um antivírus corporativo removê-lo antes ou depois da instalação, o Setup continua funcionando.
A desinstalação permanece disponível por installer\uninstall.ps1 e
desinstalar_nexoflow.cmd.

Não coloque credenciais dentro deste pacote.
"@
[IO.File]::WriteAllText((Join-Path $SetupRoot "LEIA-ME INSTALACAO.txt"), $readme, (New-Object Text.UTF8Encoding($false)))
[IO.File]::WriteAllText((Join-Path $SetupRoot "SETUP VALIDADO.txt"), "NexoFlow $Version - Setup validado automaticamente em Windows para instalação, atualização e ausência do Uninstall opcional.", (New-Object Text.UTF8Encoding($false)))

$signing = @'
param()
Write-Host "Assinatura Authenticode não automatizada neste pacote."
Write-Host "Assine os executáveis somente quando houver certificado corporativo confiável."
'@
[IO.File]::WriteAllText((Join-Path $SetupRoot "Assinar Release.ps1"), $signing, (New-Object Text.UTF8Encoding($true)))

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

Write-Host "==> Incorporando ícone próprio no NexoFlow Setup.exe"
& (Join-Path $PSScriptRoot "embed_windows_version.ps1") `
    -ExecutablePath (Join-Path $SetupRoot "NexoFlow Setup.exe") `
    -Description "NexoFlow — instalação e atualização"
& (Join-Path $PSScriptRoot "embed_windows_icon.ps1") `
    -ExecutablePath (Join-Path $SetupRoot "NexoFlow Setup.exe") `
    -IconPath (Join-Path (Join-Path $RepoRoot "assets") "installer.ico")

Write-Host "==> Gerando checksums internos do Setup"
Write-Checksums -Root $SetupRoot -OutputFile (Join-Path $SetupRoot "checksums SHA256.txt")

$SetupZip = Join-Path $DistDir "NexoFlow-Setup-$Version.zip"
$ProjectZip = Join-Path $DistDir "NexoFlow-$Version.zip"
$ShaFile = Join-Path $DistDir "SHA256SUMS-$Version.txt"

Write-Host "==> Compactando Setup"
Compress-Archive -Path $SetupRoot -DestinationPath $SetupZip -CompressionLevel Optimal -Force

Write-Host "==> Compactando projeto completo"
Compress-Archive -Path $ProjectRoot -DestinationPath $ProjectZip -CompressionLevel Optimal -Force

# Garantir a entrada vazia mesmo em ferramentas que omitam diretórios sem arquivos.
Add-Type -AssemblyName System.IO.Compression.FileSystem
foreach ($item in @(
    @{ Path = $SetupZip; Entry = 'NexoFlow Setup/payload/importacoes/' },
    @{ Path = $ProjectZip; Entry = 'NexoFlow/importacoes/' }
)) {
    $archive = [IO.Compression.ZipFile]::Open($item.Path, [IO.Compression.ZipArchiveMode]::Update)
    try {
        if (-not $archive.GetEntry($item.Entry)) { $archive.CreateEntry($item.Entry) | Out-Null }
    } finally { $archive.Dispose() }
    Assert-ZipEntry -ZipPath $item.Path -EntryName $item.Entry
}


Assert-ZipEntry -ZipPath $SetupZip -EntryName "NexoFlow Setup/NexoFlow Setup.exe"
Assert-ZipEntry -ZipPath $SetupZip -EntryName "NexoFlow Setup/payload/payload manifest.json"
Assert-ZipEntry -ZipPath $SetupZip -EntryName "NexoFlow Setup/payload/NexoFlow Noturno.exe"
Assert-ZipEntry -ZipPath $ProjectZip -EntryName "NexoFlow/NexoFlow Noturno.exe"
Assert-ZipEntry -ZipPath $SetupZip -EntryName "NexoFlow Setup/payload/NexoFlow Recompra.exe"
Assert-ZipEntry -ZipPath $ProjectZip -EntryName "NexoFlow/NexoFlow Recompra.exe"
Assert-ZipEntry -ZipPath $SetupZip -EntryName "NexoFlow Setup/payload/app/weni_update.py"
foreach ($module in @("weni_dedup", "contact_dedup_guard", "dedup_io", "dedup_sheets", "dedup_bi", "recompra_lock", "recompra_review_audit", "farmalider_customers", "recompra_profiles", "recompra_cleanup")) {
    Assert-ZipEntry -ZipPath $SetupZip -EntryName "NexoFlow Setup/payload/app/$module.py"
    Assert-ZipEntry -ZipPath $ProjectZip -EntryName "NexoFlow/app/$module.py"
}
foreach ($command in @("limpar_cancelados_recompra.bat", "atualizar_recompra_pets.bat")) {
    Assert-ZipEntry -ZipPath $SetupZip -EntryName "NexoFlow Setup/payload/comandos/$command"
    Assert-ZipEntry -ZipPath $ProjectZip -EntryName "NexoFlow/comandos/$command"
}
Assert-ZipEntry -ZipPath $SetupZip -EntryName "NexoFlow Setup/payload/app/task_progress.py"
Assert-ZipEntry -ZipPath $ProjectZip -EntryName "NexoFlow/app/task_progress.py"
Assert-ZipEntry -ZipPath $SetupZip -EntryName "NexoFlow Setup/payload/app/observed_orders.py"
Assert-ZipEntry -ZipPath $ProjectZip -EntryName "NexoFlow/app/observed_orders.py"
Assert-ZipEntry -ZipPath $SetupZip -EntryName "NexoFlow Setup/payload/app/analytics.py"
Assert-ZipEntry -ZipPath $SetupZip -EntryName "NexoFlow Setup/payload/app/looker_bi.py"
Assert-ZipEntry -ZipPath $SetupZip -EntryName "NexoFlow Setup/payload/app/run_looker.py"
Assert-ZipEntry -ZipPath $ProjectZip -EntryName "NexoFlow/app/looker_bi.py"
Assert-ZipEntry -ZipPath $SetupZip -EntryName "NexoFlow Setup/payload/scripts/confirmar_revisao_weni.ps1"
Assert-ZipEntry -ZipPath $ProjectZip -EntryName "NexoFlow/scripts/confirmar_revisao_weni.ps1"
Assert-ZipEntry -ZipPath $SetupZip -EntryName "NexoFlow Setup/payload/scripts/resultado_carga_weni.ps1"
Assert-ZipEntry -ZipPath $ProjectZip -EntryName "NexoFlow/scripts/resultado_carga_weni.ps1"
Assert-ZipEntry -ZipPath $SetupZip -EntryName "NexoFlow Setup/payload/scripts/build_documentation.py"
Assert-ZipEntry -ZipPath $ProjectZip -EntryName "NexoFlow/scripts/build_documentation.py"

$setupHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $SetupZip).Hash.ToLowerInvariant()
$projectHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $ProjectZip).Hash.ToLowerInvariant()

$shaLines = @(
    "$setupHash  NexoFlow-Setup-$Version.zip",
    "$projectHash  NexoFlow-$Version.zip"
)
[IO.File]::WriteAllLines($ShaFile, $shaLines, (New-Object Text.UTF8Encoding($false)))

$releaseNotes = @"
# NexoFlow $Version

Aplicativos Windows para integrar Weni e FarmaLíder, organizar pedidos no Google Sheets e alimentar painéis do Looker Studio.

## Downloads

- **NexoFlow-Setup-$Version.zip** — instalador recomendado para Windows.
- **NexoFlow-$Version.zip** — projeto completo.
- **SHA256SUMS-$Version.txt** — hashes dos dois pacotes.

Extraia todo o ZIP do Setup e execute **NexoFlow Setup.exe**. A distribuição inclui Weni, Analytics, Planilha, Recompra, Terminal e Noturno. Configure suas próprias credenciais; os pacotes não incluem chaves ou tokens.

## Primeira execução

Siga a ordem: Weni completa → Planilha, se houver exports → Analytics completo → Recompra → Analytics incremental. Revise os relatórios e confirme as aplicações solicitadas. Depois atualize o Looker Studio. Para a rotina sem confirmações, use **NexoFlow Noturno.exe**; confira o resultado em `logs/noturno/`.

A publicação é validada por testes no Windows, check-up e testes de instalação e atualização.

[Instalação](https://github.com/felipetelesbarbosa/NexoFlow/blob/main/docs/README%20INSTALACAO.md) · [Guia de operação](https://github.com/felipetelesbarbosa/NexoFlow/blob/main/docs/Documentacao%20NexoFlow.md) · [Histórico de mudanças](https://github.com/felipetelesbarbosa/NexoFlow/blob/main/CHANGELOG.md)
"@
[IO.File]::WriteAllText((Join-Path $DistDir "release-notes.md"), $releaseNotes, (New-Object Text.UTF8Encoding($false)))

Write-Host "==> Artefatos gerados"
Get-ChildItem -LiteralPath $DistDir -File | Select-Object Name,Length
# NexoFlow 1.0
