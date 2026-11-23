"""Central técnica de homologação, com leitura restrita ao operador autenticado."""

from __future__ import annotations

import json
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from threading import BoundedSemaphore
from typing import Annotated, Literal

import jwt
import psycopg
from fastapi import FastAPI, HTTPException, Query, Request
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

from .api_observability import read_consumption
from .infrastructure import read_infrastructure

SEGMENTS = {"FARMA", "PET"}


@dataclass(frozen=True)
class CentralSettings:
    dsn: str = field(repr=False)
    issuer: str
    audience: str
    jwks_file: Path
    identities_file: Path
    infrastructure_file: Path | None = None

    def __post_init__(self):
        if not re.fullmatch(
            r"https://[a-z0-9][a-z0-9-]*\.cloudflareaccess\.com", self.issuer
        ):
            raise ValueError("EMISSOR_ACCESS_INVALIDO")
        if not self.audience.strip():
            raise ValueError("AUDIENCIA_ACCESS_OBRIGATORIA")
        try:
            info = conninfo_to_dict(self.dsn)
        except psycopg.ProgrammingError:
            raise ValueError("DSN_CENTRAL_INVALIDO") from None
        if info.get("user") != "hub_central_leitor" or not re.fullmatch(
            r"nexoflow_hub_hml(?:_[a-z0-9]+)?", str(info.get("dbname", ""))
        ):
            raise ValueError("DESTINO_LEITURA_HML_OBRIGATORIO")

    @classmethod
    def load(cls):
        if (
            os.getenv("HUB_AMBIENTE") != "homologacao"
            or os.getenv("HUB_ESCRITA_REAL", "false").lower() != "false"
        ):
            raise ValueError("CENTRAL_SOMENTE_HOMOLOGACAO")
        return cls(
            Path(os.environ["CENTRAL_DSN_FILE"]).read_text().strip(),
            os.environ["CENTRAL_ACCESS_ISSUER"],
            os.environ["CENTRAL_ACCESS_AUD"],
            Path(os.environ["CENTRAL_ACCESS_JWKS_FILE"]),
            Path(os.environ["CENTRAL_IDENTIDADES_FILE"]),
            Path(value) if (value := os.getenv("CENTRAL_INFRA_FILE")) else None,
        )


def _unique_fields(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("CAMPO_DUPLICADO")
        obj[key] = value
    return obj


def _private_object(path: Path) -> dict:
    try:
        obj = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_unique_fields
        )
        if not isinstance(obj, dict):
            raise ValueError
        return obj
    except (OSError, ValueError):
        raise HTTPException(503, "CONFIGURACAO_CENTRAL_INDISPONIVEL") from None


def operator_segments(assertion: str, settings: CentralSettings) -> list[str]:
    if not assertion or len(assertion) > 16384:
        raise HTTPException(401, "AUTENTICACAO_NECESSARIA")
    try:
        header = jwt.get_unverified_header(assertion)
        kid = header.get("kid")
        if header.get("alg") != "RS256" or not isinstance(kid, str) or not kid:
            raise jwt.InvalidTokenError()
        keys = _private_object(settings.jwks_file).get("keys")
        if not isinstance(keys, list) or not keys:
            raise HTTPException(503, "CHAVES_ACCESS_INDISPONIVEIS")
        matches = [
            key
            for key in keys
            if isinstance(key, dict)
            and key.get("kid") == kid
            and key.get("kty") == "RSA"
            and key.get("use", "sig") == "sig"
            and key.get("alg", "RS256") == "RS256"
        ]
        if len(matches) != 1:
            raise jwt.InvalidTokenError()
        public_key = jwt.PyJWK.from_dict(matches[0], algorithm="RS256")
        claims = jwt.decode(
            assertion,
            public_key,
            algorithms=["RS256"],
            audience=settings.audience,
            issuer=settings.issuer,
            options={"require": ["iss", "aud", "exp", "iat", "sub", "type"]},
        )
        if (
            claims["type"] != "app"
            or "common_name" in claims
            or not isinstance(claims.get("email"), str)
            or not claims["email"].strip()
        ):
            raise jwt.InvalidTokenError()
    except (jwt.PyJWTError, ValueError, TypeError, OverflowError):
        raise HTTPException(401, "IDENTIDADE_ACCESS_INVALIDA") from None

    # Releitura em cada consulta permite revogar o escopo sem reiniciar o serviço.
    grant = _private_object(settings.identities_file).get(claims["sub"])
    segments = [grant] if isinstance(grant, str) else grant
    if (
        not isinstance(segments, list)
        or not segments
        or not all(isinstance(value, str) and value in SEGMENTS for value in segments)
        or len(set(segments)) != len(segments)
    ):
        raise HTTPException(403, "OPERADOR_SEM_ACESSO_A_CENTRAL")
    return segments


