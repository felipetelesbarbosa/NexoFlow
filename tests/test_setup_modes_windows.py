"""Escolha real do modo do Setup e aplicação da política de dados no Windows."""

import os
import unittest

from tests import test_imports_lifecycle_windows as lifecycle


@unittest.skipUnless(os.name == "nt", "Requer Windows PowerShell e Windows Forms")
class SetupModesWindowsTests(unittest.TestCase):
    run_harness = lifecycle.ImportsLifecycleWindowsTests.run_harness

    def test_dialog_buttons_and_close_select_preserve_clean_or_cancel(self):
        self.run_harness(
            "install.ps1",
            r"""
Add-Type -AssemblyName System.Windows.Forms
foreach ($case in @(
    @{ Button = 'Preserve'; Expected = 'Preserve' },
    @{ Button = 'Clean'; Expected = 'Clean' },
    @{ Button = 'Cancel'; Expected = 'Cancel' },
    @{ Button = 'Close'; Expected = 'Cancel' }
)) {
    $script:SetupTestButton = $case.Button
    $timer = New-Object Windows.Forms.Timer
    $timer.Interval = 100
    $timer.Add_Tick({
        param($sender, $eventArgs)
        $window = [Windows.Forms.Application]::OpenForms | Where-Object { $_.Name -eq 'NexoFlowInstallMode' } | Select-Object -First 1
        if ($window) {
            $sender.Stop()
            if ($script:SetupTestButton -eq 'Close') { $window.Close() }
            else { $window.Controls[$script:SetupTestButton].PerformClick() }
        }
    })
    $timer.Start()
    try { $actual = Show-InstallModeDialog }
    finally { $timer.Stop(); $timer.Dispose() }
    Assert-True ($actual -ceq $case.Expected) 'O dialogo do Setup retornou um modo diferente do botao escolhido.'
}
""",
        )

    def test_console_fallback_retries_invalid_input_and_supports_cancel(self):
        self.run_harness(
            "install.ps1",
            r"""
$NonInteractive = $false
$InstallMode = 'Preserve'
function Show-InstallModeDialog { throw 'Interface indisponivel no fixture.' }
function Read-Host { param($Prompt) return $script:SetupAnswers.Dequeue() }
foreach ($case in @(
    @{ Answers = @('invalido', '2'); Expected = 'Clean' },
    @{ Answers = @('1'); Expected = 'Preserve' },
    @{ Answers = @('0'); Expected = 'Cancel' },
    @{ Answers = @(''); Expected = 'Cancel' }
)) {
    $script:SetupAnswers = New-Object 'System.Collections.Generic.Queue[string]'
    foreach ($answer in $case.Answers) { $script:SetupAnswers.Enqueue($answer) }
    Assert-True ((Select-InstallMode) -ceq $case.Expected) 'O menu de console selecionou o modo errado.'
}
""",
        )

    def test_noninteractive_mode_is_explicit_and_does_not_open_dialog(self):
        self.run_harness(
            "install.ps1",
            r"""
$NonInteractive = $true
function Show-InstallModeDialog { throw 'Nao deve abrir interface em modo nao interativo.' }
foreach ($mode in @('Preserve', 'Clean', 'Cancel')) {
    $InstallMode = $mode
    Assert-True ((Select-InstallMode) -ceq $mode) 'O modo explicito foi ignorado.'
}
""",
        )

    def test_clean_mode_restores_only_imports_from_all_previous_sources(self):
        self.run_harness(
            "install.ps1",
            r"""
$backup = Join-Path $root 'backup'
foreach ($name in @('legacy preserved', 'legacy installed', 'preserved', 'installed')) {
    $source = Join-Path $backup $name
    Write-Fixture (Join-Path $source 'secrets_config.py') ('configuracao sintetica ' + $name)
    Write-Fixture (Join-Path $source 'credentials\synthetic.json') '{}'
    Write-Fixture (Join-Path $source 'logs\checkpoint.json') '{}'
    Write-Fixture (Join-Path $source 'logs\PET\recompra_state.json') '{}'
    Write-Fixture (Join-Path $source ('importacoes\' + $name + '.xlsx')) ('export ' + $name)
}
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Restore-SetupData -BackupRoot $backup -Target $InstallDir -Mode Clean
foreach ($path in @('secrets_config.py', 'credentials', 'logs')) {
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $InstallDir $path))) 'A instalacao limpa restaurou configuracao ou estado antigo.'
}
Assert-True (@(Get-ChildItem -LiteralPath (Join-Path $InstallDir 'importacoes') -File).Count -eq 4) 'A instalacao limpa perdeu exports do usuario.'
Assert-True (Test-Path -LiteralPath (Join-Path $backup 'installed\secrets_config.py')) 'A recuperacao foi descartada antes de concluir a instalacao.'
""",
        )

    def test_preserve_mode_restores_configuration_credentials_and_both_states(self):
        self.run_harness(
            "install.ps1",
            r"""
$backup = Join-Path $root 'backup'
Write-Fixture (Join-Path $backup 'preserved\secrets_config.py') 'configuracao anterior'
Write-Fixture (Join-Path $backup 'installed\secrets_config.py') 'configuracao atual'
Write-Fixture (Join-Path $backup 'installed\credentials\synthetic.json') 'credencial atual'
Write-Fixture (Join-Path $backup 'installed\logs\checkpoint.json') 'marco farma'
Write-Fixture (Join-Path $backup 'installed\logs\PET\checkpoint.json') 'marco pet'
Write-Fixture (Join-Path $backup 'installed\importacoes\original.xlsx') 'export original'
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Restore-SetupData -BackupRoot $backup -Target $InstallDir -Mode Preserve
Assert-True ((Get-Content -LiteralPath (Join-Path $InstallDir 'secrets_config.py') -Raw) -ceq 'configuracao atual') 'A configuracao instalada nao prevaleceu.'
Assert-True ((Get-Content -LiteralPath (Join-Path $InstallDir 'credentials\synthetic.json') -Raw) -ceq 'credencial atual') 'Credencial perdida.'
Assert-True ((Get-Content -LiteralPath (Join-Path $InstallDir 'logs\checkpoint.json') -Raw) -ceq 'marco farma') 'Estado Farma perdido.'
Assert-True ((Get-Content -LiteralPath (Join-Path $InstallDir 'logs\PET\checkpoint.json') -Raw) -ceq 'marco pet') 'Estado Pets perdido.'
Assert-True ((Get-Content -LiteralPath (Join-Path $InstallDir 'importacoes\original.xlsx') -Raw) -ceq 'export original') 'Export perdido.'
""",
        )

    def test_clean_network_settings_stay_in_private_backup(self):
        self.run_harness(
            "install.ps1",
            r"""
$backup = Join-Path $root 'backup'
Assert-True ($null -eq (Get-SetupNetworkSettingsDirectory -BackupRoot $backup)) 'Inventou configuracao de rede ausente.'
Write-Fixture (Join-Path $backup 'preserved\secrets_config.py') 'configuracao preservada sintetica'
Write-Fixture (Join-Path $backup 'installed\secrets_config.py') 'configuracao instalada sintetica'
$network = Get-SetupNetworkSettingsDirectory -BackupRoot $backup
Assert-True ($network -ceq (Join-Path $backup 'installed')) 'A rede nao priorizou a configuracao instalada.'
Assert-True (-not (Test-Path -LiteralPath (Join-Path $InstallDir 'secrets_config.py'))) 'A configuracao de rede foi copiada para a instalacao limpa.'
""",
        )
