"""Contrato entre os atalhos criados pelo Setup e sua remoção."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class UninstallShortcutContractTests(unittest.TestCase):
    def test_uninstaller_covers_every_shortcut_created_by_setup(self):
        installer = (ROOT / "installer/install.ps1").read_text(encoding="utf-8-sig")
        uninstaller = (ROOT / "installer/uninstall.ps1").read_text(encoding="utf-8-sig")
        created = set(
            re.findall(
                r"Create-Shortcut -ShortcutPath \(Join-Path \$(?:desktop|startMenu) '([^']+\.lnk)'\)",
                installer,
            )
        )
        cleanup = uninstaller.split("function Remove-Shortcuts {", 1)[1].split(
            "function Remove-OptionalPrivateData", 1
        )[0]
        removable = set(re.findall(r"'([^']+\.lnk)'", cleanup))
        self.assertTrue(created)
        self.assertFalse(
            created - removable, f"Atalhos sem remoção: {created - removable}"
        )
        self.assertIn("NexoFlow Recompra.lnk", removable)

    def test_cleanup_keeps_original_user_roots_through_elevation_and_stage2(self):
        uninstaller = (ROOT / "installer/uninstall.ps1").read_text(encoding="utf-8-sig")
        elevation = uninstaller.split("function Ensure-Administrator {", 1)[1].split(
            "function Get-ShortcutDirectories", 1
        )[0]
        self.assertIn("'-ShortcutRootsBase64', $ShortcutRootsBase64", elevation)
        stage2 = uninstaller.split("$argLine =", 1)[1]
        self.assertIn('-ShortcutRootsBase64 "{4}"', stage2)


if __name__ == "__main__":
    unittest.main()
