"""FARMA HML: sessões HTTP somente GET, com saída dedicada e TLS verificado."""

import os
from pathlib import Path
from time import monotonic
from urllib.parse import urlsplit

import requests


class ProbePending(RuntimeError):
    """Somente códigos internos, nunca URL, credencial ou dados da resposta."""


def require_scope():
    required = {
        "HUB_AMBIENTE": "homologacao",
        "HUB_ESCRITA_REAL": "false",
        "NEXOFLOW_PERFIL": "FARMA",
        "HUB_REAL_READ_PROBE_ENABLED": "true",
        "WENI_PROXY_ACTIVE": "0",
    }
    if any(os.environ.get(k) != v for k, v in required.items()):
        raise ProbePending("ESCOPO_FARMA_HML_OBRIGATORIO")


def private_token(variable):
    path = os.environ.get(variable)
    if not path:
        raise ProbePending("CREDENCIAL_NAO_PROVISIONADA")
    try:
        value = Path(path).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        raise ProbePending("CREDENCIAL_NAO_PROVISIONADA") from None
    if not value or any(c.isspace() for c in value):
        raise ProbePending("CREDENCIAL_INVALIDA")
    return value


class ReadOnlySession(requests.Session):
    """Mesmo transporte requests, sem proxy herdado, redirecionamentos ou HTTP."""

    def __init__(self, *, host, port, path_allowed, proxy_var, proxy_expected):
        super().__init__()
        self.trust_env = False
        self.host = host
        self.port = port
        self.path_allowed = path_allowed
        proxy = os.environ.get(proxy_var, "")
        if proxy != proxy_expected:
            self.close()
            raise ProbePending("SAIDA_PRIVADA_NAO_CONFIGURADA")
        self.proxies = {"https": proxy}
        self.deadline = monotonic() + 900
        self.remaining_requests = 2000

    def send(self, request, **kwargs):
        parsed = urlsplit(request.url)
        if (
            request.method != "GET"
            or parsed.scheme != "https"
            or parsed.hostname != self.host
            or (parsed.port or 443) != self.port
            or parsed.username
            or parsed.password
            or parsed.fragment
            or not self.path_allowed(parsed.path)
            or kwargs.get("verify") is False
        ):
            raise ProbePending("CONSULTA_FORA_ESCOPO_LEITURA")
        remaining = self.deadline - monotonic()
        if remaining <= 0 or self.remaining_requests <= 0:
            raise ProbePending("LIMITE_AMOSTRA_EXCEDIDO")
        self.remaining_requests -= 1
        # Uma leitura não pode exceder o orçamento restante; o corpo também é limitado.
        timeout = kwargs.get("timeout")
        if isinstance(timeout, tuple):
            kwargs["timeout"] = tuple(min(float(t), remaining) for t in timeout)
        else:
            kwargs["timeout"] = min(float(timeout or 90), remaining)
        kwargs["allow_redirects"] = False
        kwargs["verify"] = True
        # Nem o cliente Windows nem o ambiente podem sobrescrever a saída.
        kwargs["proxies"] = dict(self.proxies)
        kwargs["stream"] = True
        response = super().send(request, **kwargs)
        try:
            body = bytearray()
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if (
                    monotonic() > self.deadline
                    or len(body) + len(chunk) > 64 * 1024 * 1024
                ):
                    raise ProbePending("LIMITE_AMOSTRA_EXCEDIDO")
                body.extend(chunk)
            response._content = bytes(body)
            response._content_consumed = True
            return response
        finally:
            response.close()
