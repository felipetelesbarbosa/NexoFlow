from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _configure_proxy() -> None:
    try:
        from proxy_config import configure_proxy
    except ModuleNotFoundError as exc:
        if exc.name == "secrets_config":
            if os.environ.get("NEXOFLOW_NETWORK_MODE", "").lower() != "personal":
                raise ValueError(
                    "REDE_AMBIGUA: configure a rede ou escolha Personal no Setup antes de instalar dependências."
                ) from None
            for key in (
                "HTTP_PROXY",
                "HTTPS_PROXY",
                "ALL_PROXY",
                "http_proxy",
                "https_proxy",
                "all_proxy",
            ):
                os.environ.pop(key, None)
            os.environ["NO_PROXY"] = "*"
            from pip_network import pip_environment, preflight

            env = pip_environment(False)
            preflight(env)
            os.environ.update(env)
            return
        raise

    status = configure_proxy()
    print(f"[INFO] Rota das dependências: {status.safe_summary}")
    from pip_network import pip_environment, preflight

    env = pip_environment(status.active)
    preflight(env)
    print("[OK] Acesso HTTPS ao índice de dependências confirmado nesta etapa.")
    os.environ.update(env)


def main() -> int:
    if len(sys.argv) < 2:
        print(
            "Uso: app/run_pip.py <argumentos do pip>\n"
            "Exemplo: app/run_pip.py install -r requirements.txt"
        )
        return 2

    try:
        _configure_proxy()
    except (ImportError, SyntaxError, OSError, ValueError) as exc:
        print(
            "[ERRO] A preparação da rede pip falhou; confira seleção de rede, proxy e CA."
        )
        if isinstance(exc, ValueError) and str(exc).startswith(
            ("PROXY_", "REDE_", "TLS_")
        ):
            print(str(exc))
        return 1

    command = [
        sys.executable,
        "-m",
        "pip",
        "--disable-pip-version-check",
        *sys.argv[1:],
    ]
    if sys.argv[1] == "install":
        command += ["--retries", "0", "--timeout", "15"]

    # Não exibimos o comando completo porque argumentos futuros podem
    # eventualmente conter informações sensíveis.
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )
        if completed.returncode:
            print(
                "[ERRO] pip não concluiu a etapa. Saída bruta omitida para proteger URLs e credenciais; nenhuma etapa seguinte será iniciada."
            )
        else:
            print("[OK] Dependências solicitadas nesta etapa instaladas ou já compatíveis.")
        return completed.returncode
    except (OSError, subprocess.TimeoutExpired):
        print(
            "[ERRO] Não foi possível concluir o pip no prazo; confira rede e ambiente. Nenhuma etapa seguinte será iniciada."
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
