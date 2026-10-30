param(
    [Parameter(Mandatory = $true)][string]$SetupRoot,
    [string]$ExpectedThumbprint = ''
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'sign_release.ps1')
$files = @()
foreach ($file in @(Get-ChildItem -LiteralPath $SetupRoot -Recurse -File |
    Where-Object { $_.Extension -in @('.exe', '.ps1') -and $_.FullName -notlike '*\prerequisites\*' })) {
    $signature = Get-AuthenticodeSignature -LiteralPath $file.FullName
    if ($ExpectedThumbprint) {
        Assert-NexoSignature -Path $file.FullName -Thumbprint $ExpectedThumbprint.Replace(' ', '').ToUpperInvariant()
    } elseif ($signature.Status -ne 'NotSigned') {
        throw "Assinatura inesperada no pacote sem editor configurado: $($file.Name)"
    }
    $files += [ordered]@{
        arquivo = $file.FullName.Substring($SetupRoot.Length).TrimStart('\', '/')
        sha256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        assinatura = [string]$signature.Status
        timestamp = [bool]$signature.TimeStamperCertificate
    }
}
# Sem alterar a proteção da máquina: se o Defender estiver ativo, examinar a pasta.
$scanner = 'não disponível ou inativo; nenhuma aprovação antivírus afirmada'
$status = $null
if (Get-Command Get-MpComputerStatus -ErrorAction SilentlyContinue) {
    try { $status = Get-MpComputerStatus -ErrorAction Stop } catch { }
}
if ($status -and $status.AntivirusEnabled -and $status.RealTimeProtectionEnabled) {
    Start-MpScan -ScanType CustomScan -ScanPath $SetupRoot -ErrorAction Stop
    $detections = @(Get-MpThreatDetection -ErrorAction Stop | Where-Object {
        $match = $false
        foreach ($resource in $_.Resources) {
            if ($resource.IndexOf($SetupRoot, [StringComparison]::OrdinalIgnoreCase) -ge 0) { $match = $true }
        }
        $match
    })
    if ($detections.Count) { throw 'O Microsoft Defender registrou detecção no pacote; publicação bloqueada para revisão.' }
    foreach ($file in $files) {
        $actual = (Get-FileHash -LiteralPath (Join-Path $SetupRoot $file.arquivo) -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne $file.sha256) { throw 'Arquivo removido ou alterado após a análise do pacote.' }
    }
    $scanner = 'Microsoft Defender: exame concluído sem detecções registradas para esta pasta nesta execução'
}
$report = [ordered]@{
    versao = (Get-Content -LiteralPath (Join-Path $SetupRoot 'payload/VERSION') -Raw).Trim()
    commit = (& git rev-parse HEAD | Out-String).Trim()
    utc = [DateTime]::UtcNow.ToString('o')
    assinatura_configurada = [bool]$ExpectedThumbprint
    antivirus = $scanner
    limite = 'Não comprova ausência de malware e não garante aprovação de outros antivírus ou do SmartScreen.'
    arquivos = $files
}
[IO.File]::WriteAllText((Join-Path $SetupRoot 'RELATORIO DE SEGURANCA.json'), ($report | ConvertTo-Json -Depth 6), (New-Object Text.UTF8Encoding($false)))
Write-Host "[OK] Integridade e estado das assinaturas registrados. Antivírus: $scanner"
