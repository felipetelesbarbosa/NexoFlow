"""Reutiliza somente pacotes do mesmo SHA, após todos os checks obrigatórios."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

REPO = "felipetelesbarbosa/NexoFlow"
REQUIRED = {
    "Qualidade e dependências",
    "verificar-segredos",
    "Testes Python 3.11",
    "Testes Python 3.14",
    "validar-e-publicar",
    "verificar-pacotes",
}


def api(path):
    result = subprocess.run(
        ["gh", "api", path],
        capture_output=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode:
        raise ValueError("GitHub não confirmou as evidências; publicação bloqueada.")
    return json.loads(result.stdout)


def validate_run(repo, sha, run_id, version, fetch=api):
    if repo != REPO or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Repositório ou SHA inválido.")
    if not re.fullmatch(r"[1-9][0-9]{0,19}", str(run_id)):
        raise ValueError("Informe o ID numérico da execução validada.")
    base = f"repos/{repo}"
    run = fetch(f"{base}/actions/runs/{run_id}")
    if (
        run["head_sha"] != sha
        or run["head_branch"] != "main"
        or run["head_repository"]["full_name"] != repo
        or run["path"] != ".github/workflows/release-v1.yml"
        or run["event"] not in ("push", "workflow_dispatch")
        or run["status"] != "completed"
        or run["conclusion"] != "success"
    ):
        raise ValueError("Execução de origem incompatível ou não aprovada.")
    jobs = fetch(f"{base}/actions/runs/{run_id}/jobs?per_page=100")["jobs"]
    for name in REQUIRED:
        found = [j for j in jobs if j["name"] == name]
        if len(found) != 1 or found[0]["conclusion"] != "success":
            raise ValueError(f"Check obrigatório não aprovado: {name}.")
    artifacts = fetch(f"{base}/actions/runs/{run_id}/artifacts?per_page=100")[
        "artifacts"
    ]
    found = [a for a in artifacts if a["name"] == f"NexoFlow-{version}-pacotes"]
    if (
        len(found) != 1
        or found[0]["expired"]
        or not re.fullmatch(
            r"sha256:[0-9a-f]{64}",
            (found[0].get("digest") or ""),
        )
    ):
        raise ValueError("Artefato ausente, expirado, duplicado ou sem digest.")
    for workflow in ("codeql.yml", "meta-ads-mcp.yml"):
        runs = fetch(
            f"{base}/actions/workflows/{workflow}/runs?head_sha={sha}&per_page=100"
        )["workflow_runs"]
        matching = [
            r for r in runs if r["head_sha"] == sha and r["head_branch"] == "main"
        ]
        latest = max(matching, key=lambda r: r["id"], default={})
        if latest.get("status") != "completed" or latest.get("conclusion") != "success":
            raise ValueError(f"Check do mesmo SHA não aprovado: {workflow}.")
    print(f"[OK] Execução {run_id}: checks e artefato comprovados no SHA {sha}.")


def validate_assets(directory, version):
    expected = {f"NexoFlow-Setup-{version}.zip", f"NexoFlow-{version}.zip"}
    lines = (
        (directory / f"SHA256SUMS-{version}.txt")
        .read_text(encoding="utf-8-sig")
        .splitlines()
    )
    checks = {}
    for line in lines:
        if not line.strip():
            continue
        digest, name = line.split()
        if (
            name not in expected
            or name in checks
            or not re.fullmatch(r"[0-9a-fA-F]{64}", digest)
        ):
            raise ValueError("Arquivo de hashes inválido.")
        checks[name] = digest.lower()
    if checks.keys() != expected:
        raise ValueError("Os dois pacotes precisam estar presentes.")
    for name, digest in checks.items():
        with (directory / name).open("rb") as handle:
            if hashlib.file_digest(handle, "sha256").hexdigest() != digest:
                raise ValueError("Hash do pacote divergente.")
        with zipfile.ZipFile(directory / name) as archive:
            if archive.testzip() is not None or len(archive.namelist()) != len(
                set(archive.namelist())
            ):
                raise ValueError("CRC ou entradas do ZIP inválidos.")
            prefix = "NexoFlow Setup/payload/" if "Setup" in name else "NexoFlow/"
            if archive.read(prefix + "VERSION").decode().strip() != version:
                raise ValueError("Versão do pacote divergente.")
    subprocess.run(
        [
            sys.executable,
            "scripts/check_history_quota_contract.py",
            "--assets-dir",
            str(directory),
            "--version",
            version,
        ],
        check=True,
    )
    print(
        "[OK] Hashes, CRC, versão e contrato histórico dos mesmos pacotes conferidos."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=REPO)
    parser.add_argument("--sha")
    parser.add_argument("--run-id")
    parser.add_argument("--assets-dir", type=Path)
    args = parser.parse_args()
    version = Path("VERSION").read_text(encoding="utf-8-sig").strip()
    try:
        if args.assets_dir:
            validate_assets(args.assets_dir, version)
        else:
            validate_run(args.repo, args.sha or "", args.run_id or "", version)
    except (
        OSError,
        ValueError,
        KeyError,
        subprocess.CalledProcessError,
        zipfile.BadZipFile,
    ) as exc:
        print(f"[ERRO] Publicação bloqueada: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
