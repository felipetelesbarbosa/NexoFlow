"""APIs separadas: bearer dedicado, destino fechado e erros sem dados privados."""

from __future__ import annotations

import hmac

import psycopg
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from ds_backend.contract import MAX_BYTES, StorageError


def create_app(store, token, *, reader=False):
    if not isinstance(token, str) or len(token) < 32:
        raise StorageError("DS_CREDENCIAL_AUSENTE")
    api = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @api.middleware("http")
    async def protect(request: Request, call_next):
        if not hmac.compare_digest(
            request.headers.get("authorization", "").encode(),
            ("Bearer " + token).encode(),
        ):
            return JSONResponse({"error": "DS_AUTENTICACAO"}, status_code=401)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_BYTES:
                return JSONResponse({"error": "DS_CORPO_EXCESSIVO"}, status_code=413)
        request._body = bytes(body)
        return await call_next(request)

    @api.exception_handler(StorageError)
    async def contract_error(_request, error):
        return JSONResponse({"error": str(error)}, status_code=409)

    @api.exception_handler(psycopg.Error)
    async def database_error(_request, error):
        code = (
            "DS_PERMISSAO"
            if isinstance(error, psycopg.errors.InsufficientPrivilege)
            else "DS_BANCO_INDISPONIVEL"
        )
        return JSONResponse({"error": code}, status_code=503)

    @api.get("/v1/destino")
    def info():
        return store.info()

    async def body(request):
        try:
            data = await request.json()
            if not isinstance(data, dict):
                raise ValueError
            return data
        except (ValueError, UnicodeError):
            raise StorageError("DS_JSON_INVALIDO") from None

    async def invoke(request, func, fields):
        data = await body(request)
        if set(data) != set(fields):
            raise StorageError("DS_PARAMETROS_INVALIDOS")
        return await run_in_threadpool(func, **data)

    if reader:

        @api.post("/v1/consulta")
        async def query(request: Request):
            return await invoke(
                request,
                store.query,
                ("table", "fields", "start", "end", "filters", "aggregation"),
            )

        return api

    @api.get("/v1/conferencia")
    def audit():
        return store.audit()

    @api.get("/v1/capacidade")
    def capacity():
        return store.capacity()

    @api.post("/v1/revisoes")
    async def begin(request: Request):
        return await invoke(request, store.begin, ("revision", "purpose", "evidence"))

    @api.get("/v1/revisoes/{revision}")
    def inspect(revision: str):
        return store.inspect(revision)

    @api.post("/v1/linhas")
    async def rows(request: Request):
        return await invoke(request, store.rows, ("name", "revision", "after", "limit"))

    @api.post("/v1/lotes")
    async def batch(request: Request):
        return await invoke(
            request,
            store.batch,
            ("revision", "batch_id", "name", "rows", "remove", "simulate"),
        )

    @api.get("/v1/lotes/{batch}")
    def receipt(batch: str):
        result = store.receipt(batch)
        return (
            result
            if result is not None
            else JSONResponse({"error": "DS_LOTE_AUSENTE"}, status_code=404)
        )

    @api.post("/v1/substituicoes")
    async def replace(request: Request):
        return await invoke(request, store.replace, ("revision", "name", "expected"))

    @api.post("/v1/selar")
    async def seal(request: Request):
        return await invoke(request, store.seal, ("revision", "manifest"))

    @api.post("/v1/confirmar")
    async def finish(request: Request):
        return await invoke(request, store.finish, ("revision", "manifest", "complete"))

    @api.post("/v1/reverter")
    async def rollback(request: Request):
        return await invoke(request, store.rollback, ("revision", "expected_version"))

    @api.post("/v1/abortar")
    async def abort(request: Request):
        return await invoke(request, store.abort, ("revision",))

    @api.post("/v1/estados/ler")
    async def state_get(request: Request):
        return await invoke(request, store.state_get, ("name",))

    @api.post("/v1/estados/gravar")
    async def state_put(request: Request):
        return await invoke(
            request,
            store.state_put,
            ("name", "expected_version", "document", "receipt_id"),
        )

    return api
