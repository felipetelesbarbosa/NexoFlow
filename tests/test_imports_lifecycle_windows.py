"""Preservação real de arquivos sintéticos em diretórios temporários do Windows."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "nt", "Requer Windows PowerShell")
class ImportsLifecycleWindowsTests(unittest.TestCase):
    def run_harness(self, installer, body):
        source = ROOT / "installer" / installer
        literal = str(source).replace("'", "''")
        with tempfile.TemporaryDirectory(prefix="nexo importacoes ") as temp:
            root = Path(temp)
            root_literal = str(root).replace("'", "''")
            harness = root / "harness.ps1"
            harness.write_text(
                f"""$ErrorActionPreference = 'Stop'
$root = '{root_literal}'
$InstallDir = Join-Path $root 'instalado'
$DataDir = Join-Path $root 'preservado'
$sourceScript = '{literal}'
$tokens = $null; $parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($sourceScript, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) {{ throw 'Erro de sintaxe no instalador/desinstalador.' }}
$functions = $ast.FindAll({{ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] }}, $false)
foreach ($function in $functions) {{ . ([scriptblock]::Create($function.Extent.Text)) }}
function Assert-True([bool]$condition, [string]$message) {{ if (-not $condition) {{ throw $message }} }}
function Write-Fixture([string]$path, [string]$text) {{
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $path) | Out-Null
    [IO.File]::WriteAllText($path, $text)
}}
{body}
""",
                encoding="utf-8-sig",
            )
            result = subprocess.run(
                [
                    str(
                        Path(os.environ["SystemRoot"])
                        / "System32/WindowsPowerShell/v1.0/powershell.exe"
                    ),
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(harness),
                ],
                capture_output=True,
                timeout=45,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_uninstall_preserves_all_imports_and_conflicting_previous_backups(self):
        self.run_harness(
            "uninstall.ps1",
            r"""
$source = Join-Path $InstallDir 'importacoes'
$target = Join-Path $DataDir 'importacoes'
Write-Fixture (Join-Path $source 'Conversas_Delivery.xlsx') 'nova versao sintetica'
Write-Fixture (Join-Path $source 'subpasta\arquivo.txt') 'dados internos sinteticos'
New-Item -ItemType Directory -Force -Path (Join-Path $source 'vazia') | Out-Null
Write-Fixture (Join-Path $target 'Conversas_Delivery.xlsx') 'versao anterior sintetica'
Write-Fixture (Join-Path $target 'somente-no-backup.txt') 'backup anterior'
Write-Fixture (Join-Path $DataDir 'secrets_config.py') 'segredo sintetico'
Write-Fixture (Join-Path $DataDir 'credentials\credencial.json') '{}'
Write-Fixture (Join-Path $DataDir 'logs\log.txt') 'log sintetico'
Preserve-Imports
Remove-OptionalPrivateData
Assert-True ((Get-Content -LiteralPath (Join-Path $target 'Conversas_Delivery.xlsx') -Raw) -eq 'nova versao sintetica') 'O arquivo atual nao foi preservado.'
Assert-True (Test-Path -LiteralPath (Join-Path $target 'subpasta\arquivo.txt')) 'Arquivo em subpasta foi perdido.'
Assert-True (Test-Path -LiteralPath (Join-Path $target 'vazia') -PathType Container) 'Pasta vazia foi perdida.'
Assert-True (Test-Path -LiteralPath (Join-Path $target 'somente-no-backup.txt')) 'Backup anterior foi apagado.'
$archived = @(Get-ChildItem -LiteralPath (Join-Path $target 'historico_preservado') -File -Recurse)
Assert-True ($archived.Count -eq 1) 'Conteudo anterior com nome igual nao foi arquivado.'
Assert-True ((Get-Content -LiteralPath $archived[0].FullName -Raw) -eq 'versao anterior sintetica') 'Historico incorreto.'
Assert-True (-not (Test-Path -LiteralPath (Join-Path $DataDir 'secrets_config.py'))) 'Limpeza opcional nao removeu configuracao.'
$before = @(Get-ChildItem -LiteralPath $target -File -Recurse).Count
Preserve-Imports
Assert-True (@(Get-ChildItem -LiteralPath $target -File -Recurse).Count -eq $before) 'A preservacao repetida duplicou arquivos.'
""",
        )

    def test_reinstall_empty_backup_never_erases_preserved_imports_and_conflicts_keep_both(
        self,
    ):
        self.run_harness(
            "install.ps1",
            r"""
