"""Publicação rápida só aceita evidências completas do mesmo commit."""

import copy
import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

try:
    from scripts.validate_release_run import (
        REPO,
        REQUIRED,
        validate_assets,
        validate_run,
    )
except ModuleNotFoundError:
    if (
        Path(__file__).resolve().parents[1] / ".github/workflows/release-v1.yml"
    ).is_file():
        raise
    raise unittest.SkipTest(
        "Validador exclusivo do CI; não integra a instalação Windows."
    ) from None

SHA = "a" * 40


class ValidatedReleaseTests(unittest.TestCase):
    def evidence(self):
        return {
            "run": dict(
                head_sha=SHA,
                head_branch="main",
                head_repository=dict(full_name=REPO),
                path=".github/workflows/release-v1.yml",
                event="workflow_dispatch",
                status="completed",
                conclusion="success",
            ),
            "jobs": [dict(name=name, conclusion="success") for name in REQUIRED],
            "artifacts": [
                dict(
                    name="NexoFlow-1.5.33-pacotes",
                    expired=False,
                    digest="sha256:" + "b" * 64,
                )
            ],
            "workflow_runs": [
                dict(
                    id=10,
                    head_sha=SHA,
                    head_branch="main",
                    status="completed",
                    conclusion="success",
                )
            ],
        }

    def fetcher(self, evidence):
        def fetch(path):
            if "/workflows/" in path:
                return dict(workflow_runs=copy.deepcopy(evidence["workflow_runs"]))
            for key in ("jobs", "artifacts"):
                if f"/{key}?" in path:
                    return {key: copy.deepcopy(evidence[key])}
            return copy.deepcopy(evidence["run"])

        return fetch

    def test_accepts_same_sha_with_all_required_evidence(self):
        validate_run(REPO, SHA, "123", "1.5.33", self.fetcher(self.evidence()))

    def test_rejects_other_sha_branch_fork_workflow_and_unfinished_run(self):
        for key, value in (
            ("head_sha", "c" * 40),
            ("head_branch", "other"),
            ("conclusion", "failure"),
            ("status", "in_progress"),
            ("head_repository", dict(full_name="other/repo")),
            ("path", ".github/workflows/arbitrary.yml"),
            ("event", "pull_request"),
        ):
            with self.subTest(key=key):
                evidence = self.evidence()
                evidence["run"][key] = value
                with self.assertRaises(ValueError):
                    validate_run(REPO, SHA, "123", "1.5.33", self.fetcher(evidence))

    def test_missing_failed_duplicate_jobs_and_invalid_artifacts_block(self):
        cases = []
        for name in REQUIRED:
            e = self.evidence()
            e["jobs"] = [j for j in e["jobs"] if j["name"] != name]
            cases.append(e)
        e = self.evidence()
        e["jobs"][0]["conclusion"] = "failure"
        cases.append(e)
        e = self.evidence()
        e["jobs"].append(e["jobs"][0].copy())
        cases.append(e)
        for field, value in [
            ("expired", True),
            ("digest", ""),
            ("name", "NexoFlow-1.5.32-pacotes"),
        ]:
            e = self.evidence()
            e["artifacts"][0][field] = value
            cases.append(e)
        for evidence in cases:
            with self.assertRaises(ValueError):
                validate_run(REPO, SHA, "123", "1.5.33", self.fetcher(evidence))

    def test_newer_pending_or_failed_codeql_cannot_use_older_green_run(self):
        for state, conclusion in [("in_progress", None), ("completed", "failure")]:
            e = self.evidence()
            e["workflow_runs"].append(
                dict(
                    id=11,
                    head_sha=SHA,
                    head_branch="main",
                    status=state,
                    conclusion=conclusion,
                )
            )
            with self.assertRaises(ValueError):
                validate_run(REPO, SHA, "123", "1.5.33", self.fetcher(e))

    def test_invalid_inputs_are_rejected_before_any_api_call(self):
        for repo, sha, run in [
            (REPO, SHA, "1;unsafe"),
            ("other/repo", SHA, "123"),
            (REPO, "bad", "123"),
        ]:
            with self.assertRaises(ValueError):
                validate_run(
                    repo, sha, run, "1.5.33", lambda _: self.fail("API inesperada")
                )

    def test_checks_received_archives_and_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            lines = []
            for name, prefix in [
                ("NexoFlow-1.5.33.zip", "NexoFlow/"),
                ("NexoFlow-Setup-1.5.33.zip", "NexoFlow Setup/payload/"),
            ]:
                with zipfile.ZipFile(root / name, "w") as archive:
                    archive.writestr(prefix + "VERSION", "1.5.33\n")
                lines.append(
                    f"{hashlib.sha256((root / name).read_bytes()).hexdigest()}  {name}"
                )
            (root / "SHA256SUMS-1.5.33.txt").write_text("\n".join(lines))
            with patch("scripts.validate_release_run.subprocess.run") as contract:
                validate_assets(root, "1.5.33")
                contract.assert_called_once()
                (root / "NexoFlow-1.5.33.zip").write_bytes(b"changed")
                with self.assertRaisesRegex(ValueError, "Hash"):
                    validate_assets(root, "1.5.33")
                self.assertEqual(contract.call_count, 1)

    def test_fast_job_reuses_exact_publication_steps_and_skips_heavy_jobs(self):
        import re

        source = (
            Path(__file__).resolve().parents[1] / ".github/workflows/release-v1.yml"
        ).read_text(encoding="utf-8")
        jobs = dict(
            re.findall(
                r"^  ([a-z][a-z-]*):\n(.*?)(?=^  [a-z][a-z-]*:|\Z)", source, re.M | re.S
            )
        )
        self.assertIn("steps: &publicar_steps", jobs["publicar"])
        self.assertIn("steps: *publicar_steps", jobs["publicar-validado"])
        for name in [
            "qualidade",
            "verificar-segredos",
            "validar-python",
            "validar-e-publicar",
            "verificar-pacotes",
            "publicar",
        ]:
            self.assertIn(
                "!inputs.validated_run_id",
                next(
                    line
                    for line in jobs[name].splitlines()
                    if line.strip().startswith("if:")
                ),
            )
        self.assertIn(
            "[preparar pacotes]",
            next(
                line
                for line in jobs["validar-e-publicar"].splitlines()
                if line.strip().startswith("if:")
            ),
        )
        self.assertIn("[skip release]", jobs["publicar"].splitlines()[0])

    def test_build_depends_on_full_matrix_without_fifth_duplicate_suite(self):
        source = (
            Path(__file__).resolve().parents[1] / ".github/workflows/release-v1.yml"
        ).read_text(encoding="utf-8")
        matrix = source.split("  validar-python:", 1)[1].split(
            "  validar-e-publicar:", 1
        )[0]
        build = source.split("  validar-e-publicar:", 1)[1].split(
            "  verificar-pacotes:", 1
        )[0]
        self.assertIn('python-version: ["3.11", "3.14"]', matrix)
        self.assertEqual(matrix.count("python -m unittest discover"), 2)
        self.assertIn("needs: [qualidade, verificar-segredos, validar-python]", build)
        self.assertNotIn("python -m unittest discover", build)
        for required in [
            "Executar check-up operacional",
            "Testar executável Noturno sem APIs",
            "Smoke test do Setup",
        ]:
            self.assertIn(required, build)
