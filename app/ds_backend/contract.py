"""Contrato fechado de armazenamento; não importa Google nem lê credenciais."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

PROTOCOL = "nexoflow_datastudio_1"
REGISTRY = json.loads(
    Path(__file__).with_name("registry.json").read_text(encoding="utf-8")
)
DATABASES = {
    "producao": "nexoflow_datastudio",
    "homologacao": "nexoflow_datastudio_homologacao",
}
MAX_ROWS = 1000
MAX_BYTES = 7_000_000


class StorageError(ValueError):
    """Código sanitizado; nunca contém resposta/linha/URL externa."""


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()
    ).hexdigest()


SCHEMA_HASH = digest(REGISTRY)


def identifier(value):
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise StorageError("DS_IDENTIFICADOR_INVALIDO") from None


def target(environment, segment):
    if environment not in DATABASES or segment not in ("FARMA", "PET"):
        raise StorageError("DS_DESTINO_INVALIDO")
    return f"{DATABASES[environment]}.{segment.lower()}"


def table_contract(name):
    if not isinstance(name, str) or name not in REGISTRY:
        raise StorageError("DS_TABELA_NAO_AUTORIZADA")
    return REGISTRY[name]


def normalize(name, rows, segment):
    spec = table_contract(name)
    if not isinstance(rows, list) or len(rows) > MAX_ROWS:
        raise StorageError("DS_LIMITE_LOTE")
    output = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != set(spec["columns"]):
            raise StorageError("DS_SCHEMA_DIVERGENTE")
        result = {}
        for field in spec["columns"]:
            value = row[field]
            if value is None:
                value = ""
            if (
                isinstance(value, (dict, list, bool))
                or isinstance(value, float)
                and not math.isfinite(value)
            ):
                raise StorageError("DS_TIPO_INVALIDO")
            kind = spec["types"][field]
            if value != "" and kind == "number":
                try:
                    number = Decimal(str(value))
                    if not number.is_finite() or abs(number) > Decimal("1e25"):
                        raise ValueError
                    value = format(number, "f")
                except (InvalidOperation, ValueError):
                    raise StorageError("DS_NUMERO_INVALIDO") from None
            elif value != "" and kind == "date":
                try:
                    if isinstance(value, (int, float)):
                        value = (
                            date(1899, 12, 30) + timedelta(days=int(value))
                        ).isoformat()
                    elif len(str(value)) > 10:
                        parsed = datetime.fromisoformat(
                            str(value).replace("Z", "+00:00")
                        )
                        value = (
                            (
                                parsed.astimezone(ZoneInfo("America/Belem"))
                                if parsed.tzinfo
                                else parsed
                            )
                            .date()
                            .isoformat()
                        )
                    else:
                        value = date.fromisoformat(str(value)).isoformat()
                except (ValueError, TypeError, OverflowError):
                    raise StorageError("DS_DATA_INVALIDA") from None
            value = str(value)
            try:
                value.encode("utf-8")
            except UnicodeEncodeError:
                raise StorageError("DS_CELULA_INVALIDA") from None
            if "\x00" in value or len(value) > 200_000:
                raise StorageError("DS_CELULA_INVALIDA")
            result[field] = value
        if (
            name.startswith("Cache_")
            and "segment" in result
            and result["segment"] != segment
        ):
            raise StorageError("DS_SEGMENTO_DIVERGENTE")
        if "segmento" in result and result["segmento"] not in (
            segment,
            "COMPARTILHADO",
            "NAO_CLASSIFICADO",
        ):
            raise StorageError("DS_SEGMENTO_DIVERGENTE")
        # Origens compartilhadas Meta não recebem autorização para destinos de outra marca.
        if (
            "segmento" in result
            and result["segmento"] not in (segment,)
            and not name.startswith(("Meta_", "BI_Meta_"))
        ):
            raise StorageError("DS_SEGMENTO_DIVERGENTE")
        if not any(result[k] for k in spec["keys"]):
            raise StorageError("DS_CHAVE_AUSENTE")
        if name in ("Historico_Pedidos", "Historico_Itens", "BI_LTV_Clientes"):
            expected = (
                segment
                + ":"
                + (
                    result["cliente_id"]
                    if name == "BI_LTV_Clientes"
                    else result["pedido_id"]
                )
            )
            if name == "Historico_Itens":
                expected += ":" + result["item_id"]
            if result["chave"] != expected:
                raise StorageError("DS_CHAVE_OFICIAL_DIVERGENTE")
        if name == "Historico_Pedidos" and result["estado"] == "valido":
            if not result["cliente_id"] or not result["data"]:
                raise StorageError("DS_COMPRA_VALIDA_SEM_IDENTIDADE_OU_DATA")
            money = [
                Decimal(result[f]) if result[f] else Decimal("-1")
                for f in ("produtos", "frete", "faturamento")
            ]
            if (
                any(v < 0 or v != v.quantize(Decimal("0.01")) for v in money)
                or money[0] + money[1] != money[2]
            ):
                raise StorageError("DS_BASE_FINANCEIRA_DIVERGENTE")
        if name == "Historico_Itens" and result["frete"] not in ("Sim", "Não"):
            raise StorageError("DS_FRETE_ITEM_INVALIDO")
        output.append(result)
    return output


def record_key(name, record):
    return digest([record[k] for k in table_contract(name)["keys"]])