$saved = Join-Path $root 'backup salvo'
$current = Join-Path $root 'backup instalado'
Write-Fixture (Join-Path $saved 'importacoes\Contatos_Delivery.xlsx') 'contatos preservados'
New-Item -ItemType Directory -Force -Path (Join-Path $current 'importacoes') | Out-Null
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Restore-PrivateData -Backup $saved -Target $InstallDir
Restore-PrivateData -Backup $current -Target $InstallDir
$target = Join-Path $InstallDir 'importacoes'
Assert-True ((Get-Content -LiteralPath (Join-Path $target 'Contatos_Delivery.xlsx') -Raw) -eq 'contatos preservados') 'Backup vazio apagou dados preservados.'
Write-Fixture (Join-Path $current 'importacoes\Contatos_Delivery.xlsx') 'contatos mais recentes'
Restore-PrivateData -Backup $current -Target $InstallDir
Assert-True ((Get-Content -LiteralPath (Join-Path $target 'Contatos_Delivery.xlsx') -Raw) -eq 'contatos mais recentes') 'A restauracao atual falhou.'
$history = @(Get-ChildItem -LiteralPath (Join-Path $target 'historico_preservado') -Recurse -File)
Assert-True ($history.Count -eq 1) 'A restauracao perdeu a versao anterior.'
""",
        )

    def test_unsafe_preservation_destination_blocks_deletion(self):
        self.run_harness(
            "uninstall.ps1",
            r"""
Write-Fixture (Join-Path $InstallDir 'importacoes\arquivo.txt') 'preservar'
$DataDir = Join-Path $InstallDir 'backup interno'
$blocked = $false
try { Preserve-Imports } catch { $blocked = $true }
Assert-True $blocked 'Destino dentro da instalacao nao foi bloqueado.'
Assert-True (Test-Path -LiteralPath (Join-Path $InstallDir 'importacoes\arquivo.txt')) 'Arquivo foi removido apos erro de preservacao.'
""",
        )

    def test_actual_stage2_preserves_imports_when_optional_data_is_removed(self):
        self.run_harness(
            "uninstall.ps1",
            r"""
