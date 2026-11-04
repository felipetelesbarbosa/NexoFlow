"""Validação offline do ambiente isolado; não lê token nem consulta serviços."""

from __future__ import annotations

import importlib
import importlib.metadata
import re
import sys
from collections.abc import Callable


def _version_pair(value: str) -> tuple[int, int] | None:
    match = re.fullmatch(r"([0-9]+)\.([0-9]+)(?:\.[0-9]+)*(?:\.post[0-9]+)?", value)
    return (int(match[1]), int(match[2])) if match else None


def environment_compatible(
    python_version: tuple[int, ...] | None = None,
    *,
    package_version: Callable[[str], str] = importlib.metadata.version,
    import_module: Callable[[str], object] = importlib.import_module,
) -> bool:
    """Versões injetáveis apenas para testes; a CLI sempre usa o runtime real."""
    actual = sys.version_info[:2] if python_version is None else python_version[:2]
    if actual != (3, 14):
        return False
    try:
        mcp = _version_pair(package_version("mcp"))
        requests = _version_pair(package_version("requests"))
        if (
            mcp is None
            or requests is None
            or not ((1, 28) <= mcp < (2, 0) and (2, 33) <= requests < (3, 0))
        ):
            return False
        sdk = import_module("mcp.server.fastmcp")
        return callable(getattr(sdk, "FastMCP", None))
    except Exception:
        # Falha de import/dependência gera incompatibilidade explícita. Não
        # imprimir traceback de bibliotecas ou conteúdo de configuração local.
        return False


def main() -> int:
    if sys.argv[1:] == ["--python-only"]:
        return 0 if sys.version_info[:2] == (3, 14) else 1
    if sys.argv[1:]:
        return 2
    return 0 if environment_compatible() else 1


if __name__ == "__main__":
    raise SystemExit(main())
