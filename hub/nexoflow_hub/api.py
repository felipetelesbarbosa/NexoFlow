"""API interna autenticada, somente tarefas sintéticas de homologação."""

from __future__ import annotations

from datetime import datetime
from time import monotonic
from typing import Literal
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Request, Security
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer
from pydantic import BaseModel, ConfigDict, Field
from starlette.background import BackgroundTask

from order_history import MAX_HISTORY_PAGE_SIZE

from . import __version__
from .api_observability import authenticated_segment, observe
from .config import Settings
from .contracts import NoturnoScenario, NoturnoStage, Scenario, noturno_stages
from .store import Conflict, Store
from .weni_events import register_webhook


class TaskSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    segmento: Literal["FARMA", "PET"]
    origem: Literal["manual", "n8n", "teste"] = "manual"
    chave: str = Field(
        min_length=1,
        max_length=96,
        pattern=r"^[a-zA-Z0-9_-]+$",
        description="Chave da execução. Reutilize no reenvio da mesma solicitação.",
        examples=["ensaio-farma-001"],
    )


class TaskRequest(TaskSubmission):
    cenario: Scenario = "normal"


class HistoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    segmento: Literal["FARMA", "PET"]
    origem: Literal["manual", "n8n", "teste"] = "manual"
    chave: str = Field(min_length=1, max_length=96, pattern=r"^[a-zA-Z0-9_-]+$")
    inicio: str = Field(description="Primeiro dia, inclusive", examples=["2026-11-01"])
    fim: str = Field(description="Último dia, inclusive", examples=["2026-11-06"])
    limite: int = Field(default=500, ge=1, le=MAX_HISTORY_PAGE_SIZE)
    max_paginas: int = Field(default=100, ge=1, le=10000)
    modo: Literal["historica", "incremental", "reconciliacao"] = "historica"
    reiniciar: bool = False
    quantidade_sintetica: int = Field(default=205, ge=0, le=1200)


class NoturnoRequest(TaskSubmission):
    cenario: NoturnoScenario = "normal"


class NoturnoProgress(BaseModel):
    etapa: NoturnoStage
    estado: str


class NoturnoStages(BaseModel):
    estado: str
    etapas: list[NoturnoProgress]
    erro: str | None


class TaskOutcome(BaseModel):
    id: UUID
    segmento: Literal["FARMA", "PET"]
    estado: str
    resultado: dict | None


class TaskView(TaskOutcome):
    origem: str
    criada_em: datetime
    atualizada_em: datetime
    tentativa: int
    erro: str | None


class TaskError(BaseModel):
    id: UUID
    segmento: Literal["FARMA", "PET"]
    erro: str | None


