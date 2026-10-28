"""Mensagens e códigos do BAT real da Recompra, com CLI e revisão simuladas."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "nt", "Requer CMD e Windows PowerShell")
class RecompraBatchWindowsTests(unittest.TestCase):
    def invoke(
        self,
        *,
        apply_code=0,
        dry_code=0,
        check_code=0,
        strict=False,
        cleanup=False,
        profile="FARMA",
    ):
        with tempfile.TemporaryDirectory(prefix="nexo recompra resultado ") as temp:
            root = Path(temp)
            for folder in ("app", "comandos", "scripts"):
                (root / folder).mkdir()
            (root / "scenario.json").write_text(
                json.dumps({"apply": apply_code, "dry": dry_code, "check": check_code}),
                encoding="utf-8",
            )
            # Somente as fronteiras externas são substituídas. O fluxo de
            # controle, revisão, ramificação e saída é o BAT distribuído.
            (root / "app/run_recompra.py").write_text(
                """import json, sys
from pathlib import Path
args = sys.argv[1:]
with Path('calls.jsonl').open('a', encoding='utf-8') as handle:
    handle.write(json.dumps(args) + '\\n')
scenario = json.loads(Path('scenario.json').read_text(encoding='utf-8'))
if '--check-only' in args:
    raise SystemExit(scenario['check'])
if '--dry-run' in args:
    review = Path(args[args.index('--review-out') + 1])
    review.parent.mkdir(exist_ok=True, parents=True)
    review.write_text('{}', encoding='utf-8')
    review.with_suffix('.txt').write_text('Revisao sintetica.', encoding='utf-8')
    raise SystemExit(scenario['dry'])
if '--check-review' in args:
    assert Path(args[args.index('--require-review') + 1]).is_file()
if '--apply' in args:
    assert Path('confirmed').is_file(), 'Aplicacao anterior a confirmacao'
    assert Path(args[args.index('--require-review') + 1]).is_file()
    raise SystemExit(scenario['apply'])
