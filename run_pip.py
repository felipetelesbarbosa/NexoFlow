from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _configure_proxy() -> None:
    try:
        from proxy_config import configure_proxy
    except ModuleNotFoundError as exc:
        if exc.name == "secrets_config":
            print(
                "[AVISO] secrets_config.py não foi encontrado.\n"
                "        O pip tentará usar conexão direta.\n"
                "        Se estiver na empresa e o proxy exigir autenticação,\n"
                "        crie/configure secrets_config.py e execute novamente."
            )
            return
        raise

    status = configure_proxy()
    print(f"[INFO] Proxy para pip: {status.safe_summary}")


def main() -> int:
    if len(sys.argv) < 2:
        print(
            "Uso: run_pip.py <argumentos do pip>\n"
            "Exemplo: run_pip.py install -r requirements.txt"
        )
        return 2

    try:
        _configure_proxy()
    except (ImportError, SyntaxError, OSError, ValueError) as exc:
        print(f"[ERRO] Não foi possível configurar o proxy para o pip: {exc}")
        return 1

    command = [sys.executable, "-m", "pip", *sys.argv[1:]]

    # Não exibimos o comando completo porque argumentos futuros podem
    # eventualmente conter informações sensíveis.
    try:
        completed = subprocess.run(command, cwd=ROOT)
        return completed.returncode
    except OSError as exc:
        print(f"[ERRO] Falha ao executar o pip: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
