from __future__ import annotations

import sys

from proxy_config import configure_proxy


def run() -> int:
    try:
        status = configure_proxy()
    except Exception as exc:
        print(f"[ERRO] Configuração de proxy inválida: {exc}")
        return 1

    print("=== Diagnóstico de rede ===")
    print(f"[INFO] {status.safe_summary}")
    print()

    # Importa o diagnóstico existente somente depois de configurar a rede.
    from logging_config import configure_logging
    configure_logging()
    from diagnostico import main

    return main()


if __name__ == "__main__":
    sys.exit(run())
