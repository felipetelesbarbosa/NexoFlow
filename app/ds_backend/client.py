"""Cliente privado Windows: sem DSN, sem Google e sem fallback de destino."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import requests

from ds_backend.contract import (
    PROTOCOL,
    SCHEMA_HASH,
    StorageError,
    digest,
    identifier,
    normalize,
    target,
)

POSTGRES_LABEL = "PostgreSQL da VPS"
_TRANSIENT_SERVER_ERRORS = {
    "DS_BANCO_INDISPONIVEL",
    "DS_HTTP_502",
    "DS_HTTP_503",
    "DS_HTTP_504",
    "DS_HTTP_524",
}
UNCERTAIN_RESPONSE_ERRORS = _TRANSIENT_SERVER_ERRORS | {"DS_RESPOSTA_NAO_CONFIRMADA_RETOMAR"}


def replay_revision_request(call, path, data):
    """Repete uma vez somente abertura ou selo, com o mesmo UUID e conteúdo."""
    try:
        return call(path, data)
    except StorageError as error:
        if str(error) not in UNCERTAIN_RESPONSE_ERRORS:
            raise
        logging.warning(
            "%s: resposta incerta em %s (%s); repetindo uma vez com a mesma revisão %s.",
            POSTGRES_LABEL, path, error, data["revision"],
        )
        time.sleep(1)
        return call(path, data)


def backend_label(postgres: bool) -> str:
    return POSTGRES_LABEL if postgres else "Google Sheets"


def enabled(settings):
    mode = getattr(settings, "ARMAZENAMENTO_BACKEND", "sheets")
    if mode not in ("sheets", "postgres"):
        raise StorageError("DS_BACKEND_INVALIDO")
    return mode == "postgres"


class _PageResponseError(StorageError):
    def __init__(self, reason):
        super().__init__("DS_RESPOSTA_NAO_CONFIRMADA_RETOMAR")
        self.reason = reason


class Client:
    def __init__(self, config, *, session=None):
        required = {
            "endpoint",
            "api_token",
            "access_client_id",
            "access_client_secret",
            "environment",
            "segment",
            "protocol",
        }
        if set(config) != required or config["protocol"] != PROTOCOL:
            raise StorageError("DS_CONFIGURACAO_INVALIDA")
        endpoint = urlsplit(config["endpoint"])
        if (
            endpoint.scheme != "https"
            or not endpoint.hostname
            or endpoint.username
            or endpoint.password
            or endpoint.query
            or endpoint.fragment
            or endpoint.path not in ("", "/")
        ):
            raise StorageError("DS_ENDPOINT_INVALIDO")
        if any(
            not isinstance(config[k], str) or not config[k].strip() for k in required
        ):
            raise StorageError("DS_CREDENCIAL_INCOMPLETA")
        self.expected_target = target(config["environment"], config["segment"])
        self.config = config.copy()
        self.session = session or requests.Session()
        self.endpoint = config["endpoint"].rstrip("/")
        self.session.headers.update(
            {
                "Authorization": "Bearer " + config["api_token"],
                "CF-Access-Client-Id": config["access_client_id"],
                "CF-Access-Client-Secret": config["access_client_secret"],
            }
        )
        self.expected_read_version: int | None = None
        self.reads = self.writes = 0
        self.verify()

    @classmethod
    def from_settings(cls, settings, **kwargs):
        from project_paths import ROOT
        from runtime_profile import segment

        path = Path(str(getattr(settings, "DATASTUDIO_CREDENTIALS_FILE", "")))
        if not path.is_absolute():
            path = ROOT / path
        if not path.is_file():
            raise StorageError("DS_ARQUIVO_PRIVADO_AUSENTE")
        try:
            config = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            raise StorageError("DS_ARQUIVO_PRIVADO_INVALIDO") from None
        if config.get("segment") != segment() or config.get("environment") != getattr(
            settings, "DATASTUDIO_AMBIENTE", "homologacao"
        ):
            raise StorageError("DS_PERFIL_DIVERGENTE")
        return cls(config, **kwargs)

    def call(self, path, data=None, *, method=None):
        method = method or ("GET" if data is None else "POST")
        self.reads += int(method == "GET" or path == "/v1/linhas")
        self.writes += int(method != "GET" and path != "/v1/linhas")
        try:
            response = self.session.request(
                method,
                self.endpoint + path,
                json=data,
                timeout=(
                    10,
                    120 if method == "POST" and path == "/v1/confirmar" else 65,
                ),
                allow_redirects=False,
            )
            if response.status_code not in (200, 201):
                # Não incluir texto, headers, URL ou mensagem arbitrária do provedor.
                code = f"DS_HTTP_{response.status_code}"
                try:
                    error = response.json().get("error")
                    if (
                        isinstance(error, str)
                        and error.startswith("DS_")
                        and error.replace("_", "").isalnum()
                    ):
                        code = error
                except (ValueError, AttributeError):
                    pass
                raise StorageError(code)
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError
            return result
        except (requests.RequestException, ValueError) as error:
            if isinstance(error, StorageError):
                raise
            if path == "/v1/linhas" and not isinstance(
                error, requests.exceptions.SSLError
            ):
                if isinstance(
                    error,
                    (
                        requests.Timeout,
                        requests.ConnectionError,
                        requests.exceptions.ChunkedEncodingError,
                        requests.exceptions.ContentDecodingError,
                        ValueError,
                    ),
                ):
                    # A mensagem original pode conter URL, credenciais ou conteúdo da página.
                    raise _PageResponseError(type(error).__name__) from None
            raise StorageError("DS_RESPOSTA_NAO_CONFIRMADA_RETOMAR") from None

    def verify(self):
        info = self.call("/v1/destino")
        if any(
            info.get(k) != v
            for k, v in {
                "protocol": PROTOCOL,
                "target": self.expected_target,
                "segment": self.config["segment"],
                "environment": self.config["environment"],
                "schema_hash": SCHEMA_HASH,
            }.items()
        ):
            raise StorageError("DS_CONTRATO_DESTINO_DIVERGENTE")
        self.info = info
        return info

    def _read_page(self, name, revision, cursor, number):
        request = dict(name=name, revision=revision, after=cursor, limit=1000)
        attempt = 1
        while True:
            try:
                return self.call("/v1/linhas", request)
            except StorageError as error:
                if isinstance(error, _PageResponseError):
                    reason = error.reason
                elif str(error) in _TRANSIENT_SERVER_ERRORS | {
                    "DS_HTTP_408",
                    "DS_HTTP_429",
                }:
                    reason = str(error)
                else:
                    raise
                logging.warning(
                    "%s: falha ao ler %s, página %d, tentativa %d/3, motivo=%s.",
                    POSTGRES_LABEL,
                    name,
                    number,
                    attempt,
                    reason,
                )
                if attempt == 3:
                    raise
                time.sleep(attempt)
                attempt += 1

    def rows(self, name, revision):
        cursor = ""
        version = self.expected_read_version
        number = 1
        while True:
            page = self._read_page(name, revision, cursor, number)
            if type(page.get("version")) is not int:
                raise StorageError("DS_VERSAO_LEITURA_INVALIDA")
            if version is not None and page["version"] != version:
                raise StorageError("DS_VERSAO_ALTERADA_DURANTE_LEITURA")
            version = page["version"]
            rows = page.get("rows")
            if (
                not isinstance(rows, list)
                or len(rows) > 1000
                or "next" not in page
                or not all(isinstance(row, dict) for row in rows)
            ):
                raise StorageError("DS_PAGINA_INVALIDA")
            next_cursor = page["next"]
            if next_cursor is not None and (
                not rows or not isinstance(next_cursor, str) or next_cursor <= cursor
            ):
                raise StorageError("DS_CURSOR_INVALIDO")
            yield from rows
            if next_cursor is None:
                break
            cursor = next_cursor
            number += 1

    def begin(self, purpose, evidence=None):
        revision = str(uuid4())
        result = replay_revision_request(
            self.call,
            "/v1/revisoes",
            dict(revision=revision, purpose=purpose, evidence=evidence or {}),
        )
        if result.get("revision") != revision or result.get("state") != "WRITING":
            raise StorageError("DS_REVISAO_NAO_CONFIRMADA")
        return result

    def send(self, revision, name, rows, *, remove=None, batch_id=None, simulate=False):
        revision = identifier(revision)
        batch_id = identifier(batch_id) if batch_id is not None else str(uuid4())
        data = dict(
            revision=revision,
            batch_id=batch_id,
            name=name,
            rows=rows,
            remove=remove or [],
            simulate=simulate,
        )
        expected = digest(
            dict(
                revision=revision,
                table=name,
                rows=normalize(name, rows, self.config["segment"]),
                remove=remove or [],
            )
        )
        for attempt in range(2):
            try:
                receipt = self.call("/v1/lotes", data)
                break
            except StorageError as error:
                if str(error) not in UNCERTAIN_RESPONSE_ERRORS:
                    raise
            # O GET pode ocorrer antes do COMMIT. A API serializa pelo UUID
            # da revisão e reconfere o hash do mesmo lote sob a trava.
            logging.warning(
                "%s: resposta incerta; consultando recibo. Revisão=%s; tabela=%s; lote=%s.",
                POSTGRES_LABEL, revision, name, batch_id,
            )
            try:
                receipt = self.call("/v1/lotes/" + batch_id)
                break
            except StorageError as error:
                if str(error) != "DS_LOTE_AUSENTE" or attempt:
                    raise
                logging.warning(
                    "%s: recibo ausente; repetindo uma vez o mesmo lote %s.",
                    POSTGRES_LABEL, batch_id,
                )
        else:
            raise StorageError("DS_RESPOSTA_NAO_CONFIRMADA_RETOMAR")
        if (
            receipt.get("id") != batch_id
            or receipt.get("revision") != revision
            or receipt.get("hash") != expected
            or receipt.get("state") != ("SIMULADO" if simulate else "CONFIRMADO")
        ):
            raise StorageError("DS_RECIBO_DIVERGENTE")
        if any(
            not isinstance(receipt.get(k), int) or receipt[k] < 0
            for k in ("inserted", "updated", "unchanged", "removed")
        ):
            raise StorageError("DS_RECIBO_DIVERGENTE")
        return receipt

    def close(self):
        self.session.close()


def configured():
    """Seleciona só o backend, sem exigir credenciais para utilitários offline."""
    import importlib
    from types import SimpleNamespace

    from runtime_profile import segment

    try:
        raw = importlib.import_module("secrets_config")
    except ModuleNotFoundError as error:
        if error.name == "secrets_config":
            return False
        raise
    profiles = getattr(raw, "PERFIS", {})
    overrides = profiles.get(segment(), {}) if isinstance(profiles, dict) else {}
    mode = (
        overrides.get(
            "ARMAZENAMENTO_BACKEND", getattr(raw, "ARMAZENAMENTO_BACKEND", "sheets")
        )
        if isinstance(overrides, dict)
        else getattr(raw, "ARMAZENAMENTO_BACKEND", "sheets")
    )
    return enabled(SimpleNamespace(ARMAZENAMENTO_BACKEND=mode))
