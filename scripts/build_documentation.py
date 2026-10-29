"""Gera e confere o HTML operacional a partir da documentação Markdown."""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_NAME = "docs/Documentacao NexoFlow.md"
OUTPUT_NAME = "docs/Documentacao NexoFlow.html"
MARKER = re.compile(
    r"<!-- NexoFlow documentation: source-sha256=([a-f0-9]{64}) "
    r"content-sha256=([a-f0-9]{64}) -->\n?\Z"
)


def _digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def documentation_is_current(source: Path, output: Path) -> bool:
    """Confere fonte e HTML, tolerando CRLF do checkout no Windows."""
    try:
        markdown = source.read_text(encoding="utf-8")
        html = output.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False
    match = MARKER.search(html)
    return bool(
        match
        and match.group(1) == _digest(markdown)
        and match.group(2) == _digest(html[: match.start()])
    )


def generate_documentation(source: Path, output: Path) -> None:
    markdown = source.read_text(encoding="utf-8")
    rendered = subprocess.run(
        [
            "pandoc",
            "--from=gfm",
            "--to=html5",
            "--standalone",
            "--metadata=lang:pt-BR",
            "--metadata=title:NexoFlow 1.5 - Documentação",
        ],
        input=markdown,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    ).stdout.replace("\r\n", "\n")
    marker = (
        "<!-- NexoFlow documentation: "
        f"source-sha256={_digest(markdown)} "
        f"content-sha256={_digest(rendered)} -->\n"
    )
    with output.open("w", encoding="utf-8", newline="\n") as target:
        target.write(rendered + marker)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="Conferir sem gerar nem exigir Pandoc."
    )
    args = parser.parse_args(argv)
    source = ROOT / SOURCE_NAME
    output = ROOT / OUTPUT_NAME
    if args.check:
        if not documentation_is_current(source, output):
            print(
                "[ERRO] Documentação HTML desatualizada. Execute scripts/build_documentation.py."
            )
            return 1
        print("[OK] Documentação HTML corresponde à fonte Markdown.")
        return 0
    try:
        generate_documentation(source, output)
    except FileNotFoundError:
        print("[ERRO] Instale o Pandoc para gerar a documentação HTML.")
        return 1
    except (OSError, UnicodeError, subprocess.CalledProcessError):
        print("[ERRO] Não foi possível gerar a documentação HTML.")
        return 1
    print("[OK] Documentação HTML gerada a partir do Markdown.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
