"""Auxiliar controlado: correção das origens sem substituir a instalação 1.5.22.

Executar o arquivo de um checkout oficial validado, com o Python já instalado.
Não baixa código, não copia credenciais e não altera arquivos de programa.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import sys
from pathlib import Path

# Fontes efetivamente publicadas na v1.5.22, normalizadas para LF.
BASE_HASHES = {
    "sheets_continuation": "36bcd119e2ba994f6c8bd5f8dd2ef8ec8797c56d2a0af35b24361591e057c3b1",
    "sheets_provisioning": "3805da845a93dec013f1c425c033d4b469635c7b33ae27b8b11862248618694e",
    "run_sheets_continuation": "9f3041d10d42e59aadcf7d3f927cfe361a0155f30ab3eb3493820431ad41d459",
}
MODULES = ("sheets_continuation", "sheets_provisioning", "run_sheets_continuation")


def source_hash(path: Path) -> str:
    return hashlib.sha256(
        path.read_text(encoding="utf-8-sig").encode("utf-8")
    ).hexdigest()


def validate_installation(root: Path, expected=None):
    if root == Path(__file__).resolve().parents[1]:
        raise ValueError("O auxiliar deve ficar fora da instalação operacional.")
    if (root / "VERSION").read_text(encoding="utf-8-sig").strip() != "1.5.22":
        raise ValueError("Auxiliar exclusivo para a instalação original 1.5.22.")
    for module, digest in (BASE_HASHES if expected is None else expected).items():
        if source_hash(root / "app" / (module + ".py")) != digest:
            raise ValueError(
                "Módulos instalados divergem da 1.5.22; preservar e conferir antes de continuar."
            )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instalacao", type=Path, required=True)
    parser.add_argument(
        "operacao", choices=("diagnosticar-origens", "configurar", "status")
    )
    args = parser.parse_args(argv)
    root = args.instalacao.resolve()
    try:
        validate_installation(root)
        # Dependências, configuração, caminhos e rede continuam sendo os instalados.
        sys.path.insert(0, str(root / "app"))
        import config
        import project_paths

        if project_paths.ROOT.resolve() != root or config.BASE_DIR.resolve() != root:
            raise ValueError(
                "Raiz de configuração não corresponde à instalação informada."
            )
        corrected = Path(__file__).resolve().parents[1] / "app"
        for module in MODULES:
            spec = importlib.util.spec_from_file_location(
                module, corrected / (module + ".py")
            )
            if spec is None or spec.loader is None:
                raise ValueError(
                    "Fonte corrigida incompleta; use o checkout oficial inteiro."
                )
            loaded = importlib.util.module_from_spec(spec)
            sys.modules[module] = loaded
            spec.loader.exec_module(loaded)
        return sys.modules["run_sheets_continuation"].run([args.operacao])
    except (ValueError, OSError):
        print(
            "[ERRO] Instalação/checkout incompatível ou inacessível. Use a 1.5.22 original e o checkout oficial validado, em pastas separadas. Nenhum arquivo instalado foi substituído."
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
