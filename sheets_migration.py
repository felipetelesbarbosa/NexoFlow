"""Cópia nativa, conferência e ativação da separação dos arquivos Sheets."""

from __future__ import annotations

import hashlib
import json
import os
import time
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from gspread.exceptions import APIError
from gspread.utils import absolute_range_name, rowcol_to_a1

from sheets_native_copy import copy_native_blocks
from sheets_storage import STORAGE_SHEET, SheetsStorage


def referenced_sheet_ids(value) -> set[int]:
    if isinstance(value, list):
        return set().union(*(referenced_sheet_ids(item) for item in value))
    if isinstance(value, dict):
        result = {value["sheetId"]} if "sheetId" in value else set()
        for item in value.values():
            result.update(referenced_sheet_ids(item))
        return result
    return set()


class SheetsMigration:
    def __init__(self, client, layout: SheetsStorage, journal: Path):
        self.client = client
        self.layout = SheetsStorage.from_values(layout.values(), layout.dashboard)
        self.journal = journal
        self._last_read = 0.0
        self.books = {
            key: client.open_by_key(key)
            for key in (layout.dashboard, layout.operations, layout.history)
        }
        self.state: dict[str, Any] = {"layout": layout.values(), "copies": {}}
        if journal.exists():
            self.state = json.loads(journal.read_text(encoding="utf-8"))
            if self.state.get("layout") != layout.values():
                raise ValueError("O registro da migração pertence a outros arquivos.")

    def _save(self) -> None:
        self.journal.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.journal.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.chmod(0o600)
        os.replace(temporary, self.journal)

    def _read(self, operation):
        for attempt in range(6):
            time.sleep(max(0.0, 1.1 - (time.monotonic() - self._last_read)))
            self._last_read = time.monotonic()
            try:
                return operation()
            except APIError as exc:
                if exc.code not in (429, 500, 502, 503, 504) or attempt == 5:
                    raise
                time.sleep(min(30, 2 ** (attempt + 1)))
        raise RuntimeError("Leitura não concluída.")

    def _blocks(self, book, ws):
        rows_per_block = max(1, 40000 // ws.col_count)
        starts = list(range(1, ws.row_count + 1, rows_per_block))
        for offset in range(0, len(starts), 4):
            bounds = [
                (start, min(ws.row_count, start + rows_per_block - 1))
                for start in starts[offset : offset + 4]
            ]
            ranges = [
                absolute_range_name(
                    ws.title, f"A{start}:{rowcol_to_a1(end, ws.col_count)}"
                )
                for start, end in bounds
            ]
            response = self._read(
                lambda ranges=ranges: book.values_batch_get(
                    ranges, params={"valueRenderOption": "FORMULA"}
                )
            )
            blocks = response.get("valueRanges", [])
            if len(blocks) != len(bounds):
                raise ValueError("A API não retornou todos os blocos para conferência.")
            for (start, end), block in zip(bounds, blocks, strict=True):
                yield end - start + 1, block.get("values", [])

    def _fingerprint(self, book, ws, *, progress=None) -> str:
        """Conferência de todas as células, em blocos limitados; sem log de dados."""
        digest = hashlib.sha256()
        for row_count, values in self._blocks(book, ws):
            for index in range(row_count):
                row = values[index] if index < len(values) else []
                padded = row + [""] * (ws.col_count - len(row))
                digest.update(
                    json.dumps(
                        padded, ensure_ascii=False, separators=(",", ":")
                    ).encode("utf-8")
                    + b"\n"
                )
            if progress:
                progress.advance(row_count)
        return digest.hexdigest()

    def _verify_native(self, source, target, destination) -> None:
        def sample(book, ws):
            ranges = [
                absolute_range_name(
                    ws.title, f"A1:{rowcol_to_a1(min(2, ws.row_count), ws.col_count)}"
                )
            ]
            metadata = self._read(
                lambda: book.fetch_sheet_metadata(
                    params={"includeGridData": "true", "ranges": ranges}
                )
            )
            sheet = next(
                s for s in metadata["sheets"] if s["properties"]["sheetId"] == ws.id
            )
            return sheet

        original = sample(self.books[self.layout.dashboard], source)
        copied = sample(destination, target)
        if referenced_sheet_ids(original.get("charts", [])) - {
            source.id
        } or referenced_sheet_ids(copied.get("charts", [])) - {target.id}:
            raise ValueError(
                f"Gráfico em {source.title} depende de outra aba; migração interrompida para revisão."
            )
        if (
            original["properties"]["gridProperties"]
            != copied["properties"]["gridProperties"]
        ):
            raise ValueError(f"Estrutura de grade divergente em {source.title}.")

        def safe_cells(sheet):
            rows = [
                [
                    {
                        key: value
                        for key, value in cell.items()
                        if key
                        in {
                            "userEnteredValue",
                            "userEnteredFormat",
                            "dataValidation",
                            "chipRuns",
                            "textFormatRuns",
                            "note",
                        }
                    }
                    for cell in row.get("values", [])
                ]
                for data in sheet.get("data", [])
                for row in data.get("rowData", [])
            ]
            # O Google pode omitir células finais sem conteúdo nativo.
            # Uma representação esparsa equivale às mesmas células vazias.
            width = sheet["properties"]["gridProperties"]["columnCount"]
            height = min(2, sheet["properties"]["gridProperties"]["rowCount"])
            rows += [[] for _ in range(height - len(rows))]
            return [row + [{} for _ in range(width - len(row))] for row in rows]

        if safe_cells(original) != safe_cells(copied):
            raise ValueError(f"Estrutura nativa divergente em {source.title}.")

        # Metadados nativos usam IDs locais; não dependem do arquivo original.
        def normalize(value):
            if isinstance(value, list):
                return [normalize(item) for item in value]
            if isinstance(value, dict):
                return {
                    key: normalize(item)
                    for key, item in value.items()
                    if key
                    not in {
                        "sheetId",
                        "tableId",
                        "bandedRangeId",
                        "protectedRangeId",
                        "filterViewId",
                        "chartId",
                    }
                }
            return value

        for key in (
            "merges",
            "conditionalFormats",
            "basicFilter",
            "filterViews",
            "protectedRanges",
            "tables",
            "bandedRanges",
            "charts",
        ):
            if normalize(original.get(key)) != normalize(copied.get(key)):
                raise ValueError(f"Metadados {key} divergentes em {source.title}.")

    def plan(self, managed_titles: set[str]) -> list:
        original = self.books[self.layout.dashboard]
        worksheets = original.worksheets()
        config = next((ws for ws in worksheets if ws.title == STORAGE_SHEET), None)
        if config:
            current = SheetsStorage.from_values(
                config.get("A1:B5"), self.layout.dashboard
            )
            if current != self.layout:
                raise ValueError("O arquivo original já aponta para outros destinos.")
        managed_titles = managed_titles | {"Tickets_Delivery_Weni"}
        planned = [
            ws
            for ws in worksheets
            if ws.title in managed_titles and not ws.title.startswith("BI_")
        ]
        if not planned and not config:
            raise ValueError(
                "Nenhuma aba operacional foi encontrada no arquivo original."
            )
        return planned

    def copy_and_verify(self, worksheets: list, *, progress_factory=None) -> None:
        original = self.books[self.layout.dashboard]
        for source in worksheets:
            destination_id = self.layout.destination(source.title)
            destination = self.books[destination_id]
            copies = self.state["copies"]
            entry = copies.get(source.title)
            targets = destination.worksheets()
            if entry is None:
                if any(ws.title == source.title for ws in targets):
                    raise ValueError(
                        f"A aba {source.title} já existe no destino; não será sobrescrita."
                    )
                entry = copies[source.title] = {
                    "source_id": source.id,
                    "destination": destination_id,
                    "rows": source.row_count,
                    "columns": source.col_count,
                    "before_ids": [ws.id for ws in targets],
                }
                self._save()
                copy_context = (
                    progress_factory(
                        f"Migração: copiando {source.title}", 1, unit="abas"
                    )
                    if progress_factory
                    else nullcontext(None)
                )
                try:
                    with copy_context as progress:
                        result = source.copy_to(destination_id)
                        if progress:
                            progress.advance()
                except APIError as exc:
                    if exc.code not in (500, 502, 503, 504):
                        raise
                    candidates = [
                        ws
                        for ws in destination.worksheets()
                        if ws.id not in entry["before_ids"]
                    ]
                    if len(candidates) == 1:
                        result = {"sheetId": candidates[0].id}
                    elif not candidates:
                        entry["native_copy_failed"] = True
                        self._save()
                        copied = copy_native_blocks(
                            self,
                            source,
                            destination,
                            entry,
                            progress_factory=progress_factory,
                        )
                        result = {"sheetId": copied.id}
                    else:
                        raise ValueError(
                            "Cópia integral inconclusiva; os originais foram preservados."
                        ) from exc
                entry["target_id"] = result["sheetId"]
                self._save()
            elif entry.get("block_copy") or (
                entry.get("native_copy_failed") and "target_id" not in entry
            ):
                copy_native_blocks(
                    self, source, destination, entry, progress_factory=progress_factory
                )
            elif "target_id" not in entry:
                candidates = [ws for ws in targets if ws.id not in entry["before_ids"]]
                if len(candidates) != 1:
                    raise ValueError(
                        f"Cópia de {source.title} inconclusiva. Confira o destino antes de retomar."
                    )
                entry["target_id"] = candidates[0].id
                self._save()
            target = destination.get_worksheet_by_id(entry["target_id"])
            if target.title != source.title:
                if any(
                    ws.title == source.title and ws.id != target.id for ws in targets
                ):
                    raise ValueError(f"Há outra aba chamada {source.title} no destino.")
                target.update_title(source.title)
            if (source.row_count, source.col_count) != (
                entry["rows"],
                entry["columns"],
            ) or (target.row_count, target.col_count) != (
                source.row_count,
                source.col_count,
            ):
                raise ValueError(
                    f"As dimensões de {source.title} mudaram. Os originais foram preservados."
                )
            context = (
                progress_factory(
                    f"Migração: conferindo {source.title}",
                    source.row_count * 2,
                    unit="linhas",
                )
                if progress_factory
                else nullcontext(None)
            )
            with context as progress:
                source_hash = self._fingerprint(original, source, progress=progress)
                target_hash = self._fingerprint(destination, target, progress=progress)
            if source_hash != target_hash:
                raise ValueError(
                    f"Conteúdo divergente em {source.title}. Os originais foram preservados."
                )
            self._verify_native(source, target, destination)
            entry["sha256"] = source_hash
            entry["verified"] = True
            self._save()

    def activate(self, worksheets: list) -> None:
        if any(
            not self.state["copies"].get(ws.title, {}).get("verified")
            for ws in worksheets
        ):
            raise ValueError(
                "Todas as cópias precisam ser conferidas antes da ativação."
            )
        original = self.books[self.layout.dashboard]
        existing = {ws.title: ws for ws in original.worksheets()}
        config = existing.get(STORAGE_SHEET)
        if config is None:
            config = original.add_worksheet(title=STORAGE_SHEET, rows=5, cols=2)
        config.update(
            range_name="A1:B5", values=self.layout.values(), value_input_option="RAW"
        )
        if (
            SheetsStorage.from_values(config.get("A1:B5"), self.layout.dashboard)
            != self.layout
        ):
            raise ValueError(
                "A configuração não foi confirmada; os originais foram preservados."
            )
        self.state["active"] = True
        self._save()

    def remove_originals(
        self, worksheets: list, *, routines_stopped: bool, progress_factory=None
    ) -> None:
        if not routines_stopped or not self.state.get("active"):
            raise ValueError(
                "Encerre as rotinas e ative a migração antes de retirar os originais."
            )
        original = self.books[self.layout.dashboard]
        config = next(ws for ws in original.worksheets() if ws.title == STORAGE_SHEET)
        if (
            SheetsStorage.from_values(config.get("A1:B5"), self.layout.dashboard)
            != self.layout
        ):
            raise ValueError("A configuração ativa foi alterada; limpeza interrompida.")
        moving_ids = {ws.id for ws in worksheets}
        metadata = original.fetch_sheet_metadata()
        if any(
            item.get("range", {}).get("sheetId") in moving_ids
            for item in metadata.get("namedRanges", [])
        ):
            raise ValueError(
                "Há intervalos nomeados nas abas originais; revise as dependências antes de removê-las."
            )
        if any(
            sheet["properties"]["sheetId"] not in moving_ids
            and referenced_sheet_ids(sheet.get("charts", [])) & moving_ids
            for sheet in metadata["sheets"]
        ):
            raise ValueError(
                "Um gráfico no dashboard depende de uma aba movida; limpeza interrompida."
            )
        # Fontes BI são valores materializados. Fórmulas que dependem de abas
        # movidas precisam de revisão, não de remoção automática.
        moving_names = {ws.title.casefold() for ws in worksheets}
        remaining_sheets = [
            ws
            for ws in original.worksheets()
            if ws.id not in moving_ids and ws.title != STORAGE_SHEET
        ]
        context = (
            progress_factory(
                "Migração: conferindo dependências do dashboard",
                sum(ws.row_count for ws in remaining_sheets),
                unit="linhas",
            )
            if progress_factory
            else nullcontext(None)
        )
        with context as progress:
            for remaining in remaining_sheets:
                for row_count, rows in self._blocks(original, remaining):
                    if any(
                        isinstance(value, str)
                        and value.startswith("=")
                        and any(
                            f"{name}!" in value.casefold()
                            or f"'{name}'!" in value.casefold()
                            for name in moving_names
                        )
                        for row in rows
                        for value in row
                    ):
                        raise ValueError(
                            f"Fórmula em {remaining.title} depende de uma aba movida; limpeza interrompida."
                        )
                    if progress:
                        progress.advance(row_count)
        # Reconfere origem e destino imediatamente antes de cada retirada.
        for source in worksheets:
            entry = self.state["copies"][source.title]
            source = original.get_worksheet_by_id(entry["source_id"])
            target_book = self.books[entry["destination"]]
            target = target_book.get_worksheet_by_id(entry["target_id"])
            if (
                source.title != target.title
                or (source.row_count, source.col_count)
                != (entry["rows"], entry["columns"])
                or (target.row_count, target.col_count)
                != (entry["rows"], entry["columns"])
            ):
                raise ValueError(
                    f"Dimensões ou nome de {source.title} alterados. Limpeza interrompida."
                )
            context = (
                progress_factory(
                    f"Migração: conferência final de {source.title}",
                    source.row_count * 2,
                    unit="linhas",
                )
                if progress_factory
                else nullcontext(None)
            )
            with context as progress:
                source_hash = self._fingerprint(original, source, progress=progress)
                target_hash = self._fingerprint(target_book, target, progress=progress)
            if (
                not entry.get("verified")
                or source_hash != target_hash
                or source_hash != entry["sha256"]
            ):
                raise ValueError(
                    f"Aba {source.title} alterada desde a conferência. Limpeza interrompida."
                )
            self._verify_native(source, target, target_book)
            original.del_worksheet(source)
            entry["removed"] = True
            self._save()
