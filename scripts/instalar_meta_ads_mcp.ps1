[CmdletBinding()]
param([switch]$SemRegistroCodex)

$ErrorActionPreference = 'Stop'
$raiz = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$mcpDir = Join-Path $raiz 'connectors\meta_ads_mcp'
$venvDir = Join-Path $mcpDir '.venv'
$venvPython = Join-Path $venvDir 'Scripts\python.exe'
$server = Join-Path $mcpDir 'server.py'
$credDir = Join-Path $raiz 'credentials\mcp'
$credFile = Join-Path $credDir 'meta_ads_credentials.json'
$credExample = Join-Path $raiz 'configuracao\meta_ads_credentials.example.json'

Write-Host 'Instalando NexoFlow Meta Ads MCP local — somente leitura.'
if (-not (Test-Path -LiteralPath $venvPython)) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.14 -m venv $venvDir
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3,14) else 1)'
        if ($LASTEXITCODE -ne 0) { throw 'É necessário Python 3.14 para este conector.' }
        & python -m venv $venvDir
    } else { throw 'Python 3.14 não encontrado. Instale-o ou configure o PATH.' }
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao criar o ambiente isolado do MCP.' }
}
& $venvPython -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3,14) else 1)'
if ($LASTEXITCODE -ne 0) { throw 'O ambiente MCP existente não usa Python 3.14; preserve-o e recrie somente connectors/meta_ads_mcp/.venv com essa versão.' }
& $venvPython -m pip install -r (Join-Path $mcpDir 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Falha ao instalar as dependências do MCP.' }

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

function Confirm-McpRegistration {
    $raw = & codex mcp get nexoflow-meta-read --json 2>$null
    if ($LASTEXITCODE -ne 0) { return $false }
    try { $record = ($raw -join "`n") | ConvertFrom-Json } catch { throw 'Cadastro MCP ilegível. Nenhum servidor foi alterado.' }
    $transport = $record.transport
    $argumentos = @($transport.args)
    if ($transport.type -ne 'stdio' -or $transport.command -ne $venvPython -or
        $argumentos.Count -ne 1 -or $argumentos[0] -ne $server -or
        ($transport.env -and @($transport.env.PSObject.Properties).Count -gt 0) -or
        ($transport.env_vars -and @($transport.env_vars).Count -gt 0)) {
        throw 'nexoflow-meta-read já existe com configuração diferente. Nada foi sobrescrito. Confira comando, argumento e ausência de credenciais no cadastro antes de ajustá-lo manualmente.'
    }
    return $true
}

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
