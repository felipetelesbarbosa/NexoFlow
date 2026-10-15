"""Cópia nativa em blocos quando o Google não conclui sheets.copyTo."""

from __future__ import annotations

import copy
import json
import logging
import time
from contextlib import nullcontext

from google.auth.exceptions import TransportError as GoogleAuthTransportError
from gspread.exceptions import APIError
from gspread.utils import absolute_range_name, rowcol_to_a1
from network_diagnostics import classify_network_failure
from requests.exceptions import RequestException

CELL_FIELDS = (
    "userEnteredValue,userEnteredFormat,note,dataValidation,textFormatRuns,chipRuns"
)
UNSUPPORTED = (
    "merges",
    "conditionalFormats",
    "basicFilter",
    "filterViews",
    "protectedRanges",
    "tables",
    "bandedRanges",
    "charts",
    "rowGroups",
    "columnGroups",
    "developerMetadata",
)


def write_native(migration, operation):
    # Leituras e escritas têm cotas distintas. Repetir um bloco fixo é idempotente.
    for attempt in range(6):
        time.sleep(
            max(
                0.0,
                1.1
                - (time.monotonic() - getattr(migration, "_last_native_write", 0.0)),
            )
        )
        migration._last_native_write = time.monotonic()
        try:
            return operation()
        except APIError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 5:
                raise
            logging.warning(
                "Google Sheets: bloco nativo repetido após HTTP %s (%s/6).",
                exc.code,
                attempt + 1,
            )
            time.sleep(min(30, 2 ** (attempt + 1)))
        except (RequestException, GoogleAuthTransportError) as exc:
            failure = classify_network_failure(exc)
            if not failure.retryable or attempt == 5:
                raise
            logging.warning(
                "Google Sheets: repetindo o mesmo bloco após falha transitória [%s] (%s/6).",
                failure.category,
                attempt + 1,
            )
            time.sleep(min(30, 2 ** (attempt + 1)))
    raise RuntimeError("Bloco não gravado.")


def dimension_requests(sheet_id, dimension, start, metadata):
    requests = []
    previous = None
    for index, properties in enumerate(metadata):
        properties = {
            key: value
            for key, value in properties.items()
            if key in {"pixelSize", "hiddenByUser"}
        }
        if not properties:
            previous = None
            continue
        if previous is not None and previous["properties"] == properties:
            previous["range"]["endIndex"] = start + index + 1
        else:
            previous = {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": dimension,
                    "startIndex": start + index,
                    "endIndex": start + index + 1,
                },
                "properties": properties,
                "fields": ",".join(sorted(properties)),
            }
            requests.append({"updateDimensionProperties": previous})
    return requests


