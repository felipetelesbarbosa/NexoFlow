[CmdletBinding()]
param([switch]$SemRegistroCodex, [switch]$InstalarCodex, [switch]$Reinstall, [switch]$FunctionsOnly,
      [ValidateSet('FARMA','PET')][string]$Perfil = $(if ($env:NEXOFLOW_PERFIL) { $env:NEXOFLOW_PERFIL } else { 'FARMA' }))

$ErrorActionPreference = 'Stop'
$raiz = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$mcpDir = Join-Path $raiz 'connectors\meta_ads_mcp'
$venvDir = Join-Path $mcpDir '.venv'
$venvPython = Join-Path $venvDir 'Scripts\python.exe'
$credDir = Join-Path $raiz 'credentials\mcp'
$credFile = Join-Path $credDir 'meta_ads_credentials.json'
$credExample = Join-Path $raiz 'configuracao\meta_ads_credentials.example.json'

function Test-MetaAdsEnvironment {
    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) { return $false }
    & $venvPython (Join-Path $mcpDir 'validate_environment.py') *> $null
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
    $refreshEnvironment = [bool]$Force
    if (Test-Path -LiteralPath $venvDir) {
        if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
            & $venvPython (Join-Path $mcpDir 'validate_environment.py') --python-only *> $null
            if ($LASTEXITCODE -ne 0) { $refreshEnvironment = $true }
        } else { $refreshEnvironment = $true }
    }
    try {
        if ($refreshEnvironment -and (Test-Path -LiteralPath $venvDir)) {
            $backup = $venvDir + '.recuperacao-' + [Guid]::NewGuid().ToString('N')
            Move-Item -LiteralPath $venvDir -Destination $backup
        }
        if (-not (Test-Path -LiteralPath $venvPython)) {
            if (Get-Command py -ErrorAction SilentlyContinue) {
                & py -3.14 -m venv $venvDir
            } elseif (Get-Command python -ErrorAction SilentlyContinue) {
                & python (Join-Path $mcpDir 'validate_environment.py') --python-only
                if ($LASTEXITCODE -ne 0) { throw 'É necessário Python 3.14 para este conector.' }
                & python -m venv $venvDir
            } else { throw 'Python 3.14 não encontrado.' }
            if ($LASTEXITCODE -ne 0) { throw 'Falha ao criar ambiente virtual MCP.' }
        }
        & $venvPython (Join-Path $mcpDir 'validate_environment.py') --python-only *> $null
        if ($LASTEXITCODE -ne 0) { throw 'O ambiente MCP recriado não usa Python 3.14. A instalação anterior será recuperada.' }
        Invoke-MetaAdsDependencyInstall
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
function Invoke-MetaAdsDependencyInstall {
    $nativePython = Join-Path $raiz '.venv/Scripts/python.exe'
    $runner = Join-Path $raiz 'app/run_mcp_pip.py'
    if (-not (Test-Path -LiteralPath $nativePython -PathType Leaf) -or -not (Test-Path -LiteralPath $runner -PathType Leaf)) {
        throw 'Ambiente principal do NexoFlow ou auxiliar de rede ausente. Conclua o Setup antes de instalar o MCP.'
    }
    & $nativePython $runner --python $venvPython --perfil $Perfil
    if ($LASTEXITCODE -ne 0) { throw 'Instalação MCP pendente. Confira o diagnóstico sanitizado em logs/meta_ads_mcp_dependencias.json; falha do índice não comprova ausência do pacote.' }
}

function Write-MetaAdsInstallStatus {
    param([ValidateSet('instalado','pendente')][string]$Status)
    $folder = Join-Path $raiz 'logs'
    New-Item -ItemType Directory -Force -Path $folder | Out-Null
    $record = @{ componente = 'Meta Ads MCP'; status = $Status; perfil_rede = $Perfil;
        acesso_meta = 'nao_validado'; registro_cliente = 'manual_opcional';
        diagnostico_dependencias = 'logs/meta_ads_mcp_dependencias.json';
        atualizado_em = (Get-Date).ToUniversalTime().ToString('o') }
    if ($Status -eq 'pendente') {
        $record.proxima_acao = "Executar scripts/instalar_meta_ads_mcp.ps1 -Perfil $Perfil após conferir a configuração de rede"
    }
    $record | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $folder 'meta_ads_mcp_instalacao.json') -Encoding UTF8
}

if ($FunctionsOnly) { return }
# Compatibilidade: aceitar chamadas antigas, sem instalar/validar/registrar Codex.
if ($InstalarCodex -or $SemRegistroCodex) {
    Write-Warning 'Parâmetro legado ignorado. Este auxiliar instala somente o MCP e não acessa configurações de clientes de IA.'
}
try {
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


Write-Host 'Conector instalado e testes offline concluídos. Acesso real à Meta ainda exige token ads_read e confirmação da conta autorizada.'
Write-Host 'Status: logs/meta_ads_mcp_instalacao.json. Diagnóstico da última etapa pip, quando executada: logs/meta_ads_mcp_dependencias.json.'

    Write-MetaAdsInstallStatus -Status instalado
} catch {
    try { Write-MetaAdsInstallStatus -Status pendente } catch { }
    throw 'Meta Ads MCP pendente. Confira logs/meta_ads_mcp_instalacao.json e logs/meta_ads_mcp_dependencias.json (última etapa pip, quando executada); a instalação principal foi preservada.'
}
