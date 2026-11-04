"""Validação offline por arquivo, sem quoting de código Python entre shells."""

import importlib.metadata
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from connectors.meta_ads_mcp.validate_environment import environment_compatible

ROOT = Path(__file__).resolve().parents[1]


class MetaEnvironmentValidatorTests(unittest.TestCase):
    def validate(self, py=(3, 14), mcp="1.28.0", requests="2.33.0", sdk=None):
        versions = {"mcp": mcp, "requests": requests}
        return environment_compatible(
            py,
            package_version=versions.__getitem__,
            import_module=lambda _: sdk or SimpleNamespace(FastMCP=lambda: None),
        )

    def test_supported_versions_and_patch_updates(self):
        self.assertTrue(self.validate())
        self.assertTrue(self.validate(mcp="1.29.5", requests="2.34.1"))

    def test_python_must_be_314(self):
        for py in ((3, 12), (3, 13), (3, 15)):
            self.assertFalse(self.validate(py=py))

    def test_missing_wrong_or_malformed_packages(self):
        for mcp, requests in [
            ("1.27.9", "2.33.0"),
            ("2.0.0", "2.33.0"),
            ("1.28.0", "2.32.0"),
            ("1.28.0", "3.0.0"),
            ("invalid", "2.33.0"),
            ("1.28.0rc1", "2.33.0"),
        ]:
            self.assertFalse(self.validate(mcp=mcp, requests=requests))
        with self.subTest("missing package"):
            missing = Mock(side_effect=importlib.metadata.PackageNotFoundError("mcp"))
            self.assertFalse(environment_compatible((3, 14), package_version=missing))

    def test_sdk_import_must_succeed_and_expose_fastmcp(self):
        self.assertFalse(self.validate(sdk=SimpleNamespace(FastMCP=None)))
        importer = Mock(side_effect=ImportError("synthetic"))
        self.assertFalse(
            environment_compatible(
                (3, 14), package_version=lambda name: "1.28.0" if name == "mcp" else "2.33.0", import_module=importer
            )
        )

    def test_script_invocation_has_no_syntax_error_or_stdout(self):
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "connectors/meta_ads_mcp/validate_environment.py"),
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertIn(result.returncode, (0, 1))
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")

    def test_powershell_invokes_file_without_python_code_quoting(self):
        shell = shutil.which("pwsh") or shutil.which("powershell")
        if shell is None:
            private = Path("/workspace/private/powershell/pwsh")
            shell = str(private) if private.is_file() else None
        if shell is None:
            self.skipTest("PowerShell indisponível")
        script = ROOT / "scripts/instalar_meta_ads_mcp.ps1"
        code = (
            ". '"
            + str(script).replace("'", "''")
            + "' -FunctionsOnly\n$venvPython='"
            + sys.executable.replace("'", "''")
            + "'\n$result=Test-MetaAdsEnvironment\nif($result -isnot [bool]){throw 'Expected boolean'}\n"
        )
        result = subprocess.run(
            [shell, "-NoProfile", "-Command", code],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("SyntaxError", result.stderr)
        self.assertNotIn("import re,sys", script.read_text(encoding="utf-8-sig"))
