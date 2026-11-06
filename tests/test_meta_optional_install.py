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

    def test_changed_remote_installer_is_rejected_before_execution(self):
        self.run_ps(r"""
. (Join-Path $repo 'scripts/instalar_codex_cli.ps1') -FunctionsOnly
$fixture=Join-Path ([IO.Path]::GetTempPath()) ('nexo-hash-'+[Guid]::NewGuid().ToString('N'))
try {
 'untrusted-script'|Set-Content -LiteralPath $fixture
 $blocked=$false
 try{Assert-NexoCodexInstallerIntegrity -Path $fixture}catch{$blocked=$true}
 if(-not $blocked){throw 'Script alterado foi aceito.'}
}finally{Remove-Item -LiteralPath $fixture -Force}
""")

    def test_setup_network_choice_propagates_to_children_without_settings_write(self):
        self.run_ps(r"""
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $repo 'installer/install.ps1'),[ref]$tokens,[ref]$errors)
$f=$ast.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Select-SetupNetwork'},$true)
. ([scriptblock]::Create($f.Extent.Text))
$NonInteractive=$true
function Read-Host { throw 'Não deveria solicitar entrada.' }
$NetworkMode='Personal'
Select-SetupNetwork
if($env:NEXOFLOW_NETWORK_MODE -ne 'personal'){throw 'Rota pessoal não propagada.'}
$NetworkMode='Corporate'
Select-SetupNetwork
if($env:NEXOFLOW_NETWORK_MODE -ne 'corporate'){throw 'Rota corporativa não propagada.'}
""")

    def test_codex_compatible_twice_never_downloads_or_installs(self):
        self.run_ps(r"""
. (Join-Path $repo 'scripts/instalar_codex_cli.ps1') -FunctionsOnly
function Assert-NexoCodexInteractiveUser { }
function Assert-NexoCodexInstallerIntegrity { }
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
function Assert-NexoCodexInstallerIntegrity { }
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

    def test_setup_optional_fatal_child_exit_is_pending_and_does_not_abort(self):
        self.run_ps(r"""
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $repo 'installer/install.ps1'),[ref]$tokens,[ref]$errors)
$function=$ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Invoke-OptionalMetaAdsSetup'},$true)
Invoke-Expression $function.Extent.Text
$InstallDir=Join-Path ([IO.Path]::GetTempPath()) ('nexo-optional-test-'+[Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory (Join-Path $InstallDir 'logs'),(Join-Path $InstallDir 'scripts') -Force|Out-Null
try{
 $helper=Join-Path $InstallDir 'scripts/instalar_meta_ads_mcp.ps1'
 "param([switch]`$InstalarCodex,[switch]`$Reinstall)" | Set-Content -LiteralPath $helper
 function Start-Process { [pscustomobject]@{ExitCode=1073741845} }
 Invoke-OptionalMetaAdsSetup -Unattended
 $status=Join-Path $InstallDir 'logs/meta_ads_mcp_instalacao.json'
 if(Test-Path -LiteralPath $status){throw 'Não deveria tentar a integração sem a flag.'}
 Invoke-OptionalMetaAdsSetup -Selected -Unattended
 $record=Get-Content -LiteralPath $status -Raw|ConvertFrom-Json
 if($record.status -ne 'pendente'){throw 'Falha opcional sem pendência.'}
 if($record.proxima_acao -match 'InstalarCodex'){throw 'Orientação legada no JSON.'}
}finally{Remove-Item -LiteralPath $InstallDir -Recurse -Force}
""")

    def test_mcp_status_references_separate_report_without_reading_or_changing_it(self):
        self.run_ps(r"""
. (Join-Path $repo 'scripts/instalar_meta_ads_mcp.ps1') -FunctionsOnly
$fixture=Join-Path ([IO.Path]::GetTempPath()) ('nexo-mcp-report-'+[Guid]::NewGuid().ToString('N'))
$raiz=$fixture
$Perfil='PET'
New-Item -ItemType Directory (Join-Path $fixture 'logs') -Force|Out-Null
try{
 $report=Join-Path $fixture 'logs/meta_ads_mcp_dependencias.json'
 'SYNTHETIC_PRIVATE_DIAGNOSTIC'|Set-Content -LiteralPath $report
 $before=(Get-FileHash -LiteralPath $report).Hash
 foreach($expected in @('instalado','pendente')){
  Write-MetaAdsInstallStatus -Status $expected
  $text=Get-Content -LiteralPath (Join-Path $fixture 'logs/meta_ads_mcp_instalacao.json') -Raw
  $record=$text|ConvertFrom-Json
  if($record.status -ne $expected){throw 'Status do auxiliar incorreto.'}
  if($record.diagnostico_dependencias -cne 'logs/meta_ads_mcp_dependencias.json'){throw 'Referência do diagnóstico ausente ou não relativa.'}
  if($text -match 'SYNTHETIC_PRIVATE_DIAGNOSTIC'){throw 'Conteúdo do relatório propagado ao status.'}
  if((Get-FileHash -LiteralPath $report).Hash -ne $before){throw 'Relatório de dependências alterado pelo auxiliar.'}
 }
}finally{Remove-Item -LiteralPath $fixture -Recurse -Force}
""")

    def test_setup_status_keeps_dependency_report_reference_for_success_and_failure(self):
        self.run_ps(r"""
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $repo 'installer/install.ps1'),[ref]$tokens,[ref]$errors)
$function=$ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Invoke-OptionalMetaAdsSetup'},$true)
Invoke-Expression $function.Extent.Text
$InstallDir=Join-Path ([IO.Path]::GetTempPath()) ('nexo-setup-report-'+[Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory (Join-Path $InstallDir 'logs'),(Join-Path $InstallDir 'scripts'),(Join-Path $InstallDir 'credentials') -Force|Out-Null
try{
 'param()'|Set-Content -LiteralPath (Join-Path $InstallDir 'scripts/instalar_meta_ads_mcp.ps1')
 $report=Join-Path $InstallDir 'logs/meta_ads_mcp_dependencias.json'
 'SYNTHETIC_PRIVATE_DIAGNOSTIC'|Set-Content -LiteralPath $report
 $credential=Join-Path $InstallDir 'credentials/existing.json'
 'SYNTHETIC_META_CREDENTIAL'|Set-Content -LiteralPath $credential
 $reportBefore=(Get-FileHash -LiteralPath $report).Hash
 $credentialBefore=(Get-FileHash -LiteralPath $credential).Hash
 function Start-Process { [pscustomobject]@{ExitCode=$script:helperExitCode} }
 foreach($case in @(@{Code=0;Status='instalado'},@{Code=1073741845;Status='pendente'})){
  $script:helperExitCode=$case.Code
  Invoke-OptionalMetaAdsSetup -Selected -Unattended
  $text=Get-Content -LiteralPath (Join-Path $InstallDir 'logs/meta_ads_mcp_instalacao.json') -Raw
  $record=$text|ConvertFrom-Json
  if($record.status -ne $case.Status){throw 'Status do Setup incorreto.'}
  if($record.diagnostico_dependencias -cne 'logs/meta_ads_mcp_dependencias.json'){throw 'Setup perdeu a referência relativa do diagnóstico.'}
  if($text -match 'SYNTHETIC_PRIVATE_DIAGNOSTIC|SYNTHETIC_META_CREDENTIAL'){throw 'Conteúdo privado propagado ao status.'}
  if((Get-FileHash -LiteralPath $report).Hash -ne $reportBefore){throw 'Setup alterou o relatório de dependências.'}
  if((Get-FileHash -LiteralPath $credential).Hash -ne $credentialBefore){throw 'Setup alterou credencial existente.'}
 }
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
 "param([switch]`$InstalarCodex,[switch]`$Reinstall)" | Set-Content -LiteralPath (Join-Path $InstallDir 'scripts/instalar_meta_ads_mcp.ps1')
 $script:helperArguments=@()
 function Start-Process {
  param($FilePath,$ArgumentList,[switch]$Wait,[switch]$PassThru,[switch]$NoNewWindow,$ErrorAction)
  $script:helperArguments=@($ArgumentList)
  [pscustomobject]@{ExitCode=0}
 }
 Invoke-OptionalMetaAdsSetup -Selected -Unattended -Mode Preserve
 if($script:helperArguments -contains '-Reinstall'){throw 'Preserve não deve forçar reinstalação.'}
 Invoke-OptionalMetaAdsSetup -Selected -Unattended -Mode Clean
 if($script:helperArguments -notcontains '-Reinstall'){throw 'Clean selecionado deve forçar reinstalação.'}
 $status=Get-Content -LiteralPath (Join-Path $InstallDir 'logs/meta_ads_mcp_instalacao.json') -Raw|ConvertFrom-Json
 if($status.status -ne 'instalado'){throw 'Sucesso isolado não foi registrado.'}
}finally{Remove-Item -LiteralPath $InstallDir -Recurse -Force}
""")

    def test_mcp_installer_has_no_codex_execution_or_registration(self):
        helper = (ROOT / "scripts/instalar_meta_ads_mcp.ps1").read_text(encoding="utf-8-sig")
        setup = (ROOT / "installer/install.ps1").read_text(encoding="utf-8-sig")
        for forbidden in ("Install-NexoCodexCli", "Assert-NexoCodexInteractiveUser", "Get-Command codex", "& codex", "instalar_codex_cli.ps1"):
            self.assertNotIn(forbidden, helper)
        self.assertNotIn("'-InstalarCodex'", setup)
        self.assertNotIn("codex_login", setup)
        self.assertNotIn("Codex CLI e Meta Ads MCP", setup)

    def test_full_mcp_path_ignores_legacy_codex_flag_and_preserves_credentials(self):
        self.run_ps(r"""
. (Join-Path $repo 'scripts/instalar_meta_ads_mcp.ps1') -FunctionsOnly
$fixture=Join-Path ([IO.Path]::GetTempPath()) ('nexo-mcp-independent-'+[Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $fixture|Out-Null
try {
 $raiz=$fixture
 $credDir=$fixture
 $credFile=Join-Path $fixture 'credentials.json'
 'SYNTHETIC_META_CREDENTIAL'|Set-Content -LiteralPath $credFile
 $before=(Get-FileHash -LiteralPath $credFile).Hash
 $venvPython=Join-Path $fixture 'offline.ps1'
 '$global:LASTEXITCODE=0'|Set-Content -LiteralPath $venvPython
 function Install-MetaAdsEnvironment { $script:mcpAttempted=$true }
 function codex { throw 'Não pode iniciar Codex.' }
 $InstalarCodex=$true; $SemRegistroCodex=$false; $FunctionsOnly=$false
 $source=Get-Content -LiteralPath (Join-Path $repo 'scripts/instalar_meta_ads_mcp.ps1') -Raw
 $body=$source.Substring($source.IndexOf('if ($FunctionsOnly) { return }'))
 Invoke-Expression $body
 if(-not $script:mcpAttempted){throw 'MCP não foi instalado independentemente.'}
 if((Get-FileHash -LiteralPath $credFile).Hash -ne $before){throw 'Credencial alterada.'}
 $status=Get-Content -LiteralPath (Join-Path $fixture 'logs/meta_ads_mcp_instalacao.json') -Raw|ConvertFrom-Json
 if($status.status -ne 'instalado'){throw 'Reexecução manual não atualizou status.'}
 function Install-MetaAdsEnvironment { throw 'SYNTHETIC_PRIVATE_ERROR' }
 $failed=$false
 try{Invoke-Expression $body}catch{ $failed=$true; if($_.Exception.Message -match 'SYNTHETIC_PRIVATE_ERROR'){throw 'Erro privado exposto.'} }
 if(-not $failed){throw 'Falha independente foi ignorada.'}
 $status=Get-Content -LiteralPath (Join-Path $fixture 'logs/meta_ads_mcp_instalacao.json') -Raw|ConvertFrom-Json
 if($status.status -ne 'pendente' -or $status.proxima_acao -match 'InstalarCodex'){throw 'Pendência independente inválida.'}
 if((Get-FileHash -LiteralPath $credFile).Hash -ne $before){throw 'Falha alterou credencial.'}
}finally{Remove-Item -LiteralPath $fixture -Recurse -Force}
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
function Assert-NexoCodexInstallerIntegrity { }
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
function Invoke-MetaAdsDependencyInstall { $global:LASTEXITCODE=0 }
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
