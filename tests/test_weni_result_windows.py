"""Código e mensagem do BAT Weni real ao receber êxito parcial da Recompra."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "nt", "Requer CMD e Windows PowerShell")
class WeniResultWindowsTests(unittest.TestCase):
    def test_result_dialog_distinguishes_partial_from_critical_code_three(self):
        with tempfile.TemporaryDirectory(prefix="weni dialogo ") as folder:
            root = Path(folder)
            (root / "scripts").mkdir()
            script = root / "scripts/resultado_carga_weni.ps1"
            script.write_bytes((ROOT / "scripts/resultado_carga_weni.ps1").read_bytes())
            for stage, expected in (
                ("PARCIAL", "Carga concluída com pendências"),
                ("ERRO", "Carga interrompida. Código: 3"),
            ):
                with self.subTest(stage=stage):
                    # Substitui somente a janela; executa a classificação real.
                    command = (
                        "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
                        f". '{script}' -Stage '{stage}' -ResultCode 3; "
                        "function Show-WeniResult { param([string]$Message) [Console]::WriteLine($Message) }; "
                        "exit (Complete-WeniResult)"
                    )
                    process = subprocess.run(
                        [
                            "powershell.exe",
                            "-NoLogo",
                            "-NoProfile",
                            "-Command",
                            command,
                        ],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        timeout=30,
                        check=False,
                    )
                    text = process.stdout.decode("utf-8", errors="replace")
                    self.assertEqual(process.returncode, 0, text)
                    self.assertIn(expected, text)
                    if stage == "PARCIAL":
                        self.assertIn("Gere uma nova revisão", text)
                        self.assertNotIn("Carga interrompida", text)
                    else:
                        self.assertNotIn("Carga concluída com pendências", text)

    def invoke(self, recompra_code):
        with tempfile.TemporaryDirectory(prefix="weni resultado ") as folder:
            root = Path(folder)
            for directory in ("app", "comandos", "scripts"):
                (root / directory).mkdir()
            for name in ("check-up.bat", "testar_update_weni.bat"):
                (root / "comandos" / name).write_text("@exit /b 0\n")
            (root / "comandos/atualizar_recompra.bat").write_text(
                f"@exit /b {recompra_code}\n"
            )
            (root / "app/run_update_weni.py").write_text(
                "from pathlib import Path\n"
                "Path('weni_called').touch()\n"
                "raise SystemExit(0)\n"
            )
            (root / "secrets_config.py").write_text("RECOMPRA_ENABLED=True\n")
            (root / "scripts/confirmar_revisao_weni.ps1").write_text(
                "exit 0\n", encoding="utf-8-sig"
            )
            (root / "notepad_stub.py").write_text("raise SystemExit(0)\n")
            batch = (ROOT / "comandos/atualizar_weni.bat").read_text(encoding="utf-8")
            batch = batch.replace('".venv\\Scripts\\python.exe"', f'"{sys.executable}"')
            batch = batch.replace(
                'start "" notepad.exe',
                f'"{sys.executable}" "{root / "notepad_stub.py"}"',
            )
            (root / "comandos/atualizar_weni.bat").write_text(batch, encoding="utf-8")
            process = subprocess.run(
                [
                    os.environ.get("COMSPEC", "cmd.exe"),
                    "/d",
                    "/c",
                    "comandos\\atualizar_weni.bat",
                ],
                cwd=root,
                env={**os.environ, "NEXOFLOW_TERMINAL": "1"},
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=45,
                check=False,
            )
            self.assertTrue((root / "weni_called").is_file())
            return process.returncode, process.stdout.decode("utf-8", errors="replace")

    def test_partial_recompra_preserves_confirmations_and_partial_code(self):
        code, output = self.invoke(3)
        self.assertEqual(code, 3, output)
        self.assertIn("etapa Recompra com pendências de validação", output)
        self.assertIn("alterações já confirmadas foram preservadas", output)
        self.assertNotIn("recompra nao foi concluida", output)
        self.assertNotIn("[ERRO]", output)

    def test_success_and_critical_failure_remain_distinct(self):
        code, output = self.invoke(0)
        self.assertEqual(code, 0, output)
        self.assertIn("[OK] NexoFlow Weni concluído com sucesso", output)
        code, output = self.invoke(7)
        self.assertEqual(code, 7, output)
        self.assertIn(
            "[ERRO] Weni concluída; a etapa Recompra foi interrompida", output
        )
        self.assertNotIn("Fluxo Weni concluído com pendências", output)
