"""Prévia de expansão BI, sem alterar fatos, grades, trava ou manifesto.

É uma detecção antecipada, não uma autorização de escrita. O publicador
existente continua revalidando capacidade, origem, schema, fonte e trava.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sheets_continuation import (
    ContinuationError,
    Part,
    additional_rows,
    allocated_cells,
    fingerprint,
)
from sheets_partitions import role_for, roots_for


class BIContinuationPending(ContinuationError):
    """Expansão depende de validação e ligação reais da fonte no Data Studio."""


@dataclass(frozen=True)
class Replacement:
    worksheet: Any
    headers: list[str]
    rows: int


def _occupied_rows(store, worksheet, row_count):
    # Ler apenas a chave em blocos limitados. Não baixar novamente todos os
    # valores de centenas de milhares de linhas para contar ocupação.
    last = 1
    for start in range(2, row_count + 1, 10000):
        end = min(start + 9999, row_count)
        values = store._read_with_retry(
            "prévia BI: contar linhas da parte",
            lambda start=start, end=end: worksheet.get(
                f"A{start}:A{end}", value_render_option="UNFORMATTED_VALUE"
            ),
        )
        for offset, row in enumerate(values):
            if row and row[0] not in ("", None):
                last = start + offset
    return last - 1


def check_replacements(store, replacements: Sequence[Replacement]) -> None:
    manager = getattr(store, "_continuity", None)
    if manager is None:
        return

    # Usar o índice carregado somente se ainda for o índice remoto. A prévia
    # não assume uma revisão de outro segmento ou uma configuração alterada.
    def check_index():
        values = store._read_with_retry(
            "prévia BI: conferir manifesto", manager.sheet.get_all_values
        )
        if fingerprint(values) != manager.persisted_hash:
            raise ContinuationError("O manifesto mudou; refaça a prévia BI.")

    check_index()
    metadata: dict[str, Any] = {}
    cells: dict[str, int] = {}
    threshold = manager.index.config["threshold"]
    max_rows = manager.index.config["max_part_rows"]
    confirmed = manager.index.config["connector_tables"]
    pending = []
    for replacement in replacements:
        ws, headers, remaining = (
            replacement.worksheet,
            replacement.headers,
            replacement.rows,
        )
        if remaining < 0:
            raise ValueError("Quantidade de linhas BI inválida.")
        parts = manager.index.table_parts(ws.title)
        if not parts:
            parts = [
                Part(
                    ws.title,
                    0,
                    roots_for(store)[role_for(ws.title)],
                    ws.id,
                    len(headers),
                    fingerprint(headers),
                )
            ]
        for part in parts:
            if part.schema != fingerprint(headers) or part.width != len(headers):
                raise ContinuationError("Schema divergente na prévia BI.")
            book = manager._book(part.book_id)
            if part.book_id not in metadata:
                metadata[part.book_id] = store._read_with_retry(
                    "prévia BI: conferir grade", book.fetch_sheet_metadata
                )
                cells[part.book_id] = allocated_cells(metadata[part.book_id])
            matches = [
                sheet["properties"]
                for sheet in metadata[part.book_id].get("sheets", [])
                if sheet.get("properties", {}).get("sheetId") == part.sheet_id
            ]
            if len(matches) != 1 or matches[0].get("title") != ws.title:
                raise ContinuationError("Parte ausente ou renomeada na prévia BI.")
            grid = matches[0]["gridProperties"]
            rows, columns = grid["rowCount"], grid["columnCount"]
            if columns < len(headers):
                raise ContinuationError("Largura divergente na prévia BI.")
            physical = (
                manager.worksheet(part) if manager.index.table_parts(ws.title) else ws
            )
            actual_header = store._read_with_retry(
                "prévia BI: conferir cabeçalho",
                lambda physical=physical, columns=columns: physical.get(
                    f"A1:{manager.store_column(columns)}1",
                    value_render_option="UNFORMATTED_VALUE",
                ),
            )
            if actual_header != [headers]:
                raise ContinuationError("Cabeçalho divergente na prévia BI.")
            maximum = min(
                rows
                - 1
                + additional_rows(cells[part.book_id], columns, threshold=threshold),
                max_rows - 1,
            )
            if cells[part.book_id] >= threshold:
                # Acima da margem não há expansão na raiz. Tabela já
                # confirmada pode transbordar: não reler suas chaves aqui.
                occupied = (
                    rows - 1
                    if ws.title in confirmed or remaining == 0
                    else _occupied_rows(store, physical, rows)
                )
                maximum = min(maximum, occupied)
            taken = min(remaining, max(0, maximum))
            # Não liberar espaço por uma redução: o gravador conserva a grade.
            cells[part.book_id] += max(0, taken + 1 - rows) * columns
            remaining -= taken
        if (
            remaining
            and role_for(ws.title) == "dashboard"
            and ws.title not in confirmed
        ):
            pending.append((ws.title, replacement.rows, remaining))
        # Partes novas são criadas em arquivos próprios. Não consomem espaço
        # adicional das raízes; o provisionador real mantém suas verificações.
    check_index()
    if pending:
        detail = "; ".join(
            f"{title}: {rows} linhas previstas, {overflow} exigem continuação"
            for title, rows, overflow in pending
        )
        raise BIContinuationPending(
            "BI_FONTE_NAO_CONFIRMADA — " + detail + ". "
            "Prévia interrompida antes das substituições BI deste grupo. "
            "O Work deve validar e ligar a fonte ao conector no Data Studio; "
            "só depois o operador confirma as tabelas validadas com "
            "nexo armazenamento ativar-data-studio --abas <tabelas> --confirmar-fontes. "
            "Não confirme fontes para contornar este bloqueio."
        )


def looker_replacements(store, tables) -> list[Replacement]:
    from looker_bi import SCHEMAS

    if set(tables) != set(SCHEMAS):
        raise ValueError("Conjunto de tabelas comerciais BI incompleto.")
    return [
        Replacement(getattr(store, "looker_" + title), headers, len(tables[title]))
        for title, headers in SCHEMAS.items()
    ]
