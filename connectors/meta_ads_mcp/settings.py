"""Configuração local. Credenciais nunca ficam no Git nem são impressas."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
CREDENTIALS_FILE = ROOT_DIR / "credentials" / "mcp" / "meta_ads_credentials.json"
_VERSION = re.compile(r"^v[0-9]+\.[0-9]+$")
_DIGITS = re.compile(r"^[0-9]{5,25}$")


class SettingsError(ValueError):
    """Configuração inválida, sem revelar credenciais."""


def account_number(value: str) -> str:
    """Padroniza um ID de conta, mas nunca amplia a lista autorizada."""
    value = str(value).strip()
    if value.startswith("act_"):
        value = value[4:]
    if not _DIGITS.fullmatch(value):
        raise SettingsError("ID de conta de anúncios inválido.")
    return value


@dataclass(frozen=True)
class MetaSettings:
    token: str = field(repr=False)
    api_version: str
    allowed_account_ids: tuple[str, ...]

    def __post_init__(self):
        if (
            not isinstance(self.token, str)
            or not self.token.strip()
            or "COLE_" in self.token
        ):
            raise SettingsError("Token Meta não configurado.")
        if any(c in self.token for c in "\r\n"):
            raise SettingsError("Formato de token Meta inválido.")
        if not isinstance(self.api_version, str) or not _VERSION.fullmatch(
            self.api_version
        ):
            raise SettingsError("Versão da API Meta inválida.")
        if (
            not isinstance(self.allowed_account_ids, tuple)
            or not self.allowed_account_ids
        ):
            raise SettingsError("Allowlist Meta obrigatória.")
        if any(
            not isinstance(a, str) or account_number(a) != a
            for a in self.allowed_account_ids
        ):
            raise SettingsError("IDs da allowlist devem estar normalizados.")


def load_settings(path: Path | None = None) -> MetaSettings:
    target = path or CREDENTIALS_FILE
    if not target.is_file():
        raise SettingsError(
            "Credenciais Meta ausentes em credentials/mcp/meta_ads_credentials.json. "
            "Copie o modelo de configuracao e edite o arquivo local."
        )
    try:
        data = json.loads(target.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise SettingsError(
            "Arquivo de credenciais Meta ilegível ou JSON inválido."
        ) from None
    if not isinstance(data, dict):
        raise SettingsError("Configuração Meta deve ser um objeto JSON.")
    token = data.get("access_token")
    if not isinstance(token, str) or not token.strip() or "COLE_" in token:
        raise SettingsError("Token Meta não configurado.")
    version = data.get("api_version", "v26.0")
    if not isinstance(version, str) or not _VERSION.fullmatch(version):
        raise SettingsError("Versão da API Meta inválida.")
    raw = data.get("allowed_ad_account_ids")
    if not isinstance(raw, list) or not raw or not all(isinstance(a, str) for a in raw):
        raise SettingsError(
            "Informe ao menos uma conta na lista allowed_ad_account_ids."
        )
    ids = tuple(dict.fromkeys(account_number(a) for a in raw))
    return MetaSettings(
        token=token.strip(), api_version=version, allowed_account_ids=ids
    )
