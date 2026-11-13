$ErrorActionPreference = 'Stop'
$tokens = $null; $errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot '../installer/install.ps1'), [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'Sintaxe do instalador inválida.' }
foreach ($name in @('Get-VerifiedPythonInstaller','Get-Sha256File','Install-PythonIfNeeded')) {
    $node = $ast.Find({ param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name }, $true)
    Invoke-Expression $node.Extent.Text
}
function Write-Step { param($Message) }
$PythonInstallerUrl = 'https://www.python.org/ftp/python/3.14.8/python-3.14.8-amd64.exe'
$bytes = [Text.Encoding]::UTF8.GetBytes('synthetic-only')
$sha = [Security.Cryptography.SHA256]::Create()
$BundledPythonSha256 = ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-','').ToLowerInvariant()
$script:mode = 'success'; $script:DownloadedPythonDirectory = $null
function Invoke-WebRequest {
    param($Uri,$OutFile,[switch]$UseBasicParsing,$TimeoutSec,$ErrorAction)
    if ($Uri -ne $PythonInstallerUrl -or $TimeoutSec -ne 180) { throw 'Destino inesperado.' }
    if ($script:mode -eq 'network') { throw 'synthetic-network-failure' }
    [IO.File]::WriteAllBytes($OutFile, $bytes)
}
try {
    function Get-CompatiblePython { return @{Path='C:\synthetic\python.exe';Validated=$true;Version='3.14';Bits=64} }
    function Confirm-PythonInstall { throw 'Não deveria pedir download com Python existente.' }
    if ((Install-PythonIfNeeded) -ne 'C:\synthetic\python.exe') { throw 'Python existente não foi reaproveitado.' }
    $file = Get-VerifiedPythonInstaller
    if (-not (Test-Path -LiteralPath $file)) { throw 'Download não confirmado.' }
    Remove-Item -LiteralPath $script:DownloadedPythonDirectory -Recurse -Force
    foreach ($mode in @('hash','network')) {
        $script:mode = $mode
        if ($mode -eq 'hash') { $BundledPythonSha256 = 'invalid' }
        $blocked = $false
        try { Get-VerifiedPythonInstaller | Out-Null } catch { $blocked = $true }
        if (-not $blocked -or $script:DownloadedPythonDirectory) { throw 'Falha não bloqueada/limpa.' }
    }
    Write-Host '[OK] Download oficial: sucesso, hash divergente e falha de rede; sem executar instaladores.'
} finally {
    if ($script:DownloadedPythonDirectory) { Remove-Item -LiteralPath $script:DownloadedPythonDirectory -Recurse -Force }
}
