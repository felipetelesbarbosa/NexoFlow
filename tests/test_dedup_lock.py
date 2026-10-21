"""Recuperação e exclusão mútua no caminho real do bloqueio da carga Weni."""

import json
import os
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dedup_io import DEDUP_LOCK_PROTOCOL, DedupExecutionLockError, execution_lock

APP = Path(__file__).resolve().parents[1] / "app"
CHILD = """
import sys
sys.path.insert(0, sys.argv[1])
from dedup_io import DedupExecutionLockError, execution_lock
try:
    with execution_lock(sys.argv[2]) as record:
        print('LOCKED', record['pid'], flush=True)
        sys.stdin.readline()
except DedupExecutionLockError:
    print('BLOCKED', flush=True)
    sys.exit(42)
"""


class DedupLockTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.directory = Path(folder.name) / "duplicados"
        self.directory.mkdir()
        self.lock = self.directory / "execucao.lock"
        self.journal = self.directory / "state.json"
        self.journal.write_text('{"done": false}', encoding="utf-8")
        self.before = self.journal.read_bytes()

    def read_record(self):
        return json.loads(self.lock.read_text(encoding="utf-8"))

    def child(self):
        child = subprocess.Popen(
            [sys.executable, "-u", "-c", CHILD, str(APP), str(self.directory)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )

        def cleanup():
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=10)

        self.addCleanup(cleanup)
        return child

    def owner_pid(self, child):
        marker, pid = child.stdout.readline().strip().split()
        self.assertEqual(marker, "LOCKED")
        self.assertEqual(int(pid), self.read_record()["pid"])
        return int(pid)

    def test_terminated_legacy_owner_is_recovered_at_existing_weni_path(self):
        owner = subprocess.Popen([sys.executable, "-c", "pass"])
        owner.wait(timeout=10)
        self.lock.write_text(str(owner.pid), encoding="utf-8")
        inode = self.lock.stat().st_ino
        with execution_lock(self.directory) as record:
            self.assertEqual(record["protocol"], DEDUP_LOCK_PROTOCOL)
            self.assertEqual(record["pid"], os.getpid())
            self.assertIn("Weni", record["operation"])
        self.assertEqual(self.read_record()["status"], "released")
        self.assertEqual(self.lock.stat().st_ino, inode)
        self.assertEqual(self.journal.read_bytes(), self.before)

    def test_active_legacy_pid_and_unverifiable_metadata_are_preserved(self):
        for content, alive in (
            (str(os.getpid()), True),
            ("12345", None),
            ("", False),
            ("corrompido", False),
        ):
            with self.subTest(content=content):
                self.lock.write_text(content, encoding="utf-8")
                with patch("recompra_lock._pid_is_alive", return_value=alive):
                    with self.assertRaises(DedupExecutionLockError):
                        with execution_lock(self.directory):
                            self.fail("Não há comprovação do encerramento.")
                self.assertEqual(self.lock.read_text(encoding="utf-8"), content)

    def test_active_weni_owner_blocks_both_local_and_subprocess_loads(self):
        owner = self.child()
        pid = self.owner_pid(owner)
        with self.assertRaisesRegex(DedupExecutionLockError, f"Weni.*PID {pid}"):
            with execution_lock(self.directory):
                self.fail("Duas cargas simultâneas foram admitidas.")
        contender = self.child()
        out, err = contender.communicate(timeout=10)
        self.assertEqual((contender.returncode, out.strip(), err), (42, "BLOCKED", ""))
        owner.communicate(input="encerrar\n", timeout=10)
        self.assertEqual(owner.returncode, 0)
        with execution_lock(self.directory):
            pass

    def test_killed_weni_owner_does_not_block_next_load(self):
        owner = self.child()
        pid = self.owner_pid(owner)
        inode = self.lock.stat().st_ino
        execution_id = self.read_record()["execution_id"]
        os.kill(pid, signal.SIGTERM)
        owner.communicate(timeout=10)
        self.assertEqual(self.read_record()["status"], "active")
        with execution_lock(self.directory) as recovered:
            self.assertNotEqual(recovered["execution_id"], execution_id)
        self.assertEqual(self.lock.stat().st_ino, inode)
        self.assertEqual(self.journal.read_bytes(), self.before)

    def test_interrupt_and_exception_release_without_deleting_audit_or_lock(self):
        for error in (RuntimeError("sintético"), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__):
                with self.assertRaises(type(error)):
                    with execution_lock(self.directory):
                        raise error
                self.assertEqual(self.read_record()["status"], "released")
                with execution_lock(self.directory):
                    pass
                self.assertEqual(self.journal.read_bytes(), self.before)
