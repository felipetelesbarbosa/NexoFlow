"""API exclusiva do piloto; origem em rede privada atrás do Cloudflare Access."""

from __future__ import annotations

import hmac
import json
import os
from pathlib import Path

import psycopg
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from bi_postgres_contract import PROTOCOL, TARGET, PublicationError
from integrations.bi_itens_publisher.store import Store


def create_app(store: Store, token: str) -> FastAPI:
    if len(token) < 32:
        raise RuntimeError("Credencial dedicada de publicação ausente ou curta.")
    api = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @api.middleware("http")
    async def authenticate(request: Request, call_next):
        if not hmac.compare_digest(
            request.headers.get("authorization", "").encode(),
            ("Bearer " + token).encode(),
        ):
            return JSONResponse({"error": "BI_PG_AUTENTICACAO"}, status_code=401)
        # Corpo limitado antes do parser. Nenhum handler registra dados/exceções brutas.
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 8_000_000:
                return JSONResponse({"error": "BI_PG_CORPO_EXCESSIVO"}, status_code=413)
        request._body = bytes(body)
        return await call_next(request)

    @api.exception_handler(PublicationError)
    async def contract_error(_request, error):
        return JSONResponse({"error": str(error)}, status_code=409)

    @api.exception_handler(psycopg.Error)
    async def database_error(_request, error):
        if isinstance(error, psycopg.errors.InsufficientPrivilege):
            return JSONResponse({"error": "BI_PG_PERMISSAO"}, status_code=403)
        if isinstance(error, (psycopg.DataError, psycopg.IntegrityError)):
            return JSONResponse({"error": "BI_PG_RESTRICAO_DESTINO"}, status_code=409)
        return JSONResponse({"error": "BI_PG_BANCO_NAO_CONFIRMOU"}, status_code=503)

    @api.get("/publicacao/destino")
    def target():
        with store.connect() as conn:
            store.check(conn)
        return {"protocol": PROTOCOL, "target": TARGET, "segment": "FARMA"}

    async def body(request):
        try:
            return await request.json()
        except (json.JSONDecodeError, UnicodeError):
            raise PublicationError("BI_PG_JSON_INVALIDO") from None

    @api.post("/publicacao/farma/bi-itens/sessoes")
    async def session(request: Request):
        data = await body(request)
        if not isinstance(data, dict) or set(data) != {"session_id"}:
            raise PublicationError("BI_PG_SESSAO_INVALIDA")
        return await run_in_threadpool(store.session, data["session_id"])

    @api.post("/publicacao/farma/bi-itens/planos")
    async def plan(request: Request):
        data = await body(request)
        if not isinstance(data, dict) or set(data) != {
            "session_id",
            "manifest",
            "complete",
        }:
            raise PublicationError("BI_PG_PLANO_INVALIDO")
        return await run_in_threadpool(
            store.plan, data["session_id"], data["manifest"], data["complete"]
        )

    @api.post("/publicacao/farma/bi-itens/lotes")
    async def apply(request: Request):
        return await run_in_threadpool(store.apply, await body(request))

    @api.post("/publicacao/farma/bi-itens/simular")
    async def simulate(request: Request):
        return await run_in_threadpool(store.apply, await body(request), simulate=True)

    @api.get("/publicacao/farma/bi-itens/sessoes/{identifier}")
    def session_status(identifier: str):
        return store.plan_status(identifier)

    @api.get("/publicacao/farma/bi-itens/lotes/{identifier}")
    def receipt(identifier: str):
        result = store.receipt(identifier)
        return (
            result
            if result
            else JSONResponse({"error": "BI_PG_LOTE_AUSENTE"}, status_code=404)
        )

    return api


def app_factory():
    # Secrets Docker: não usar senha/DSN na linha de comando ou no compose público.
    token = Path(os.environ["PUBLISH_TOKEN_FILE"]).read_text().strip()
    dsn = Path(os.environ["PUBLISH_DSN_FILE"]).read_text().strip()
    return create_app(Store(dsn, require_dedicated_role=True), token)
