"""Exercise the Windows review gate without opening UI or calling services."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "nt", "Requires Windows CMD and Windows PowerShell")
class WeniReviewBatchWindowsTests(unittest.TestCase):
    """Run the real BAT, replacing only its external service and UI calls."""

    def _wait_until(self, predicate, process, output_path: Path, description: str) -> None:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if predicate():
                return
            if process.poll() is not None:
                self.fail(
                    f"CMD exited before {description}: {process.returncode}\n"
                    f"{output_path.read_text(encoding='utf-8', errors='replace')}"
                )
            time.sleep(0.05)
        self.fail(f"Timed out waiting for {description}")

    def _close_process(self, process) -> None:
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

    def _fixture(self, directory: Path) -> None:
        (directory / "scripts").mkdir()
        (directory / "scripts" / "confirmar_revisao_weni.ps1").write_bytes(
            (REPOSITORY / "scripts" / "confirmar_revisao_weni.ps1").read_bytes()
        )
        for name in ("check-up.bat", "testar_update_weni.bat"):
            (directory / name).write_text("@echo off\nexit /b 0\n", encoding="ascii")
        (directory / "run_update_weni.py").write_text(
            """import json
import sys
from pathlib import Path

args = sys.argv[1:]
if '--dry-run' in args:
    snapshot = Path(args[args.index('--review-out') + 1])
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    payload = {'fixture': 'frozen-review-snapshot', 'dry_run_args': args}
    snapshot.write_text(json.dumps(payload), encoding='utf-8')
    snapshot.with_suffix('.txt').write_text('Synthetic review, no customer data.', encoding='utf-8')
    Path('dry_run.json').write_text(json.dumps(args), encoding='utf-8')
elif '--apply' in args:
    snapshot = Path(args[args.index('--require-review') + 1])
    payload = json.loads(snapshot.read_text(encoding='utf-8'))
    Path('apply.json').write_text(json.dumps({'args': args, 'snapshot': payload}), encoding='utf-8')
else:
    raise SystemExit('Unexpected fixture command')
""",
            encoding="utf-8",
        )
        (directory / "notepad_stub.py").write_text(
            """import json
import sys
from pathlib import Path
Path('notepad_closed.json').write_text(json.dumps(sys.argv[1:]), encoding='utf-8')
""",
            encoding="utf-8",
        )
        (directory / "review_gate_stub.py").write_text(
            """import json
import sys
import time
from pathlib import Path
Path('review_waiting.json').write_text(json.dumps(sys.argv[1:]), encoding='utf-8')
deadline = time.monotonic() + 30
decision = Path('review_decision.txt')
while not decision.exists():
    if time.monotonic() >= deadline:
        raise SystemExit(90)
    time.sleep(0.05)
