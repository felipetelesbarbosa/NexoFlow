"""Confirmação da carga XLSX no CMD, sem serviços externos ou UI real."""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "nt", "Requer CMD do Windows")
class SpreadsheetReviewWindowsTests(unittest.TestCase):
    def run_case(self, target, decision, dry_failure=False, closed_stdin=False):
        with tempfile.TemporaryDirectory(prefix="nexo planilhas ") as temp:
            root = Path(temp)
            (root / "run_delivery_tickets.py").write_text(
                """import json,sys
from pathlib import Path
args=sys.argv[1:]
if '--dry-run' in args:
    if Path('fail_dry').exists(): raise SystemExit(9)
    p=Path(args[args.index('--review-out')+1]);p.parent.mkdir(exist_ok=True)
    p.write_text(json.dumps({'args':args}))
    p.with_suffix('.txt').write_text('Revisao sintetica sem dados pessoais.')
else:
    p=Path(args[args.index('--require-review')+1])
    Path('applied.json').write_text(json.dumps({'args':args,'snapshot':json.loads(p.read_text())}))
""",
                encoding="utf-8",
            )
            (root / "notepad_stub.py").write_text(
                f"from pathlib import Path\nPath({str(root / 'note_closed')!r}).write_text('closed')\n",
                encoding="utf-8",
            )
            if dry_failure:
                (root / "fail_dry").touch()
            batch = (ROOT / "carga_planilhas.bat").read_text(encoding="utf-8")
            batch = batch.replace('".venv\\Scripts\\python.exe"', f'"{sys.executable}"')
            # A GUI editor does not share CMD's blocked stdin. A /b console
            # Python child can block during startup while SET /P reads the pipe.
            gui_python = Path(sys.executable).with_name("pythonw.exe")
            self.assertTrue(gui_python.is_file())
            batch = batch.replace(
                'start "" notepad.exe',
                f'start "" "{gui_python}" "{root / "notepad_stub.py"}"',
            )
            scripts = root / "scripts"
            scripts.mkdir()
            real_script = scripts / "real_review.ps1"
            real_script.write_bytes(
                (ROOT / "scripts" / "confirmar_revisao_weni.ps1").read_bytes()
            )
            (scripts / "confirmar_revisao_weni.ps1").write_text(
                "param([string]$Expected,[string]$Title)\n"
                '. "$PSScriptRoot/real_review.ps1" -Expected $Expected -Title $Title\n'
                "function Show-WeniReviewDialog { param([string]$Message,[string]$Title)\n"
                ' Set-Content -LiteralPath "$PSScriptRoot/../dialog_open" -Value $Message -Encoding UTF8\n'
                ' while (-not (Test-Path -LiteralPath "$PSScriptRoot/../decision")) { Start-Sleep -Milliseconds 50 }\n'
                ' return (Get-Content -LiteralPath "$PSScriptRoot/../decision" -Raw)\n}\n'
                "exit (Confirm-WeniReview -Expected $Expected -Title $Title)\n",
                encoding="utf-8-sig",
            )
            (root / "carga_planilhas.bat").write_text(batch, encoding="utf-8")
            env = {**os.environ, "NEXOFLOW_LAUNCHER": "1"}
            output = root / "console.log"
            with output.open("wb") as handle:
                process = subprocess.Popen(
                    [
                        os.environ.get("COMSPEC", "cmd.exe"),
                        "/d",
                        "/c",
                        "carga_planilhas.bat",
                        target,
                    ],
                    cwd=root,
                    env=env,
                    stdin=subprocess.DEVNULL if closed_stdin else subprocess.PIPE,
                    stdout=handle,
                    stderr=subprocess.STDOUT,
                )
                try:
                    if dry_failure:
                        self.assertEqual(process.wait(timeout=15), 9)
                    else:
                        deadline = time.monotonic() + 45
                        while (
                            not (
                                (root / "note_closed").exists()
                                and (root / "dialog_open").exists()
                            )
                            and time.monotonic() < deadline
                        ):
                            if process.poll() is not None:
                                self.fail(
                                    "CMD fechou antes da revisão: "
                                    + output.read_text(
                                        encoding="utf-8", errors="replace"
                                    )
                                )
                            time.sleep(0.05)
                        self.assertTrue(
                            (root / "note_closed").exists(),
                            output.read_text(encoding="utf-8", errors="replace"),
                        )
                        self.assertTrue((root / "dialog_open").exists())
                        self.assertIn(
                            "PLANILHAS REVISADAS",
                            (root / "dialog_open").read_text(encoding="utf-8-sig"),
                        )
                        self.assertIsNone(
                            process.poll(),
                            "Fechar o Bloco de Notas não pode fechar o CMD",
                        )
                        self.assertFalse((root / "applied.json").exists())
                        # Publicar a resposta completa: o PowerShell pode ler
                        # entre a criação do arquivo e a escrita de seu conteúdo.
                        pending = root / "decision.pending"
                        pending.write_text(decision, encoding="ascii")
                        os.replace(pending, root / "decision")
                        self.assertEqual(
                            process.wait(timeout=15),
                            0 if decision == "PLANILHAS REVISADAS" else 2,
                            output.read_text(encoding="utf-8", errors="replace"),
                        )
                    if not dry_failure and decision == "PLANILHAS REVISADAS":
                        applied = json.loads((root / "applied.json").read_text())
                        args = applied["args"]
                        dry = applied["snapshot"]["args"]
                        self.assertEqual(args[args.index("--target") + 1], target)
                        self.assertEqual(dry[dry.index("--target") + 1], target)
                        self.assertIn("--planilhas", dry)
                        self.assertEqual(
                            args[args.index("--require-review") + 1],
                            dry[dry.index("--review-out") + 1],
                        )
                    else:
                        self.assertFalse((root / "applied.json").exists())
                finally:
                    if process.poll() is None:
                        subprocess.run(
                            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=10,
                            check=False,
                        )
                        process.wait(timeout=10)
                    if process.stdin:
                        process.stdin.close()

    def test_both_targets_apply_only_after_review_and_notepad_exit_keeps_cmd_open(self):
        for target in ["weni", "analytics"]:
            with self.subTest(target=target):
                self.run_case(target, "PLANILHAS REVISADAS")

    def test_closed_stdin_still_waits_for_explicit_dialog_confirmation(self):
        for target in ["weni", "analytics"]:
            with self.subTest(target=target):
                self.run_case(target, "PLANILHAS REVISADAS", closed_stdin=True)

    def test_cancellation_does_not_apply(self):
        self.run_case("weni", "CANCELAR")

    def test_failed_dry_run_never_applies(self):
        self.run_case("analytics", "PLANILHAS REVISADAS", dry_failure=True)
