"""Compatibilidade de empacotamento e documentação de fonte única."""

import io
import subprocess
import tempfile
import tomllib
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts import build_documentation as documentation

ROOT = Path(__file__).resolve().parents[1]


class DocumentationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / documentation.SOURCE_NAME
        self.output = self.root / documentation.OUTPUT_NAME
        self.source.parent.mkdir(parents=True, exist_ok=True)
        self.source.write_text(
            "# Operação\n\nRevisão antes da aplicação.\n", encoding="utf-8"
        )

    def generate(self, *, html_newline="\n"):
        rendered = '<!DOCTYPE html>\n<html lang="pt-BR"><body>Operação</body></html>\n'
        rendered = rendered.replace("\n", html_newline)
        with patch.object(
            documentation.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, stdout=rendered),
        ) as runner:
            documentation.generate_documentation(self.source, self.output)
        return runner

    def test_generation_passes_the_entire_source_and_portuguese_metadata(self):
        runner = self.generate()
        self.assertTrue(
            documentation.documentation_is_current(self.source, self.output)
        )
        runner.assert_called_once()
        self.assertEqual(
            runner.call_args.kwargs["input"], self.source.read_text(encoding="utf-8")
        )
        self.assertIn("--metadata=lang:pt-BR", runner.call_args.args[0])

    def test_source_change_requires_regeneration(self):
        self.generate()
        self.source.write_text("# Operação\n\nNova instrução.\n", encoding="utf-8")
        self.assertFalse(
            documentation.documentation_is_current(self.source, self.output)
        )

    def test_manual_html_change_is_rejected(self):
        self.generate()
        self.output.write_text(
            self.output.read_text(encoding="utf-8").replace(
                "Operação", "Instrução divergente"
            ),
            encoding="utf-8",
        )
        self.assertFalse(
            documentation.documentation_is_current(self.source, self.output)
        )

    def test_windows_checkout_newlines_do_not_invalidate_the_documentation(self):
        markdown = self.source.read_text(encoding="utf-8")
        for initial_newline in ("\n", "\r\n"):
            with self.subTest(initial_newline=repr(initial_newline)):
                self.source.write_bytes(
                    markdown.replace("\n", initial_newline).encode("utf-8")
                )
                self.generate()
                for path in (self.source, self.output):
                    # A fonte pode já ter CRLF; simular outro checkout não deve
                    # criar CRCRLF e, portanto, linhas extras ao reler o texto.
                    normalized = path.read_bytes().replace(b"\r\n", b"\n")
                    path.write_bytes(normalized.replace(b"\n", b"\r\n"))
                    self.assertNotIn(b"\r\r\n", path.read_bytes())
                self.assertTrue(
                    documentation.documentation_is_current(self.source, self.output)
                )

    def test_generation_normalizes_windows_source_and_pandoc_output(self):
        self.source.write_bytes(
            self.source.read_text(encoding="utf-8")
            .replace("\n", "\r\n")
            .encode("utf-8")
        )
        self.generate(html_newline="\r\n")
        self.assertNotIn(b"\r\n", self.output.read_bytes())
        self.assertTrue(
            documentation.documentation_is_current(self.source, self.output)
        )

    def test_check_does_not_call_pandoc_and_rejects_missing_output(self):
        with (
            patch.object(documentation, "ROOT", self.root),
            patch.object(documentation.subprocess, "run") as runner,
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(documentation.main(["--check"]), 1)
        runner.assert_not_called()

    def test_generation_reports_a_missing_pandoc(self):
        with (
            patch.object(documentation, "ROOT", self.root),
            patch.object(
                documentation.subprocess, "run", side_effect=FileNotFoundError
            ),
            redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(documentation.main([]), 1)
        self.assertIn("Instale o Pandoc", output.getvalue())

    def test_installed_html_matches_the_only_canonical_markdown(self):
        self.assertTrue(
            documentation.documentation_is_current(
                ROOT / documentation.SOURCE_NAME, ROOT / documentation.OUTPUT_NAME
            )
        )
        for name in (documentation.SOURCE_NAME, documentation.OUTPUT_NAME):
            self.assertFalse((ROOT / Path(name).name).exists())


class PackagingMetadataTests(unittest.TestCase):
    def test_metadata_preserves_version_and_python_311_support(self):
        metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(metadata["project"]["version"], "1.5")
        self.assertEqual(metadata["project"]["requires-python"], ">=3.11")
        self.assertEqual(metadata["tool"]["ruff"]["target-version"], "py311")

    def test_dependency_sources_and_public_modules_exclude_private_configuration(self):
        metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        setuptools = metadata["tool"]["setuptools"]
        self.assertEqual(
            setuptools["dynamic"]["dependencies"]["file"], ["requirements.txt"]
        )
        self.assertEqual(
            setuptools["dynamic"]["optional-dependencies"]["webhook"]["file"],
            ["dependencias/requirements-webhook.txt"],
        )
        self.assertIn("nexo_cli", setuptools["py-modules"])
        self.assertNotIn("secrets_config", setuptools["py-modules"])
        self.assertNotIn("secrets_config.example", setuptools["py-modules"])


if __name__ == "__main__":
    unittest.main()
