"""PowerShell de instalação opcional: comandos externos são simulados."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")
if not POWERSHELL:
    private = Path("/workspace/private/powershell/pwsh")
    POWERSHELL = str(private) if private.is_file() else None


@unittest.skipUnless(
    POWERSHELL, "PowerShell necessário para executar o contrato do instalador."
)
class OptionalInstallTests(unittest.TestCase):
    def run_ps(self, code):
        with tempfile.TemporaryDirectory(prefix="nexo_optional_") as directory:
            path = Path(directory) / "harness.ps1"
            prefix = (
                "$ErrorActionPreference='Stop'\n$repo="
                + "'"
                + str(ROOT).replace("'", "''")
                + "'\n"
            )
            path.write_text(prefix + code, encoding="utf-8-sig")
            result = subprocess.run(
                [POWERSHELL, "-NoProfile", "-File", str(path)],
                capture_output=True,
                text=True,
                timeout=40,
            )
            self.assertEqual(
                result.returncode, 0, (result.stdout + result.stderr)[-4000:]
            )

    def test_codex_compatible_twice_never_downloads_or_installs(self):
        self.run_ps(r"""
. (Join-Path $repo 'scripts/instalar_codex_cli.ps1') -FunctionsOnly
function Assert-NexoCodexInteractiveUser { }
function codex {
 if ($args -contains '--version') { 'codex-cli 0.100.0' }
 elseif ($args -contains 'get') { '--json' }
 else { 'COMMAND' }
 $global:LASTEXITCODE=0
}
function Invoke-WebRequest { throw 'Download desnecessário.' }
Install-NexoCodexCli
Install-NexoCodexCli
""")

    def test_codex_force_runs_official_installer_without_touching_auth(self):
        self.run_ps(r"""
. (Join-Path $repo 'scripts/instalar_codex_cli.ps1') -FunctionsOnly
function Assert-NexoCodexInteractiveUser { }
function Test-NexoCodexCompatible { return $true }
function Update-NexoCodexPath { }
function Get-NexoCodexReleasesPath { return (Join-Path ([IO.Path]::GetTempPath()) ('nexo-codex-no-releases-'+[Guid]::NewGuid().ToString('N'))) }
$script:downloads=0; $script:installs=0
function Invoke-WebRequest { param($Uri,$OutFile,[switch]$UseBasicParsing)
 if($Uri -cne 'https://chatgpt.com/codex/install.ps1'){throw 'Origem inesperada'}
 '# instalador sintético' | Set-Content -LiteralPath $OutFile
 $script:downloads++
}
function powershell.exe { $script:installs++; $global:LASTEXITCODE=0 }
Install-NexoCodexCli -Force
if($script:downloads -ne 1 -or $script:installs -ne 1){throw 'Reinstalação não foi executada uma vez.'}
""")

    def test_mcp_compatible_twice_skips_pip_install(self):
        self.run_ps(r"""
