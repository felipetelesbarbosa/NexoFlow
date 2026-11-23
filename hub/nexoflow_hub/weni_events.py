"""Recebe um evento técnico do fluxo FARMA em homologação."""

from __future__ import annotations

import secrets
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .store import Conflict, Store


class FlowEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    evento_id: Annotated[
        str, Field(pattern=r"^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")
    ]
    tipo: Literal["atendimento_transferido"]
    ocorrido_em: Annotated[
        str,
        Field(
            pattern=r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$"
        ),
    ]

    @field_validator("ocorrido_em")
    @classmethod
    def validate_time(cls, stamp: str) -> str:
        datetime.fromisoformat(stamp)
        return stamp


def receive_event(store: Store, event: FlowEvent):
    event_id = UUID(event.evento_id)
    occurred = datetime.fromisoformat(event.ocorrido_em)
    with store.connect() as db:
        row = db.execute(
            """INSERT INTO hub.eventos_weni (segmento, evento_id, tipo, ocorrido_em)
               VALUES ('FARMA', %s, %s, %s)
               ON CONFLICT (segmento, evento_id) DO NOTHING
               RETURNING tipo, ocorrido_em, recibo, recebido_em""",
            (event_id, event.tipo, occurred),
        ).fetchone()
        if row is None:
            row = db.execute(
                """SELECT tipo, ocorrido_em, recibo, recebido_em FROM hub.eventos_weni
                   WHERE segmento = 'FARMA' AND evento_id = %s""",
                (event_id,),
            ).fetchone()
            if row is None:
                raise RuntimeError("RECIBO_INDISPONIVEL")
            if row["tipo"] != event.tipo or row["ocorrido_em"] != occurred:
                raise Conflict("EVENTO_CONFLITANTE")
    return {
        "estado": "CONFIRMADO",
        "recibo": row["recibo"],
        "recebido_em": row["recebido_em"],
    }


def register_webhook(app: FastAPI, store: Store, token: str):
    @app.post("/v1/webhooks/weni/farma")
    def accept(
        body: FlowEvent, request: Request, authorization: str = Header(default="")
    ):
        if not secrets.compare_digest(
            authorization.encode(), ("Bearer " + token).encode()
        ):
            raise HTTPException(401, "AUTENTICACAO_INVALIDA")
        request.state.api_body = {"tipo": body.tipo}
        try:
            return receive_event(store, body)
        except Conflict:
            raise HTTPException(409, "EVENTO_CONFLITANTE") from None
