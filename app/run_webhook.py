from __future__ import annotations

import sys

from proxy_config import configure_proxy


def run() -> int:
    status = configure_proxy()
    print(f"[INFO] Proxy: {status.safe_summary}")

    try:
        import uvicorn
    except ImportError:
        print(
            "[ERRO] Uvicorn não instalado. Execute:\n"
            ".venv\\Scripts\\python.exe -m pip install -r requirements-webhook.txt"
        )
        return 1

    uvicorn.run(
        "webhook_eventos:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
    )
    return 0


if __name__ == "__main__":
    sys.exit(run())
