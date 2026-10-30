"""Roteamento dos arquivos Google Sheets, sem credenciais."""

from __future__ import annotations

import re
from dataclasses import dataclass

from config import SHEET_HISTORICO

STORAGE_SHEET = "NexoFlow_Arquivos"
STORAGE_HEADERS = ["papel", "planilha_id"]


@dataclass(frozen=True)
class SheetsStorage:
    dashboard: str
    operations: str
    history: str

    def values(self) -> list[list[str]]:
        return [
            STORAGE_HEADERS[:],
            ["formato", "1"],
            ["dashboard", self.dashboard],
            ["operacao", self.operations],
            ["historico", self.history],
        ]

    @classmethod
    def from_values(cls, values: list[list[str]], hub_id: str) -> SheetsStorage:
        if not values or values[0] != STORAGE_HEADERS:
            raise ValueError("Cabeçalho inválido em NexoFlow_Arquivos.")
        entries: dict[str, str] = {}
        for row in values[1:]:
            if not row or not any(row):
                continue
            if (
                len(row) != 2
                or any(not isinstance(value, str) for value in row)
                or row[0] in entries
            ):
                raise ValueError("Configuração de arquivos incompleta ou duplicada.")
            entries[row[0]] = row[1].strip()
        if (
            set(entries) != {"formato", "dashboard", "operacao", "historico"}
            or entries.get("formato") != "1"
        ):
            raise ValueError("Formato inválido em NexoFlow_Arquivos.")
        layout = cls(entries["dashboard"], entries["operacao"], entries["historico"])
        if (
            layout.dashboard != hub_id
            or len({layout.dashboard, layout.operations, layout.history}) != 3
        ):
            raise ValueError(
                "Os três arquivos devem ser diferentes; o dashboard permanece no arquivo original."
            )
        if any(
            not re.fullmatch(r"[A-Za-z0-9_-]+", value)
            for value in (layout.dashboard, layout.operations, layout.history)
        ):
            raise ValueError("Use IDs de planilhas válidos em NexoFlow_Arquivos.")
        return layout

    def destination(self, title: str) -> str:
        if title == SHEET_HISTORICO:
            return self.history
        if title.startswith("BI_"):
            return self.dashboard
        return self.operations


def configured_storage(hub_id: str) -> SheetsStorage | None:
    """IDs explícitos são alternativa ao mapa remoto, nunca destinos inferidos."""
    from project_paths import load_private_settings
    from runtime_profile import validate_sheet_destinations

    settings = load_private_settings()
    operations = str(
        getattr(settings, "GOOGLE_OPERATIONS_SPREADSHEET_ID", "") or ""
    ).strip()
    history = str(getattr(settings, "GOOGLE_HISTORY_SPREADSHEET_ID", "") or "").strip()
    if not operations and not history:
        return None
    if not operations or not history:
        raise ValueError(
            "Preencha os IDs de Operação e Histórico juntos, ou use o mapa NexoFlow_Arquivos."
        )
    configured_hub = str(
        getattr(settings, "GOOGLE_SPREADSHEET_ID", hub_id) or ""
    ).strip()
    if configured_hub != hub_id:
        raise ValueError("O Dashboard informado diverge do perfil selecionado.")
    layout = SheetsStorage.from_values(
        SheetsStorage(hub_id, operations, history).values(), hub_id
    )
    validate_sheet_destinations(layout.dashboard, layout.operations, layout.history)
    return layout
