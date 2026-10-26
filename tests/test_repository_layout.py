"""Caminhos do repositório e dos pacotes instalados."""

import tempfile
import unittest
from pathlib import Path

from project_paths import launcher_path


class RepositoryLayoutTests(unittest.TestCase):
    def test_installed_launcher_has_priority_over_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root / "native_launcher/prebuilt/Test.exe"
            reference.parent.mkdir(parents=True)
            reference.write_bytes(b"reference")
            self.assertEqual(launcher_path(root, "Test.exe"), reference)
            installed = root / "Test.exe"
            installed.write_bytes(b"installed")
            self.assertEqual(launcher_path(root, "Test.exe"), installed)

    def test_packages_recompile_instead_of_copying_reference_binaries(self):
        root = Path(__file__).resolve().parents[1]
        build_path = root / "scripts/build_release.ps1"
        if not build_path.is_file():
            self.skipTest("Script de build disponível somente no repositório.")
        build = build_path.read_text(encoding="utf-8-sig")
        self.assertIn(
            'if ($relative -like "native_launcher/prebuilt/*") { continue }', build
        )
        self.assertIn("go build -trimpath", build)
        for name in (
            "NexoFlow Analytics.exe",
            "NexoFlow Weni.exe",
            "NexoFlow Terminal.exe",
        ):
            self.assertTrue(launcher_path(root, name).is_file())
