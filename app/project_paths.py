"""Localiza os dados da instalação sem depender da pasta de execução."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def ensure_root_import_path() -> None:
    """Mantém a configuração privada na raiz, fora dos módulos públicos."""
    root = str(ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


def load_private_settings():
    """Carrega a configuração local compatível com instalações anteriores."""
    import importlib

    ensure_root_import_path()
    return importlib.import_module("secrets_config")


def launcher_path(root: Path, name: str) -> Path:
    """Resolve o executável instalado ou a referência pré-compilada do repositório."""
    installed = root / name
    if installed.is_file():
        return installed
    return root / "native_launcher" / "prebuilt" / name
