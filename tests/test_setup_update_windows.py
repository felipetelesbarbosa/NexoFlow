"""Atualização com handles reais do Windows e preservação da instalação anterior."""

import os
import unittest

from tests import test_imports_lifecycle_windows as lifecycle

DIRECTORY_LOCK = r"""
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
public static class NexoFlowTestDirectoryLock {
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern SafeFileHandle CreateFile(string name, uint access, uint share,
        IntPtr security, uint creation, uint flags, IntPtr template);
    public static SafeFileHandle Open(string path) {
        SafeFileHandle handle = CreateFile(path, 0x80000000, 3, IntPtr.Zero, 3, 0x02000000, IntPtr.Zero);
        if (handle.IsInvalid) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
        return handle;
    }
}
'@
"""


@unittest.skipUnless(os.name == "nt", "Requer handles de diretório do Windows")
class SetupUpdateWindowsTests(unittest.TestCase):
    run_harness = lifecycle.ImportsLifecycleWindowsTests.run_harness

    def test_process_path_matches_single_separator_and_respects_directory_boundary(
        self,
    ):
        self.run_harness(
            "install.ps1",
            r"""
Assert-True (Test-InstalledProcessPath (Join-Path $InstallDir 'NexoFlow Weni.exe')) 'Launcher instalado nao foi reconhecido.'
Assert-True (Test-InstalledProcessPath (Join-Path $InstallDir '.venv\Scripts\python.exe')) 'Python instalado nao foi reconhecido.'
Assert-True (-not (Test-InstalledProcessPath ($InstallDir + '-outro\python.exe'))) 'Processo externo foi reconhecido como instalado.'
Assert-True (-not (Test-InstalledProcessPath '')) 'Caminho ausente foi aceito.'
""",
        )

    def test_locked_root_can_stage_and_restore_without_deleting_root(self):
        self.run_harness(
            "install.ps1",
            DIRECTORY_LOCK
            + r"""
Write-Fixture (Join-Path $InstallDir 'app\original.py') 'codigo anterior'
Write-Fixture (Join-Path $InstallDir 'credentials\synthetic.json') 'credencial sintetica'
Write-Fixture (Join-Path $InstallDir 'logs\checkpoint.json') 'estado anterior'
$handle = [NexoFlowTestDirectoryLock]::Open($InstallDir)
try {
    $rollback = Stage-ExistingInstall
    Assert-True $script:RollbackUsesExistingRoot 'Nao acionou a preservacao da raiz bloqueada.'
    Assert-True (Test-Path -LiteralPath $InstallDir) 'A pasta principal foi removida.'
    Assert-True (@(Get-ChildItem -LiteralPath $InstallDir -Force).Count -eq 0) 'A preparacao deixou arquivos antigos no destino.'
    Assert-True ((Get-Content -LiteralPath (Join-Path $rollback 'app\original.py') -Raw) -eq 'codigo anterior') 'O backup nao corresponde ao original.'
    Write-Fixture (Join-Path $InstallDir 'app\novo.py') 'instalacao incompleta'
    Assert-True (Restore-PreviousInstall -RollbackPath $rollback) 'Rollback com raiz bloqueada falhou.'
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $InstallDir 'app\novo.py'))) 'Codigo incompleto permaneceu.'
    Assert-True ((Get-Content -LiteralPath (Join-Path $InstallDir 'app\original.py') -Raw) -eq 'codigo anterior') 'O codigo anterior nao foi restaurado.'
    Assert-True ((Get-Content -LiteralPath (Join-Path $InstallDir 'credentials\synthetic.json') -Raw) -eq 'credencial sintetica') 'Credencial foi perdida.'
    Assert-True ((Get-Content -LiteralPath (Join-Path $InstallDir 'logs\checkpoint.json') -Raw) -eq 'estado anterior') 'Checkpoint foi perdido.'
    Assert-True (-not (Test-Path -LiteralPath $rollback)) 'Rollback concluido deixou uma copia redundante.'
} finally { $handle.Dispose() }
""",
        )

    def test_locked_file_aborts_staging_and_puts_already_moved_files_back(self):
        self.run_harness(
            "install.ps1",
            DIRECTORY_LOCK
            + r"""
Write-Fixture (Join-Path $InstallDir 'a-original.txt') 'arquivo movido primeiro'
Write-Fixture (Join-Path $InstallDir 'b-bloqueado.txt') 'arquivo em uso'
$handle = [NexoFlowTestDirectoryLock]::Open($InstallDir)
$file = [IO.File]::Open((Join-Path $InstallDir 'b-bloqueado.txt'), 'Open', 'Read', 'None')
try {
    $failed = $false
    try { Stage-ExistingInstall | Out-Null } catch { $failed = $true }
    Assert-True $failed 'Um arquivo ainda em uso nao bloqueou a preparacao.'
    Assert-True ((Get-Content -LiteralPath (Join-Path $InstallDir 'a-original.txt') -Raw) -eq 'arquivo movido primeiro') 'Arquivo movido antes da falha nao foi devolvido.'
    Assert-True (@(Get-ChildItem -LiteralPath $root -Directory -Filter 'instalado.__rollback__.*').Count -eq 0) 'Restauracao deixou rollback desnecessario.'
    Assert-True (@(Get-ChildItem -LiteralPath $InstallDir -Filter '.nexoflow-write-probe-*').Count -eq 0) 'Arquivo de verificacao permaneceu.'
} finally { $file.Dispose(); $handle.Dispose() }
Assert-True ((Get-Content -LiteralPath (Join-Path $InstallDir 'b-bloqueado.txt') -Raw) -eq 'arquivo em uso') 'Arquivo bloqueado foi modificado.'
""",
        )

    def test_normal_update_keeps_directory_rollback_path(self):
        self.run_harness(
            "install.ps1",
            r"""
Write-Fixture (Join-Path $InstallDir 'original.txt') 'original'
$rollback = Stage-ExistingInstall
Assert-True (-not $script:RollbackUsesExistingRoot) 'Atualizacao comum usou modo alternativo.'
Assert-True (-not (Test-Path -LiteralPath $InstallDir)) 'A pasta anterior nao foi movida.'
Assert-True (Restore-PreviousInstall -RollbackPath $rollback) 'Rollback comum falhou.'
Assert-True ((Get-Content -LiteralPath (Join-Path $InstallDir 'original.txt') -Raw) -eq 'original') 'Rollback comum alterou o arquivo.'
""",
        )

    def test_preserve_update_and_rollback_keep_locked_logs_in_place(self):
        self.run_harness(
            "install.ps1",
            DIRECTORY_LOCK
            + r"""
Write-Fixture (Join-Path $InstallDir 'app\original.py') 'codigo anterior'
Write-Fixture (Join-Path $InstallDir 'secrets_config.py') 'configuracao atual'
Write-Fixture (Join-Path $InstallDir 'credentials\synthetic.json') 'credencial atual'
Write-Fixture (Join-Path $InstallDir 'logs\checkpoint.json') 'marco Farma'
Write-Fixture (Join-Path $InstallDir 'logs\PET\checkpoint.json') 'marco Pets'
Write-Fixture (Join-Path $InstallDir 'importacoes\original.xlsx') 'export original'
$backup = Join-Path $root 'backup'
Backup-PrivateData -Source $InstallDir -Backup (Join-Path $backup 'installed')
$rootHandle = [NexoFlowTestDirectoryLock]::Open($InstallDir)
$logsHandle = [NexoFlowTestDirectoryLock]::Open((Join-Path $InstallDir 'logs'))
try {
    $rollback = Stage-ExistingInstall -Mode Preserve
    Assert-True (Test-Path -LiteralPath (Join-Path $InstallDir 'logs\checkpoint.json')) 'Logs foram movidos.'
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $rollback 'logs'))) 'Dados privados foram movidos ao rollback.'
    $PayloadDir = Join-Path $root 'payload'
    Write-Fixture (Join-Path $PayloadDir 'app\novo.py') 'codigo novo'
    Write-Fixture (Join-Path $PayloadDir 'logs\checkpoint.json') 'modelo que nao pode sobrescrever estado'
    Write-Fixture (Join-Path $PayloadDir 'secrets_config.py') 'modelo que nao pode sobrescrever configuracao'
    Copy-ProgramPayload -Mode Preserve
    Restore-SetupData -BackupRoot $backup -Target $InstallDir -Mode Preserve -KeepExistingData
    Assert-True ((Get-Content -Raw -LiteralPath (Join-Path $InstallDir 'logs\checkpoint.json')) -ceq 'marco Farma') 'Marco Farma foi sobrescrito.'
    Assert-True ((Get-Content -Raw -LiteralPath (Join-Path $InstallDir 'logs\PET\checkpoint.json')) -ceq 'marco Pets') 'Marco Pets foi sobrescrito.'
    Assert-True ((Get-Content -Raw -LiteralPath (Join-Path $InstallDir 'secrets_config.py')) -ceq 'configuracao atual') 'Configuracao foi sobrescrita.'
    Assert-True (Restore-PreviousInstall -RollbackPath $rollback) 'Rollback falhou com logs abertos.'
    Assert-True ((Get-Content -Raw -LiteralPath (Join-Path $InstallDir 'app\original.py')) -ceq 'codigo anterior') 'Codigo anterior nao foi recuperado.'
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $InstallDir 'app\novo.py'))) 'Codigo incompleto permaneceu.'
    Assert-True ((Get-Content -Raw -LiteralPath (Join-Path $InstallDir 'credentials\synthetic.json')) -ceq 'credencial atual') 'Credencial foi perdida.'
    Assert-True ((Get-Content -Raw -LiteralPath (Join-Path $InstallDir 'logs\checkpoint.json')) -ceq 'marco Farma') 'Rollback apagou logs.'
    Assert-True ((Get-Content -Raw -LiteralPath (Join-Path $InstallDir 'logs\PET\checkpoint.json')) -ceq 'marco Pets') 'Rollback apagou estado Pets.'
    Assert-True ((Get-Content -Raw -LiteralPath (Join-Path $InstallDir 'importacoes\original.xlsx')) -ceq 'export original') 'Export perdido.'
} finally { $logsHandle.Dispose(); $rootHandle.Dispose() }
""",
        )
