"""Instala somente dependências MCP, com a rota NexoFlow e saída sanitizada."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import time
from pathlib import Path

from network_diagnostics import NetworkFailure, classify_network_failure

ROOT = Path(__file__).resolve().parents[1]


def pip_failure(output: str) -> NetworkFailure:
    """Inspeciona mensagens localmente; nunca devolve linhas/URLs do pip."""
    import requests

    text = output.lower()
    for code in (407, 403, 502, 503):
        if re.search(rf"tunnel connection failed:\s*{code}\b", text) or re.search(
            rf"\b{code}\s+proxy authentication", text
        ):
            return classify_network_failure(
                requests.exceptions.ProxyError(
                    OSError(f"Tunnel connection failed: {code}")
                )
            )
    if "certificate verify failed" in text or "certificate_verify_failed" in text:
        return classify_network_failure(requests.exceptions.SSLError())
    if "timed out" in text or "timeout" in text:
        return classify_network_failure(requests.exceptions.Timeout())
    return NetworkFailure(
        "PIP_INSTALACAO",
        "O pip não concluiu a instalação MCP.",
        "Confira acesso ao índice, requisitos e dependências; falha de acesso não comprova ausência de uma versão.",
        False,
    )


def dependency_environment() -> dict[str, str]:
    from proxy_config import configure_proxy

    # Falha de configuração não autoriza fallback direto. A configuração é
    # importada somente depois da seleção de perfil pelo ponto de entrada.
    status = configure_proxy()
    print(
        f"[INFO] Rede MCP: rota={'proxy' if status.active else 'direta explícita/sem proxy configurado'}; "
        f"credenciais={'configuradas' if status.has_credentials else 'ausentes'}; HTTPS ainda não comprovado.",
        flush=True,
    )
    env = dict(os.environ)
    # Não deixar pip.ini/PIP_PROXY sobrepor a rota escolhida. A mudança vale
    # só para o filho; índices e certificados fornecidos por ambiente permanecem.
    env["PIP_CONFIG_FILE"] = os.devnull
    env["PIP_PROXY"] = env.get("HTTPS_PROXY", "") if status.active else ""
    env["PIP_TRUSTED_HOST"] = ""
    # pip tem configuração própria de CA; usar a mesma CA explícita do requests.
    bundle = (
        env.get("REQUESTS_CA_BUNDLE")
        or env.get("CURL_CA_BUNDLE")
        or env.get("PIP_CERT")
        or env.get("SSL_CERT_FILE")
    )
    if bundle:
        if not Path(bundle).is_file():
            raise ValueError("CA configurada indisponível")
        env["PIP_CERT"] = bundle
        env["REQUESTS_CA_BUNDLE"] = bundle
    return env


def install(python: Path, *, run=subprocess.run, sleep=time.sleep) -> int:
    try:
        env = dependency_environment()
    except Exception:
        print(
            "[ERRO] CONFIGURACAO_REDE_MCP: confira secrets_config.py, perfil e CA aprovada; detalhes privados não são exibidos."
        )
        return 2
    command = [
        str(python),
        "-m",
        "pip",
        "--disable-pip-version-check",
        "install",
        "--no-input",
        "--retries",
        "0",
        "--timeout",
        "45",
        "-r",
        str(ROOT / "connectors/meta_ads_mcp/requirements.txt"),
    ]
    for attempt in range(1, 4):
        print(f"[INFO] Dependências MCP: tentativa {attempt}/3.", flush=True)
        try:
            result = run(
                command,
                cwd=ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=600,
            )
            if result.returncode == 0:
                print(
                    "[OK] Dependências MCP instaladas; validação offline será executada."
                )
                return 0
            failure = pip_failure(result.stdout or "")
        except subprocess.TimeoutExpired:
            failure = NetworkFailure(
                "TIMEOUT",
                "O pip excedeu o prazo de instalação.",
                "Confira a rota e o índice.",
                True,
            )
        except OSError:
            failure = NetworkFailure(
                "PIP_EXECUCAO",
                "Não foi possível iniciar o pip MCP.",
                "Confira o ambiente Python instalado.",
                False,
            )
        print(f"[ERRO] {failure.summary}", flush=True)
        if not failure.retryable or attempt == 3:
            return 1
        sleep(2 ** (attempt - 1))
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Dependências MCP com rede NexoFlow; sem Codex."
    )
    parser.add_argument("--python", required=True, type=Path)
    parser.add_argument(
        "--perfil",
        choices=["FARMA", "PET"],
        default=os.environ.get("NEXOFLOW_PERFIL", "FARMA"),
    )
    args = parser.parse_args()
    os.environ["NEXOFLOW_PERFIL"] = args.perfil
    expected = ROOT / "connectors/meta_ads_mcp/.venv/Scripts/python.exe"
    if args.python.resolve() != expected.resolve() or not expected.is_file():
        print("[ERRO] Interpretador MCP ausente ou fora da instalação esperada.")
        return 2
    return install(expected)


if __name__ == "__main__":
    raise SystemExit(main())
