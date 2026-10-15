"""Classify connection failures without emitting exception text or credentials."""

from __future__ import annotations

import errno
import re
import socket
from dataclasses import dataclass

import requests


@dataclass(frozen=True)
class NetworkFailure:
    category: str
    detail: str
    action: str
    retryable: bool = True
    status: int | None = None

    @property
    def summary(self) -> str:
        status = f" HTTP={self.status};" if self.status is not None else ""
        return f"[{self.category}]{status} {self.detail} {self.action}"


def classify_network_failure(error: BaseException) -> NetworkFailure:
    # urllib3 nests ProxyError/MaxRetryError and CONNECT failures in args/reason.
    pending = [error]
    seen: set[int] = set()
    errors: list[BaseException] = []
    texts: list[str] = []
    while pending and len(seen) < 24:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        errors.append(current)
        for item in current.args:
            if isinstance(item, BaseException):
                pending.append(item)
            elif isinstance(item, str):
                # Only inspect locally. No original text is returned or logged.
                texts.append(item[:4096].lower())
        for name in ("reason", "original_error", "__cause__", "__context__"):
            child = getattr(current, name, None)
            if isinstance(child, BaseException):
                pending.append(child)

    text = " ".join(texts)
    proxy = any(
        isinstance(e, requests.exceptions.ProxyError)
        or type(e).__name__ == "ProxyError"
        for e in errors
    )
    match = re.search(r"tunnel connection failed:\s*(\d{3})\b", text)
    response = getattr(error, "response", None)
    response_status = getattr(response, "status_code", None)
    status = (
        int(match[1])
        if match
        else response_status
        if isinstance(response_status, int)
        else None
    )
    if status == 407:
        return NetworkFailure(
            "PROXY_AUTENTICACAO",
            "O proxy exige autenticação ou recusou as credenciais.",
            "Confira usuário, senha e método de autenticação exigido pelo proxy.",
            False,
            407,
        )
    if proxy and status == 403:
        return NetworkFailure(
            "PROXY_ACESSO_NEGADO",
            "O proxy negou o túnel HTTPS.",
            "Confira a liberação do domínio de destino com a equipe de rede.",
            False,
            403,
        )
    if (
        any(
            isinstance(e, requests.exceptions.SSLError)
            or type(e).__name__ == "SSLError"
            for e in errors
        )
        or "certificate_verify_failed" in text
        or "certificate verify failed" in text
    ):
        return NetworkFailure(
            "TLS_CERTIFICADO",
            "Falha na negociação TLS ou validação do certificado.",
            "Confira a cadeia de certificados, a CA corporativa e o relógio do computador; mantenha a verificação TLS ativa.",
            False,
        )
    if any(
        isinstance(e, socket.gaierror) or type(e).__name__ == "NameResolutionError"
        for e in errors
    ):
        return NetworkFailure(
            "DNS",
            "Não foi possível resolver um endereço da rota de conexão.",
            "Confira DNS e os endereços do proxy e do serviço.",
        )
    if any(
        isinstance(e, (requests.exceptions.Timeout, TimeoutError))
        or type(e).__name__ in {"ConnectTimeoutError", "ReadTimeoutError"}
        for e in errors
    ):
        return NetworkFailure(
            "TIMEOUT",
            "A conexão ou resposta excedeu o tempo limite.",
            "Confira a disponibilidade da rota e do serviço.",
        )
    if any(
        isinstance(e, OSError)
        and (e.errno == errno.ECONNREFUSED or getattr(e, "winerror", None) == 10061)
        for e in errors
    ):
        return NetworkFailure(
            "CONEXAO_RECUSADA",
            "Uma conexão da rota foi recusada.",
            "Confira host, porta, firewall e disponibilidade do proxy/serviço.",
        )
    if proxy:
        return NetworkFailure(
            "PROXY_CONEXAO",
            "Não foi possível estabelecer a conexão pelo proxy.",
            "A porta acessível não comprova acesso HTTPS; confira autenticação e regras do domínio de destino.",
            status=status,
        )
    if status is not None:
        return NetworkFailure(
            "HTTP",
            "O serviço respondeu com erro HTTP.",
            "Confira o código de resposta e as permissões do serviço.",
            status == 429 or status >= 500,
            status,
        )
    return NetworkFailure(
        "REDE",
        "Falha de conexão sem causa específica identificada.",
        "Confira a rota, DNS, firewall e disponibilidade do serviço.",
    )
