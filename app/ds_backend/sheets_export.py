"""Única leitura Sheets do corte; não grava dados, origem, lease ou manifesto."""

from __future__ import annotations

from contextlib import closing
from pathlib import Path

from ds_backend.contract import REGISTRY, StorageError, digest
from ds_backend.migration import Export, SourceKeyConflict, private_json


def export_sheets(store, path, segment, revision, exclusions):
    if (
        exclusions.get("segment") != segment
        or exclusions.get("revision") != revision
        or not isinstance(exclusions.get("rows"), list)
        or not exclusions.get("source_sha256")
    ):
        raise StorageError("DS_EXCLUSOES_NAO_CONFERIDAS")
    from gspread.utils import rowcol_to_a1

    from sheets_continuation import ContinuationIndex, fingerprint, verify_book_stamp
    from sheets_partitions import role_for, roots_for

    manager = store._continuity
    if manager is None:
        raise StorageError("DS_ORIGEM_SEM_MANIFESTO")

    def guard():
        # Sem assumir que expiração de lease autoriza adotar um gravador interrompido.
        if manager.lease._lookup() is not None:
            raise StorageError("DS_ORIGEM_COM_GRAVADOR_OU_RECUPERACAO")
        values = store._read_with_retry(
            "conferir manifesto do corte PostgreSQL", manager.sheet.get_all_values
        )
        index = ContinuationIndex.parse(
            values, hub=store._hub_id, segment=segment, roots=roots_for(store)
        )
        if index.config.get("history_publication") != {
            "state": "READY",
            "revision": revision,
        }:
            raise StorageError("DS_REVISAO_ORIGEM_DIVERGENTE")
        if any(s.get("state") != "READY" for s in index.status.values()):
            raise StorageError("DS_ORIGEM_COM_PUBLICACAO_INCOMPLETA")
        return index, digest(values)

    index, manifest_hash = guard()
    from order_history_sheets import SCHEMAS as HISTORY_SCHEMAS

    if any(not index.table_parts(name) for name in HISTORY_SCHEMAS):
        raise StorageError("DS_FONTE_HISTORICA_AUSENTE")
    roots = roots_for(store)
    books = {**{v: manager._book(v) for v in roots.values()}}
    for part in index.parts.values():
        books.setdefault(part.book_id, manager._book(part.book_id))
    versions = {}
    for bid, book in books.items():
        role = next((r for r, value in roots.items() if value == bid), None)
        if role is None:
            file = index.files.get(bid)
            if file is None:
                raise StorageError("DS_PARTE_ORFA")
            role = file["role"]
        if not verify_book_stamp(book, hub=store._hub_id, segment=segment, role=role):
            raise StorageError("DS_ORIGEM_NAO_COMPROVADA")
        response = store._read_with_retry(
            "conferir versão Drive do corte",
            lambda bid=bid: store.client.http_client.request(
                "get",
                "https://www.googleapis.com/drive/v3/files/" + bid,
                params={"fields": "id,version,trashed"},
            ).json(),
        )
        if response.get("trashed") or not response.get("version"):
            raise StorageError("DS_VERSAO_DRIVE_NAO_COMPROVADA")
        versions[bid] = response["version"]
    missing = []
    present = []
    with closing(Export(path, create=True)) as output:
        output.add("Exclusoes_Publicacao", exclusions["rows"], segment)
        for name, spec in REGISTRY.items():
            if name.startswith("Cache_") or name == "Exclusoes_Publicacao":
                continue
            parts = index.table_parts(name)
            physical = []
            if parts:
                physical = [(manager.worksheet(p), p) for p in parts]
            else:
                book = manager._book(roots[role_for(name)])
                physical = [
                    (ws, None)
                    for ws in store._read_with_retry(
                        "localizar tabela do corte", book.worksheets
                    )
                    if ws.title == name
                ]
                if not physical:
                    # Ausência é documentada no manifesto, nunca inventa uma métrica zero.
                    missing.append(name)
                    continue
            present.append(name)
            for ws, part in physical:
                header = store._read_with_retry(
                    "conferir cabeçalho do corte",
                    lambda ws=ws: ws.get(
                        "A1:" + rowcol_to_a1(1, ws.col_count),
                        value_render_option="UNFORMATTED_VALUE",
                    ),
                )
                if len(header) != 1:
                    raise StorageError("DS_SCHEMA_ORIGEM_DIVERGENTE")
                columns = list(header[0])
                # A grade pode reservar colunas vazias além do cabeçalho real.
                # Ler toda a primeira linha também detecta campos extras à direita.
                while columns and columns[-1] in ("", None):
                    columns.pop()
                if part is not None and (
                    fingerprint(columns) != part.schema or len(columns) != part.width
                ):
                    raise StorageError("DS_SCHEMA_ORIGEM_DIVERGENTE")
                if (
                    any(not isinstance(field, str) or not field for field in columns)
                    or len(columns) != len(spec["columns"])
                    or len(set(columns)) != len(columns)
                    or set(columns) != set(spec["columns"])
                ):
                    raise StorageError("DS_SCHEMA_ORIGEM_DIVERGENTE")
                for offset in range(2, ws.row_count + 1, 1000):
                    end = min(offset + 999, ws.row_count)
                    values = store._read_with_retry(
                        "exportar bloco do corte",
                        lambda ws=ws, offset=offset, end=end, spec=spec: ws.get(
                            rowcol_to_a1(offset, 1)
                            + ":"
                            + rowcol_to_a1(end, len(spec["columns"])),
                            value_render_option="UNFORMATTED_VALUE",
                        ),
                    )
                    rows = []
                    locations = []
                    for position, values_row in enumerate(values, start=offset):
                        if not any(v not in ("", None) for v in values_row):
                            continue
                        if len(values_row) > len(spec["columns"]):
                            raise StorageError("DS_SCHEMA_ORIGEM_DIVERGENTE")
                        padded = list(values_row) + [""] * (
                            len(spec["columns"]) - len(values_row)
                        )
                        rows.append(dict(zip(columns, padded, strict=True)))
                        locations.append(
                            dict(
                                part=part.number if part else None,
                                sheet_id=ws.id,
                                row=position,
                            )
                        )
                    try:
                        output.add(name, rows, segment, locations=locations)
                    except SourceKeyConflict as error:
                        private_json(
                            Path(path).with_suffix(".diagnostico.json"),
                            dict(
                                diagnostic="conflito_chave_v1",
                                segment=segment,
                                revision=revision,
                                state="BLOQUEADO",
                                source_consistency="NAO_CONCLUIDA",
                                conflict=error.diagnostic,
                            ),
                        )
                        raise
        for bid, version in versions.items():
            current = store._read_with_retry(
                "reconferir versão Drive do corte",
                lambda bid=bid: store.client.http_client.request(
                    "get",
                    "https://www.googleapis.com/drive/v3/files/" + bid,
                    params={"fields": "version"},
                ).json(),
            )
            if current.get("version") != version:
                raise StorageError("DS_ORIGEM_ALTERADA_DURANTE_EXPORTACAO")
        if guard()[1] != manifest_hash:
            raise StorageError("DS_MANIFESTO_ORIGEM_ALTERADO")
        return output.seal(
            segment,
            dict(
                state="READY",
                scope="CORTE_COMPLETO",
                revision=revision,
                manifest_hash=manifest_hash,
                versions=versions,
                exclusions_source_hash=exclusions["source_sha256"],
                missing_tables=missing,
                present_tables=present,
            ),
        )
