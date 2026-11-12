"""Serviço de leitura separado: nenhuma rota de publicação, DSN ou token de escrita."""

import hmac
import os
from pathlib import Path
from threading import BoundedSemaphore

import psycopg
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from bi_postgres_contract import PublicationError
from integrations.bi_itens_publisher.reader import READ_PROTOCOL, READ_TARGET, Reader


def create_app(reader, token):
    if len(token) < 32:
        raise RuntimeError("Credencial dedicada de leitura ausente ou curta.")
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    gate = BoundedSemaphore(4)

    @app.middleware("http")
    async def authenticate(request, call_next):
        if not hmac.compare_digest(
            request.headers.get("authorization", "").encode(),
            ("Bearer " + token).encode(),
        ):
            return JSONResponse(
                {"error": "BI_PG_LEITURA_AUTENTICACAO"}, status_code=401
            )
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 64_000:
                return JSONResponse(
                    {"error": "BI_PG_CONSULTA_EXCESSIVA"}, status_code=413
                )
        request._body = bytes(data)
        return await call_next(request)

    @app.exception_handler(PublicationError)
    async def invalid(_request, error):
        # Somente códigos controlados; não serializar exceções Google/SQL ou filtros.
        return JSONResponse({"error": str(error).split(";")[0]}, status_code=409)

    @app.exception_handler(psycopg.Error)
    async def database(_request, _error):
        return JSONResponse({"error": "BI_PG_LEITURA_BANCO_PENDENTE"}, status_code=503)

    @app.get("/consulta/destino")
    def destination():
        with reader.connect() as conn:
            state = reader.check(conn, require_ready=False)
        return {
            "protocol": READ_PROTOCOL,
            "target": READ_TARGET,
            "segment": "FARMA",
            **state,
        }

    @app.post("/consulta/farma/bi-itens")
    async def query(request: Request):
        try:
            data = await request.json()
        except (ValueError, UnicodeError):
            raise PublicationError("BI_PG_JSON_INVALIDO") from None
        if not gate.acquire(blocking=False):
            return JSONResponse({"error": "BI_PG_LEITURA_OCUPADA"}, status_code=503)
        try:
            return await run_in_threadpool(reader.query, data)
        finally:
            gate.release()

    return app


def app_factory():
    return create_app(
        Reader(Path(os.environ["READ_DSN_FILE"]).read_text().strip()),
        Path(os.environ["READ_TOKEN_FILE"]).read_text().strip(),
    )
