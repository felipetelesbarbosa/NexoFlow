"""Pré-verificação local; testes de desenvolvimento exigem opção explícita."""

from __future__ import annotations

import argparse
import importlib
import logging
import os
import sys
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from runtime_profile import segment

REQUIRED_FILES = (
    "app/runtime_profile.py",
    "app/weni_update.py",
    "app/run_update_weni.py",
    "app/main.py",
    "app/run_main.py",
    "app/recompra.py",
    "app/run_recompra.py",
    "app/run_noturno.py",
    "app/auditar_consistencia.py",
    "app/meta_ads_native.py",
    "connectors/meta_ads_mcp/client.py",
    "connectors/meta_ads_mcp/settings.py",
)
RUNTIME_IMPORTS = (
    "requests",
    "gspread",
    "google.auth",
    "google_auth_oauthlib.flow",
    "openpyxl",
)


def operational_checkup(root: Path) -> int:
    """Não lê credenciais/estado, não usa rede, não inicia scripts ou cargas."""
    errors = []
    try:
        profile = segment()
    except ValueError:
        print("[ERRO] Perfil inválido: use FARMA ou PET.")
        return 1
    for relative in REQUIRED_FILES:
        if not (root / relative).is_file():
            errors.append(f"Componente obrigatório ausente: {relative}.")
    # Escopo público explícito: nunca percorrer credentials, logs, importações,
    # secrets_config.py nem a .venv opcional do MCP. Compilar não executa código
    # e, ao contrário de compileall, não grava bytecode na instalação.
    sources = sorted(
        path
        for folder in (root / "app", root / "connectors/meta_ads_mcp")
        for path in folder.glob("*.py")
    )
    for path in sources:
        try:
            compile(path.read_text(encoding="utf-8-sig"), path.name, "exec")
        except (OSError, UnicodeError, SyntaxError, ValueError):
            # Não imprimir linha-fonte nem mensagem da exceção (pode ter dados).
            errors.append(f"Falha de leitura ou sintaxe: {path.relative_to(root)}.")
    for module in RUNTIME_IMPORTS:
        try:
            importlib.import_module(module)
        except Exception:
            errors.append(f"Falha ao carregar dependência obrigatória: {module}.")
    try:
        ZoneInfo("America/Belem")
    except ZoneInfoNotFoundError:
        errors.append("Fuso America/Belem indisponível; confira a dependência tzdata.")
    if errors:
        for message in errors:
            print("[ERRO] " + message)
        print("[INFO] Repare os componentes pelo instalador; a carga não foi iniciada.")
        return 1
    print(
        f"[OK] Pré-verificação local: perfil={profile}; "
        f"arquivos Python={len(sources)}; dependências={len(RUNTIME_IMPORTS)}."
    )
    print(
        "[INFO] Sem acesso às APIs. Configurações, credenciais e conexões são "
        "conferidas pelos diagnósticos de cada integração."
    )
    return 0


def development_tests() -> int:
    # O check-up deve mostrar somente o que importa. Logs/warnings esperados
    # dos mocks ficam silenciosos; falhas e tracebacks do unittest continuam
    # visíveis normalmente pelo TextTestRunner.
    # Synthetic HTTP500 fixtures must never appear as real customer failures.
    previous_logging = logging.root.manager.disable
    try:
        logging.disable(logging.CRITICAL)
        with (
            warnings.catch_warnings(),
            patch.dict(os.environ, {"NEXOFLOW_PERFIL": "FARMA"}),
            tempfile.TemporaryDirectory(prefix="nexoflow_checkup_") as directory,
            patch(
                "private_diagnostics.private_diagnostic_directory",
                return_value=Path(directory),
            ),
        ):
            warnings.simplefilter("ignore")
            suite = unittest.defaultTestLoader.discover(
                "tests", pattern="test_*.py", top_level_dir="."
            )
            runner = unittest.TextTestRunner(verbosity=0, buffer=True)
            if os.environ.get("NEXOFLOW_CHECKUP_VERBOSE") == "1":
                runner.verbosity = 2
            result = runner.run(suite)
        return 0 if result.wasSuccessful() else 1
    finally:
        logging.disable(previous_logging)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--development-tests",
        action="store_true",
        help="Executar toda a suíte de desenvolvimento, incluindo instaladores opcionais.",
    )
    args = parser.parse_args([] if argv is None else argv)
    if args.development_tests:
        return development_tests()
    return operational_checkup(Path(__file__).resolve().parents[1])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
