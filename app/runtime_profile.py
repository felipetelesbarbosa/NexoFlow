"""Seleção de segmento por processo, antes de carregar clientes e caminhos."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace


def segment() -> str:
    value = os.environ.get("NEXOFLOW_PERFIL", "FARMA").strip().upper()
    if value not in {"FARMA", "PET"}:
        raise ValueError("NEXOFLOW_PERFIL deve ser FARMA ou PET.")
    return value


def scoped_path(path: str | Path) -> Path:
    value = Path(path)
    parts = list(value.parts)
    if (
        segment() == "PET"
        and not value.is_absolute()
        and parts
        and parts[0] in {"logs", "importacoes"}
    ):
        if len(parts) < 2 or parts[1] != "PET":
            return Path(parts[0], "PET", *parts[1:])
    return value


def select_settings(settings):
    if segment() == "FARMA":
        profiles = getattr(settings, "PERFIS", {})
        if not isinstance(profiles, dict) or "FARMA" not in profiles:
            return settings
        overrides = profiles["FARMA"]
    else:
        profiles = getattr(settings, "PERFIS", {})
        if not isinstance(profiles, dict) or not isinstance(profiles.get("PET"), dict):
            raise ValueError(
                'Configure PERFIS["PET"]; credenciais Farma não serão reutilizadas.'
            )
        overrides = profiles["PET"]
        for key in ("WENI_API_TOKEN", "FARMALIDER_API_TOKEN", "GOOGLE_SPREADSHEET_ID"):
            if not str(overrides.get(key) or "").strip():
                raise ValueError("Configuração PET ausente: " + key)
        if any(
            overrides.get(k) == profiles.get("FARMA", {}).get(k)
            for k in ("WENI_API_TOKEN", "GOOGLE_SPREADSHEET_ID")
        ):
            raise ValueError(
                "Weni e Dashboard precisam ser exclusivos de cada segmento."
            )
    if (
        not isinstance(overrides, dict)
        or overrides.get("SEGMENTO", segment()) != segment()
    ):
        raise ValueError("Perfil de configuração divergente.")
    values = dict(vars(settings))
    if segment() == "PET":
        for key in (
            "WENI_CHATS_API_TOKEN",
            "WENI_CHATS_API_BASE_URL",
            "WENI_CHATS_ORDER_ID_FIELD",
        ):
            values[key] = ""
    values.update(overrides)
    return SimpleNamespace(**values)


def last_purchase_field() -> str:
    return "compra_recente" if segment() == "PET" else "ultima_compra"


def recompra_group() -> str:
    return "Recompra Pets Líder" if segment() == "PET" else "Recompra FarmaLíder"


def recompra_days() -> int:
    return 30 if segment() == "PET" else 25


def validate_sheet_destinations(dashboard: str, operations: str, history: str) -> None:
    if segment() != "PET":
        return
    from project_paths import load_private_settings

    settings = load_private_settings()
    expected = tuple(
        str(getattr(settings, key, "") or "")
        for key in (
            "GOOGLE_SPREADSHEET_ID",
            "GOOGLE_OPERATIONS_SPREADSHEET_ID",
            "GOOGLE_HISTORY_SPREADSHEET_ID",
        )
    )
    if not all(expected) or expected != (dashboard, operations, history):
        raise ValueError(
            "Destinos PET divergentes. Configure os três IDs do perfil PET e confira NexoFlow_Arquivos."
        )
    if len(set(expected)) != 3:
        raise ValueError(
            "Dashboard, Operação e Histórico PET precisam ser arquivos diferentes."
        )
    farma = getattr(settings, "PERFIS", {}).get("FARMA", {})
    forbidden = {
        str(farma.get(key) or "")
        for key in (
            "GOOGLE_SPREADSHEET_ID",
            "GOOGLE_OPERATIONS_SPREADSHEET_ID",
            "GOOGLE_HISTORY_SPREADSHEET_ID",
        )
    }
    if "" in forbidden:
        raise ValueError(
            "Preencha também os três IDs FARMA para validar a separação dos destinos."
        )
    if set(expected) & forbidden:
        raise ValueError(
            "Um destino PET pertence ao perfil FARMA; nenhuma gravação autorizada."
        )
