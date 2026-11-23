"""API interna autenticada, somente tarefas sintéticas de homologação."""

from __future__ import annotations

from time import monotonic
from typing import Literal
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.background import BackgroundTask

from order_history import MAX_HISTORY_PAGE_SIZE

from .api_observability import authenticated_segment, observe
from .config import Settings
from .contracts import Scenario
from .store import Conflict, Store
from .weni_events import register_webhook


class TaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    segmento: Literal["FARMA", "PET"]
    origem: Literal["manual", "n8n", "teste"] = "manual"
    chave: str = Field(min_length=1, max_length=96, pattern=r"^[a-zA-Z0-9_-]+$")
    cenario: Scenario = "normal"


class HistoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    segmento: Literal["FARMA", "PET"]
    origem: Literal["manual", "n8n", "teste"] = "manual"
    chave: str = Field(min_length=1, max_length=96, pattern=r"^[a-zA-Z0-9_-]+$")
    inicio: str
    fim: str
    limite: int = Field(default=500, ge=1, le=MAX_HISTORY_PAGE_SIZE)
    max_paginas: int = Field(default=100, ge=1, le=10000)
    modo: Literal["historica", "incremental", "reconciliacao"] = "historica"
    reiniciar: bool = False
    quantidade_sintetica: int = Field(default=205, ge=0, le=1200)


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
        segment = authenticated_segment(authorization, settings.tokens)
        if segment is not None:
            return segment
        raise HTTPException(401, "AUTENTICACAO_INVALIDA")

    dependency = Depends(scope)

    @app.middleware("http")
    async def bounded_body(request: Request, call_next):
        started = monotonic()
        if request.method == "POST":
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 4096:
                    return JSONResponse({"erro": "CORPO_EXCESSIVO"}, status_code=413)
            request._body = bytes(body)
        try:
            response = await call_next(request)
        except Exception:
            request.state.api_error = "SERVICO_INDISPONIVEL"
            response = JSONResponse({"erro": "SERVICO_INDISPONIVEL"}, status_code=503)
        response.background = BackgroundTask(
            observe,
            request,
            response.status_code,
            store=store,
            settings=settings,
            duration=round((monotonic() - started) * 1000),
        )
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid(request, _error):
        request.state.api_error = "REQUISICAO_INVALIDA"
        return JSONResponse({"erro": "REQUISICAO_INVALIDA"}, status_code=422)

    @app.exception_handler(HTTPException)
    async def http_error(request, error):
        request.state.api_error = error.detail
        return await http_exception_handler(request, error)

    @app.get("/saude")
    def health():
        return {"estado": "ativo", "ambiente": "homologacao", "escrita_real": False}

    @app.get("/prontidao")
    def ready(_segment=dependency):
        if not store.ready():
            raise HTTPException(503, "SCHEMA_INDISPONIVEL")
        return {"estado": "pronto"}

    @app.post("/tarefas", status_code=202)
    def create(body: TaskRequest, request: Request, segment=dependency):
        request.state.api_body = {"origem": body.origem, "cenario": body.cenario}
        if body.segmento != segment:
            raise HTTPException(403, "SEGMENTO_NAO_AUTORIZADO")
        try:
            return public(store.create(segment, body.origem, body.chave, body.cenario))
        except Conflict:
            raise HTTPException(409, "IDEMPOTENCIA_CONFLITANTE") from None

    @app.post("/tarefas/historico", status_code=202)
    def history(body: HistoryRequest, request: Request, segment=dependency):
        request.state.api_body = {
            "origem": body.origem,
            "modo": body.modo,
            "limite": body.limite,
        }
        if body.segmento != segment:
            raise HTTPException(403, "SEGMENTO_NAO_AUTORIZADO")
        from .history import validate_parameters

        parameters = body.model_dump(exclude={"segmento", "origem", "chave"})
        try:
            validate_parameters(segment, parameters)
            return public(
                store.create(
                    segment, body.origem, body.chave, "normal", history=parameters
                )
            )
        except ValueError:
            raise HTTPException(422, "PARAMETROS_HISTORICO_INVALIDOS") from None
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

    if settings.weni_farma_token is not None:
        register_webhook(app, store, settings.weni_farma_token)

    return app
