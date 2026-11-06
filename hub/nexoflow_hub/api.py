"""API interna autenticada, somente tarefas sintéticas de homologação."""

from __future__ import annotations

import secrets
from typing import Literal
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .config import Settings
from .store import Conflict, Store


class TaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    segmento: Literal["FARMA", "PET"]
    origem: Literal["manual", "n8n", "teste"] = "manual"
    chave: str = Field(min_length=1, max_length=96, pattern=r"^[a-zA-Z0-9_-]+$")
    cenario: Literal[
        "normal",
        "dados_incompletos",
        "sem_pedido",
        "segmento_desconhecido",
        "segmento_divergente",
        "cancelado",
        "pagamento_cancelado",
        "itens_vazios",
        "frete_divergente",
        "identidade_divergente",
        "recusa",
        "optout",
        "compra_recente",
        "retroativo",
        "rede_temporaria",
        "autenticacao",
        "resposta_incerta",
    ] = "normal"


def public(task):
    return {
        key: task[key]
        for key in (
            "id",
            "segmento",
            "origem",
            "estado",
            "criada_em",
            "atualizada_em",
            "tentativa",
            "erro",
            "resultado",
        )
    }


def create_app(settings: Settings | None = None):
    settings = settings or Settings.load()
    store = Store(settings)
    app = FastAPI(
        title="NexoFlow Hub — Homologação",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    def scope(authorization: str = Header(default="")):
        if not authorization.startswith("Bearer "):
            raise HTTPException(401, "AUTENTICACAO_OBRIGATORIA")
        supplied = authorization[7:]
        for segment, token in settings.tokens.items():
            if secrets.compare_digest(supplied.encode(), token.encode()):
                return segment
        raise HTTPException(401, "AUTENTICACAO_INVALIDA")

    dependency = Depends(scope)

    @app.middleware("http")
    async def bounded_body(request: Request, call_next):
        if request.method == "POST":
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 4096:
                    return JSONResponse({"erro": "CORPO_EXCESSIVO"}, status_code=413)
            request._body = bytes(body)
        try:
            return await call_next(request)
        except Exception:
            return JSONResponse({"erro": "SERVICO_INDISPONIVEL"}, status_code=503)

    @app.exception_handler(RequestValidationError)
    async def invalid(_request, _error):
        return JSONResponse({"erro": "REQUISICAO_INVALIDA"}, status_code=422)

    @app.get("/saude")
    def health():
        return {"estado": "ativo", "ambiente": "homologacao", "escrita_real": False}

    @app.get("/prontidao")
    def ready(_segment=dependency):
        if not store.ready():
            raise HTTPException(503, "SCHEMA_INDISPONIVEL")
        return {"estado": "pronto"}

    @app.post("/tarefas", status_code=202)
    def create(body: TaskRequest, segment=dependency):
        if body.segmento != segment:
            raise HTTPException(403, "SEGMENTO_NAO_AUTORIZADO")
        try:
            return public(store.create(segment, body.origem, body.chave, body.cenario))
        except Conflict:
            raise HTTPException(409, "IDEMPOTENCIA_CONFLITANTE") from None

    @app.get("/tarefas")
    def list_tasks(segment=dependency):
        return [public(t) for t in store.list(segment)]

    def lookup(uid, segment):
        task = store.get(segment, uid)
        if task is None:
            raise HTTPException(404, "TAREFA_NAO_ENCONTRADA")
        return task

    @app.get("/tarefas/{uid}")
    def get(uid: UUID, segment=dependency):
        return public(lookup(uid, segment))

    @app.get("/tarefas/{uid}/resultado")
    def result(uid: UUID, segment=dependency):
        task = lookup(uid, segment)
        return {
            "id": task["id"],
            "segmento": segment,
            "estado": task["estado"],
            "resultado": task["resultado"],
        }

    @app.get("/tarefas/{uid}/erros")
    def errors(uid: UUID, segment=dependency):
        task = lookup(uid, segment)
        return {"id": task["id"], "segmento": segment, "erro": task["erro"]}

    return app
