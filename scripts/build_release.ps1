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
    # de copiar qualquer arquivo privado; nunca leia seu conteudo no build.
    $publicPlaceholders = @(
        "secrets_config.example.py",
        "secrets_config.example_webhook.txt",
        "secrets_config.pyi",
        "credentials/coloque_a_credencial_google_aqui.txt",
        "logs/.gitkeep"
    )
    $privatePatterns = @(
        '(^|/)(\.git|\.venv|venv|__pycache__)(/|$)',
        '(^|/)(credentials|secrets|logs)(/|$)',
        '(^|/)diagnosticos_privados(/|$)',
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
        throw ("Build bloqueado: arquivos privados estao rastreados no Git. " +
            "Remova-os do indice antes de publicar: " + ($unsafe -join ", "))
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

# Um .ico ao lado do EXE nao altera o icone exibido pelo Explorer.
# Cada launcher deve incorporar seu proprio RT_ICON + RT_GROUP_ICON.
$launcherIcons = @(
    @{ Executable = "NexoFlow Analytics.exe"; Icon = "NexoFlow.ico" },
    @{ Executable = "NexoFlow Weni.exe"; Icon = "NexoFlow_Weni.ico" },
    @{ Executable = "NexoFlow Terminal.exe"; Icon = "NexoFlow_Terminal.ico" },
    @{ Executable = "NexoFlow Uninstall.exe"; Icon = "uninstaller.ico" }
)
Write-Host "==> Incorporando icones PE dos executaveis no projeto e no payload"
foreach ($folder in @($ProjectRoot, $PayloadDir)) {
    foreach ($item in $launcherIcons) {
        & (Join-Path $PSScriptRoot "embed_windows_icon.ps1") `
            -ExecutablePath (Join-Path $folder $item.Executable) `
            -IconPath (Join-Path (Join-Path $RepoRoot "assets") $item.Icon)
    }
}

# O manifest deve refletir os EXEs depois da incorporacao dos icones.
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

O Setup solicita elevacao do Windows automaticamente quando necessario.
Atualizacoes preservam a instalacao anterior para rollback automatico se houver falha.

O launcher NexoFlow Uninstall.exe permanece opcional.
Se um antivirus corporativo remove-lo antes ou depois da instalacao, o Setup continua funcionando.
A desinstalacao permanece disponivel por installer\uninstall.ps1 e
desinstalar_nexoflow.cmd.

Nao coloque credenciais dentro deste pacote.
"@
[IO.File]::WriteAllText((Join-Path $SetupRoot "LEIA-ME INSTALACAO.txt"), $readme, (New-Object Text.UTF8Encoding($false)))
[IO.File]::WriteAllText((Join-Path $SetupRoot "SETUP VALIDADO.txt"), "NexoFlow $Version - Setup validado automaticamente em Windows para instalacao, atualizacao e ausencia do Uninstall opcional.", (New-Object Text.UTF8Encoding($false)))

$signing = @'
param()
Write-Host "Assinatura Authenticode nao automatizada neste pacote."
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

Write-Host "==> Incorporando icone proprio no NexoFlow Setup.exe"
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

Assert-ZipEntry -ZipPath $SetupZip -EntryName "NexoFlow Setup/NexoFlow Setup.exe"
Assert-ZipEntry -ZipPath $SetupZip -EntryName "NexoFlow Setup/payload/payload manifest.json"
Assert-ZipEntry -ZipPath $SetupZip -EntryName "NexoFlow Setup/payload/weni_update.py"
Assert-ZipEntry -ZipPath $SetupZip -EntryName "NexoFlow Setup/payload/analytics.py"

$setupHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $SetupZip).Hash.ToLowerInvariant()
$projectHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $ProjectZip).Hash.ToLowerInvariant()

$shaLines = @(
    "$setupHash  NexoFlow-Setup-$Version.zip",
    "$projectHash  NexoFlow-$Version.zip"
)
[IO.File]::WriteAllLines($ShaFile, $shaLines, (New-Object Text.UTF8Encoding($false)))

