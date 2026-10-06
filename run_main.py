from __future__ import annotations

import logging
import sys

from proxy_config import configure_proxy


def run() -> int:
    status = configure_proxy()

    # Importamos o projeto depois da configuração do proxy.
    # Isso mantém Weni, Google e futuras APIs no mesmo ambiente de rede.
    from main import main

    logging.getLogger(__name__).info(
        "Proxy: %s",
        status.safe_summary,
    )
    return main()


if __name__ == "__main__":
    sys.exit(run())
