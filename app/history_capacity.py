"""Plano puro de grades e intervalos: nenhuma chamada ou criação no Google."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, NotRequired, TypedDict

from order_history import HistoryError
from sheets_continuation import CELL_LIMIT
from sheets_storage import storage_role


class PlannedPart(TypedDict):
    title: str
    number: int
    book: str
    sheet: NotRequired[int]
    width: int
    cols: NotRequired[int]
    allocated_rows: int
    used_rows: int
    create: NotRequired[bool]
    confirmed_rows: NotRequired[int | None]


def allocate(
    schemas, additions, parts: list[PlannedPart], books, roots, *, threshold, max_rows
) -> dict[str, Any]:
    """Compartilha a reserva por arquivo entre TODAS as tabelas do plano.

    ``parts`` inclui cabeçalho em allocated_rows/used_rows. Nenhuma grade é
    reduzida; espaços já alocados podem ser usados sem expansão da grade.
    Arquivos virtuais são dedicados a uma parte e criados somente no apply.
    """
    if not 100 <= threshold < CELL_LIMIT or max_rows < 2:
        raise HistoryError("CAPACIDADE_CONFIG_INVALIDA")
    grids: dict[str, int] = deepcopy(books)
    if any(type(v) is not int or v < 0 or v > CELL_LIMIT for v in grids.values()):
        raise HistoryError("GRADE_FISICA_INVALIDA")
    result: list[PlannedPart] = deepcopy(parts)
    ranges: dict[str, list[dict[str, Any]]] = {}
    creations: list[PlannedPart] = []
    for title, headers in schemas.items():
        width = len(headers)
        remaining = additions.get(title, 0)
        if type(remaining) is not int or remaining < 0:
            raise HistoryError("CONTAGEM_INVALIDA")
        selected = sorted(
            (p for p in result if p["title"] == title), key=lambda p: p["number"]
        )
        if [p["number"] for p in selected] != list(range(len(selected))):
            raise HistoryError("SEQUENCIA_DE_PARTES_INVALIDA")
        for p in selected:
            if p["width"] != width or not 1 <= p["used_rows"] <= p["allocated_rows"]:
                raise HistoryError("PARTE_INVALIDA")
        ranges[title] = []
        while remaining or not selected:
            part = selected[-1] if selected else None
            available = 0
            if part is not None:
                grid = grids[part["book"]]
                padding = max(0, part["allocated_rows"] - part["used_rows"])
                expansion = max(
                    0, (threshold - grid) // part.get("cols", part["width"])
                )
                available = max(
                    0, min(padding + expansion, max_rows - part["used_rows"])
                )
            if part is None or not available:
                number = len(selected)
                root = roots[storage_role(title)]
                # A primeira parte pode adotar uma aba ainda ausente na origem.
                new_book = number != 0 or grids[root] + width > threshold
                book = f"new:{title}#{number}" if new_book else root
                if new_book:
                    grids[book] = 0
                grids[book] += width
                part = PlannedPart(
                    title=title,
                    number=number,
                    book=book,
                    width=width,
                    allocated_rows=1,
                    used_rows=1,
                    create=True,
                )
                selected.append(part)
                result.append(part)
                creations.append(deepcopy(part))
                available = min(
                    max_rows - 1, max(0, (threshold - grids[book]) // width)
                )
                if remaining and available == 0:
                    raise HistoryError("CAPACIDADE_INSUFICIENTE_PARA_LINHA")
                if not remaining:
                    break
            take = min(available, remaining)
            ranges[title].append(
                dict(
                    part=part["number"],
                    book=part["book"],
                    start=part["used_rows"] + 1,
                    rows=take,
                )
            )
            end = part["used_rows"] + take
            growth = max(0, end - part["allocated_rows"])
            grids[part["book"]] += growth * part.get("cols", width)
            part["allocated_rows"] += growth
            part["used_rows"] = end
            remaining -= take
    return dict(
        parts=result,
        ranges=ranges,
        creations=creations,
        books=[
            dict(
                book=b,
                before=books.get(b, 0),
                after=n,
                remaining_hard=CELL_LIMIT - n,
                remaining_operational=max(0, threshold - n),
            )
            for b, n in grids.items()
        ],
    )
