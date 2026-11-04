[CmdletBinding()]
param([switch]$SemRegistroCodex, [switch]$InstalarCodex, [switch]$Reinstall, [switch]$FunctionsOnly)

$ErrorActionPreference = 'Stop'
$raiz = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$mcpDir = Join-Path $raiz 'connectors\meta_ads_mcp'
$venvDir = Join-Path $mcpDir '.venv'
$venvPython = Join-Path $venvDir 'Scripts\python.exe'
$server = Join-Path $mcpDir 'server.py'
$credDir = Join-Path $raiz 'credentials\mcp'
$credFile = Join-Path $credDir 'meta_ads_credentials.json'
$credExample = Join-Path $raiz 'configuracao\meta_ads_credentials.example.json'

function Test-MetaAdsEnvironment {
    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) { return $false }
    & $venvPython -c 'import re,sys; from importlib.metadata import version; from mcp.server.fastmcp import FastMCP; v=lambda n: tuple(int(x) for x in re.match(r"^([0-9]+)\.([0-9]+)",version(n)).groups()); raise SystemExit(0 if sys.version_info[:2]==(3,14) and (1,28)<=v("mcp")<(2,0) and (2,33)<=v("requests")<(3,0) else 1)' *> $null
    if ($LASTEXITCODE -ne 0) { return $false }
    & $venvPython -m pip check *> $null
    return ($LASTEXITCODE -eq 0)
}
function Install-MetaAdsEnvironment {
    param([switch]$Force)
    if ((Test-MetaAdsEnvironment) -and -not $Force) {
        Write-Host 'Ambiente MCP compatível: nenhuma reinstalação de dependências necessária.'
        return
    }
    $backup = $null
    try {
        if ($Force -and (Test-Path -LiteralPath $venvDir)) {
            $backup = $venvDir + '.recuperacao-' + [Guid]::NewGuid().ToString('N')
            Move-Item -LiteralPath $venvDir -Destination $backup
        }
        if (-not (Test-Path -LiteralPath $venvPython)) {
            if (Get-Command py -ErrorAction SilentlyContinue) {
                & py -3.14 -m venv $venvDir
            } elseif (Get-Command python -ErrorAction SilentlyContinue) {
                & python -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3,14) else 1)'
                if ($LASTEXITCODE -ne 0) { throw 'É necessário Python 3.14 para este conector.' }
                & python -m venv $venvDir
            } else { throw 'Python 3.14 não encontrado.' }
            if ($LASTEXITCODE -ne 0) { throw 'Falha ao criar ambiente virtual MCP.' }
        }
        & $venvPython -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3,14) else 1)' *> $null
        if ($LASTEXITCODE -ne 0) { throw 'O ambiente MCP existente não usa Python 3.14. Preserve-o ou escolha reinstalação explícita do conector.' }
        & $venvPython -m pip install -r (Join-Path $mcpDir 'requirements.txt')
        if ($LASTEXITCODE -ne 0 -or -not (Test-MetaAdsEnvironment)) { throw 'As dependências MCP não puderam ser instaladas e validadas.' }
        if ($backup) { Remove-Item -LiteralPath $backup -Recurse -Force }
    } catch {
        if ($backup -and (Test-Path -LiteralPath $backup)) {
            if (Test-Path -LiteralPath $venvDir) { Remove-Item -LiteralPath $venvDir -Recurse -Force }
            Move-Item -LiteralPath $backup -Destination $venvDir
        }
        throw
    }
}
function Confirm-McpRegistration {
    $previousErrorAction = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $raw = & codex mcp get nexoflow-meta-read --json 2>$null
        $code = $LASTEXITCODE
    } finally { $ErrorActionPreference = $previousErrorAction }
    if ($code -ne 0) { return $false }
    try { $record = ($raw -join "`n") | ConvertFrom-Json } catch { throw 'Cadastro MCP ilegível. Nenhum servidor foi alterado.' }
    $transport = $record.transport
    $argumentos = @($transport.args)
    if ($record.enabled -eq $false -or $transport.type -ne 'stdio' -or $transport.command -ne $venvPython -or
        $argumentos.Count -ne 1 -or $argumentos[0] -ne $server -or
        ($transport.env -and @($transport.env.PSObject.Properties).Count -gt 0) -or
        ($transport.env_vars -and @($transport.env_vars).Count -gt 0)) {
        throw 'nexoflow-meta-read já existe com configuração diferente. Nada foi sobrescrito. Confira comando, argumento e ausência de credenciais no cadastro antes de ajustá-lo manualmente.'
    }
    return $true
}


if ($FunctionsOnly) { return }
. (Join-Path $PSScriptRoot 'instalar_codex_cli.ps1') -FunctionsOnly
Assert-NexoCodexInteractiveUser
if ($InstalarCodex) { Install-NexoCodexCli -Force:$Reinstall }
Write-Host 'Instalando/validando NexoFlow Meta Ads MCP local — somente leitura.'
Install-MetaAdsEnvironment -Force:$Reinstall

New-Item -Path $credDir -ItemType Directory -Force | Out-Null
if (-not (Test-Path -LiteralPath $credFile)) {
    Copy-Item -LiteralPath $credExample -Destination $credFile
    # Um arquivo novo não deve herdar permissões de leitura de outros usuários.
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    & icacls $credFile /inheritance:r /grant:r "*$($sid):(F)" '*S-1-5-18:(F)' *> $null
    if ($LASTEXITCODE -ne 0) { throw 'Não foi possível restringir o acesso ao novo arquivo de credenciais. Verifique suas permissões NTFS.' }
    Write-Warning 'Modelo local criado. Preencha o token somente em credentials/mcp/meta_ads_credentials.json.'
} else {
    Write-Host 'Credenciais existentes preservadas. Confira suas permissões NTFS; nenhum token foi lido ou exibido.'
}
Push-Location $raiz
try {
    & $venvPython -m unittest discover -s 'connectors/meta_ads_mcp/tests' -p 'test_*.py' -v
    if ($LASTEXITCODE -ne 0) { throw 'Testes offline do MCP falharam; registro não realizado.' }
} finally { Pop-Location }


if (-not $SemRegistroCodex) {
    if (-not (Get-Command codex -ErrorAction SilentlyContinue)) {
        throw 'Codex não encontrado no PATH. O MCP foi instalado, mas ainda não foi registrado. Execute novamente após configurar o Codex.'
    }
    if (-not (Confirm-McpRegistration)) {
        & codex mcp add nexoflow-meta-read -- $venvPython $server
        if ($LASTEXITCODE -ne 0) { throw 'Falha ao registrar o MCP no Codex.' }
        if (-not (Confirm-McpRegistration)) { throw 'O registro criado não pôde ser confirmado.' }
    }
    Write-Host 'Cadastro nexoflow-meta-read confirmado: STDIO, Python isolado e server.py, sem credenciais no registro.'
}
Write-Host 'Conector instalado e testes offline concluídos. Acesso real à Meta ainda exige token ads_read e confirmação da conta autorizada.'
