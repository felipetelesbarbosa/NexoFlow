"""Rota pip compartilhada, preflight HTTPS limitado e diagnósticos sem segredos."""

from __future__ import annotations

import os
import re
import socket
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit


def pip_environment(active: bool) -> dict[str, str]:
    env = dict(os.environ)
    env["PIP_CONFIG_FILE"] = os.devnull
    env["PIP_PROXY"] = env.get("HTTPS_PROXY", "") if active else ""
    env["PIP_TRUSTED_HOST"] = ""
    bundle = (
        env.get("REQUESTS_CA_BUNDLE")
        or env.get("CURL_CA_BUNDLE")
        or env.get("PIP_CERT")
        or env.get("SSL_CERT_FILE")
    )
    if bundle:
        if not Path(bundle).is_file():
            raise ValueError("TLS_CERTIFICADO: arquivo de CA aprovado não encontrado.")
        env["PIP_CERT"] = bundle
        env["REQUESTS_CA_BUNDLE"] = bundle
    return env


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def preflight(env: dict[str, str]) -> None:
    url = env.get("PIP_INDEX_URL") or "https://pypi.org/simple/"
    if urlsplit(url).scheme != "https":
        raise ValueError("TLS_INDICE: o índice pip precisa usar HTTPS.")
    proxy = env.get("PIP_PROXY") or ""
    try:
        context = ssl.create_default_context(cafile=env.get("PIP_CERT") or None)
    except OSError:
        raise ValueError(
            "TLS_CERTIFICADO: não foi possível carregar a CA aprovada."
        ) from None
    opener = urllib.request.build_opener(
        _NoRedirect(),
        urllib.request.ProxyHandler({"https": proxy} if proxy else {}),
        urllib.request.HTTPSHandler(context=context),
    )
    waits = (2, 4, None)
    for attempt, wait in enumerate(waits, start=1):
        try:
            with opener.open(urllib.request.Request(url, method="HEAD"), timeout=10):
                return
        except urllib.error.HTTPError as exc:
            exc.close()
            # O índice pode recusar HEAD após estabelecer o transporte HTTPS.
            if exc.code == 405:
                return
            category = f"REDE_PIP_HTTP_{exc.code}"
            retry = exc.code in (408, 500, 502, 503, 504)
        except OSError as exc:
            category, retry = _transport_failure(exc)
        if wait is None or not retry:
            raise ValueError(
                f"{category}: a verificação HTTPS falhou na tentativa {attempt}/{len(waits)}. "
                "Nenhuma dependência foi solicitada."
            ) from None
        print(
            f"[AVISO] {category}: tentativa {attempt}/{len(waits)}. "
            f"Nova tentativa na mesma rota em {wait}s.",
            flush=True,
        )
        time.sleep(wait)


def _transport_failure(exc: OSError) -> tuple[str, bool]:
    reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    raw = str(reason).lower()  # apenas para classificar; nunca imprimir
    match = re.search(r"tunnel connection failed:\s*(\d{3})", raw)
    if match:
        code = match[1]
        return f"PROXY_CONNECT_{code}", code in ("500", "502", "503", "504")
    if isinstance(reason, TimeoutError) or "timed out" in raw:
        return "REDE_PIP_TIMEOUT", True
    if isinstance(reason, ssl.SSLError) or "certificate" in raw:
        return "TLS_CERTIFICADO", False
    if isinstance(reason, socket.gaierror):
        return "REDE_PIP_DNS", reason.errno == socket.EAI_AGAIN
    return "REDE_PIP_INDISPONIVEL", True