@contextmanager
def read_cursor(dsn: str, segment: str):
    with (
        psycopg.connect(
            dsn,
            connect_timeout=4,
            options=(
                "-c default_transaction_read_only=on -c statement_timeout=4000 -c lock_timeout=1500"
            ),
        ) as connection,
        connection.cursor(row_factory=dict_row) as db,
    ):
        db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        db.execute("SELECT set_config('nexoflow.segmento', %s, true)", (segment,))
        yield db


def read_summary(dsn: str, segment: str):
    with read_cursor(dsn, segment) as db:
        tasks = db.execute(
            """SELECT id, estado, criado_em, atualizado_em FROM hub.central_tarefas
               WHERE segmento=%s ORDER BY criado_em DESC, id DESC LIMIT 50""",
            (segment,),
        ).fetchall()
        events = db.execute(
            """SELECT tipo, ocorrido_em, recebido_em FROM hub.central_eventos
               WHERE segmento=%s ORDER BY recebido_em DESC, ocorrido_em DESC, tipo LIMIT 50""",
            (segment,),
        ).fetchall()
        operation = db.execute(
            """SELECT worker_estado, worker_ultimo_ciclo_em, fila_prontas,
                      fila_em_espera, fila_leases_expirados, fila_espera_segundos,
                      ultima_conclusao_em FROM hub.central_operacao WHERE segmento=%s""",
            (segment,),
        ).fetchone()
    return {
        "segmento": segment,
        "ambiente": "homologacao",
        "metricas": {"habilitado": False},
        "tarefas": tasks,
        "integracoes": {"hub": "pronto", "processamento": "homologacao"},
        "eventos": events,
        "operacao": operation,
    }


def create_app(settings: CentralSettings | None = None):
    config = settings or CentralSettings.load()
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    slots = BoundedSemaphore(4)

    @app.middleware("http")
    async def private_response(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/api/central/v1/infraestrutura")
    def infrastructure(request: Request):
        tokens = request.headers.getlist("cf-access-jwt-assertion")
        operator_segments(tokens[0] if len(tokens) == 1 else "", config)
        return read_infrastructure(config.infrastructure_file)

    @app.get("/api/central/v1/consumo")
    def consumption(
        request: Request,
        segmento: Literal["FARMA", "PET"] | None = None,
        api: Literal["hub", "weni"] | None = None,
        antes: Annotated[int | None, Query(ge=1, le=2**53 - 1)] = None,
        so_erros: bool = False,
    ):
        tokens = request.headers.getlist("cf-access-jwt-assertion")
        allowed = operator_segments(tokens[0] if len(tokens) == 1 else "", config)
        segment = segmento or allowed[0]
        if segment not in allowed:
            raise HTTPException(403, "SEGMENTO_NAO_AUTORIZADO")
        if not slots.acquire(blocking=False):
            raise HTTPException(503, "CENTRAL_OCUPADA")
        try:
            with read_cursor(config.dsn, segment) as db:
                return dict(
                    read_consumption(
                        db, segment, api=api, before=antes, only_errors=so_erros
                    ),
                    segmento=segment,
                )
        except psycopg.Error:
            raise HTTPException(503, "LEITURA_CENTRAL_INDISPONIVEL") from None
        finally:
            slots.release()

    @app.get("/api/central/v1/resumo")
    def summary(request: Request):
        tokens = request.headers.getlist("cf-access-jwt-assertion")
        allowed = operator_segments(tokens[0] if len(tokens) == 1 else "", config)
        params = request.query_params.multi_items()
        segment = allowed[0]
        if params:
            if (
                len(params) != 1
                or params[0][0] != "segmento"
                or params[0][1] not in SEGMENTS
            ):
                raise HTTPException(422, "SEGMENTO_DA_CONSULTA_INVALIDO")
            segment = params[0][1]
            if segment not in allowed:
                raise HTTPException(403, "SEGMENTO_NAO_AUTORIZADO")
        if not slots.acquire(blocking=False):
            raise HTTPException(503, "CENTRAL_OCUPADA")
        try:
            return {
                **read_summary(config.dsn, segment),
                "segmentos_autorizados": allowed,
            }
        except psycopg.Error:
            raise HTTPException(503, "LEITURA_CENTRAL_INDISPONIVEL") from None
        finally:
            slots.release()

    return app
