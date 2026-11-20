"""Recebe partes FARMA em staging; a troca do checkpoint é uma única transação CAS."""

import re

from ds_backend.contract import StorageError, digest
from ds_backend.state_transfer import MAX_PARTS, PART_SIZE, receipt_key


def receive(
    store, *, name, expected_version, receipt_id, checksum, raw_hash, count, index, data
):
    if (
        store.segment != "FARMA"
        or name != "recompra"
        or type(expected_version) is not int
        or expected_version < 0
        or not all(
            isinstance(h, str) and re.fullmatch("[a-f0-9]{64}", h)
            for h in (checksum, raw_hash)
        )
        or receipt_id != receipt_key(store.target, name, expected_version, checksum)
        or type(count) is not int
        or not 2 <= count <= MAX_PARTS
        or type(index) is not int
        or not 0 <= index < count
        or not isinstance(data, str)
        or not 0 < len(data) <= PART_SIZE
        or index < count - 1
        and len(data) != PART_SIZE
        or len(data) % 4
        or not re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", data)
    ):
        raise StorageError("DS_ESTADO_PARTE_INVALIDA")
    with store.connect() as conn:
        store.lock_state(conn, name)
        done = conn.execute(
            "SELECT recibo FROM farma.nf_estado_recibos WHERE id=%s", (receipt_id,)
        ).fetchone()
        if done:
            receipt = done["recibo"]
            if (
                receipt["hash"] != checksum
                or receipt["version"] != expected_version + 1
            ):
                raise StorageError("DS_RECIBO_REUTILIZADO")
            return receipt
        current = conn.execute(
            "SELECT versao FROM farma.nf_estados WHERE nome=%s", (name,)
        ).fetchone()
        if (current["versao"] if current else 0) != expected_version:
            raise StorageError("DS_ESTADO_EDICAO_CONCORRENTE")
        if index == 0:
            conn.execute(
                "DELETE FROM farma.nf_estado_partes WHERE criado < now() - interval '2 days'"
            )
            # Limitar também o número de uploads abandonados. Uma repetição do mesmo
            # documento sempre usa o mesmo identificador e pode avançar imediatamente.
            pending = conn.execute(
                "SELECT count(DISTINCT upload) AS n FROM farma.nf_estado_partes WHERE upload<>%s",
                (receipt_id,),
            ).fetchone()
            if pending["n"] >= 2:
                raise StorageError("DS_ESTADO_ENVIOS_PENDENTES")
        elif not conn.execute(
            "SELECT 1 FROM farma.nf_estado_partes WHERE upload=%s AND posicao=%s",
            (receipt_id, index - 1),
        ).fetchone():
            raise StorageError("DS_ESTADO_PARTE_ANTERIOR_AUSENTE")
        row = conn.execute(
            "SELECT dados FROM farma.nf_estado_partes WHERE upload=%s AND posicao=%s",
            (receipt_id, index),
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO farma.nf_estado_partes(upload,posicao,dados) VALUES(%s,%s,%s)",
                (receipt_id, index, data),
            )
        elif row["dados"] != data:
            raise StorageError("DS_ESTADO_PARTE_DIVERGENTE")
        if index + 1 < count:
            return dict(state="PARTE_RECEBIDA", id=receipt_id, index=index)
        full = conn.execute(
            "SELECT string_agg(dados,'' ORDER BY posicao) AS data,count(*) AS n FROM farma.nf_estado_partes WHERE upload=%s",
            (receipt_id,),
        ).fetchone()
        document = dict(encoding="zlib_json_1", sha256=raw_hash, data=full["data"])
        if full["n"] != count or digest(document) != checksum:
            raise StorageError("DS_ESTADO_HASH_DIVERGENTE")
        receipt = store.write_state(conn, name, expected_version, document, receipt_id)
        conn.execute(
            "DELETE FROM farma.nf_estado_partes WHERE upload=%s", (receipt_id,)
        )
        return receipt
