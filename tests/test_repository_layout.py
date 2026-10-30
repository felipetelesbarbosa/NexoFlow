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


class ReleaseSigningOrderTests(unittest.TestCase):
    def test_build_signs_final_bytes_before_payload_hashes_and_archives(self):
        root = Path(__file__).resolve().parents[1]
        path = root / "scripts/build_release.ps1"
        if not path.is_file():
            self.skipTest("Build disponível no repositório, fora da instalação.")
        text = path.read_text(encoding="utf-8-sig")
        icon = text.index('Write-Host "==> Incorporando ícones PE')
        sign = text.index("Invoke-NexoFolderSigning -Root $PayloadDir")
        manifest = text.index("Write-PayloadManifest -Payload $PayloadDir")
        setup_icon = text.index('Write-Host "==> Incorporando ícone próprio')
        setup_sign = text.index(
            "Set-AuthenticodeSignature -LiteralPath (Join-Path $SetupRoot"
        )
        report = text.index("test_release_security_windows.ps1")
        checksum = text.index("Write-Checksums -Root $SetupRoot")
        archive = text.index("Compress-Archive -Path $SetupRoot")
        self.assertEqual(
            sorted(
                [
                    icon,
                    sign,
                    manifest,
                    setup_icon,
                    setup_sign,
                    report,
                    checksum,
                    archive,
                ]
            ),
            [icon, sign, manifest, setup_icon, setup_sign, report, checksum, archive],
        )
        self.assertIn("elseif ($RequireSignature)", text)
        self.assertNotIn("Add-MpPreference", text)
