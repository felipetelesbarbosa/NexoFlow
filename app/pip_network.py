"""Rota pip compartilhada, preflight HTTPS limitado e diagnósticos sem segredos."""

from __future__ import annotations

import os
import re
import ssl
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
    opener = urllib.request.build_opener(
        _NoRedirect(),
        urllib.request.ProxyHandler({"https": proxy} if proxy else {}),
        urllib.request.HTTPSHandler(
            context=ssl.create_default_context(cafile=env.get("PIP_CERT") or None)
        ),
    )
    try:
        with opener.open(urllib.request.Request(url, method="HEAD"), timeout=10):
            return
    except urllib.error.HTTPError as exc:
        # O índice pode recusar HEAD, mas ainda comprova o transporte HTTPS.
        if exc.code == 405:
            return
        code = exc.code
        raise ValueError(
            f"REDE_PIP_HTTP_{code}: índice/proxy recusou a verificação; nenhuma dependência foi solicitada."
        ) from None
    except (OSError, urllib.error.URLError) as exc:
        raw = str(exc).lower()  # apenas para classificar; nunca imprimir
        match = re.search(r"tunnel connection failed:\s*(\d{3})", raw)
        if match:
            code = match[1]
            raise ValueError(
                f"PROXY_CONNECT_{code}: túnel HTTPS não estabelecido; confira autenticação e política com a TI."
            ) from None
        category = (
            "TLS_CERTIFICADO"
            if "certificate" in raw or isinstance(exc, ssl.SSLError)
            else "REDE_PIP_INDISPONIVEL"
        )
        raise ValueError(
            f"{category}: preflight HTTPS falhou; nenhuma dependência foi solicitada."
        ) from None