Write-Fixture (Join-Path $InstallDir 'importacoes\Conversas_Delivery.xlsx') 'export sintetico'
Write-Fixture (Join-Path $DataDir 'secrets_config.py') 'configuracao sintetica'
Write-Fixture (Join-Path $DataDir 'logs\arquivo.txt') 'log sintetico'
$text = Get-Content -LiteralPath $sourceScript -Raw
# Only UI and machine-wide cleanup are replaced. The real Stage2 file-copy,
# verification and directory removal code executes on the temporary fixture.
$show = $functions | Where-Object { $_.Name -eq 'Show-Message' } | Select-Object -First 1
$text = $text.Remove($show.Extent.StartOffset, $show.Extent.EndOffset - $show.Extent.StartOffset).Insert($show.Extent.StartOffset, 'function Show-Message([string]$Text, [string]$Title, [string]$Icon) { Write-Host $Text }')
$text = $text.Replace('        Remove-Shortcuts', '        # Fixture: no desktop cleanup')
$text = $text.Replace('        Remove-Item -LiteralPath $UninstallKey -Recurse -Force -ErrorAction SilentlyContinue', '        # Fixture: no registry cleanup')
$text = $text.Replace('        Remove-Item -LiteralPath $AppKey -Recurse -Force -ErrorAction SilentlyContinue', '        # Fixture: no registry cleanup')
$fixture = Join-Path $root 'uninstall-fixture.ps1'
[IO.File]::WriteAllText($fixture, $text, (New-Object Text.UTF8Encoding($true)))
& (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe') -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $fixture -Stage2 -InstallDir $InstallDir -DataDir $DataDir -KeepDataFlag 0
Assert-True ($LASTEXITCODE -eq 0) 'Stage2 falhou.'
Assert-True (-not (Test-Path -LiteralPath $InstallDir)) 'A instalacao nao foi removida.'
Assert-True ((Get-Content -LiteralPath (Join-Path $DataDir 'importacoes\Conversas_Delivery.xlsx') -Raw) -eq 'export sintetico') 'Stage2 apagou o export.'
Assert-True (-not (Test-Path -LiteralPath (Join-Path $DataDir 'secrets_config.py'))) 'Stage2 nao removeu configuracao opcional.'
Assert-True (-not (Test-Path -LiteralPath (Join-Path $DataDir 'logs'))) 'Stage2 nao removeu logs opcionais.'
""",
        )

    def test_uninstall_removes_current_and_legacy_shortcuts_and_preserves_other_files(
        self,
    ):
        self.run_harness(
            "uninstall.ps1",
            r"""
$fixtureRoots = @(
    (Join-Path $root 'desktop comum'),
    (Join-Path $root 'desktop usuario'),
    (Join-Path $root 'OneDrive\Área de Trabalho'),
    (Join-Path $root 'menu comum'),
    (Join-Path $root 'menu usuario')
)
function Get-ShortcutDirectories { return $fixtureRoots }
$expectedNames = @(
    'NexoFlow Analytics.lnk', 'NexoFlow Weni.lnk', 'NexoFlow Recompra.lnk',
    'NexoFlow Planilha.lnk', 'NexoFlow Terminal.lnk', 'NexoFlow - Update Weni.lnk',
    'NexoFlow Console.lnk', 'NexoFlow.lnk', 'Desinstalar NexoFlow.lnk',
    'NexoFlow Uninstall.lnk', 'Documentacao NexoFlow.lnk', 'Documentação NexoFlow.lnk',
    'Weni WhatsApp Analytics.lnk', 'Weni WhatsApp Analytics - Sincronizar.lnk'
)
foreach ($directory in $fixtureRoots) {
    foreach ($name in $expectedNames) {
        Write-Fixture (Join-Path $directory $name) 'atalho sintetico'
        Write-Fixture (Join-Path (Join-Path $directory 'NexoFlow') $name) 'atalho sintetico'
    }
    Write-Fixture (Join-Path $directory 'NexoFlow Pessoal.lnk') 'atalho alheio'
    Write-Fixture (Join-Path $directory 'anotacoes.txt') 'arquivo alheio'
}
$protectedMenu = Join-Path $fixtureRoots[0] 'NexoFlow'
Write-Fixture (Join-Path $protectedMenu 'Outro aplicativo.lnk') 'preservar'
$legacyMenu = Join-Path $fixtureRoots[1] 'Weni WhatsApp Analytics'
Write-Fixture (Join-Path $legacyMenu 'Weni WhatsApp Analytics.lnk') 'atalho legado'
# Um .lnk real cujo executável já foi removido também precisa ser apagado.
$brokenPath = Join-Path $fixtureRoots[2] 'NexoFlow Recompra.lnk'
Remove-Item -LiteralPath $brokenPath -Force
$shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($brokenPath)
$shortcut.TargetPath = Join-Path $InstallDir 'NexoFlow Recompra.exe'
$shortcut.Save()
Assert-True (-not (Test-Path -LiteralPath $shortcut.TargetPath)) 'A fixture deveria conter destino inexistente.'
Remove-Shortcuts
foreach ($directory in $fixtureRoots) {
    foreach ($name in $expectedNames) {
        Assert-True (-not (Test-Path -LiteralPath (Join-Path $directory $name))) "Atalho restante: $name"
        Assert-True (-not (Test-Path -LiteralPath (Join-Path (Join-Path $directory 'NexoFlow') $name))) "Atalho restante no menu: $name"
    }
    Assert-True (Test-Path -LiteralPath (Join-Path $directory 'NexoFlow Pessoal.lnk')) 'Atalho de nome semelhante foi apagado.'
    Assert-True (Test-Path -LiteralPath (Join-Path $directory 'anotacoes.txt')) 'Arquivo alheio foi apagado.'
}
Assert-True (Test-Path -LiteralPath (Join-Path $protectedMenu 'Outro aplicativo.lnk')) 'Atalho alheio dentro do menu foi apagado.'
Assert-True (-not (Test-Path -LiteralPath (Join-Path $fixtureRoots[1] 'NexoFlow'))) 'Pasta vazia do menu nao foi removida.'
Assert-True (-not (Test-Path -LiteralPath $legacyMenu)) 'Pasta vazia do menu legado nao foi removida.'
Remove-Shortcuts
""",
        )

    def test_uninstall_finds_onedrive_and_original_user_roots_after_elevation(self):
        self.run_harness(
            "uninstall.ps1",
            r"""
$env:USERPROFILE = Join-Path $root 'usuario elevado'
$env:APPDATA = Join-Path $root 'appdata elevado'
$env:ProgramData = Join-Path $root 'programdata'
$env:OneDrive = Join-Path $root 'OneDrive pessoal'
$env:OneDriveConsumer = Join-Path $root 'OneDrive consumer'
$env:OneDriveCommercial = Join-Path $root 'OneDrive empresa'
$originalRoots = @((Join-Path $root 'usuario original\desktop redirecionado'), (Join-Path $root 'usuario original\menu'))
$json = ConvertTo-Json -InputObject $originalRoots -Compress
$ShortcutRootsBase64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($json))
$actual = @(Get-ShortcutDirectories)
foreach ($directory in @(
    $originalRoots[0], $originalRoots[1],
    (Join-Path $env:USERPROFILE 'Desktop'),
    (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'),
    (Join-Path $env:ProgramData 'Microsoft\Windows\Start Menu\Programs'),
    (Join-Path $env:OneDrive 'Desktop'),
    (Join-Path $env:OneDrive 'Área de Trabalho'),
    (Join-Path $env:OneDriveConsumer 'Desktop'),
    (Join-Path $env:OneDriveCommercial 'Desktop')
)) {
    Assert-True ($actual -contains $directory) "Pasta de atalhos nao encontrada: $directory"
}
Assert-True ($actual.Count -eq @($actual | Select-Object -Unique).Count) 'Pastas de atalhos duplicadas.'
""",
        )
