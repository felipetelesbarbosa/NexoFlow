"""Telemetria por tentativa HTTP, limitada a rotas e campos técnicos conhecidos."""

from __future__ import annotations

import logging
import secrets

from psycopg.types.json import Jsonb
from starlette.concurrency import run_in_threadpool

WENI_ROUTE = "/v1/webhooks/weni/farma"
ROUTES = {
    ("POST", "/tarefas"),
    ("POST", "/tarefas/historico"),
    ("GET", "/tarefas"),
    ("GET", "/tarefas/{uid}"),
    ("GET", "/tarefas/{uid}/resultado"),
    ("GET", "/tarefas/{uid}/erros"),
    ("POST", WENI_ROUTE),
}
ERROR_CODES = frozenset(
    {
        "SEGMENTO_NAO_AUTORIZADO",
        "TAREFA_NAO_ENCONTRADA",
        "IDEMPOTENCIA_CONFLITANTE",
        "PARAMETROS_HISTORICO_INVALIDOS",
        "EVENTO_CONFLITANTE",
        "REQUISICAO_INVALIDA",
        "SERVICO_INDISPONIVEL",
    }
)


def authenticated_segment(authorization, tokens):
    if authorization.startswith("Bearer "):
        supplied = authorization[7:].encode()
        for segment, token in tokens.items():
            if secrets.compare_digest(supplied, token.encode()):
                return segment
    return None


def save(store, *, segment, api, method, endpoint, status, duration, body, error):
    with store.connect() as db:
        db.execute("SET LOCAL statement_timeout = '300ms'")
        db.execute("SET LOCAL lock_timeout = '150ms'")
        db.execute(
            """INSERT INTO hub.api_requisicoes
               (segmento, api, metodo, endpoint, http, duracao_ms, corpo, erro)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                segment,
                api,
                method,
                endpoint,
                status,
                duration,
                Jsonb(body) if body is not None else None,
                error,
            ),
        )


async def observe(request, status, *, store, settings, duration):
    endpoint = getattr(request.scope.get("route"), "path", None)
    method = request.method
    headers = request.headers.getlist("authorization")
    if (method, endpoint) not in ROUTES or len(headers) != 1:
        return
    api = "weni" if endpoint == WENI_ROUTE else "hub"
    tokens = settings.tokens
    if api == "weni":
        if settings.weni_farma_token is None:
            return
        tokens = {"FARMA": settings.weni_farma_token}
    segment = authenticated_segment(headers[0], tokens)
    if segment is None:
        return
    code = getattr(request.state, "api_error", None)
    error = (
        code
        if isinstance(code, str) and code in ERROR_CODES
        else (f"HTTP_{status}" if status >= 400 else None)
    )
    try:
        await run_in_threadpool(
            save,
            store,
            segment=segment,
            api=api,
            method=method,
            endpoint=endpoint,
            status=status,
            duration=duration,
            body=getattr(request.state, "api_body", None),
            error=error,
        )
    except Exception:
        # A falha de telemetria não altera a resposta original.
        logging.warning("TELEMETRIA_API_INDISPONIVEL")


def read_consumption(db, segment, *, api=None, before=None, only_errors=False):
    base = """FROM hub.central_api_requisicoes
              WHERE segmento=%s AND ocorrido_em >= now() - interval '24 hours'"""
    summary = db.execute(
        """SELECT api, count(*) AS total, count(*) FILTER (WHERE http BETWEEN 200 AND 299) AS sucesso,
                  count(*) FILTER (WHERE http NOT BETWEEN 200 AND 299) AS erros,
                  percentile_disc(0.95) WITHIN GROUP (ORDER BY duracao_ms) AS p95_ms """
        + base
        + " GROUP BY api ORDER BY api",
        (segment,),
    ).fetchall()
    trend = db.execute(
        """SELECT api, date_trunc('hour', ocorrido_em) AS hora,
                  count(*) FILTER (WHERE http BETWEEN 200 AND 299) AS sucesso,
                  count(*) FILTER (WHERE http NOT BETWEEN 200 AND 299) AS erros """
        + base
        + " GROUP BY api, hora ORDER BY hora",
        (segment,),
    ).fetchall()
    page = []
    if api is not None:
        page = db.execute(
            """SELECT id, ocorrido_em, metodo, endpoint, http, duracao_ms, corpo, erro """
            + base
            + """ AND api=%s AND (%s::bigint IS NULL OR id<%s)
                    AND (NOT %s OR http NOT BETWEEN 200 AND 299)
                    ORDER BY id DESC LIMIT 51""",
            (segment, api, before, before, only_errors),
        ).fetchall()
    return {
        "resumo": summary,
        "serie": trend,
        "requisicoes": page[:50],
        "proximo": page[49]["id"] if len(page) > 50 else None,
    }
