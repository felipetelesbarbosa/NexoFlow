"""Bloqueios reais na leitura SHA-256, sem executar a instalação ou acessar APIs."""

import os
import unittest

from tests import test_imports_lifecycle_windows as lifecycle

RELEASING_LOCK = r"""
Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Threading;
public static class NexoFlowHashTestLock {
    public static FileStream Hold(string path, int milliseconds) {
        FileStream handle = File.Open(path, FileMode.Open, FileAccess.Read, FileShare.None);
        Thread worker = new Thread(delegate() {
            Thread.Sleep(milliseconds);
            handle.Dispose();
        });
        worker.IsBackground = true;
        worker.Start();
        return handle;
    }
}
'@
"""


@unittest.skipUnless(os.name == "nt", "Requer bloqueios reais do Windows")
class SetupIntegrityWindowsTests(unittest.TestCase):
    run_harness = lifecycle.ImportsLifecycleWindowsTests.run_harness

    def test_hash_waits_for_exclusive_handle_and_reads_actual_content(self):
        self.run_harness(
            "install.ps1",
            RELEASING_LOCK
            + r"""
$path = Join-Path $root 'NexoFlow Noturno.exe'
Write-Fixture $path 'conteudo sintetico'
$expected = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
$handle = [NexoFlowHashTestLock]::Hold($path, 700)
try {
    # Reproduz a linha antiga antes de testar a recuperação do instalador.
    $blocked = $false
    try {
        $probe = [IO.File]::Open($path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
        $probe.Dispose()
    } catch {
        $errorCause = $_.Exception
        while ($errorCause.InnerException) { $errorCause = $errorCause.InnerException }
        $blocked = (($errorCause.HResult -band 0xffff) -eq 32)
    }
    Assert-True $blocked 'O fixture nao reproduziu a falha de arquivo em uso.'
    $actual = Get-Sha256File -Path $path -RetryTimeoutSeconds 3 -RetryDelayMilliseconds 25
    Assert-True ($actual -ceq $expected) 'A leitura apos a liberacao nao confirmou o hash real.'
} finally { $handle.Dispose() }
Assert-True ((Get-Content -LiteralPath $path -Raw) -ceq 'conteudo sintetico') 'A verificacao modificou o arquivo.'
""",
        )

    def test_persistent_lock_stops_at_deadline_without_returning_hash(self):
        self.run_harness(
            "install.ps1",
            r"""
$path = Join-Path $root 'NexoFlow Noturno.exe'
Write-Fixture $path 'conteudo sintetico'
$handle = [IO.File]::Open($path, 'Open', 'Read', 'None')
$watch = [Diagnostics.Stopwatch]::StartNew()
$message = ''
$actual = $null
try {
    try { $actual = Get-Sha256File -Path $path -RetryTimeoutSeconds 0.2 -RetryDelayMilliseconds 25 }
    catch { $message = $_.Exception.Message }
} finally { $handle.Dispose() }
Assert-True ($message -like '*arquivo continua em uso*') 'Bloqueio persistente nao recebeu diagnostico proprio.'
Assert-True ($message.Contains($path)) 'O erro nao identifica o componente bloqueado.'
Assert-True ($null -eq $actual) 'Um arquivo nao lido recebeu um hash.'
Assert-True ($watch.Elapsed.TotalSeconds -lt 3) 'A espera excedeu o prazo limitado.'
""",
        )

    def test_missing_file_is_not_retried_as_sharing_violation(self):
        self.run_harness(
            "install.ps1",
            r"""
$watch = [Diagnostics.Stopwatch]::StartNew()
$failed = $false
try { Get-Sha256File -Path (Join-Path $root 'ausente.exe') -RetryTimeoutSeconds 5 | Out-Null }
catch {
    $failure = $_.Exception
    while ($failure.InnerException) { $failure = $failure.InnerException }
    $failed = $failure -is [IO.FileNotFoundException]
}
Assert-True $failed 'Arquivo ausente foi aceito ou confundido com bloqueio temporario.'
Assert-True ($watch.Elapsed.TotalSeconds -lt 3) 'Arquivo ausente acionou espera indevida.'
""",
        )

    def test_payload_still_rejects_changed_bytes_after_lock_is_released(self):
        self.run_harness(
            "install.ps1",
            RELEASING_LOCK
            + r"""
$PayloadDir = Join-Path $root 'payload'
$ManifestPath = Join-Path $PayloadDir 'payload manifest.json'
$path = Join-Path $PayloadDir 'NexoFlow Noturno.exe'
Write-Fixture $path 'conteudo original'
$expected = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
@{ files = @(@{ path = 'NexoFlow Noturno.exe'; sha256 = $expected }) } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $ManifestPath -Encoding UTF8
Write-Fixture $path 'conteudo alterado'
Write-Fixture (Join-Path $InstallDir 'original.txt') 'instalacao anterior'
$handle = [NexoFlowHashTestLock]::Hold($path, 700)
$message = ''
try { try { Validate-Payload } catch { $message = $_.Exception.Message } }
finally { $handle.Dispose() }
Assert-True ($message -like '*Falha de integridade*') 'O bloqueio fez o Setup dispensar a verificacao do manifesto.'
Assert-True ((Get-Content -LiteralPath (Join-Path $InstallDir 'original.txt') -Raw) -ceq 'instalacao anterior') 'A instalacao anterior foi alterada.'
""",
        )
