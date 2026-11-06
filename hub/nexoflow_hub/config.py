"""Configuração explícita, sem reutilizar credenciais do Windows."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from psycopg import ProgrammingError
from psycopg.conninfo import conninfo_to_dict


@dataclass(frozen=True)
class Settings:
    dsn: str = field(repr=False)
    tokens: dict[str, str] = field(repr=False)
    lease_seconds: int = 30
    max_attempts: int = 3

    def __post_init__(self):
        try:
            info = conninfo_to_dict(self.dsn)
        except ProgrammingError:
            raise ValueError("DSN_INVALIDO") from None
        if not re.fullmatch(
            r"nexoflow_hub_hml(?:_[a-z0-9]+)?", str(info.get("dbname", ""))
        ):
            raise ValueError("BANCO_HOMOLOGACAO_OBRIGATORIO")
        if set(self.tokens) != {"FARMA", "PET"} or any(
            len(v) < 32 for v in self.tokens.values()
        ):
            raise ValueError("CHAVES_DE_SEGMENTO_OBRIGATORIAS")
        if self.tokens["FARMA"] == self.tokens["PET"]:
            raise ValueError("CHAVES_DEVEM_SER_DISTINTAS")
        if not 5 <= self.lease_seconds <= 300 or not 1 <= self.max_attempts <= 10:
            raise ValueError("LIMITES_INVALIDOS")

    @classmethod
    def load(cls):
        if (
            os.environ.get("HUB_AMBIENTE", "homologacao") != "homologacao"
            or os.environ.get("HUB_ESCRITA_REAL", "false").lower() != "false"
        ):
            raise ValueError("OPERACAO_REAL_BLOQUEADA")
        return cls(
            Path(os.environ["HUB_DSN_FILE"]).read_text().strip(),
            {
                s: Path(os.environ[f"HUB_{s}_TOKEN_FILE"]).read_text().strip()
                for s in ("FARMA", "PET")
            },
        )
