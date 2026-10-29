"""Versão pública e sequência conservadora das publicações do NexoFlow."""

from __future__ import annotations

import re
from importlib.metadata import version as package_version
from pathlib import Path


def parts(version: str) -> tuple[int, int, int]:
    if not re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)(?:\.([1-9]\d?))?", version):
        raise ValueError(
            "Versão deve usar maior.menor ou maior.menor.patch, com patch de 1 a 99."
        )
    values = [int(x) for x in version.split(".")]
    return values[0], values[1], values[2] if len(values) == 3 else 0


def next_version(version: str) -> str:
    major, minor, patch = parts(version)
    return f"{major}.{minor + 1}" if patch == 99 else f"{major}.{minor}.{patch + 1}"


def windows_version(version: str) -> str:
    major, minor, patch = parts(version)
    return f"{major}.{minor}.{patch}.0"


_VERSION_FILE = Path(__file__).resolve().parents[1] / "VERSION"
CURRENT_VERSION = (
    _VERSION_FILE.read_text(encoding="ascii").strip()
    if _VERSION_FILE.is_file()
    else package_version("nexoflow")
)
parts(CURRENT_VERSION)
