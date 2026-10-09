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


@unittest.skipUnless(os.name == 'nt', 'Requer CMD do Windows')
class SpreadsheetReviewWindowsTests(unittest.TestCase):
    def run_case(self, target, decision, dry_failure=False):
        with tempfile.TemporaryDirectory(prefix='nexo planilhas ') as temp:
            root = Path(temp)
            (root/'run_delivery_tickets.py').write_text('''import json,sys
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
''',encoding='utf-8')
            (root/'notepad_stub.py').write_text("from pathlib import Path\nPath('note_closed').write_text('closed')\n",encoding='utf-8')
            if dry_failure: (root/'fail_dry').touch()
            batch=(ROOT/'carga_planilhas.bat').read_text(encoding='utf-8')
            batch=batch.replace('".venv\\Scripts\\python.exe"', f'"{sys.executable}"')
            batch=batch.replace('start "" notepad.exe', f'start "" /b "{sys.executable}" "{root / "notepad_stub.py"}"')
            (root/'carga_planilhas.bat').write_text(batch,encoding='utf-8')
            env={**os.environ,'NEXOFLOW_LAUNCHER':'1'}
            output=root/'console.log'
            with output.open('wb') as handle:
                process=subprocess.Popen([os.environ.get('COMSPEC','cmd.exe'),'/d','/c','carga_planilhas.bat',target],cwd=root,env=env,stdin=subprocess.PIPE,stdout=handle,stderr=subprocess.STDOUT)
                try:
                    if dry_failure:
                        self.assertEqual(process.wait(timeout=15),9)
                    else:
                        deadline=time.monotonic()+15
                        while not (root/'note_closed').exists() and time.monotonic()<deadline:
                            if process.poll() is not None:
                                self.fail('CMD fechou antes da revisão: '+output.read_text(encoding='utf-8',errors='replace'))
                            time.sleep(.05)
                        self.assertTrue((root/'note_closed').exists())
                        self.assertIsNone(process.poll(), 'Fechar o Bloco de Notas não pode fechar o CMD')
                        self.assertFalse((root/'applied.json').exists())
                        process.stdin.write((decision+'\r\n').encode('ascii'));process.stdin.flush()
                        self.assertEqual(process.wait(timeout=15),0 if decision=='PLANILHAS REVISADAS' else 2)
                    if not dry_failure and decision=='PLANILHAS REVISADAS':
                        applied=json.loads((root/'applied.json').read_text())
                        args=applied['args'];dry=applied['snapshot']['args']
                        self.assertEqual(args[args.index('--target')+1],target)
                        self.assertEqual(dry[dry.index('--target')+1],target)
                        self.assertIn('--planilhas',dry)
                        self.assertEqual(args[args.index('--require-review')+1],dry[dry.index('--review-out')+1])
                    else:self.assertFalse((root/'applied.json').exists())
                finally:
                    if process.poll() is None:
                        process.kill();process.wait(timeout=10)
                    process.stdin.close()

    def test_both_targets_apply_only_after_review_and_notepad_exit_keeps_cmd_open(self):
        for target in ['weni','analytics']:
            with self.subTest(target=target):self.run_case(target,'PLANILHAS REVISADAS')

    def test_cancellation_does_not_apply(self):
        self.run_case('weni','CANCELAR')

    def test_failed_dry_run_never_applies(self):
        self.run_case('analytics','PLANILHAS REVISADAS',dry_failure=True)