def copy_native_blocks(migration, source, destination, entry, *, progress_factory=None):
    original = migration.books[migration.layout.dashboard]
    metadata = migration._read(lambda: original.fetch_sheet_metadata())
    sheet = next(
        item
        for item in metadata["sheets"]
        if item["properties"]["sheetId"] == source.id
    )
    if any(sheet.get(key) for key in UNSUPPORTED):
        raise ValueError(
            f"A aba {source.title} possui estruturas que exigem cópia integral. Os originais foram preservados."
        )
    entry["block_copy"] = True
    migration._save()
    if "target_id" not in entry:
        before = destination.worksheets()
        matches = [
            ws
            for ws in before
            if ws.title == source.title and ws.id not in entry["before_ids"]
        ]
        if len(matches) > 1:
            raise ValueError("Há mais de uma cópia em blocos no destino.")
        if matches:
            target = matches[0]
        else:
            properties = copy.deepcopy(sheet["properties"])
            properties.pop("sheetId", None)
            properties.pop("index", None)
            response = destination.batch_update(
                {"requests": [{"addSheet": {"properties": properties}}]}
            )
            target = destination.get_worksheet_by_id(
                response["replies"][0]["addSheet"]["properties"]["sheetId"]
            )
        entry["target_id"] = target.id
        entry["block_copy"] = True
        migration._save()
    target = destination.get_worksheet_by_id(entry["target_id"])
    if (target.row_count, target.col_count) != (source.row_count, source.col_count):
        raise ValueError(
            "Dimensões diferentes na cópia em blocos; originais preservados."
        )
    completed = entry.get("copied_rows", 0)
    context = (
        progress_factory(
            f"Migração: transferência em blocos de {source.title}",
            source.row_count,
            unit="linhas",
            initial_completed=completed,
        )
        if progress_factory
        else nullcontext(None)
    )
    with context as progress:
        while completed < source.row_count:
            end = min(
                source.row_count,
                completed + min(400, max(1, 40000 // source.col_count)),
            )
            target_range = absolute_range_name(
                source.title, f"A{completed + 1}:{rowcol_to_a1(end, source.col_count)}"
            )
            field_mask = (
                "sheets(properties(sheetId),data(startRow,startColumn,rowData(values("
                + CELL_FIELDS
                + ",pivotTable,dataSourceTable,dataSourceFormula)),rowMetadata(pixelSize,hiddenByUser),columnMetadata(pixelSize,hiddenByUser)))"
            )
            if progress:
                progress.set_activity("aguardando API: leitura do bloco de origem")
            response = migration._read(
                lambda target_range=target_range, field_mask=field_mask: (
                    original.fetch_sheet_metadata(
                        params={
                            "includeGridData": "true",
                            "ranges": [target_range],
                            "fields": field_mask,
                        }
                    )
                )
            )
            source_sheet = next(
                item
                for item in response["sheets"]
                if item["properties"]["sheetId"] == source.id
            )
            data = source_sheet.get("data", [{}])[0]
            if data.get("startRow", 0) != completed or data.get("startColumn", 0) != 0:
                raise ValueError("A API retornou um bloco diferente do solicitado.")
            rows = copy.deepcopy(data.get("rowData", []))
            rows += [{} for _ in range(end - completed - len(rows))]
            for row in rows:
                values = row.setdefault("values", [])
                if any(
                    any(
                        cell.get(key)
                        for key in (
                            "pivotTable",
                            "dataSourceTable",
                            "dataSourceFormula",
                        )
                    )
                    for cell in values
                ):
                    raise ValueError(
                        "O bloco contém estruturas vinculadas; originais preservados."
                    )
                values += [{} for _ in range(source.col_count - len(values))]
                for cell in values:
                    for key in ("pivotTable", "dataSourceTable", "dataSourceFormula"):
                        cell.pop(key, None)
            # Blocos com descrições extensas são divididos para manter payloads pequenos.
            offset = 0
            while offset < len(rows):
                count = len(rows) - offset
                while (
                    count > 1
                    and len(
                        json.dumps(
                            rows[offset : offset + count], ensure_ascii=False
                        ).encode("utf-8")
                    )
                    > 1_300_000
                ):
                    count //= 2
                subset = rows[offset : offset + count]
                begin = completed + offset
                current_fields = sorted(
                    {
                        key
                        for row in subset
                        for cell in row["values"]
                        for key in cell
                        if key in CELL_FIELDS.split(",")
                    }
                    | {"userEnteredValue"}
                )
                block_key = f"{begin}:{begin + count}"
                previous_fields = entry.setdefault("block_fields", {}).get(
                    block_key, []
                )
                current_fields = sorted(set(current_fields) | set(previous_fields))
                entry["block_fields"][block_key] = current_fields
                migration._save()
                requests = [
                    {
                        "updateCells": {
                            "range": {
                                "sheetId": target.id,
                                "startRowIndex": begin,
                                "endRowIndex": begin + count,
                                "startColumnIndex": 0,
                                "endColumnIndex": source.col_count,
                            },
                            "rows": subset,
                            "fields": ",".join(current_fields),
                        }
                    }
                ]
                requests.extend(
                    dimension_requests(
                        target.id,
                        "ROWS",
                        begin,
                        data.get("rowMetadata", [])[offset : offset + count],
                    )
                )
                if begin == 0:
                    requests.extend(
                        dimension_requests(
                            target.id, "COLUMNS", 0, data.get("columnMetadata", [])
                        )
                    )
                if progress:
                    progress.set_activity(
                        "aguardando API: gravação do bloco no destino"
                    )
                write_native(
                    migration,
                    lambda requests=requests: destination.batch_update(
                        {"requests": requests}
                    ),
                )
                offset += count
                entry["copied_rows"] = completed + offset
                migration._save()
                if progress:
                    progress.set_activity("")
                    progress.advance(count)
            completed = end
    return target
