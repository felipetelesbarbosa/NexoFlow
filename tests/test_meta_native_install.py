"""Instalação Meta nativa sem SDK MCP; credenciais sintéticas e testes offline."""

import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")
if not POWERSHELL:
    candidate = Path("/workspace/private/powershell/pwsh")
    POWERSHELL = str(candidate) if candidate.is_file() else None


@unittest.skipUnless(POWERSHELL, "Requer PowerShell para exercitar o instalador.")
class MetaCredentialsInstallTests(unittest.TestCase):
    def run_ps(self, body):
        with tempfile.TemporaryDirectory(prefix="nexo_native_install_") as temp:
            root = Path(temp)
            harness = root / "harness.ps1"
            prefix = f"""$ErrorActionPreference='Stop'
$repo='{str(ROOT).replace("'", "''")}'
$root='{str(root).replace("'", "''")}'
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $repo 'installer/install.ps1'),[ref]$tokens,[ref]$errors)
if($errors.Count){{throw 'Sintaxe inválida no Setup.'}}
foreach($f in $ast.FindAll({{param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst]}},$false)){{. ([scriptblock]::Create($f.Extent.Text))}}
function Assert-Native([bool]$condition,[string]$message){{if(-not $condition){{throw $message}}}}
function Copy-ImportDirectory{{param($Source,$Target) New-Item -ItemType Directory -Force -Path $Target|Out-Null; Copy-Item -Path (Join-Path $Source '*') -Destination $Target -Recurse -Force}}
function Write-Native([string]$path,[string]$value){{New-Item -ItemType Directory -Force -Path (Split-Path -Parent $path)|Out-Null;[IO.File]::WriteAllText($path,$value)}}
"""
            harness.write_text(prefix + body, encoding="utf-8-sig")
            result = subprocess.run(
                [POWERSHELL, "-NoProfile", "-File", str(harness)],
                capture_output=True,
                text=True,
                timeout=45,
            )
            output = result.stdout + result.stderr
            self.assertNotIn("SYNTHETIC_PRIVATE_META_TOKEN", output)
            self.assertEqual(result.returncode, 0, output[-3000:])

    def test_clean_restores_token_and_allowlist_without_restoring_other_credentials(
        self,
    ):
        self.run_ps(r"""
$backup=Join-Path $root 'backup'
$target=Join-Path $root 'installed'
$meta='credentials/mcp/meta_ads_credentials.json'
Write-Native (Join-Path (Join-Path $backup 'installed') $meta) '{"access_token":"SYNTHETIC_PRIVATE_META_TOKEN","allowed_ad_account_ids":["123456789"]}'
Write-Native (Join-Path $backup 'installed/credentials/google_credentials.json') 'google anterior'
Write-Native (Join-Path $backup 'installed/secrets_config.py') 'secrets anteriores'
Write-Native (Join-Path $backup 'installed/logs/state.json') 'estado anterior'
$expected=(Get-FileHash -LiteralPath (Join-Path (Join-Path $backup 'installed') $meta)).Hash
New-Item -ItemType Directory -Path $target|Out-Null
Restore-SetupData -BackupRoot $backup -Target $target -Mode Clean
Assert-Native (Test-Path -LiteralPath (Join-Path $target $meta) -PathType Leaf) 'Instalação limpa perdeu a credencial Meta.'
Assert-Native ((Get-FileHash -LiteralPath (Join-Path $target $meta)).Hash -eq $expected) 'Token ou allowlist Meta foram alterados.'
Assert-Native (-not (Test-Path -LiteralPath (Join-Path $target 'credentials/google_credentials.json'))) 'Clean restaurou credencial Google indevidamente.'
Assert-Native (-not (Test-Path -LiteralPath (Join-Path $target 'secrets_config.py'))) 'Clean restaurou secrets indevidamente.'
Assert-Native (-not (Test-Path -LiteralPath (Join-Path $target 'logs/state.json'))) 'Clean restaurou estado indevidamente.'
""")

    def test_clean_uses_current_installation_before_legacy_and_never_overwrites_current_token(
        self,
    ):
        self.run_ps(r"""
$backup=Join-Path $root 'backup';$target=Join-Path $root 'installed';$meta='credentials/mcp/meta_ads_credentials.json'
Write-Native (Join-Path (Join-Path $backup 'legacy installed') $meta) 'credencial antiga'
Write-Native (Join-Path (Join-Path $backup 'installed') $meta) 'credencial atual'
New-Item -ItemType Directory -Path $target|Out-Null
Restore-SetupData -BackupRoot $backup -Target $target -Mode Clean
Assert-Native ([IO.File]::ReadAllText((Join-Path $target $meta)) -eq 'credencial atual') 'Credencial legada substituiu a atual.'
Write-Native (Join-Path $target $meta) 'credencial editada durante instalação'
Restore-SetupData -BackupRoot $backup -Target $target -Mode Clean
Assert-Native ([IO.File]::ReadAllText((Join-Path $target $meta)) -eq 'credencial editada durante instalação') 'Setup sobrescreveu uma credencial Meta já presente.'
""")

    def test_build_guard_rejects_private_meta_file_without_reading_it(self):
        # O pacote operacional não distribui o script de build. A proteção é
        # exercitada no checkout de desenvolvimento e pelos jobs de release;
        # no check-up da instalação não há arquivo a validar.
        if not (ROOT / "scripts" / "build_release.ps1").is_file():
            self.skipTest("Script de build não integra o pacote operacional.")
        self.run_ps(r"""
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $repo 'scripts/build_release.ps1'),[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Sintaxe inválida no build.'}
$f=$ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Assert-PublicTrackedFiles'},$true)
. ([scriptblock]::Create($f.Extent.Text))
function Get-Content { throw 'Build tentou interpretar uma credencial.' }
$blocked=$false
try { Assert-PublicTrackedFiles -Paths @('credentials/mcp/meta_ads_credentials.json') } catch { $blocked=$true }
Assert-Native $blocked 'Build aceitou credencial Meta privada.'
Assert-PublicTrackedFiles -Paths @('connectors/meta_ads_mcp/client.py','connectors/meta_ads_mcp/settings.py','credentials/mcp/README.md')
""")

    def test_absent_meta_file_does_not_create_default_token(self):
        self.run_ps(r"""
$backup=Join-Path $root 'backup';$target=Join-Path $root 'installed'
New-Item -ItemType Directory -Path $backup,$target|Out-Null
Restore-SetupData -BackupRoot $backup -Target $target -Mode Clean
Assert-Native (-not (Test-Path -LiteralPath (Join-Path $target 'credentials/mcp/meta_ads_credentials.json'))) 'Setup criou credencial padrão indevidamente.'
""")

    @unittest.skipUnless(os.name == "nt", "Handle Windows real requer Windows.")
    def test_clean_with_open_meta_token_restores_or_aborts_without_losing_it(self):
        self.run_ps(r"""
$InstallDir=Join-Path $root 'installed';$backup=Join-Path $root 'backup';$meta='credentials/mcp/meta_ads_credentials.json'
Write-Native (Join-Path $InstallDir $meta) '{"access_token":"SYNTHETIC_PRIVATE_META_TOKEN","allowed_ad_account_ids":["123456789"]}'
Write-Native (Join-Path $InstallDir 'app/main.py') 'programa anterior'
$before=(Get-FileHash -LiteralPath (Join-Path $InstallDir $meta)).Hash
Backup-PrivateData -Source $InstallDir -Backup (Join-Path $backup 'installed')
$handle=[IO.File]::Open((Join-Path $InstallDir $meta),'Open','Read','Read')
try{
 $staged=$false
 try { $rollback=Stage-ExistingInstall -Mode Clean; $staged=$true } catch { }
 if($staged){
  New-Item -ItemType Directory -Force -Path $InstallDir|Out-Null
  Restore-SetupData -BackupRoot $backup -Target $InstallDir -Mode Clean
 }
 Assert-Native (Test-Path -LiteralPath (Join-Path $InstallDir $meta) -PathType Leaf) 'Clean com handle perdeu a credencial Meta.'
 Assert-Native ((Get-FileHash -LiteralPath (Join-Path $InstallDir $meta)).Hash -eq $before) 'Clean com handle alterou token ou allowlist.'
}finally{$handle.Dispose()}
""")

    @unittest.skipUnless(os.name == "nt", "Handle Windows real requer Windows.")
    def test_preserve_with_open_meta_token_keeps_file_and_imports_in_place(self):
        self.run_ps(r"""
$InstallDir=Join-Path $root 'installed';$backup=Join-Path $root 'backup';$meta='credentials/mcp/meta_ads_credentials.json'
Write-Native (Join-Path $InstallDir $meta) '{"access_token":"SYNTHETIC_PRIVATE_META_TOKEN","allowed_ad_account_ids":["123456789"]}'
Write-Native (Join-Path $InstallDir 'app/main.py') 'programa anterior'
$before=(Get-FileHash -LiteralPath (Join-Path $InstallDir $meta)).Hash
$handle=[IO.File]::Open((Join-Path $InstallDir $meta),'Open','Read','Read')
try{
 Backup-PrivateData -Source $InstallDir -Backup (Join-Path $backup 'installed')
 $rollback=Stage-ExistingInstall -Mode Preserve
 Restore-SetupData -BackupRoot $backup -Target $InstallDir -Mode Preserve -KeepExistingData
 Assert-Native ((Get-FileHash -LiteralPath (Join-Path $InstallDir $meta)).Hash -eq $before) 'Handle Preserve perdeu a credencial.'
 Assert-Native (-not (Test-Path -LiteralPath (Join-Path $rollback $meta))) 'Preserve moveu a credencial em uso.'
}finally{$handle.Dispose()}
""")


