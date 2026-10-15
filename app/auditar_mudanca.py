from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TEXT_EXTENSIONS = {
    ".py",
    ".pyi",
    ".md",
    ".txt",
    ".bat",
    ".toml",
    ".json",
    ".yml",
    ".yaml",
    ".ini",
    ".cfg",
}
EXCLUDED_DIRS = {
    ".venv",
    ".git",
    "__pycache__",
    "logs",
    "credentials",
}
EXCLUDED_FILES = {
    "secrets_config.py",
}


def iter_text_files():
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in EXCLUDED_DIRS for part in path.parts):
            continue
        if path.name in EXCLUDED_FILES:
            continue
        if path.suffix.lower() not in TEXT_EXTENSIONS:
            continue
        yield path


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Procura referências de uma mudança em todo o projeto. "
            "Use antes e depois de alterar constantes, nomes, URLs ou regras."
        )
    )
    parser.add_argument(
        "termos",
        nargs="+",
        help='Termos a procurar, ex.: "FARMALIDER_REQUEST_DELAY_SECONDS" "0.10" "100 ms"',
    )
    args = parser.parse_args()

    found = 0
    for path in iter_text_files():
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue

        for line_no, line in enumerate(lines, start=1):
            for term in args.termos:
                if term.lower() in line.lower():
                    rel = path.relative_to(ROOT)
                    print(f"{rel}:{line_no}: {line.strip()}")
                    found += 1
                    break

    print()
    print(f"Ocorrências encontradas: {found}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
