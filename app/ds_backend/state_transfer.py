"""Transporte privado de um checkpoint, com um único recibo para o documento."""

from __future__ import annotations

from uuid import NAMESPACE_URL, uuid4, uuid5

from ds_backend.contract import StorageError, digest

# Múltiplo de 4, abaixo do limite HTTP; o conteúdo compactado é base64 ASCII.
PART_SIZE = 4_000_000
MAX_PARTS = 8


def receipt_key(target, name, version, checksum):
    return str(uuid5(NAMESPACE_URL, f"{target}/{name}/{version}/{checksum}"))


def put(client, name, version, document):
    from ds_backend.states import pack

    encoded = pack(document)
    checksum = digest(encoded)
    key = (
        receipt_key(client.expected_target, name, version, checksum)
        if client.config["segment"] == "FARMA"
        else str(uuid4())
    )
    body = dict(name=name, expected_version=version, receipt_id=key)
    data = encoded.get("data") if encoded.get("encoding") == "zlib_json_1" else None
    receipt = {}
    if (
        client.config["segment"] == "FARMA"
        and name == "recompra"
        and isinstance(data, str)
        and len(data) > PART_SIZE
    ):
        count = (len(data) + PART_SIZE - 1) // PART_SIZE
        if count > MAX_PARTS:
            raise StorageError("DS_ESTADO_EXCEDE_LIMITE")
        for index in range(count):
            receipt = client.call(
                "/v1/estados/parte",
                dict(
                    **body,
                    checksum=checksum,
                    raw_hash=encoded["sha256"],
                    count=count,
                    index=index,
                    data=data[index * PART_SIZE : (index + 1) * PART_SIZE],
                ),
            )
            if receipt.get("state") == "CONFIRMADO":
                break
            if receipt != dict(state="PARTE_RECEBIDA", id=key, index=index):
                raise StorageError("DS_ESTADO_NAO_CONFIRMADO")
    else:
        receipt = client.call("/v1/estados/gravar", dict(**body, document=encoded))
    if (
        receipt.get("state"),
        receipt.get("id"),
        receipt.get("version"),
        receipt.get("hash"),
    ) != ("CONFIRMADO", key, version + 1, checksum):
        raise StorageError("DS_ESTADO_NAO_CONFIRMADO")
    return receipt