raise SystemExit(int(decision.read_text(encoding='ascii')))
""",
            encoding="utf-8",
        )

        batch = (REPOSITORY / "atualizar_weni_carga_completa.bat").read_text(encoding="utf-8")
        # Production continues using CON. Only the isolated fixture accepts a pipe.
        batch = batch.replace(" < CON", "")
        self.assertIn('".venv\\Scripts\\python.exe"', batch)
        batch = batch.replace('".venv\\Scripts\\python.exe"', f'"{sys.executable}"')
        batch, note_count = re.subn(
            r'(?m)^start "" notepad\.exe (.+)$',
            lambda match: (
                f'start "" /b "{sys.executable}" "{directory / "notepad_stub.py"}" '
                + match.group(1)
            ),
            batch,
        )
        self.assertEqual(note_count, 1, "Notepad fixture must replace exactly one external call")
        batch, gate_count = re.subn(
            r'(?m)^"%SystemRoot%\\System32\\WindowsPowerShell\\v1\.0\\powershell\.exe"[^\n]*$',
            lambda match: (
                f'"{sys.executable}" "{directory / "review_gate_stub.py"}" %CONFIRM_PART%'
            ),
            batch,
        )
        self.assertEqual(gate_count, 1, "Review fixture must replace exactly one external call")
        (directory / "atualizar_weni_carga_completa.bat").write_text(batch, encoding="utf-8")

    def _run_batch_case(self, *, part: int, decision: int) -> None:
        with tempfile.TemporaryDirectory(prefix="nexoflow review ") as temporary:
            directory = Path(temporary)
            self._fixture(directory)
            output_path = directory / "console.log"
            with output_path.open("wb") as output:
                process = subprocess.Popen(
                    [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", "atualizar_weni_carga_completa.bat"],
                    cwd=directory,
                    stdin=subprocess.PIPE,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                )
                try:
                    process.stdin.write(f"{part}\r\n".encode("ascii"))
                    process.stdin.flush()
                    self._wait_until(
                        lambda: (directory / "review_waiting.json").exists()
                        and (directory / "notepad_closed.json").exists(),
                        process,
                        output_path,
                        "the human review gate after Notepad has closed",
                    )
                    time.sleep(0.2)
                    self.assertIsNone(process.poll(), "Closing Notepad must not close the CMD")
                    self.assertFalse((directory / "apply.json").exists(), "Apply must wait for approval")

                    suffix = f"_25_parte_{part}" if part else ""
                    snapshot_name = f"logs\\weni_update_review_full{suffix}.json"
                    review_name = f"weni_update_review_full{suffix}.txt"
                    note_args = json.loads((directory / "notepad_closed.json").read_text(encoding="utf-8"))
                    self.assertEqual(len(note_args), 1)
                    self.assertEqual(Path(note_args[0]).name, review_name)
                    self.assertTrue(Path(note_args[0]).is_absolute())
                    gate_args = json.loads((directory / "review_waiting.json").read_text(encoding="utf-8"))
                    self.assertEqual(gate_args, ["-Part", str(part)] if part else [])

                    dry_args = json.loads((directory / "dry_run.json").read_text(encoding="utf-8"))
                    self.assertIn("--full", dry_args)
                    self.assertEqual(dry_args[dry_args.index("--review-out") + 1], snapshot_name)
                    if part:
                        self.assertEqual(dry_args[dry_args.index("--quarter") + 1], str(part))
                    else:
                        self.assertNotIn("--quarter", dry_args)

                    (directory / "review_decision.txt").write_text(str(decision), encoding="ascii")
                    expected_output = {
                        0: "[ETAPA 6/6]",
                        2: "Operacao cancelada",
                        3: "Processo interrompido",
                    }[decision]
                    self._wait_until(
                        lambda: expected_output in output_path.read_text(encoding="utf-8", errors="replace"),
                        process,
                        output_path,
                        "the final diagnostic and console pause",
                    )
                    time.sleep(0.2)
                    self.assertIsNone(process.poll(), "The final diagnostic must remain visible until Enter")
                    if decision == 0:
                        applied = json.loads((directory / "apply.json").read_text(encoding="utf-8"))
                        self.assertEqual(
                            applied["args"][applied["args"].index("--require-review") + 1], snapshot_name
                        )
                        self.assertEqual(applied["snapshot"]["dry_run_args"], dry_args)
                        self.assertEqual(applied["snapshot"]["fixture"], "frozen-review-snapshot")
                        self.assertIn("--full", applied["args"])
                        if part:
                            self.assertEqual(applied["args"][applied["args"].index("--quarter") + 1], str(part))
                        else:
                            self.assertNotIn("--quarter", applied["args"])
                    else:
                        self.assertFalse((directory / "apply.json").exists(), "Cancellation or UI failure must not apply")
                    process.stdin.write(b"\r\n")
                    process.stdin.flush()
                    self.assertEqual(process.wait(timeout=10), decision)
                finally:
                    self._close_process(process)

    def test_missing_review_helper_fails_before_services_and_keeps_console_open(self) -> None:
        with tempfile.TemporaryDirectory(prefix="nexoflow missing review ") as temporary:
            directory = Path(temporary)
            self._fixture(directory)
            (directory / "scripts" / "confirmar_revisao_weni.ps1").unlink()
            output_path = directory / "console.log"
            with output_path.open("wb") as output:
                process = subprocess.Popen(
                    [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", "atualizar_weni_carga_completa.bat"],
                    cwd=directory,
                    stdin=subprocess.PIPE,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                )
                try:
                    process.stdin.write(b"0\r\n")
                    process.stdin.flush()
                    self._wait_until(
                        lambda: "[ERRO] Codigo de saida: 3" in output_path.read_text(encoding="utf-8", errors="replace"),
                        process,
                        output_path,
                        "the missing-helper diagnostic and console pause",
                    )
                    time.sleep(0.2)
                    self.assertIsNone(process.poll(), "The missing-helper diagnostic must remain visible")
                    for marker in ("dry_run.json", "notepad_closed.json", "review_waiting.json", "apply.json"):
                        self.assertFalse((directory / marker).exists(), f"Missing helper must prevent {marker}")
                    process.stdin.write(b"\r\n")
                    process.stdin.flush()
                    self.assertEqual(process.wait(timeout=10), 3)
                finally:
                    self._close_process(process)

    def test_full_load_waits_for_approval_and_applies_the_frozen_snapshot(self) -> None:
        self._run_batch_case(part=0, decision=0)

    def test_all_four_parts_wait_for_approval_and_apply_their_own_snapshot(self) -> None:
        for part in (1, 2, 3, 4):
            with self.subTest(part=part):
                self._run_batch_case(part=part, decision=0)

    def test_cancelled_review_keeps_console_open_and_returns_2(self) -> None:
        for part in (0, 2):
            with self.subTest(part=part):
                self._run_batch_case(part=part, decision=2)

    def test_failed_review_keeps_console_open_and_returns_3(self) -> None:
        for part in (0, 2):
            with self.subTest(part=part):
                self._run_batch_case(part=part, decision=3)


@unittest.skipUnless(os.name == "nt", "Requires Windows PowerShell")
class WeniReviewDialogWindowsTests(unittest.TestCase):
    """Test the actual PowerShell decision logic while replacing the GUI only."""

    def _run_dialog(self, expression: str, expected_code: int, *, part: str = "") -> None:
        script = REPOSITORY / "scripts" / "confirmar_revisao_weni.ps1"
        script_literal = str(script).replace("'", "''")
        with tempfile.TemporaryDirectory(prefix="nexoflow dialog ") as temporary:
            harness = Path(temporary) / "review_harness.ps1"
            harness.write_text(
                f". '{script_literal}'\n"
                "function Show-WeniReviewDialog {\n"
                "    param([string]$Message, [string]$Title)\n"
                f"    {expression}\n"
                "}\n"
                f"exit (Confirm-WeniReview -Part '{part}')\n",
                encoding="utf-8-sig",
            )
            result = subprocess.run(
                [
                    str(Path(os.environ["SystemRoot"]) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"),
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-STA",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(harness),
                ],
                capture_output=True,
                timeout=15,
                check=False,
            )
            self.assertEqual(expected_code, result.returncode, result.stdout + result.stderr)

    def test_exact_confirmation_and_trimmed_case_variant_are_accepted(self) -> None:
        for value in ("CARGA COMPLETA REVISADA", "  carga completa revisada  "):
            with self.subTest(response=value):
                self._run_dialog(f"return '{value}'", 0)

    def test_quarter_is_shown_in_the_real_review_message(self) -> None:
        self._run_dialog(
            "if ($Message -notlike '*Parte 2/4*') { throw 'Missing quarter in review message' }; "
            "return 'CARGA COMPLETA REVISADA'",
            0,
            part="2",
        )

    def test_empty_confirmation_is_cancelled(self) -> None:
        self._run_dialog("return ''", 2)

    def test_inexact_confirmation_is_cancelled(self) -> None:
        self._run_dialog("return 'CARGA COMPLETA REVISADA depois'", 2)

    def test_dialog_exception_fails_closed(self) -> None:
        self._run_dialog("throw 'Synthetic dialog failure'", 3)


if __name__ == "__main__":
    unittest.main()