$releaseNotes = @"
# NexoFlow $Version

Distribuicao oficial do **NexoFlow 1.0**.

O arquivo `NexoFlow-Setup-$Version.zip` contem o instalador do NexoFlow 1.0 e foi validado automaticamente em Windows para primeira instalacao e atualizacao de uma instalacao existente.

Melhorias desta distribuicao do NexoFlow 1.0:
- de-para de pagamento atualizado: 0 Cancelado; 1 Dinheiro; 2 Débito; 3 Crédito; 4 Ticket; 5 Pix por Link de Pagamento; 6 Pix no POS;
- pagamento 0 cancela o pedido: forma de pagamento Cancelado e status 3 na Weni e no BI, preservando os codigos brutos da API na tabela de pedidos;
- status -1 representa pedido pendente de pagamento e permanece em rechecagem; vendas e ultima_compra consideram somente pedidos concluidos e nao cancelados;
- diagnostico privado local identifica CPFs com falhas 5xx persistentes e captura campos seguros da resposta, fora dos logs publicos e dos pacotes;
- diagnostico seguro de proxy identifica autenticacao 407, bloqueio de tunel 403, TLS, DNS, timeout e conexao recusada; resposta 400/404 da FarmaLider nao e apresentada como autenticacao confirmada;
- listas de pedido com leitura CSV preservam virgulas e aspas nos nomes dos produtos, sem desalinhamento artificial na Weni e no Analytics;
- codigos numericos de pagamento nao documentados sao preservados e exibidos como nao identificados, com o codigo recebido, sem inventar a forma de pagamento;
- pagamento sem de-para aparece em INFO uma vez por codigo; resumo por codigo e progresso distinguem contatos com pedido validado de alteracoes propostas e gravadas;
- preparacao e auditoria continuam antes de qualquer gravacao; listas realmente inconsistentes permanecem bloqueadas;
- cooldown global e recuperacao serial apos falhas 5xx da FarmaLider, com retorno gradual da concorrencia e reducao do intervalo quando a API se recupera;
- diagnostico de HTTP 500 com referencias opacas por execucao e classificacao da resposta, sem publicar CPF, tokens ou texto livre do servidor;
- HTTP 404 continua representando cliente nao encontrado; HTTP 500 permanece uma falha da API;
- consultas por CPF que ja falharam nao sao repetidas na mesma carga; dados previamente confirmados sao preservados quando o CPF continua o mesmo;
- cargas incompletas aparecem como parciais e preservam o marco incremental para uma nova tentativa;
- empacotamento bloqueado quando arquivos privados estao rastreados no Git.

Principais garantias do Setup:
- elevacao UAC automatica quando necessaria;
- rollback automatico se uma atualizacao falhar;
- NexoFlow Uninstall.exe opcional;
- integridade SHA-256 dos componentes obrigatorios;
- preservacao de secrets_config.py, credentials e logs em atualizacoes.

Downloads:
- NexoFlow-Setup-$Version.zip - instalador do NexoFlow 1.0;
- NexoFlow-$Version.zip - projeto completo do NexoFlow 1.0;
- SHA256SUMS-$Version.txt - hashes SHA-256.

Recursos incluidos:
- NexoFlow Analytics;
- NexoFlow Weni;
- NexoFlow Terminal;
- integracao Weni, FarmaLider, Google Sheets e Looker Studio;
- tratamento de pedidos, status, LGPD, canais e atribuicao de anuncios.
"@
[IO.File]::WriteAllText((Join-Path $DistDir "release-notes.md"), $releaseNotes, (New-Object Text.UTF8Encoding($false)))

Write-Host "==> Artefatos gerados"
Get-ChildItem -LiteralPath $DistDir -File | Select-Object Name,Length
# NexoFlow 1.0
