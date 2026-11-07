param([ValidateSet('Consultar','Salvar')][string]$Action = 'Consultar',
      [ValidateSet('personal','corporate','')][string]$Mode = '', [switch]$FunctionsOnly)
# Identidade local do Windows, sem nomes de redes, IPs ou credenciais no disco.
function Get-NexoConnectedNetworks {
    $type = [Type]::GetTypeFromCLSID([Guid]'DCB00C01-570F-4A9B-8D69-199FDBA5723B')
    $manager = [Activator]::CreateInstance($type)
    try { return @($manager.GetNetworks(1)) }
    finally { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($manager) }
}
function Invoke-NexoNetworkMemory {
param([string]$Action = 'Consultar', [string]$Mode = '')
$ErrorActionPreference = 'Stop'
try {
    $networks = @(Get-NexoConnectedNetworks)
    if ($networks.Count -eq 0) { return }
    $ids = @(); $domain = $false
    foreach ($network in $networks) {
        $ids += $network.GetNetworkId().ToString()
        if ($network.GetCategory() -eq 2) { $domain = $true }
    }
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $key = -join ($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes(($ids | Sort-Object) -join '|')) | ForEach-Object { $_.ToString('x2') })
    } finally { $sha.Dispose() }
    if (-not $env:LOCALAPPDATA) { return }
    $directory = Join-Path $env:LOCALAPPDATA 'NexoFlow/rede'
    $path = Join-Path $directory ($key + '.json')
    if ($Action -eq 'Salvar') {
        if ($Mode -notin @('personal','corporate')) { return }
        # Um domínio corporativo nunca aprende autorização direta automaticamente.
        if ($domain -and $Mode -eq 'personal') { return }
        New-Item -ItemType Directory -Force -Path $directory | Out-Null
        $temp = $path + '.' + [Guid]::NewGuid().ToString('N') + '.tmp'
        try {
            @{ mode = $Mode; schema = 1 } | ConvertTo-Json | Set-Content -LiteralPath $temp -Encoding UTF8
            Move-Item -LiteralPath $temp -Destination $path -Force
        } finally { if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Force } }
        return
    }
    if ($domain) { Write-Output 'corporate'; return }
    if (Test-Path -LiteralPath $path) {
        $saved = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
        if ($saved.schema -eq 1 -and $saved.mode -in @('personal','corporate')) { Write-Output $saved.mode }
    }
} catch {
    # Falha na identificação não autoriza rota direta; o chamador mantém a pergunta.
    return
}
}
if (-not $FunctionsOnly) { Invoke-NexoNetworkMemory -Action $Action -Mode $Mode }
