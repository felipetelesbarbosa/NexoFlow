"""Compatibilidade em bytes entre a carga em andamento e o pacote corretivo."""

import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.check_history_quota_contract import MODULES, PACKAGED_SIGNATURE, verify

ROOT = Path(__file__).resolve().parents[1]


class PackageContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "test.zip"

    def package(
        self,
        *,
        prefix="NexoFlow/",
        eol=b"\r\n",
        changed=None,
        omit=None,
        duplicate=None,
        wired=True,
    ):
        with zipfile.ZipFile(self.path, "w") as archive:
            for name in (
                *MODULES,
                "history_sheets_quota.py",
                "history_publish_cli.py",
                "history_sheets_bulk.py",
                "history_batch_progress.py",
                "analytics_history_sync.py",
                "duration_display.py",
            ):
                if name == omit:
                    continue
                body = (
                    (ROOT / "app" / name)
                    .read_bytes()
                    .replace(b"\r\n", b"\n")
                    .replace(b"\n", eol)
                )
                if name == changed:
                    body += b"\n# altered"
                if not wired and name == "history_publish_cli.py":
                    body = b"from order_history_sheets import google_store_type\n"
                archive.writestr(prefix + "app/" + name, body)
                if name == duplicate:
                    with self.assertWarns(UserWarning):
                        archive.writestr(prefix + "app/" + name, body)

    def test_official_bytes_project_and_setup_are_accepted(self):
        for prefix in ("NexoFlow/", "NexoFlow Setup/payload/"):
            self.package(prefix=prefix)
            self.assertEqual(verify(self.path, prefix), PACKAGED_SIGNATURE)

    def test_equivalent_lf_is_not_enough_for_installed_windows_receipt(self):
        self.package(eol=b"\n")
        with self.assertRaisesRegex(ValueError, "Contrato da revisão mudou"):
            verify(self.path, "NexoFlow/")

    def test_changed_contract_missing_or_duplicate_modules_block(self):
        for options in (
            dict(changed="history_sheets_transport.py"),
            dict(omit="history_sheets_quota.py"),
            dict(omit="history_sheets_bulk.py"),
            dict(omit="history_batch_progress.py"),
            dict(duplicate="google_sheets.py"),
            dict(wired=False),
        ):
            with self.subTest(options=options):
                self.package(**options)
                with self.assertRaises(ValueError):
                    verify(self.path, "NexoFlow/")
