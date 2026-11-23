"""Contrato de leitura do inventário e da telemetria da VPS."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, Field, IPvAnyAddress, ValidationError

MAX_SNAPSHOT_BYTES = 128 * 1024
SNAPSHOT_NAME = "vps.json"
Capacity = Annotated[int, Field(ge=0, le=2**53 - 1)]
Sample = tuple[AwareDatetime, Annotated[float, Field(ge=0, allow_inf_nan=False)]]
Series = Annotated[list[Sample], Field(max_length=192)]


class ProviderMetrics(BaseModel):
    cpu: Series
    ram: Series
    disco: Series
    entrada: Series
    saida: Series
    uptime: Series


class Infrastructure(BaseModel):
    coletado_em: AwareDatetime
    hostname: Annotated[str, Field(pattern=r"^[a-zA-Z0-9.-]{1,253}$")]
    sistema: str | None = Field(max_length=120)
    estado: Literal["running", "stopped", "starting", "stopping", "unknown"]
    cidade: str | None = Field(max_length=120)
    pais: str | None = Field(pattern=r"^[A-Z]{2}$")
    ipv4: IPvAnyAddress | None
    plano: str | None = Field(max_length=80)
    nucleos: Capacity | None
    ram_bytes: Capacity | None
    disco_bytes: Capacity | None
    banda_bytes: Capacity | None
    validade: AwareDatetime | None
    renovacao_automatica: bool | None
    ultimo_backup_provedor: AwareDatetime | None
    metricas: ProviderMetrics | None


def read_infrastructure(path: Path | None):
    if path is None:
        return {"estado": "aguardando_coleta", "vps": None}
    try:
        with path.open("rb") as snapshot:
            raw = snapshot.read(MAX_SNAPSHOT_BYTES + 1)
        if len(raw) > MAX_SNAPSHOT_BYTES:
            raise ValueError
        vps = Infrastructure.model_validate_json(raw)
        now = datetime.now(UTC)
        if vps.coletado_em > now + timedelta(minutes=2):
            raise ValueError
    except FileNotFoundError:
        return {"estado": "aguardando_coleta", "vps": None}
    except (OSError, ValidationError, ValueError):
        return {"estado": "indisponivel", "vps": None}
    return {
        "estado": "desatualizado"
        if now - vps.coletado_em > timedelta(minutes=20)
        else "disponivel",
        "vps": vps,
    }
