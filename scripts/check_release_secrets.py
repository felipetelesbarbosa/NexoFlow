"""Bloqueia publicação se o Gitleaks não aprovar histórico ou pacotes.

O scanner é instalado externamente. Sua saída e seus relatórios nunca são
reproduzidos no console, mesmo quando ele termina com erro.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import hashlib
import json
import ntpath
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile


PACKAGE_NAMES = ("NexoFlow-Setup-1.0.zip", "NexoFlow-1.0.zip")
CHECKSUM_NAME = "SHA256SUMS-1.0.txt"
MAX_PACKAGE_BYTES = 2 * 1024 * 1024 * 1024
MAX_PACKAGE_ENTRIES = 100_000
WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {
    f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)
}


class ScanError(Exception):
    """Mensagem controlada, sem dados recebidos do scanner ou dos pacotes."""


def verify_package_hashes(assets_dir: Path) -> tuple[Path, ...]:
    """Exige hashes externos exatos dos dois arquivos distribuídos."""
    checksum_file = assets_dir / CHECKSUM_NAME
    try:
        lines = checksum_file.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ScanError("Arquivo externo de hashes ausente ou inválido.") from exc
    expected: dict[str, str] = {}
    for line in lines:
        if not line.strip():
            continue
        match = re.fullmatch(r"([0-9a-fA-F]{64})[ \t]+\*?(.+)", line)
        if not match or match[2] not in PACKAGE_NAMES or match[2] in expected:
            raise ScanError("Arquivo externo de hashes inválido para os dois pacotes oficiais.")
        expected[match[2]] = match[1].lower()
    if set(expected) != set(PACKAGE_NAMES):
        raise ScanError("O arquivo externo de hashes deve identificar os dois pacotes oficiais.")
    packages = tuple(assets_dir / name for name in PACKAGE_NAMES)
    for package in packages:
        if package.is_symlink() or not package.is_file():
            raise ScanError("Pacote oficial ausente ou não regular.")
        try:
            digest = hashlib.sha256()
            with package.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError as exc:
            raise ScanError("Não foi possível conferir os hashes dos pacotes.") from exc
        if digest.hexdigest() != expected[package.name]:
            raise ScanError("Hash SHA-256 divergente; publicação bloqueada.")
    return packages


def member_path(info: zipfile.ZipInfo) -> tuple[PurePosixPath, bool]:
    """Valida também nomes que seriam perigosos após extração no Windows."""
    original = info.orig_filename
    name = original.replace("\\", "/")
    if "\x00" in original or not name or name.startswith("/") or ntpath.splitdrive(name)[0]:
        raise ScanError("O ZIP contém caminho absoluto ou inválido.")
    is_directory = name.endswith("/")
    parts = name[:-1].split("/") if is_directory else name.split("/")
    for part in parts:
        if (
            not part
            or part in {".", ".."}
            or any(character in '<>:"|?*' or ord(character) < 32 for character in part)
            or part.endswith((".", " "))
            or part.split(".", 1)[0].upper() in WINDOWS_RESERVED
        ):
            raise ScanError("O ZIP contém caminho não portátil ou tentativa de sair do diretório.")
    file_type = stat.S_IFMT(info.external_attr >> 16)
    if file_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
        raise ScanError("O ZIP contém link simbólico ou arquivo especial.")
    if file_type == stat.S_IFDIR and not is_directory:
        raise ScanError("O ZIP contém metadados de diretório inconsistentes.")
    if is_directory and (info.file_size != 0 or file_type == stat.S_IFREG):
        raise ScanError("O ZIP contém diretório com conteúdo ou metadados de arquivo.")
    if info.flag_bits & 1:
        raise ScanError("O ZIP contém arquivo criptografado; varredura incompleta.")
    return PurePosixPath(*parts), is_directory


def validated_members(archive: zipfile.ZipFile) -> list[tuple[zipfile.ZipInfo, PurePosixPath, bool]]:
    infos = archive.infolist()
    if len(infos) > MAX_PACKAGE_ENTRIES or sum(info.file_size for info in infos) > MAX_PACKAGE_BYTES:
        raise ScanError("O ZIP excede o limite de extração da verificação.")
    entries = []
    seen: set[str] = set()
    files: set[str] = set()
    for info in infos:
        path, is_directory = member_path(info)
        key = path.as_posix().casefold()
        if key in seen:
            raise ScanError("O ZIP contém caminhos duplicados ou conflitantes.")
        seen.add(key)
        if not is_directory:
            files.add(key)
        entries.append((info, path, is_directory))
    for _, path, _ in entries:
        if any(parent.as_posix().casefold() in files for parent in path.parents if parent != PurePosixPath(".")):
            raise ScanError("O ZIP contém caminhos de arquivo e diretório conflitantes.")
    return entries


def extract_packages(assets_dir: Path, destination: Path) -> None:
    """Confere todos os hashes e caminhos antes de extrair em local isolado."""
    packages = verify_package_hashes(assets_dir)
    try:
        with ExitStack() as stack:
            archives = [stack.enter_context(zipfile.ZipFile(package)) for package in packages]
            plans = [validated_members(archive) for archive in archives]
            for package, archive, plan in zip(packages, archives, plans):
                root = destination / package.stem
                root.mkdir(parents=True, exist_ok=False)
                for info, path, is_directory in plan:
                    target = root.joinpath(*path.parts)
                    if is_directory:
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info) as source, target.open("xb") as output:
                        shutil.copyfileobj(source, output)
    except ScanError:
        raise
    except Exception as exc:
        raise ScanError("Pacote ZIP corrompido ou impossível de verificar integralmente.") from exc


def run_scanner(scanner: str, mode: str, target: Path, config: Path, private_dir: Path) -> int:
    ignore_file = private_dir / "empty.gitleaksignore"
    report_file = private_dir / "gitleaks-report.json"
    for path in (ignore_file, report_file):
        path.touch(mode=0o600, exist_ok=False)
    command = [scanner, "git" if mode == "history" else "dir", str(target)]
    if mode == "history":
        command.append("--log-opts=--all")
    command.extend([
        "--config", str(config), "--redact=100", "--ignore-gitleaks-allow",
        "--gitleaks-ignore-path", str(ignore_file), "--report-format=json",
        "--report-path", str(report_file), "--no-banner", "--exit-code=1",
    ])
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8",
            errors="replace", check=False, timeout=900,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ScanError("Não foi possível concluir a execução do scanner de segredos.") from exc
    try:
        report_file.chmod(0o600)
        findings = json.loads(report_file.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ScanError("O scanner não produziu um relatório válido; publicação bloqueada.") from exc
    if not isinstance(findings, list) or any(not isinstance(item, dict) for item in findings):
        raise ScanError("O scanner produziu um relatório inesperado; publicação bloqueada.")
    if result.returncode not in (0, 1):
        raise ScanError("O scanner terminou com erro; publicação bloqueada.")
    if result.returncode == 1 or findings:
        print(f"Segurança: publicação bloqueada; scanner sinalizou {len(findings)} ocorrência(s).")
        return 1
    print("Segurança: varredura aprovada, sem ocorrências.")
    return 0


def is_within(path: Path, directory: Path) -> bool:
    return path == directory or directory in path.parents


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="NexoFlow 1.0 — verificação de segredos antes da publicação.")
    parser.add_argument("--scanner", default="gitleaks", help="Executável Gitleaks instalado externamente.")
    parser.add_argument("--mode", choices=("history", "packages"), required=True)
    parser.add_argument("--repo", required=True, type=Path, help="Raiz com .gitleaks.toml.")
    parser.add_argument("--assets-dir", type=Path, help="Diretório dos dois ZIPs e SHA256SUMS-1.0.txt.")
    parser.add_argument("--report-dir", type=Path, help="Diretório privado, fora do repositório, para reter relatório redigido.")
    args = parser.parse_args(argv)
    try:
        repo = args.repo.resolve()
        config = repo / ".gitleaks.toml"
        if not repo.is_dir() or not config.is_file():
            raise ScanError("Raiz do projeto ou configuração .gitleaks.toml ausente.")
        assets = args.assets_dir.resolve() if args.assets_dir is not None else None
        if args.mode == "packages" and (assets is None or not assets.is_dir()):
            raise ScanError("Informe um diretório válido de pacotes com --assets-dir.")
        report_parent = args.report_dir.resolve() if args.report_dir is not None else None
        if report_parent is not None:
            if is_within(report_parent, repo) or (assets is not None and is_within(report_parent, assets)):
                raise ScanError("Relatórios devem ficar fora do repositório e dos pacotes públicos.")
            report_parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        # O diretório temporário padrão é removido. Quando solicitado, somente
        # ignore vazio e relatório redigido são retidos em subdiretório privado.
        with ExitStack() as stack:
            if report_parent is None:
                private_dir = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="nexoflow-secrets-")))
            else:
                private_dir = Path(tempfile.mkdtemp(prefix="nexoflow-secrets-", dir=report_parent))
            if args.mode == "packages":
                extraction_dir = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="nexoflow-packages-")))
                extract_packages(assets, extraction_dir)
                target = extraction_dir
            else:
                target = repo
            return run_scanner(args.scanner, args.mode, target, config, private_dir)
    except ScanError as exc:
        print(f"Segurança: {exc}")
        return 1
    except OSError:
        print("Segurança: falha de acesso aos arquivos de verificação; publicação bloqueada.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
