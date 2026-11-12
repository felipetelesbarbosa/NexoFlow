"""Contrato fechado de publicação BI_Itens FARMA, sem credenciais ou I/O."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from looker_bi import SCHEMAS

TARGET = "nexoflow_datastudio_piloto.farma.bi_itens"
COLUMNS = tuple(SCHEMAS["BI_Itens"])
BUSINESS_COLUMNS = COLUMNS[:-1]
PROTOCOL = "bi_itens_farma_1"
MAX_ROWS = 20_000
MAX_SALES = 2_000


class PublicationError(ValueError):
    """Erro público deliberadamente sem valores ou exceção de transporte."""


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def identifier(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{32}", value):
        raise PublicationError("BI_PG_IDENTIDADE_INVALIDA")
    return value


def uid(value: Any) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise PublicationError("BI_PG_LOTE_INVALIDO") from None


def normalize_rows(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list) or len(rows) > MAX_ROWS:
        raise PublicationError("BI_PG_LIMITE_DE_LOTE")
    result, keys = [], set()
    for raw in rows:
        if not isinstance(raw, (list, tuple)) or len(raw) != len(COLUMNS):
            raise PublicationError("BI_PG_SCHEMA_INVALIDO")
        row = dict(zip(COLUMNS, raw, strict=True))
        for key in ("item_chave", "venda_chave", "cliente_chave"):
            identifier(row[key])
        if row["item_chave"] in keys:
            raise PublicationError("BI_PG_CHAVE_DUPLICADA")
        keys.add(row["item_chave"])
        try:
            if (
                not isinstance(row["data"], str)
                or date.fromisoformat(row["data"]).isoformat() != row["data"]
            ):
                raise ValueError
            stamp = datetime.fromisoformat(row["atualizado_em"].replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise PublicationError("BI_PG_DATA_INVALIDA") from None
        for name in ("produto_codigo", "produto_nome", "categoria"):
            if (
                not isinstance(row[name], str)
                or len(row[name]) > 4096
                or "\x00" in row[name]
            ):
                raise PublicationError("BI_PG_TEXTO_INVALIDO")
        for name in ("quantidade", "valor_unitario", "receita_item"):
            try:
                if isinstance(row[name], bool):
                    raise ValueError
                number = Decimal(str(row[name]))
                if (
                    not number.is_finite()
                    or number < 0
                    or number > Decimal("99999999999999")
                ):
                    raise ValueError
                if name == "quantidade":
                    if number <= 0:
                        raise ValueError
                elif number != number.quantize(Decimal("0.01")):
                    raise ValueError
                row[name] = format(
                    number.quantize(Decimal("0.01"))
                    if name != "quantidade"
                    else number.normalize(),
                    "f",
                )
            except (InvalidOperation, ValueError):
                raise PublicationError("BI_PG_NUMERO_INVALIDO") from None
        if type(row["sku_informado"]) is not int or row["sku_informado"] != int(
            bool(row["produto_codigo"])
        ):
            raise PublicationError("BI_PG_SKU_INVALIDO")
        result.append(row)
    return result


def validate_payload(payload: Any) -> dict:
    if not isinstance(payload, dict) or set(payload) != {
        "protocol",
        "target",
        "segment",
        "batch_id",
        "session_id",
        "complete",
        "sales",
        "rows",
    }:
        raise PublicationError("BI_PG_CONTRATO_INVALIDO")
    if (payload["protocol"], payload["target"], payload["segment"]) != (
        PROTOCOL,
        TARGET,
        "FARMA",
    ):
        raise PublicationError("BI_PG_DESTINO_DIVERGENTE")
    if (
        type(payload["complete"]) is not bool
        or not isinstance(payload["sales"], list)
        or len(payload["sales"]) > MAX_SALES
    ):
        raise PublicationError("BI_PG_ESCOPO_INVALIDO")
    sales = [identifier(v) for v in payload["sales"]]
    if len(set(sales)) != len(sales):
        raise PublicationError("BI_PG_ESCOPO_DUPLICADO")
    rows = normalize_rows(payload["rows"])
    if any(r["venda_chave"] not in sales for r in rows):
        raise PublicationError("BI_PG_ITEM_FORA_ESCOPO")
    return {
        **payload,
        "batch_id": uid(payload["batch_id"]),
        "session_id": uid(payload["session_id"]),
        "sales": sorted(sales),
        "rows": sorted(rows, key=lambda r: r["item_chave"]),
    }