class MetaNativePackagingTests(unittest.TestCase):
    def test_native_cli_offline_from_unrelated_working_directory(self):
        with tempfile.TemporaryDirectory(prefix="nexo_native_cwd_") as temp:
            temp = Path(temp)
            payload = temp / "fixture.json"
            payload.write_text('{"segment":"PET"}', encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "app/run_meta_ads.py"),
                    "--perfil",
                    "PET",
                    "--input",
                    str(payload),
                ],
                cwd=temp,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('"mode": "offline_dry_run"', result.stdout)

    def test_packaged_client_is_explicit_and_sdk_is_not_a_core_requirement(self):
        data = tomllib.loads((ROOT / "pyproject.toml").read_text())
        tools = data["tool"]["setuptools"]
        self.assertIn("connectors.meta_ads_mcp", tools.get("packages", []))
        self.assertEqual(
            tools["package-dir"].get("connectors.meta_ads_mcp"),
            "connectors/meta_ads_mcp",
        )
        for name in (
            "meta_ads_native",
            "meta_ads_model",
            "meta_ads_sheets",
            "meta_ads_evidence",
            "run_meta_ads",
        ):
            self.assertIn(name, tools["py-modules"])
        requirements = (ROOT / "requirements.txt").read_text().lower()
        self.assertFalse(
            any(
                line.strip().startswith(("mcp", "codex"))
                for line in requirements.splitlines()
            )
        )

    def test_build_toolchain_is_prepared_in_ci_and_installed_checkup(self):
        # Python 3.14 não traz setuptools; versões antigas não atendem ao
        # backend declarado. O check-up instalado executa o mesmo wheeltest.
        bootstrap = (ROOT / "instalar.bat").read_text(encoding="utf-8")
        command = 'app\\run_pip.py install "setuptools>=77" wheel'
        self.assertIn(command, bootstrap)
        self.assertLess(
            bootstrap.index(command),
            bootstrap.index("app\\run_pip.py install -r requirements.txt"),
        )
        workflow = ROOT / ".github/workflows/release-v1.yml"
        if workflow.is_file():
            text = workflow.read_text(encoding="utf-8")
            self.assertEqual(
                text.count('python -m pip install "setuptools>=77" wheel'), 2
            )

    def test_wheel_offline_contains_native_modules_and_imports_client_without_sdk(self):
        with tempfile.TemporaryDirectory(prefix="nexo_native_wheel_") as temp:
            temp = Path(temp)
            source = temp / "source"
            source.mkdir()
            for name in ("pyproject.toml", "requirements.txt"):
                shutil.copyfile(ROOT / name, source / name)
            (source / "app").mkdir()
            modules = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"][
                "setuptools"
            ]["py-modules"]
            for module in modules:
                shutil.copyfile(
                    ROOT / "app" / (module + ".py"), source / "app" / (module + ".py")
                )
            shutil.copytree(ROOT / "dependencias", source / "dependencias")
            shutil.copytree(
                ROOT / "app/ds_backend",
                source / "app/ds_backend",
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
            connector = source / "connectors/meta_ads_mcp"
            connector.parent.mkdir(parents=True)
            shutil.copytree(
                ROOT / "connectors/meta_ads_mcp",
                connector,
                ignore=shutil.ignore_patterns("__pycache__", "tests", "*.pyc"),
            )
            dist = temp / "dist"
            dist.mkdir()
            target = temp / "site"
            target.mkdir()
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import setuptools.build_meta as b,sys;b.build_wheel(sys.argv[1])",
                    str(dist),
                ],
                cwd=source,
                capture_output=True,
                text=True,
                timeout=75,
            )
            self.assertEqual(
                result.returncode, 0, (result.stdout + result.stderr)[-3000:]
            )
            wheel = next(dist.glob("*.whl"))
            from zipfile import ZipFile

            with ZipFile(wheel) as zipped:
                names = zipped.namelist()
                for name in (
                    "meta_ads_native.py",
                    "meta_ads_model.py",
                    "meta_ads_sheets.py",
                    "meta_ads_evidence.py",
                    "run_meta_ads.py",
                    "connectors/meta_ads_mcp/client.py",
                    "connectors/meta_ads_mcp/settings.py",
                ):
                    self.assertIn(name, names)
                self.assertFalse(
                    any(
                        "/credentials/" in n or n.endswith("secrets_config.py")
                        for n in names
                    )
                )
                metadata = zipped.read(
                    next(n for n in names if n.endswith(".dist-info/METADATA"))
                ).decode()
                self.assertNotIn("Requires-Dist: mcp", metadata)
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "--no-deps",
                    "--no-index",
                    "--disable-pip-version-check",
                    "--target",
                    str(target),
                    str(wheel),
                ],
                capture_output=True,
                text=True,
                timeout=75,
            )
            self.assertEqual(
                result.returncode, 0, (result.stdout + result.stderr)[-3000:]
            )
            code = textwrap.dedent("""
                import sys,importlib.abc,types,os
                os.environ["NEXOFLOW_PERFIL"]="FARMA"
                sys.modules["secrets_config"]=types.ModuleType("secrets_config")
                class NoMcp(importlib.abc.MetaPathFinder):
                    def find_spec(self,fullname,path=None,target=None):
                        if fullname=='mcp' or fullname.startswith('mcp.'):
                            raise AssertionError('Native importou SDK MCP')
                sys.meta_path.insert(0,NoMcp())
                sys.path.insert(0,sys.argv[1])
                from connectors.meta_ads_mcp import client,settings
                import meta_ads_native,meta_ads_model,meta_ads_sheets,meta_ads_evidence,run_meta_ads
                assert client.__file__.startswith(sys.argv[1])
                assert settings.__file__.startswith(sys.argv[1])
                assert 'connectors.meta_ads_mcp.server' not in sys.modules
                print('Cliente nativo instalado sem MCP')
            """)
            result = subprocess.run(
                [sys.executable, "-I", "-c", code, str(target)],
                cwd=temp,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