. (Join-Path $repo 'scripts/instalar_meta_ads_mcp.ps1') -FunctionsOnly
function Test-MetaAdsEnvironment { return $true }
$venvPython='never-run-this'
Install-MetaAdsEnvironment
Install-MetaAdsEnvironment
""")

    def test_setup_optional_failure_is_pending_and_noninteractive_default_skips(self):
        self.run_ps(r"""
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $repo 'installer/install.ps1'),[ref]$tokens,[ref]$errors)
$function=$ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Invoke-OptionalMetaAdsSetup'},$true)
Invoke-Expression $function.Extent.Text
$InstallDir=Join-Path ([IO.Path]::GetTempPath()) ('nexo-optional-test-'+[Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory (Join-Path $InstallDir 'logs'),(Join-Path $InstallDir 'scripts') -Force|Out-Null
try{
 $helper=Join-Path $InstallDir 'scripts/instalar_meta_ads_mcp.ps1'
 "param([switch]`$InstalarCodex,[switch]`$Reinstall); throw 'falha sintética'" | Set-Content -LiteralPath $helper
 Invoke-OptionalMetaAdsSetup -Unattended
 $status=Join-Path $InstallDir 'logs/meta_ads_mcp_instalacao.json'
 if(Test-Path -LiteralPath $status){throw 'Não deveria tentar a integração sem a flag.'}
 Invoke-OptionalMetaAdsSetup -Selected -Unattended
 if((Get-Content -LiteralPath $status -Raw|ConvertFrom-Json).status -ne 'pendente'){throw 'Falha opcional sem pendência.'}
}finally{Remove-Item -LiteralPath $InstallDir -Recurse -Force}
""")

    def test_clean_selected_forces_reinstall_and_preserve_does_not(self):
        self.run_ps(r"""
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $repo 'installer/install.ps1'),[ref]$tokens,[ref]$errors)
$function=$ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Invoke-OptionalMetaAdsSetup'},$true)
Invoke-Expression $function.Extent.Text
$InstallDir=Join-Path ([IO.Path]::GetTempPath()) ('nexo-optional-test-'+[Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory (Join-Path $InstallDir 'logs'),(Join-Path $InstallDir 'scripts') -Force|Out-Null
try{
 "param([switch]`$InstalarCodex,[switch]`$Reinstall); `$global:requestedReinstall=[bool]`$Reinstall" | Set-Content -LiteralPath (Join-Path $InstallDir 'scripts/instalar_meta_ads_mcp.ps1')
 Invoke-OptionalMetaAdsSetup -Selected -Unattended -Mode Preserve
 if($global:requestedReinstall){throw 'Preserve não deve forçar reinstalação.'}
 Invoke-OptionalMetaAdsSetup -Selected -Unattended -Mode Clean
 if(-not $global:requestedReinstall){throw 'Clean selecionado deve forçar reinstalação.'}
}finally{Remove-Item -LiteralPath $InstallDir -Recurse -Force}
""")

    def test_registration_compatible_twice_never_adds_or_overwrites(self):
        self.run_ps(r"""
. (Join-Path $repo 'scripts/instalar_meta_ads_mcp.ps1') -FunctionsOnly
$script:getCalls=0
function codex {
 if($args -contains 'add'){throw 'Cadastro existente não deve ser substituído.'}
 $script:getCalls++
 @{enabled=$true;transport=@{type='stdio';command=$venvPython;args=@($server);env=@{};env_vars=@()}}|ConvertTo-Json -Depth 4
 $global:LASTEXITCODE=0
}
if(-not (Confirm-McpRegistration)){throw 'Registro não confirmado.'}
if(-not (Confirm-McpRegistration)){throw 'Registro não confirmado na repetição.'}
if($script:getCalls -ne 2){throw 'Quantidade inesperada de consultas locais.'}
""")

    def test_registration_different_command_is_rejected_without_overwrite(self):
        self.run_ps(r"""
. (Join-Path $repo 'scripts/instalar_meta_ads_mcp.ps1') -FunctionsOnly
function codex {
 if($args -contains 'add'){throw 'Não deve alterar cadastro divergente.'}
 @{enabled=$true;transport=@{type='stdio';command='outra-conta.exe';args=@($server)}}|ConvertTo-Json -Depth 4
 $global:LASTEXITCODE=0
}
$failed=$false
try{[void](Confirm-McpRegistration)}catch{$failed=$true}
if(-not $failed){throw 'Configuração diferente não foi bloqueada.'}
""")

    def test_clean_codex_fresh_releases_preserves_authentication(self):
        self.clean_codex_releases_case(fail=False)

    def test_clean_codex_failure_restores_old_releases_and_authentication(self):
        self.clean_codex_releases_case(fail=True)

    def clean_codex_releases_case(self, fail):
        self.run_ps(
            "$script:failInstall="
            + ("$true" if fail else "$false")
            + r"""
. (Join-Path $repo 'scripts/instalar_codex_cli.ps1') -FunctionsOnly
function Assert-NexoCodexInteractiveUser { }
function Test-NexoCodexCompatible { return $true }
function Update-NexoCodexPath { }
$testRoot=Join-Path ([IO.Path]::GetTempPath()) ('nexo-codex-clean-'+[Guid]::NewGuid().ToString('N'))
$script:testReleases=Join-Path $testRoot 'packages/standalone/releases'
function Get-NexoCodexReleasesPath { return $script:testReleases }
New-Item -ItemType Directory -Force -Path $script:testReleases | Out-Null
'old-program' | Set-Content -LiteralPath (Join-Path $script:testReleases 'old.exe')
$auth=Join-Path $testRoot 'auth.json'
$config=Join-Path $testRoot 'config.toml'
'authentication-synthetic'|Set-Content -LiteralPath $auth
'mcp-existing-synthetic'|Set-Content -LiteralPath $config
$authBefore=(Get-FileHash -LiteralPath $auth).Hash
$configBefore=(Get-FileHash -LiteralPath $config).Hash
function Invoke-WebRequest { param($Uri,$OutFile,[switch]$UseBasicParsing)
 '# instalador oficial sintético'|Set-Content -LiteralPath $OutFile
}
function powershell.exe {
 if(Test-Path -LiteralPath $script:testReleases){throw 'Os binários antigos não foram arquivados antes de reinstalar.'}
 New-Item -ItemType Directory -Force -Path $script:testReleases|Out-Null
 'new-program'|Set-Content -LiteralPath (Join-Path $script:testReleases 'new.exe')
 $global:LASTEXITCODE=0
 if($script:failInstall){$global:LASTEXITCODE=1}
}
try{
 $failed=$false
 try{Install-NexoCodexCli -Force}catch{$failed=$true}
 if($failed -ne $script:failInstall){throw 'Resultado inesperado da reinstalação.'}
 if($script:failInstall){
  if(-not (Test-Path -LiteralPath (Join-Path $script:testReleases 'old.exe'))){throw 'Programa antigo não restaurado.'}
 }else{
  if(-not (Test-Path -LiteralPath (Join-Path $script:testReleases 'new.exe'))){throw 'Programa novo não instalado.'}
  if(Test-Path -LiteralPath (Join-Path $script:testReleases 'old.exe')){throw 'Programa antigo permaneceu na instalação nova.'}
 }
 if((Get-FileHash -LiteralPath $auth).Hash -ne $authBefore){throw 'Autenticação foi alterada.'}
 if((Get-FileHash -LiteralPath $config).Hash -ne $configBefore){throw 'Configuração MCP foi alterada.'}
}finally{Remove-Item -LiteralPath $testRoot -Recurse -Force}
"""
        )

    def test_mcp_wrong_python_refreshes_only_its_environment(self):
        self.run_ps(r"""
. (Join-Path $repo 'scripts/instalar_meta_ads_mcp.ps1') -FunctionsOnly
$folder=Join-Path ([IO.Path]::GetTempPath()) ('nexo-python-refresh-'+[Guid]::NewGuid().ToString('N'))
$venvDir=Join-Path $folder '.venv'
$venvPython=Join-Path $venvDir 'python.ps1'
New-Item -ItemType Directory -Force -Path $venvDir|Out-Null
'$global:LASTEXITCODE=1'|Set-Content -LiteralPath $venvPython
$script:created=0
function py {
 $script:created++
 New-Item -ItemType Directory -Force -Path $venvDir|Out-Null
 '$global:LASTEXITCODE=0'|Set-Content -LiteralPath $venvPython
 $global:LASTEXITCODE=0
}
try{
 Install-MetaAdsEnvironment
 if($script:created -ne 1){throw 'Python incompatível não reconstruído.'}
 if(-not (Test-Path -LiteralPath $venvPython)){throw 'Python novo ausente.'}
 if(@(Get-ChildItem -LiteralPath $folder -Filter '.venv.recuperacao-*').Count){throw 'Backup não finalizado.'}
}finally{Remove-Item -LiteralPath $folder -Recurse -Force}
""")

    def test_scripts_have_bom_and_no_version_change(self):
        for name in [
            "installer/install.ps1",
            "scripts/instalar_codex_cli.ps1",
            "scripts/instalar_meta_ads_mcp.ps1",
        ]:
            self.assertTrue((ROOT / name).read_bytes().startswith(b"\xef\xbb\xbf"))
        self.assertIn(
            "[switch]$InstallMetaAdsMcp",
            (ROOT / "installer/install.ps1").read_text(encoding="utf-8-sig"),
        )
