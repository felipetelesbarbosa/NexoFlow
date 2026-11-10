"""Leitura agrupada sem cache: mantém contrato e proteções do publicador."""

from history_sheets_transport import SheetsTransport
from order_history import HistoryError
from order_history_sheets import HistorySheets, normalized_cells


class BulkTransport(SheetsTransport):
    def read_rows(self, part, headers, positions):
        self.manager.require()
        self._physical(part)
        geometry = self.geometry(part)
        if geometry["columns"] != part["cols"]:
            raise HistoryError("COLUNAS_ALTERADAS_APOS_REVISAO")
        if any(type(r) is not int or r < 2 for r in positions):
            raise HistoryError("POSICAO_DE_LOTE_INVALIDA")
        # Coordenadas futuras não existem ainda. Ler A2 numa aba de uma linha
        # gera HTTP 400 antes de reservar o lote. Não ampliar a grade para ler:
        # isso seria uma escrita anterior ao backup/intenção durável.
        # A grade é relida, não a do plano: expansão externa pode conter dados.
        existing = sorted({r for r in positions if r <= geometry["rows"]})
        spans = []
        for row in existing:
            if spans and row == spans[-1][1] + 1:
                spans[-1] = (spans[-1][0], row)
            else:
                spans.append((row, row))
        # Cabeçalho completo e células do lote são relidos juntos, sem cache.
        # O nome é escapado como literal A1, inclusive apóstrofos.
        title = part["title"].replace("'", "''")
        ranges = [f"'{title}'!A1:{self.manager.store_column(geometry['columns'])}1"] + [
            f"'{title}'!A{first}:{self.manager.store_column(len(headers))}{last}"
            for first, last in spans
        ]
        result = self.store._read_with_retry(
            "conferir intervalos do lote",
            lambda: self.manager._book(part["book"]).values_batch_get(
                ranges, params={"valueRenderOption": "FORMULA"}
            ),
        )
        groups = result.get("valueRanges", [])
        if len(groups) != len(spans) + 1:
            raise HistoryError("RESPOSTA_DE_INTERVALOS_INCOMPLETA")
        raw_header = groups.pop(0).get("values", [])
        if len(raw_header) > 1:
            raise HistoryError("CABECALHO_ALTERADO_APOS_REVISAO")
        actual = list(raw_header[0]) if raw_header else []
        while actual and actual[-1] in ("", None):
            actual.pop()
        if actual != headers:
            raise HistoryError("CABECALHO_ALTERADO_APOS_REVISAO")
        by_position = {}
        for (first, last), group in zip(spans, groups, strict=True):
            values = group.get("values", [])
            if len(values) > last - first + 1:
                raise HistoryError("INTERVALO_DIVERGENTE")
            # Sheets omite linhas vazias finais; manter suas posições sem
            # confundir omissão permitida com resposta de intervalo ausente.
            for offset, position in enumerate(range(first, last + 1)):
                cells = values[offset] if offset < len(values) else []
                if len(cells) > len(headers):
                    raise HistoryError("INTERVALO_DIVERGENTE")
                by_position[position] = (
                    normalized_cells(
                        dict(
                            zip(
                                headers,
                                cells + [""] * (len(headers) - len(cells)),
                                strict=True,
                            )
                        )
                    )
                    if any(v not in ("", None) for v in cells)
                    else None
                )
        return [by_position.get(r) for r in positions]


class BulkHistorySheets(HistorySheets):
    def __init__(self, store, segment, backup_dir):
        remote = store if hasattr(store, "describe") else BulkTransport(store)
        super().__init__(remote, segment, backup_dir)


def batch_budget(review, percent, maximum):
    """Fração por execução sobre o total original; o motor limita ao saldo."""
    if percent is None:
        return maximum
    if type(percent) is not int or percent not in (25, 50, 75, 100):
        raise HistoryError("PERCENTUAL_INVALIDO")
    if maximum is not None:
        raise HistoryError("PERCENTUAL_NAO_COMBINA_MAX_LOTES")
    total = review.get("batches")
    if type(total) is not int or total < 0:
        raise HistoryError("TOTAL_LOTES_INVALIDO")
    # 100% significa todo o saldo; ceil evita truncar uma fração pequena.
    return None if percent == 100 else max(1, (total * percent + 99) // 100)