HUB_TOKEN = Security(
    HTTPBearer(
        auto_error=False,
        scheme_name="TokenHub",
        description="Token de integração do segmento. Envie Authorization: Bearer SEU_TOKEN.",
    )
)
INTEGRATION_ERRORS = {
    401: {"description": "Token ausente ou inválido"},
    503: {"description": "Serviço temporariamente indisponível"},
}
CREATE_ERRORS = {
    **INTEGRATION_ERRORS,
    403: {"description": "O token não autoriza o segmento solicitado"},
    409: {"description": "A chave já foi usada com outros dados"},
    413: {"description": "Corpo acima de 4.096 bytes"},
    422: {"description": "Corpo ou parâmetros inválidos"},
}
LOOKUP_ERRORS = {
    **INTEGRATION_ERRORS,
    404: {"description": "Execução indisponível para esse token"},
    422: {"description": "Identificador inválido"},
}


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
        version=__version__,
        description=(
            "API interna para integrações do Hub. As execuções e o histórico "
            "deste ambiente usam dados sintéticos. Para o n8n na rede de "
            "homologação, use a URL base interna configurada no Compose."
        ),
        servers=[
            {"url": "http://hub-api:8000", "description": "Rede interna da homologação"}
        ],
        openapi_tags=[
            {"name": "Disponibilidade", "description": "Saúde e prontidão do serviço."},
            {
                "name": "Execuções",
                "description": "Fila, resultados e erros por segmento.",
            },
            {
                "name": "Histórico",
                "description": "Extração paginada com dados sintéticos.",
            },
            {
                "name": "Webhooks Weni",
                "description": "Eventos técnicos do fluxo FARMA.",
            },
        ],
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    def scope(request: Request, _token=HUB_TOKEN):
        authorization = request.headers.get("authorization", "")
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

    @app.get("/saude", tags=["Disponibilidade"], summary="Verificar saúde do serviço")
    def health() -> dict[str, str | bool]:
        return {"estado": "ativo", "ambiente": "homologacao", "escrita_real": False}

    @app.get(
        "/prontidao",
        tags=["Disponibilidade"],
        summary="Verificar prontidão do banco",
        responses={**INTEGRATION_ERRORS},
    )
    def ready(_segment=dependency) -> dict[str, str]:
        if not store.ready():
            raise HTTPException(503, "SCHEMA_INDISPONIVEL")
        return {"estado": "pronto"}

    @app.post(
        "/tarefas",
        status_code=202,
        tags=["Execuções"],
        summary="Enfileirar uma execução",
        description="HTTP 202 confirma a entrada na fila. Consulte a execução para obter o resultado.",
        responses={202: {"model": TaskView}, **CREATE_ERRORS},
    )
    def create(body: TaskRequest, request: Request, segment=dependency):
        request.state.api_body = {"origem": body.origem, "cenario": body.cenario}
        if body.segmento != segment:
            raise HTTPException(403, "SEGMENTO_NAO_AUTORIZADO")
        try:
            return public(store.create(segment, body.origem, body.chave, body.cenario))
        except Conflict:
            raise HTTPException(409, "IDEMPOTENCIA_CONFLITANTE") from None

    @app.post(
        "/tarefas/noturno",
        status_code=202,
        tags=["Execuções"],
        summary="Enfileirar o ensaio do Noturno FARMA",
        description="O worker confirma as etapas sintéticas na ordem e preserva o progresso após interrupções.",
        responses={202: {"model": TaskView}, **CREATE_ERRORS},
    )
    def noturno(body: NoturnoRequest, request: Request, segment=dependency):
        request.state.api_body = {"origem": body.origem, "cenario": body.cenario}
        if segment != "FARMA" or body.segmento != segment:
            raise HTTPException(403, "SEGMENTO_NAO_AUTORIZADO")
        try:
            return public(
                store.create(segment, body.origem, body.chave, body.cenario, noturno=True)
            )
        except Conflict:
            raise HTTPException(409, "IDEMPOTENCIA_CONFLITANTE") from None

    @app.post(
        "/tarefas/historico",
        status_code=202,
        tags=["Histórico"],
        summary="Enfileirar a leitura do histórico",
        description="Extrai pedidos sintéticos pelo intervalo e pelo segmento informados.",
        responses={202: {"model": TaskView}, **CREATE_ERRORS},
    )
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

    @app.get(
        "/tarefas",
        tags=["Execuções"],
        summary="Listar execuções do segmento",
        responses={200: {"model": list[TaskView]}, **INTEGRATION_ERRORS},
    )
    def list_tasks(segment=dependency):
        return [public(t) for t in store.list(segment)]

    def lookup(uid, segment):
        task = store.get(segment, uid)
        if task is None:
            raise HTTPException(404, "TAREFA_NAO_ENCONTRADA")
        return task

    @app.get(
        "/tarefas/{uid}",
        tags=["Execuções"],
        summary="Consultar uma execução",
        responses={200: {"model": TaskView}, **LOOKUP_ERRORS},
    )
    def get(uid: UUID, segment=dependency):
        return public(lookup(uid, segment))

    @app.get(
        "/tarefas/{uid}/etapas",
        tags=["Execuções"],
        summary="Consultar etapas do ensaio do Noturno",
        responses={200: {"model": NoturnoStages}, **LOOKUP_ERRORS},
    )
    def stages(uid: UUID, segment=dependency):
        task = lookup(uid, segment)
        if task["tipo"] != "noturno":
            raise HTTPException(404, "TAREFA_NAO_ENCONTRADA")
        return {
            "estado": task["estado"],
            "etapas": noturno_stages(store.checkpoints(task), task["estado"]),
            "erro": task["erro"],
        }

    @app.get(
        "/tarefas/{uid}/resultado",
        tags=["Execuções"],
        summary="Consultar resultado",
        responses={200: {"model": TaskOutcome}, **LOOKUP_ERRORS},
    )
    def result(uid: UUID, segment=dependency):
        task = lookup(uid, segment)
        return {
            "id": task["id"],
            "segmento": segment,
            "estado": task["estado"],
            "resultado": task["resultado"],
        }

    @app.get(
        "/tarefas/{uid}/erros",
        tags=["Execuções"],
        summary="Consultar erro registrado",
        responses={200: {"model": TaskError}, **LOOKUP_ERRORS},
    )
    def errors(uid: UUID, segment=dependency):
        task = lookup(uid, segment)
        return {"id": task["id"], "segmento": segment, "erro": task["erro"]}

    if settings.weni_farma_token is not None:
        register_webhook(app, store, settings.weni_farma_token)

    return app
