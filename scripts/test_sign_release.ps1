# Contratos sem certificado real, rede, alteração de confiança ou execução de EXEs.
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'sign_release.ps1')
function Assert-Fails([scriptblock]$Action) {
    $failed = $false
    try { & $Action | Out-Null } catch { $failed = $true }
    if (-not $failed) { throw 'Uma assinatura inválida foi aceita.' }
}
$thumbprint = 'A' * 40
$script:certificate = [pscustomobject]@{
    Thumbprint = $thumbprint; HasPrivateKey = $true
    NotBefore = (Get-Date).AddDays(-1); NotAfter = (Get-Date).AddDays(30)
    EnhancedKeyUsageList = @([pscustomobject]@{ObjectId = [pscustomobject]@{Value = '1.3.6.1.5.5.7.3.3'}})
}
function Get-ChildItem { param($Path) return $script:certificate }
$actual = Get-NexoSigningCertificate $thumbprint
if ($actual.Thumbprint -ne $thumbprint) { throw 'Certificado de outro editor.' }
Assert-Fails { Get-NexoSigningCertificate 'inválido' }
$script:certificate.HasPrivateKey = $false
Assert-Fails { Get-NexoSigningCertificate $thumbprint }
$script:certificate.HasPrivateKey = $true
$script:certificate.NotAfter = (Get-Date).AddDays(-1)
Assert-Fails { Get-NexoSigningCertificate $thumbprint }
$script:certificate.NotAfter = (Get-Date).AddDays(30)
$script:certificate.EnhancedKeyUsageList = @()
Assert-Fails { Get-NexoSigningCertificate $thumbprint }
$script:signature = [pscustomobject]@{Status = 'Valid'; SignerCertificate = [pscustomobject]@{Thumbprint = $thumbprint}; TimeStamperCertificate = [pscustomobject]@{Subject = 'Timestamp sintético'}}
function Get-AuthenticodeSignature { param($LiteralPath) return $script:signature }
Assert-NexoSignature -Path 'synthetic.exe' -Thumbprint $thumbprint
foreach ($status in @('NotSigned', 'HashMismatch', 'NotTrusted', 'UnknownError')) {
    $script:signature.Status = $status
    Assert-Fails { Assert-NexoSignature -Path 'synthetic.exe' -Thumbprint $thumbprint }
}
$script:signature.Status = 'Valid'
Assert-Fails { Assert-NexoSignature -Path 'synthetic.exe' -Thumbprint ('B' * 40) }
$script:signature.TimeStamperCertificate = $null
Assert-Fails { Assert-NexoSignature -Path 'synthetic.exe' -Thumbprint $thumbprint }
Write-Host '[OK] Contratos de assinatura: editor, uso de código, validade, chave e timestamp.'
