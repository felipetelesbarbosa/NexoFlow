"""Contrato da versão pública e sequência de patches autorizada."""

import tomllib
import unittest
from pathlib import Path

from versioning import CURRENT_VERSION, next_version, parts, windows_version

ROOT = Path(__file__).resolve().parents[1]


class VersionPolicyTests(unittest.TestCase):
    def test_patch_sequence_and_rollover_do_not_skip_to_another_major(self):
        for before, after in (
            ("1.5", "1.5.1"),
            ("1.5.1", "1.5.2"),
            ("1.5.98", "1.5.99"),
            ("1.5.99", "1.6"),
            ("1.6", "1.6.1"),
        ):
            with self.subTest(version=before):
                self.assertEqual(next_version(before), after)

    def test_invalid_patch_numbers_are_rejected(self):
        for version in (
            "1.5.0",
            "1.5.100",
            "1.05",
            "1.5.01",
            "1.5.1.0",
            "v1.5",
            "1.5-dev",
        ):
            with self.subTest(version=version), self.assertRaises(ValueError):
                parts(version)

    def test_windows_metadata_has_four_components(self):
        self.assertEqual(windows_version("1.5"), "1.5.0.0")
        self.assertEqual(windows_version("1.5.99"), "1.5.99.0")
        self.assertEqual(windows_version("1.6"), "1.6.0.0")

    def test_runtime_installer_package_share_current_version(self):
        from main import APP_VERSION
        from nexo_cli import VERSION

        metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(CURRENT_VERSION, "1.5.7")
        self.assertEqual(APP_VERSION, CURRENT_VERSION)
        self.assertEqual(VERSION, CURRENT_VERSION)
        self.assertEqual(metadata["project"]["version"], CURRENT_VERSION)
        installer = (ROOT / "installer/install.ps1").read_text(encoding="utf-8-sig")
        self.assertIn(f"$AppVersion = '{CURRENT_VERSION}'", installer)
        self.assertIn(
            f"/releases/download/v{CURRENT_VERSION}/NexoFlow-Setup-{CURRENT_VERSION}.zip",
            (ROOT / "README.md").read_text(encoding="utf-8"),
        )

    @unittest.skipUnless(
        (ROOT / ".github/workflows/release-v1.yml").is_file(),
        "Workflow verificado no repositório; não faz parte da instalação.",
    )
    def test_repository_workflow_matches_version_and_preserves_previous_tags(self):
        workflow = (ROOT / ".github/workflows/release-v1.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn(f"NexoFlow-Setup-{CURRENT_VERSION}.zip", workflow)
        self.assertIn(f"gh release create v{CURRENT_VERSION}", workflow)
        self.assertNotIn("git push origin refs/tags/v1.5.7 --force", workflow)
        self.assertRegex(workflow, r"Incremente o patch")

    def test_runtime_contract_without_github_in_installed_layout(self):
        import shutil
        import tempfile
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as directory:
            installed = Path(directory)
            for relative in ("pyproject.toml", "installer/install.ps1", "README.md"):
                destination = installed / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative, destination)
            self.assertFalse((installed / ".github").exists())
            with patch(f"{__name__}.ROOT", installed):
                self.test_runtime_installer_package_share_current_version()
