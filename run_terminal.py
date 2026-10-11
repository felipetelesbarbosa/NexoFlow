from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from proxy_config import configure_proxy

BASE_DIR = Path(__file__).resolve().parent


def _powershell_executable() -> str:
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    candidate = (
        system_root / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    )
    if candidate.exists():
        return str(candidate)
    found = shutil.which("powershell.exe") or shutil.which("pwsh.exe")
    if found:
        return found
    raise RuntimeError("PowerShell não foi encontrado neste Windows.")


def _prepare_environment() -> dict[str, str]:
    env = os.environ.copy()
    env["NEXOFLOW_HOME"] = str(BASE_DIR)
    env["NEXOFLOW_TERMINAL"] = "1"
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    # Facilita imports dos módulos do projeto em comandos Python iniciados na
    # terminal, sem exportar tokens/segredos para variáveis de ambiente.
    existing_pythonpath = env.get("PYTHONPATH", "").strip()
    env["PYTHONPATH"] = (
        str(BASE_DIR)
        if not existing_pythonpath
        else str(BASE_DIR) + os.pathsep + existing_pythonpath
    )

    # Permite usar o comando curto "nexo" sem precisar digitar .\nexo.cmd.
    path_parts = [str(BASE_DIR)]
    venv_scripts = BASE_DIR / ".venv" / "Scripts"
    if venv_scripts.exists():
        env["VIRTUAL_ENV"] = str(BASE_DIR / ".venv")
        path_parts.insert(0, str(venv_scripts))
    env["PATH"] = os.pathsep.join(path_parts + [env.get("PATH", "")])

    # configure_proxy altera somente o processo atual. A cópia final do
    # ambiente, feita depois desta chamada, é herdada pela PowerShell.
    status = configure_proxy()
    env.update(
        {
            key: value
            for key, value in os.environ.items()
            if key
            in {
                "HTTP_PROXY",
                "HTTPS_PROXY",
                "http_proxy",
                "https_proxy",
                "NO_PROXY",
                "no_proxy",
                "WENI_PROXY_ACTIVE",
            }
        }
    )
    for key in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "http_proxy",
        "https_proxy",
        "NO_PROXY",
        "no_proxy",
        "WENI_PROXY_ACTIVE",
    ):
        if key not in os.environ:
            env.pop(key, None)

    print("==========================================================")
    print(" NexoFlow Terminal")
    print("==========================================================")
    print(f"Pasta: {BASE_DIR}")
    print(f"Proxy: {status.safe_summary}")
    print()
    print(
        "A sessão herda a configuração de proxy do secrets_config.py sem exibir a senha."
    )
    print(
        "Tokens Weni/FarmaLíder e credenciais Google NÃO são exportados como variáveis"
    )
    print(
        "de ambiente; os scripts do NexoFlow continuam lendo os arquivos locais seguros."
    )
    print("Python/PIP usam automaticamente a .venv do NexoFlow quando ela existir.")
    print()
    print(
        'Digite "nexo" para abrir o menu simples ou "nexo ajuda" para listar comandos.'
    )
    print("Exemplo: nexo api farmalider pedido 123456")
    print()
    return env


def main() -> int:
    try:
        env = _prepare_environment()
        powershell = _powershell_executable()
        completed = subprocess.run(
            [powershell, "-NoLogo", "-NoExit", "-NoProfile"],
            cwd=BASE_DIR,
            env=env,
            check=False,
        )
        return int(completed.returncode)
    except (OSError, RuntimeError, ValueError) as exc:
        print(
            f"[ERRO] Não foi possível abrir o NexoFlow Terminal: {exc}", file=sys.stderr
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
