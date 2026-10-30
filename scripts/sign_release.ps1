# Assinatura opcional com certificado já instalado; nunca importa chaves privadas.
function Get-NexoSigningCertificate {
    param([Parameter(Mandatory = $true)][string]$Thumbprint)
    $normalized = $Thumbprint.Replace(' ', '').ToUpperInvariant()
    if ($normalized -notmatch '^[A-F0-9]{40}$') { throw 'Impressão digital do certificado inválida.' }
    $found = @(Get-ChildItem Cert:\CurrentUser\My, Cert:\LocalMachine\My |
        Where-Object { $_.Thumbprint -eq $normalized })
    if ($found.Count -ne 1) { throw 'Certificado de assinatura ausente ou ambíguo no repositório do Windows.' }
    $cert = $found[0]
    if (-not $cert.HasPrivateKey -or $cert.NotBefore -gt (Get-Date) -or $cert.NotAfter -le (Get-Date)) {
        throw 'Certificado sem chave privada acessível ou fora da validade.'
    }
    if ('1.3.6.1.5.5.7.3.3' -notin @($cert.EnhancedKeyUsageList | ForEach-Object { if ($_.ObjectId -is [string]) { $_.ObjectId } else { $_.ObjectId.Value } })) {
        throw 'O certificado não está autorizado para assinatura de código.'
    }
    return $cert
}

function Assert-NexoSignature {
    param([Parameter(Mandatory = $true)][string]$Path,
          [Parameter(Mandatory = $true)][string]$Thumbprint)
    $signature = Get-AuthenticodeSignature -LiteralPath $Path
    if ($signature.Status -ne 'Valid' -or -not $signature.SignerCertificate -or
        $signature.SignerCertificate.Thumbprint -ne $Thumbprint -or
        -not $signature.TimeStamperCertificate) {
        throw "Assinatura sem validade, editor esperado ou timestamp confiável: $([IO.Path]::GetFileName($Path))"
    }
}

function Invoke-NexoFolderSigning {
    param([Parameter(Mandatory = $true)][string]$Root,
          [Parameter(Mandatory = $true)]$Certificate)
    $files = @(Get-ChildItem -LiteralPath $Root -Recurse -File |
        Where-Object { $_.Extension -in @('.exe', '.ps1') })
    foreach ($file in $files) {
        # O instalador oficial do Python mantém sua assinatura original.
        if ($file.FullName -like '*\prerequisites\*') {
            if ((Get-AuthenticodeSignature -LiteralPath $file.FullName).Status -ne 'Valid') {
                throw 'A assinatura original do pré-requisito não é válida.'
            }
            continue
        }
        Set-AuthenticodeSignature -LiteralPath $file.FullName -Certificate $Certificate `
            -HashAlgorithm SHA256 -TimestampServer 'https://timestamp.digicert.com' | Out-Null
        Assert-NexoSignature -Path $file.FullName -Thumbprint $Certificate.Thumbprint
    }
}