""",
                encoding="utf-8",
            )
            (root / "notepad_stub.py").write_text(
                "import sys\nfrom pathlib import Path\n"
                "assert Path(sys.argv[1]).is_file()\n"
                "Path('report_opened').touch()\n",
                encoding="utf-8",
            )
            (root / "scripts/confirmar_revisao_weni.ps1").write_text(
                "param([string]$Expected,[string]$Title)\n"
                "if (-not (Test-Path 'report_opened')) { exit 8 }\n"
                "if ($Expected -cne 'RECOMPRA REVISADA') { exit 9 }\n"
                "Set-Content -LiteralPath 'confirmed' -Value 'ok'\n"
                "exit 0\n",
                encoding="utf-8-sig",
            )
            batch_name = (
                "limpar_cancelados_recompra.bat"
                if cleanup
                else "atualizar_recompra.bat"
            )
            batch = (ROOT / "comandos" / batch_name).read_text(encoding="utf-8")
            if cleanup:
                batch = batch.replace(
                    'choice /c 12 /n /m "Escolha o segmento: "',
                    f'"{sys.executable}" -c "raise SystemExit({2 if profile == "PET" else 1})"',
                )
                confirmation = root / "scripts/confirmar_revisao_weni.ps1"
                confirmation.write_text(
                    confirmation.read_text(encoding="utf-8-sig").replace(
                        "RECOMPRA REVISADA", "LIMPEZA REVISADA"
                    ),
                    encoding="utf-8-sig",
                )
            self.assertIn('".venv\\Scripts\\python.exe"', batch)
            self.assertIn('start "" notepad.exe', batch)
            batch = batch.replace(
                '".venv\\Scripts\\python.exe"', f'"{sys.executable}"'
            ).replace(
                'start "" notepad.exe',
                f'"{sys.executable}" "{root / "notepad_stub.py"}"',
            )
            (root / "comandos" / batch_name).write_text(batch, encoding="utf-8")
            env = {**os.environ, "NEXOFLOW_LAUNCHER": "1"}
            env.pop("NEXOFLOW_FULL_WORKFLOW", None)
            if strict:
                env["NEXOFLOW_FULL_WORKFLOW"] = "1"
            process = subprocess.Popen(
                [
                    os.environ.get("COMSPEC", "cmd.exe"),
                    "/d",
                    "/c",
                    "comandos\\"
                    + batch_name
                    + (" PET" if profile == "PET" and not cleanup else ""),
                ],
                cwd=root,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            try:
                output, _ = process.communicate(timeout=45)
            finally:
                if process.poll() is None:
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=10,
                        check=False,
                    )
                    process.communicate(timeout=10)
            calls = [
                json.loads(line)
                for line in (root / "calls.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            return process.returncode, output.decode("utf-8", errors="replace"), calls

    def test_apply_success_partial_and_critical_failure_preserve_codes(self):
        expected = {
            0: "[OK] Recompra concluída.",
            3: "[AVISO] Recompra concluída com pendências.",
            1: "[ERRO] Recompra interrompida.",
        }
        for code, message in expected.items():
            with self.subTest(code=code):
                result, output, calls = self.invoke(apply_code=code)
                self.assertEqual(result, code, output)
                self.assertIn(message, output)
                self.assertEqual(
                    [args[0] for args in calls],
                    ["--check-only", "--dry-run", "--check-review", "--apply"],
                )
                self.assertEqual(sum("--apply" in args for args in calls), 1)
                self.assertEqual(
                    calls[1][calls[1].index("--review-out") + 1],
                    calls[3][calls[3].index("--require-review") + 1],
                )
                if code == 3:
                    self.assertIn(
                        "As alterações confirmadas foram preservadas.", output
                    )
                    self.assertIn("Não reaplique a revisão antiga", output)
                    self.assertNotIn("[ERRO]", output)
                if code == 1:
                    self.assertNotIn("concluída com pendências", output)

    def test_strict_dry_run_partial_is_not_reported_as_applied(self):
        code, output, calls = self.invoke(dry_code=3, strict=True)
        self.assertEqual(code, 3, output)
        self.assertEqual([args[0] for args in calls], ["--check-only", "--dry-run"])
        self.assertIn("--require-complete", calls[1])
        self.assertIn("A aplicação não foi iniciada nesta tentativa.", output)
        self.assertNotIn("concluída com pendências", output)

    def test_failed_preflight_does_not_open_review_or_apply(self):
        code, output, calls = self.invoke(check_code=1)
        self.assertEqual(code, 1, output)
        self.assertEqual(calls, [["--check-only", "--perfil", "FARMA"]])
        self.assertIn("[ERRO] Recompra interrompida.", output)

    def test_cleanup_real_batch_selects_profile_and_only_applies_reviewed_removals(
        self,
    ):
        for segment in ("FARMA", "PET"):
            for code in (0, 3, 1):
                with self.subTest(segment=segment, code=code):
                    result, output, calls = self.invoke(
                        cleanup=True, profile=segment, apply_code=code
                    )
                    self.assertEqual(result, code, output)
                    self.assertEqual(len(calls), 2)
                    self.assertTrue(
                        all("--cleanup-cancelled" in args for args in calls)
                    )
                    self.assertTrue(
                        all(
                            args[args.index("--perfil") + 1] == segment
                            for args in calls
                        )
                    )
                    self.assertIn("--dry-run", calls[0])
                    self.assertIn("--apply", calls[1])

    def test_pet_batch_uses_pet_paths_and_profile(self):
        result, output, calls = self.invoke(profile="PET")
        self.assertEqual(result, 0, output)
        self.assertTrue(
            all(args[args.index("--perfil") + 1] == "PET" for args in calls)
        )
        self.assertIn("PET", calls[1][calls[1].index("--review-out") + 1])
