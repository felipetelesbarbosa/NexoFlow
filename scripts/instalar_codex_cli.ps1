[CmdletBinding()]
param([switch]$ForceReinstall, [switch]$FunctionsOnly)
$ErrorActionPreference = 'Stop'

# Oficial: https://github.com/openai/codex/blob/main/README.md
# O arquivo remoto é executado localmente; nenhum token Meta é lido aqui.
function Assert-NexoCodexInteractiveUser {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $interactive = (Get-CimInstance Win32_ComputerSystem -ErrorAction Stop).UserName
    if (-not $interactive) { throw 'Não foi possível confirmar o usuário Windows interativo. Execute este auxiliar na sessão do usuário que usará o Codex.' }
    $sid = (New-Object Security.Principal.NTAccount($interactive)).Translate([Security.Principal.SecurityIdentifier]).Value
    if ($identity.User.Value -ne $sid) { throw 'O Setup usa outra conta administrativa. Instale/registre Codex e MCP na sessão do usuário final; nenhuma configuração desta conta foi alterada.' }
}
function Update-NexoCodexPath {
    $userPath = [Environment]::GetEnvironmentVariable('Path','User')
    $machinePath = [Environment]::GetEnvironmentVariable('Path','Machine')
    $env:Path = ($env:Path, $userPath, $machinePath | Where-Object { $_ }) -join ';'
}
function Test-NexoCodexCompatible {
    if (-not (Get-Command codex -ErrorAction SilentlyContinue)) { return $false }
    $versionOutput = & codex --version 2>$null
    if ($LASTEXITCODE -ne 0 -or (($versionOutput -join '') -notmatch '^codex-cli\s+\d+\.\d+\.\d+')) { return $false }
    $getHelp = & codex mcp get --help 2>$null
    if ($LASTEXITCODE -ne 0 -or (($getHelp -join "`n") -notmatch '--json')) { return $false }
    $addHelp = & codex mcp add --help 2>$null
    return ($LASTEXITCODE -eq 0 -and (($addHelp -join "`n") -match '--COMMAND|COMMAND|command'))
}
function Get-NexoCodexReleasesPath {
    $dataRoot = if ([string]::IsNullOrWhiteSpace($env:CODEX_HOME)) {
        Join-Path ([Environment]::GetFolderPath('UserProfile')) '.codex'
    } else { $env:CODEX_HOME }
    return [IO.Path]::GetFullPath((Join-Path $dataRoot 'packages/standalone/releases'))
}
function Assert-NexoCodexProgramPath {
    param([string]$Path)
    $candidate = [IO.Path]::GetFullPath($Path)
    while ($candidate) {
        if (Test-Path -LiteralPath $candidate) {
            $item = Get-Item -LiteralPath $candidate -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw 'Reinstalação do Codex bloqueada: a pasta de programa ou um ancestral é um link/reparse point. Nenhuma credencial ou configuração foi modificada.'
            }
        }
        $parent = [IO.Path]::GetDirectoryName($candidate)
        if ($parent -eq $candidate) { break }
        $candidate = $parent
    }
}
function Assert-NexoCodexInstallerIntegrity {
    param([Parameter(Mandatory = $true)][string]$Path)
    # Snapshot do script oficial consultado em 04/11/2026. Mudança remota
    # exige nova revisão no repositório; nunca aceitar o hash vindo do download.
    $expected = 'b3664171771ff083ee95f74030070cf23fd13797472d84e387653c0df36042c3'
    $actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -cne $expected) {
        throw 'O instalador Codex divergiu do snapshot aprovado. Nenhum script baixado foi executado; solicite revisão da integração opcional.'
    }
}
function Install-NexoCodexCli {
    param([switch]$Force)
    Assert-NexoCodexInteractiveUser
    if ((Test-NexoCodexCompatible) -and -not $Force) {
        Write-Host 'Codex CLI existente compatível: instalação e configurações preservadas.'
        return
    }
    $folder = Join-Path ([IO.Path]::GetTempPath()) ('NexoFlow-Codex-' + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $folder | Out-Null
    $releasesPath = $null
    $programBackup = $null
    try {
        $scriptFile = Join-Path $folder 'install-codex.ps1'
        Invoke-WebRequest -Uri 'https://chatgpt.com/codex/install.ps1' -OutFile $scriptFile -UseBasicParsing
        Assert-NexoCodexInstallerIntegrity -Path $scriptFile
        $tokens = $null; $parseErrors = $null
        [void][Management.Automation.Language.Parser]::ParseFile($scriptFile,[ref]$tokens,[ref]$parseErrors)
        if ($parseErrors.Count -gt 0) { throw 'O instalador oficial baixado não é um script PowerShell válido.' }
        if ($Force) {
            # Somente binários do standalone oficial, nunca a raiz .codex,
            # auth.json, config.toml, projetos ou cadastros MCP.
            $releasesPath = Get-NexoCodexReleasesPath
            Assert-NexoCodexProgramPath -Path $releasesPath
            if (Test-Path -LiteralPath $releasesPath) {
                if (-not (Test-Path -LiteralPath $releasesPath -PathType Container)) { throw 'A pasta de releases do Codex não é um diretório.' }
                $programBackup = $releasesPath + '.nexoflow-recuperacao-' + [Guid]::NewGuid().ToString('N')
                Move-Item -LiteralPath $releasesPath -Destination $programBackup
            }
        }
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $scriptFile
        if ($LASTEXITCODE -ne 0) { throw 'O instalador oficial do Codex não concluiu.' }
        Update-NexoCodexPath
        if (-not (Test-NexoCodexCompatible)) { throw 'Codex instalado, mas sua CLI não foi localizada ou não oferece cadastro MCP STDIO compatível. Abra novo terminal e repita a validação.' }
        Write-Host 'Codex CLI instalado/validado. O login deve ser feito manualmente pelo usuário; nenhuma chave foi criada ou copiada.'
        if ($programBackup) { Write-Host 'Os binários anteriores do Codex foram mantidos em uma pasta privada de recuperação, ao lado de releases. Configurações e autenticação permaneceram no lugar.' }
    } catch {
        if ($programBackup -and (Test-Path -LiteralPath $programBackup -PathType Container)) {
            Assert-NexoCodexProgramPath -Path $releasesPath
            if (Test-Path -LiteralPath $releasesPath) {
                # Não apagar arquivos de uma tentativa incompleta: arquivar
                # somente a nova pasta de programa e restaurar a anterior.
                $failedProgram = $releasesPath + '.nexoflow-incompleto-' + [Guid]::NewGuid().ToString('N')
                Move-Item -LiteralPath $releasesPath -Destination $failedProgram
            }
            Move-Item -LiteralPath $programBackup -Destination $releasesPath
        }
        throw
    } finally {
        Remove-Item -LiteralPath $folder -Recurse -Force -ErrorAction SilentlyContinue
    }
}
if (-not $FunctionsOnly) { Install-NexoCodexCli -Force:$ForceReinstall }
