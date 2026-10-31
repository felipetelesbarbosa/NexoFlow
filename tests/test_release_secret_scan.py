"""Validação de publicação com arquivos e respostas do scanner sintéticos."""

import hashlib
import io
import json
import os
import stat
import subprocess
import tempfile
import unittest
import warnings
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts import check_release_secrets as scan


class ReleaseSecretScanTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        # No Windows, TEMP pode usar o alias 8.3 RUNNER~1. Compare caminhos
        # canônicos, como os que o scanner recebe, sem alterar a verificação.
        self.root = Path(self.temporary.name).resolve()
        self.repo = self.root / "repo"
        self.assets = self.root / "assets"
        self.repo.mkdir()
        self.assets.mkdir()
        (self.repo / ".gitleaks.toml").write_text(
            "[extend]\nuseDefault = true\n", encoding="utf-8"
        )

    def write_hashes(self):
        hashes = [
            f"{hashlib.sha256((self.assets / name).read_bytes()).hexdigest()}  {name}"
            for name in scan.PACKAGE_NAMES
        ]
        (self.assets / scan.CHECKSUM_NAME).write_text(
            "\n".join(hashes) + "\n", encoding="utf-8"
        )

    def write_packages(self, *, setup_entries=None, project_entries=None):
        entries = (
            setup_entries
            if setup_entries is not None
            else [("NexoFlow Setup/payload/README.txt", "setup seguro")],
            project_entries
            if project_entries is not None
            else [("NexoFlow/README.txt", "projeto seguro")],
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            for name, package_entries in zip(scan.PACKAGE_NAMES, entries, strict=False):
                with zipfile.ZipFile(
                    self.assets / name, "w", compression=zipfile.ZIP_STORED
                ) as archive:
                    for member, content in package_entries:
                        archive.writestr(member, content)
        self.write_hashes()

    def command_args(self, mode="packages", extra=()):
        args = ["--scanner", "gitleaks-test", "--mode", mode, "--repo", str(self.repo)]
        if mode == "packages":
            args.extend(["--assets-dir", str(self.assets)])
        args.extend(extra)
        return args

    def scanner_result(
        self, *, findings=(), exit_code=0, stdout="", stderr="", inspect=None
    ):
        def result(command, **kwargs):
            if inspect:
                inspect(command, kwargs)
            report = Path(command[command.index("--report-path") + 1])
            report.write_text(json.dumps(list(findings)), encoding="utf-8")
            return subprocess.CompletedProcess(
                command, exit_code, stdout=stdout, stderr=stderr
            )

        return result

    def invoke(self, mode="packages", *, scanner=None, extra=()):
        output = io.StringIO()
        with patch.object(
            scan.subprocess, "run", side_effect=scanner or self.scanner_result()
        ) as runner:
            with redirect_stdout(output):
                result = scan.main(self.command_args(mode, extra))
        return result, output.getvalue(), runner

    def assert_rejected_before_scan(self, *, message=None):
        result, output, runner = self.invoke()
        self.assertEqual(result, 1)
        runner.assert_not_called()
        if message:
            self.assertIn(message, output)

    def test_history_scans_all_refs_without_ignore_comments_or_repository_ignore_file(
        self,
    ):
        locations = []

        def inspect(command, kwargs):
            self.assertEqual(command[:3], ["gitleaks-test", "git", str(self.repo)])
            self.assertIn("--log-opts=--all", command)
            self.assertIn("--redact=100", command)
            self.assertIn("--ignore-gitleaks-allow", command)
            self.assertEqual(
                Path(command[command.index("--config") + 1]),
                self.repo / ".gitleaks.toml",
            )
            ignore_file = Path(command[command.index("--gitleaks-ignore-path") + 1])
            report_file = Path(command[command.index("--report-path") + 1])
            self.assertEqual(ignore_file.read_bytes(), b"")
            self.assertNotIn(self.repo, report_file.parents)
            self.assertEqual(ignore_file.parent, report_file.parent)
            self.assertTrue(kwargs["capture_output"])
            locations.append(report_file.parent)

        (self.repo / ".gitleaksignore").write_text("ignorar tudo", encoding="utf-8")
        result, _, runner = self.invoke(
            "history", scanner=self.scanner_result(inspect=inspect)
        )
        self.assertEqual(result, 0)
        runner.assert_called_once()
        self.assertFalse(
            locations[0].exists(), "Relatório padrão deve ser descartado fora do repo."
        )

    def test_packages_scan_only_extracted_zip_contents_not_adjacent_files(self):
        self.write_packages(
            project_entries=[("NexoFlow\\pasta\\README.txt", "portátil")]
        )
        (self.assets / "diagnostico-privado.txt").write_text(
            "não extrair", encoding="utf-8"
        )
        locations = []

        def inspect(command, kwargs):
            self.assertEqual(command[1], "dir")
            self.assertNotIn("--log-opts=--all", command)
            self.assertIn("--redact=100", command)
            extracted = Path(command[2])
            locations.append(extracted)
            self.assertNotEqual(extracted, self.assets)
            self.assertEqual(
                sorted(
                    path.relative_to(extracted).as_posix()
                    for path in extracted.rglob("*")
                    if path.is_file()
                ),
                [
                    "NexoFlow-1.5.10/NexoFlow/pasta/README.txt",
                    "NexoFlow-Setup-1.5.10/NexoFlow Setup/payload/README.txt",
                ],
            )
            self.assertEqual(
                (extracted / "NexoFlow-1.5.10/NexoFlow/pasta/README.txt").read_text(
                    encoding="utf-8"
                ),
                "portátil",
            )

        result, _, runner = self.invoke(scanner=self.scanner_result(inspect=inspect))
        self.assertEqual(result, 0)
        runner.assert_called_once()
        self.assertFalse(locations[0].exists())

    def test_external_hash_mismatch_is_rejected_before_scanner(self):
        self.write_packages()
        with (self.assets / scan.PACKAGE_NAMES[0]).open("ab") as package:
            package.write(b"modificado depois do hash")
        self.assert_rejected_before_scan(message="Hash SHA-256 divergente")

    def test_external_hashes_must_cover_both_packages_exactly_once(self):
        self.write_packages()
        checksum = self.assets / scan.CHECKSUM_NAME
        valid_lines = checksum.read_text(encoding="utf-8").splitlines()
        for invalid in (
            "",
            valid_lines[0],
            "\n".join(valid_lines + [valid_lines[0]]),
            "\n".join(valid_lines + ["0" * 64 + "  terceiro.zip"]),
        ):
            with self.subTest(invalid=invalid):
                checksum.write_text(invalid, encoding="utf-8")
                self.assert_rejected_before_scan()

    def test_missing_package_is_rejected_before_scanner(self):
        self.write_packages()
        (self.assets / scan.PACKAGE_NAMES[1]).unlink()
        self.assert_rejected_before_scan()

    def test_corrupt_zip_with_matching_hash_is_rejected_before_scanner(self):
        self.write_packages()
        (self.assets / scan.PACKAGE_NAMES[0]).write_bytes(b"arquivo sem formato ZIP")
        self.write_hashes()
        self.assert_rejected_before_scan(message="ZIP corrompido")

    def test_corrupt_payload_crc_is_rejected_before_scanner(self):
        self.write_packages(
            setup_entries=[("NexoFlow Setup/README.txt", "conteudo-original")]
        )
        package = self.assets / scan.PACKAGE_NAMES[0]
        package.write_bytes(
            package.read_bytes().replace(b"conteudo-original", b"conteudo-alterado")
        )
        self.write_hashes()
        self.assert_rejected_before_scan(message="ZIP corrompido")

    def test_unsafe_zip_paths_are_rejected_before_scanner(self):
        for name in (
            "../fora.txt",
            "pasta/../../fora.txt",
            "pasta\\..\\..\\fora.txt",
            "/absoluto.txt",
            "\\absoluto.txt",
            "C:/absoluto.txt",
            "C:relativo.txt",
            "\\\\servidor\\share\\fora.txt",
            "pasta/arquivo:stream",
            "pasta/NUL.txt",
            "pasta/arquivo. ",
            "pasta//arquivo.txt",
            "./arquivo.txt",
            "pasta/arquivo?.txt",
            'pasta/arquivo".txt',
            "pasta/arquivo\n.txt",
        ):
            with self.subTest(name=name):
                self.write_packages(project_entries=[(name, "conteúdo sintético")])
                self.assert_rejected_before_scan()
                self.assertFalse((self.root / "fora.txt").exists())

    def test_null_in_zip_filename_is_rejected_before_scanner(self):
        self.write_packages(project_entries=[("NexoFlow/aX.txt", "seguro")])
        package = self.assets / scan.PACKAGE_NAMES[1]
        package.write_bytes(
            package.read_bytes().replace(b"NexoFlow/aX.txt", b"NexoFlow/a\x00.txt")
        )
        self.write_hashes()
        self.assert_rejected_before_scan()

    def test_symlink_zip_member_is_rejected_before_scanner(self):
        link = zipfile.ZipInfo("NexoFlow/link")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        self.write_packages(project_entries=[(link, "../../fora.txt")])
        self.assert_rejected_before_scan(message="link simbólico")

    def test_duplicate_and_windows_colliding_entries_are_rejected_before_scanner(self):
        for entries in (
            [("NexoFlow/a.txt", "um"), ("NexoFlow/a.txt", "dois")],
            [("NexoFlow/a.txt", "um"), ("nexoflow/A.TXT", "dois")],
            [("NexoFlow/a.txt", "um"), ("NexoFlow\\a.txt", "dois")],
            [("NexoFlow/pasta", "arquivo"), ("NexoFlow/pasta/a.txt", "filho")],
        ):
            with self.subTest(entries=entries):
                self.write_packages(project_entries=entries)
                self.assert_rejected_before_scan()

    def test_empty_files_and_directories_are_allowed(self):
        self.write_packages(
            project_entries=[("NexoFlow/importacoes/", ""), ("NexoFlow/vazio.txt", "")]
        )
        result, _, runner = self.invoke()
        self.assertEqual(result, 0)
        runner.assert_called_once()

    def test_directory_members_with_hidden_payload_or_regular_file_metadata_are_rejected(
        self,
    ):
        regular_file = zipfile.ZipInfo("NexoFlow/pasta/")
        regular_file.create_system = 3
        regular_file.external_attr = (stat.S_IFREG | 0o600) << 16
        for entries in ([("NexoFlow/pasta/", "conteúdo oculto")], [(regular_file, "")]):
            with self.subTest(entries=entries):
                self.write_packages(project_entries=entries)
                self.assert_rejected_before_scan(message="diretório com conteúdo")

    def test_secret_findings_fail_without_printing_report_or_scanner_output(self):
        sentinel = "DADO_SINTETICO_NUNCA_EXIBIR"
        result, output, runner = self.invoke(
            "history",
            scanner=self.scanner_result(
                findings=[{"Secret": sentinel, "Match": sentinel, "File": sentinel}],
                exit_code=1,
                stdout=sentinel,
                stderr=sentinel,
            ),
        )
        self.assertEqual(result, 1)
        self.assertIn("1 ocorrência(s)", output)
        self.assertNotIn(sentinel, output)
        runner.assert_called_once()

    def test_findings_block_even_when_scanner_returns_zero(self):
        result, output, _ = self.invoke(
            "history", scanner=self.scanner_result(findings=[{"RuleID": "synthetic"}])
        )
        self.assertEqual(result, 1)
        self.assertIn("1 ocorrência(s)", output)

    def test_exit_one_without_findings_still_blocks_publication(self):
        result, _, _ = self.invoke("history", scanner=self.scanner_result(exit_code=1))
        self.assertEqual(result, 1)

    def test_scanner_execution_errors_fail_closed_without_printing_output(self):
        sentinel = "DADO_SINTETICO_NUNCA_EXIBIR"
        for exit_code in (2, 126, -9):
            with self.subTest(exit_code=exit_code):
                result, output, _ = self.invoke(
                    "history",
                    scanner=self.scanner_result(
                        exit_code=exit_code,
                        stdout=sentinel,
                        stderr=sentinel,
                    ),
                )
                self.assertEqual(result, 1)
                self.assertIn("scanner terminou com erro", output)
                self.assertNotIn(sentinel, output)

    def test_missing_scanner_and_timeout_fail_closed(self):
        for error in (
            FileNotFoundError("DADO_SINTETICO_NUNCA_EXIBIR"),
            subprocess.TimeoutExpired("DADO_SINTETICO_NUNCA_EXIBIR", 900),
        ):
            with self.subTest(error=type(error).__name__):
                result, output, _ = self.invoke("history", scanner=error)
                self.assertEqual(result, 1)
                self.assertNotIn("DADO_SINTETICO_NUNCA_EXIBIR", output)

    def test_missing_or_invalid_report_blocks_publication(self):
        for content in (
            None,
            "invalid json DADO_SINTETICO_NUNCA_EXIBIR",
            '{"unexpected": []}',
            '["unexpected"]',
        ):
            with self.subTest(content=content):

                def scanner(command, *, content=content, **kwargs):
                    report = Path(command[command.index("--report-path") + 1])
                    if content is None:
                        report.unlink()
                    else:
                        report.write_text(content, encoding="utf-8")
                    return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

                result, output, _ = self.invoke("history", scanner=scanner)
                self.assertEqual(result, 1)
                self.assertNotIn("DADO_SINTETICO_NUNCA_EXIBIR", output)

    def test_optional_report_directory_retains_private_report_outside_project(self):
        report_dir = self.root / "private-reports"
        result, _, _ = self.invoke("history", extra=["--report-dir", str(report_dir)])
        self.assertEqual(result, 0)
        reports = list(report_dir.glob("nexoflow-secrets-*/gitleaks-report.json"))
        self.assertEqual(len(reports), 1)
        self.assertEqual(json.loads(reports[0].read_text(encoding="utf-8")), [])
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(reports[0].stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(reports[0].parent.stat().st_mode), 0o700)

    def test_reports_inside_repository_or_assets_are_rejected_before_scanner(self):
        self.write_packages()
        for report_dir in (self.repo / "logs", self.assets / "reports"):
            with self.subTest(report_dir=report_dir):
                result, _, runner = self.invoke(extra=["--report-dir", str(report_dir)])
                self.assertEqual(result, 1)
                runner.assert_not_called()
                self.assertFalse(report_dir.exists())

    def test_missing_config_is_rejected_before_scanner(self):
        (self.repo / ".gitleaks.toml").unlink()
        result, _, runner = self.invoke("history")
        self.assertEqual(result, 1)
        runner.assert_not_called()

    def test_packages_mode_requires_assets_directory(self):
        output = io.StringIO()
        with patch.object(scan.subprocess, "run") as runner, redirect_stdout(output):
            result = scan.main(["--mode", "packages", "--repo", str(self.repo)])
        self.assertEqual(result, 1)
        runner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
