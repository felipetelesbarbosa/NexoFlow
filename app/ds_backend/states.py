"""Estado remoto confirmado antes da cópia local; CAS impede dois publicadores."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import uuid4

from ds_backend.client import Client, configured
from ds_backend.contract import StorageError, digest

NAMES = {
    "weni_update_state.json": "weni_update",
    "recompra_state.json": "recompra",
    "historico_pedidos_state.json": "historico_cursor",
    "full_load_25_manifest.json": "carga_fracionada",
}
_VERSIONS = {}
_DOCUMENTS = {}
_ALIASES = {}


def _client(path, explicit=None):
    path = Path(path)
    if explicit is not None:
        if explicit not in NAMES.values():
            raise StorageError("DS_ESTADO_NAO_AUTORIZADO")
        _ALIASES[path.resolve()] = explicit
    name = explicit or _ALIASES.get(path.resolve()) or NAMES.get(path.name)
    from project_paths import load_private_settings

    if name is None or not configured():
        return None
    from ds_backend.runtime import CURRENT_STORE

    if CURRENT_STORE is not None:
        return CURRENT_STORE.client
    settings = load_private_settings()
    return Client.from_settings(settings)


def load(path, default, *, name=None) -> tuple[bool, dict[str, Any]]:
    path = Path(path)
    client = _client(path, name)
    if client is None:
        return False, {}
    try:
        name = name or _ALIASES.get(path.resolve()) or NAMES[path.name]
        key = (client.expected_target, name)
        if key in _DOCUMENTS:
            return True, deepcopy(_DOCUMENTS[key])
        result = client.call("/v1/estados/ler", dict(name=name))
        if result["document"] is None:
            raise StorageError("DS_ESTADO_EXIGE_MIGRACAO_INICIAL")
        previous = _VERSIONS.get((client.expected_target, name))
        if previous is not None and previous != result["version"]:
            raise StorageError("DS_ESTADO_EDICAO_CONCORRENTE")
        _VERSIONS[(client.expected_target, name)] = result["version"]
        document = (
            unpack(result["document"]) if result["document"] is not None else default
        )
        if not isinstance(document, dict):
            raise StorageError("DS_ESTADO_INVALIDO")
        _DOCUMENTS[key] = deepcopy(document)
        return True, document
    finally:
        _release(client)


def save(path, document, *, name=None):
    path = Path(path)
    client = _client(path, name)
    if client is None:
        return False
    try:
        name = name or _ALIASES.get(path.resolve()) or NAMES[path.name]
        key = (client.expected_target, name)
        if key not in _VERSIONS:
            raise StorageError("DS_ESTADO_EXIGE_LEITURA_PREVIA")
        encoded = pack(document)
        receipt = client.call(
            "/v1/estados/gravar",
            dict(
                name=name,
                expected_version=_VERSIONS[key],
                document=encoded,
                receipt_id=str(uuid4()),
            ),
        )
        if receipt.get("state") != "CONFIRMADO" or receipt.get("hash") != digest(
            encoded
        ):
            raise StorageError("DS_ESTADO_NAO_CONFIRMADO")
        _VERSIONS[key] = receipt["version"]
        _DOCUMENTS[key] = deepcopy(document)
        return True
    finally:
        _release(client)


def _release(client):
    from ds_backend.runtime import CURRENT_STORE

    if CURRENT_STORE is None or CURRENT_STORE.client is not client:
        client.close()


def pack(document):
    import base64
    import json
    import zlib

    raw = json.dumps(
        document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    if len(raw) > 128 * 1024 * 1024:
        raise StorageError("DS_ESTADO_EXCEDE_LIMITE")
    if len(raw) < 500_000:
        return document
    return dict(
        encoding="zlib_json_1",
        sha256=__import__("hashlib").sha256(raw).hexdigest(),
        data=base64.b64encode(zlib.compress(raw)).decode(),
    )


def unpack(document):
    if not isinstance(document, dict) or document.get("encoding") != "zlib_json_1":
        return document
    import base64
    import hashlib
    import json
    import zlib

    try:
        decoder = zlib.decompressobj()
        raw = decoder.decompress(
            base64.b64decode(document["data"], validate=True), 128 * 1024 * 1024 + 1
        )
        if (
            len(raw) > 128 * 1024 * 1024
            or decoder.unconsumed_tail
            or not decoder.eof
            or hashlib.sha256(raw).hexdigest() != document["sha256"]
        ):
            raise ValueError
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError
        return result
    except (ValueError, KeyError, zlib.error):
        raise StorageError("DS_ESTADO_COMPACTADO_INVALIDO") from None
