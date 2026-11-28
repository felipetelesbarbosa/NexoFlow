"""Central de Operações, com leitura restrita ao operador autenticado."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path
from threading import BoundedSemaphore
from typing import Annotated, Literal
from uuid import UUID

import jwt
import psycopg
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Security
from fastapi.security import APIKeyHeader
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
from pydantic import BaseModel, ConfigDict, Field

from . import __version__, access_management, metricas
from .api_observability import read_consumption
from .contracts import noturno_stages
from .infrastructure import read_infrastructure

SEGMENTS = {"FARMA", "PET"}
PRODUCTION_HOST = "central.nexoflowhub.com.br"
CENTRAL_HOSTS = {PRODUCTION_HOST, "central-hml.nexoflowhub.com.br"}
Environment = Literal["homologacao", "producao"]


def validate_dsn(dsn: str, environment: Environment) -> None:
    try:
        info = conninfo_to_dict(dsn)
    except psycopg.ProgrammingError:
        raise ValueError("DSN_CENTRAL_INVALIDO") from None
    suffix = {"homologacao": "hml", "producao": "prod"}[environment]
    if info.get("user") != "hub_central_leitor" or not re.fullmatch(
        rf"nexoflow_hub_{suffix}(?:_[a-z0-9]+)?", str(info.get("dbname", ""))
    ):
        raise ValueError("DESTINO_LEITURA_" + suffix.upper() + "_OBRIGATORIO")


@dataclass(frozen=True)
class ProductionReader:
    dsn: str = field(repr=False)
    identities_file: Path

    def __post_init__(self):
        validate_dsn(self.dsn, "producao")


@dataclass(frozen=True)
class Operator:
    subject: str
    email: str
    segments: list[str]
    managed: bool = False
    role: Literal["super_admin", "admin", "convidado", "convidado_metricas"] = "convidado"


class DisplayName(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    nome: str = Field(min_length=1, max_length=80, pattern=r"^[^\x00-\x1f\x7f]+$")


class Invitation(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    email: str = Field(max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    segmentos: list[Literal["FARMA", "PET"]] = Field(min_length=1, max_length=2)
    papel: access_management.Role = "convidado"


class InviteCode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    codigo: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")


class AccessReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=256)


class RoleChange(AccessReference):
    papel: access_management.Role


CENTRAL_SESSION = Security(
    APIKeyHeader(
        name="Cf-Access-Jwt-Assertion",
        auto_error=False,
        scheme_name="SessaoCentral",
        description="O Cloudflare Access envia a identidade individual da sessão à Central.",
    )
)


@lru_cache(maxsize=1)
def hub_openapi() -> dict:
    from .api import create_app as create_hub_app
    from .config import Settings

    # A geração do contrato apenas registra rotas e modelos. Não abre o banco
    # nem lê os segredos da API de integração que está em execução.
    demo = Settings(
        "dbname=nexoflow_hub_hml",
        {"FARMA": "f" * 32, "PET": "p" * 32},
        weni_farma_token="w" * 32,
    )
    return create_hub_app(demo).openapi()


@dataclass(frozen=True)
class CentralSettings:
    dsn: str = field(repr=False)
    issuer: str
    audience: str
    jwks_file: Path
    identities_file: Path
    infrastructure_file: Path | None = None
    profiles_db: Path | None = None
    production: ProductionReader | None = None
    super_admin: str | None = field(default=None, repr=False)
    metrics_dsn: str | None = field(default=None, repr=False)
    metrics_readers_file: Path | None = None

    def __post_init__(self):
        if not re.fullmatch(
            r"https://[a-z0-9][a-z0-9-]*\.cloudflareaccess\.com", self.issuer
        ):
            raise ValueError("EMISSOR_ACCESS_INVALIDO")
        if not self.audience.strip():
            raise ValueError("AUDIENCIA_ACCESS_OBRIGATORIA")
        validate_dsn(self.dsn, "homologacao")
        if self.metrics_dsn is not None:
            if self.super_admin is None:
                raise ValueError("METRICAS_EXIGE_SUPER_ADMIN")
            metricas.validate_source(self.metrics_dsn)
        if self.super_admin is not None and (
            not self.profiles_db
            or not self.super_admin.strip()
            or len(self.super_admin) > 256
        ):
            raise ValueError("CONFIGURACAO_SUPER_ADMIN_INVALIDA")
        if (
            self.production
            and self.production.identities_file.resolve()
            == self.identities_file.resolve()
        ):
            raise ValueError("ESCOPOS_DE_PRODUCAO_DEVEM_SER_SEPARADOS")

    @classmethod
    def load(cls):
        if (
            os.getenv("HUB_AMBIENTE") != "homologacao"
            or os.getenv("HUB_ESCRITA_REAL", "false").lower() != "false"
        ):
            raise ValueError("CENTRAL_SOMENTE_HOMOLOGACAO")
        production_dsn = os.getenv("CENTRAL_PROD_DSN_FILE")
        production_scopes = os.getenv("CENTRAL_PROD_IDENTIDADES_FILE")
        if bool(production_dsn) != bool(production_scopes):
            raise ValueError("CONFIGURACAO_LEITURA_PROD_INCOMPLETA")
        production = (
            ProductionReader(
                Path(production_dsn).read_text().strip(), Path(production_scopes)
            )
            if production_dsn and production_scopes
            else None
        )
        return cls(
            Path(os.environ["CENTRAL_DSN_FILE"]).read_text().strip(),
            os.environ["CENTRAL_ACCESS_ISSUER"],
            os.environ["CENTRAL_ACCESS_AUD"],
            Path(os.environ["CENTRAL_ACCESS_JWKS_FILE"]),
            Path(os.environ["CENTRAL_IDENTIDADES_FILE"]),
            Path(value) if (value := os.getenv("CENTRAL_INFRA_FILE")) else None,
            Path(profiles) if (profiles := os.getenv("CENTRAL_PROFILES_DB")) else None,
            production,
            Path(admin_file).read_text(encoding="utf-8").strip()
            if (admin_file := os.getenv("CENTRAL_SUPER_ADMIN_FILE"))
            else None,
            Path(metrics_file).read_text(encoding="utf-8").strip()
            if (metrics_file := os.getenv("CENTRAL_METRICAS_DSN_FILE"))
            else None,
            Path(readers) if (readers := os.getenv("CENTRAL_METRICAS_LEITORES_FILE")) else None,
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


def signed_identity(assertion: str, settings: CentralSettings) -> tuple[str, str]:
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
            or not isinstance(claims["sub"], str)
            or not claims["sub"].strip()
            or "common_name" in claims
            or not isinstance(claims.get("email"), str)
            or not claims["email"].strip()
        ):
            raise jwt.InvalidTokenError()
    except (jwt.PyJWTError, ValueError, TypeError, OverflowError):
        raise HTTPException(401, "IDENTIDADE_ACCESS_INVALIDA") from None

    return claims["sub"], claims["email"]


def authorized_operator(
    subject: str, email: str, settings: CentralSettings
) -> Operator:
    # A revogação no diretório prevalece sobre os acessos legados.
    recorded = (
        access_management.member(settings.profiles_db, subject)
        if settings.profiles_db
        else None
    )
    if recorded is not None:
        if recorded["revoked"]:
            raise HTTPException(403, "OPERADOR_SEM_ACESSO_A_CENTRAL")
        segments = parse_scopes(json.loads(recorded["scopes"]))
    else:
        segments = granted_segments(settings.identities_file, subject)
    if not segments:
        raise HTTPException(403, "OPERADOR_SEM_ACESSO_A_CENTRAL")
    if subject == settings.super_admin:
        role = "super_admin"
    else:
        assigned = (
            access_management.assigned_role(settings.profiles_db, subject)
            if settings.profiles_db else None
        )
        # A concessão privada da versão anterior continua válida para
        # identidades ativas ainda sem papel explícito. A atribuição e a
        # revogação feitas pelo Super Admin prevalecem.
        if assigned is None:
            role = "admin" if subject in legacy_metric_admins(settings) else "convidado"
        elif assigned in {"admin", "convidado", "convidado_metricas"}:
            role = assigned
        else:
            raise HTTPException(403, "PAPEL_NAO_AUTORIZADO")
    return Operator(subject, email, segments, managed=recorded is not None, role=role)


def legacy_metric_admins(settings: CentralSettings) -> set[str]:
    if settings.metrics_readers_file is None:
        return set()
    return {
        subject for subject, grant in _private_object(settings.metrics_readers_file).items()
        if grant is True
    }


def granted_segments(path: Path, subject: str) -> list[str]:
    return parse_scopes(_private_object(path).get(subject))


def parse_scopes(grant) -> list[str]:
    segments = [grant] if isinstance(grant, str) else grant
    if (
        not isinstance(segments, list)
        or not segments
        or not all(isinstance(value, str) and value in SEGMENTS for value in segments)
        or len(set(segments)) != len(segments)
    ):
        return []
    return segments


def profile_name(path: Path, subject: str, name: str | None = None) -> str:
    try:
        with closing(sqlite3.connect(path, timeout=3)) as connection, connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS profiles (subject TEXT PRIMARY KEY, name TEXT NOT NULL)"
            )
            if name is not None:
                connection.execute(
                    """INSERT INTO profiles (subject, name) VALUES (?, ?)
                       ON CONFLICT(subject) DO UPDATE SET name = excluded.name""",
                    (subject, name),
                )
                return name
            row = connection.execute(
                "SELECT name FROM profiles WHERE subject = ?", (subject,)
            ).fetchone()
            return row[0] if row else ""
    except sqlite3.Error:
        raise HTTPException(503, "PERFIL_CENTRAL_INDISPONIVEL") from None


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
            """SELECT id, estado, criado_em, atualizado_em, etapas_concluidas, motivos, evidencia FROM hub.central_tarefas
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
    for task in tasks:
        completed = task.pop("etapas_concluidas")
        if task["evidencia"] is None:
            task.pop("evidencia")
        if task["motivos"] is None:
            task.pop("motivos")
        if completed is not None:
            task["tipo"] = "noturno"
            if (task.get("evidencia") or {}).get("modo") != "referencia_congelada":
                task["etapas"] = noturno_stages(completed, task["estado"])
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
    app = FastAPI(
        title="NexoFlow — Central de Operações",
        version=__version__,
        description="Consultas operacionais para operadores com conta individual e MFA.",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    slots = BoundedSemaphore(4)
    metrics_slot = BoundedSemaphore(1)

    @app.middleware("http")
    async def private_response(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def verified_session(request: Request, _session=CENTRAL_SESSION):
        tokens = request.headers.getlist("cf-access-jwt-assertion")
        return signed_identity(tokens[0] if len(tokens) == 1 else "", config)

    signed_in = Depends(verified_session)

    def authenticated(identity: tuple[str, str] = signed_in):
        return authorized_operator(*identity, config)

    operator = Depends(authenticated)

    def hub_allowed(identity: Operator) -> bool:
        return identity.role in {"super_admin", "admin", "convidado"}

    def hub_operator(identity: Operator = operator):
        if not hub_allowed(identity):
            raise HTTPException(403, "HUB_INDISPONIVEL_PARA_ESTA_CONTA")
        return identity

    hub_access = Depends(hub_operator)

    def administrator(identity: Operator = operator):
        if identity.role != "super_admin" or config.profiles_db is None:
            raise HTTPException(403, "GESTAO_EXCLUSIVA_DO_SUPER_ADMIN")
        return identity.subject, config.profiles_db

    admin = Depends(administrator)

    def require_origin(request: Request):
        host = request.headers.get("x-central-host")
        if host not in CENTRAL_HOSTS or request.headers.getlist("origin") != [
            "https://" + host
        ]:
            raise HTTPException(403, "ORIGEM_DA_CONTA_NAO_AUTORIZADA")

    access_errors = {
        401: {"description": "Sessão individual ausente ou inválida"},
        403: {"description": "A identidade não tem permissão para a consulta"},
        503: {"description": "Consulta temporariamente indisponível"},
    }

    def production_segments(request: Request, identity: Operator) -> list[str]:
        if (
            config.production is None
            or not hub_allowed(identity)
            or identity.managed
            or request.headers.get("x-central-host") != PRODUCTION_HOST
        ):
            return []
        return granted_segments(config.production.identities_file, identity.subject)

    def destination(request: Request, identity: Operator, ambiente: Environment):
        if ambiente == "homologacao":
            return config.dsn, identity.segments
        scopes = production_segments(request, identity)
        if config.production is None or not scopes:
            raise HTTPException(403, "PRODUCAO_NAO_DISPONIVEL")
        return config.production.dsn, scopes

    def metrics_allowed(identity: Operator) -> bool:
        return (
            config.metrics_dsn is not None
            and "FARMA" in identity.segments
            and identity.role in {"super_admin", "admin", "convidado_metricas"}
        )

    @app.get(
        "/api/central/v1/metricas/vendas",
        response_model=metricas.SalesReport,
        include_in_schema=False,
    )
    def sales(
        inicio: date,
        fim: date,
        revisao: UUID | None = None,
        identity: Operator = operator,
    ):
        if config.metrics_dsn is None or not metrics_allowed(identity):
            raise HTTPException(403, "METRICAS_INDISPONIVEL_PARA_ESTA_CONTA")
        if not 0 <= (fim - inicio).days < metricas.MAX_PERIOD_DAYS:
            raise HTTPException(422, "PERIODO_DE_VENDAS_INVALIDO")
        if not metrics_slot.acquire(blocking=False):
            raise HTTPException(503, "METRICAS_OCUPADO")
        try:
            return metricas.read_sales(config.metrics_dsn, inicio, fim, revisao)
        except metricas.RevisionChanged:
            raise HTTPException(409, "REVISAO_DE_VENDAS_ALTERADA") from None
        except (psycopg.Error, metricas.SourceUnavailable):
            raise HTTPException(503, "FONTE_DE_VENDAS_INDISPONIVEL") from None
        finally:
            metrics_slot.release()

    @app.get(
        "/api/central/v1/metricas/produtos",
        response_model=metricas.ProductsReport,
        include_in_schema=False,
    )
    @app.get(
        "/api/central/v1/metricas/anuncios",
        response_model=metricas.AdsReport,
        include_in_schema=False,
    )
    @app.get(
        "/api/central/v1/metricas/pedidos-anuncios",
        response_model=metricas.AdOrdersReport,
        include_in_schema=False,
    )
    def advanced_metrics(
        request: Request,
        inicio: date,
        fim: date,
        revisao: UUID | None = None,
        tipo: Literal["campanha", "grupo", "anuncio"] | None = None,
        identificador: Annotated[str | None, Query(pattern=r"^[0-9]{1,25}$")] = None,
        identity: Operator = operator,
    ):
        if config.metrics_dsn is None or not metrics_allowed(identity):
            raise HTTPException(403, "METRICAS_INDISPONIVEL_PARA_ESTA_CONTA")
        if not 0 <= (fim - inicio).days < metricas.MAX_PERIOD_DAYS:
            raise HTTPException(422, "PERIODO_DE_METRICAS_INVALIDO")
        report = request.url.path.rsplit("/", 1)[-1]
        if report == "pedidos-anuncios" and (tipo is None or identificador is None):
            raise HTTPException(422, "INFORME_IDENTIFICACAO_DO_ANUNCIO")
        if not metrics_slot.acquire(blocking=False):
            raise HTTPException(503, "METRICAS_OCUPADO")
        try:
            if report == "pedidos-anuncios" and tipo is not None and identificador is not None:
                return metricas.read_ad_orders(config.metrics_dsn, inicio, fim, tipo, identificador, revisao)
            if report == "anuncios":
                return metricas.read_ads(config.metrics_dsn, inicio, fim, revisao)
            return metricas.read_products(config.metrics_dsn, inicio, fim, revisao)
        except metricas.RevisionChanged:
            raise HTTPException(409, "REVISAO_DE_METRICAS_ALTERADA") from None
        except (psycopg.Error, metricas.SourceUnavailable):
            raise HTTPException(503, "FONTE_DE_METRICAS_INDISPONIVEL") from None
        finally:
            metrics_slot.release()

    @app.get("/api/central/v1/sessao", include_in_schema=False)
    def session(request: Request, identity: Operator = operator):
        environments = ["homologacao"]
        if production_segments(request, identity):
            environments.append("producao")
        result = {"ambientes": environments}
        if metrics_allowed(identity):
            result = {**result, "metricas_farma": True}
        if config.super_admin is not None:
            return {
                **result,
                "gerencia_usuarios": identity.role == "super_admin",
                "papel": identity.role,
                "hub_disponivel": hub_allowed(identity),
            }
        return result

    @app.get("/api/central/v1/usuarios", include_in_schema=False)
    def users(manager: tuple[str, Path] = admin):
        actor, registry = manager
        legacy = {
            subject: scopes
            for subject, grant in _private_object(config.identities_file).items()
            if (scopes := parse_scopes(grant))
        }
        return access_management.overview(registry, legacy, actor, legacy_metric_admins(config))

    @app.post("/api/central/v1/convites", status_code=201, include_in_schema=False)
    def create_invite(
        request: Request, details: Invitation, manager: tuple[str, Path] = admin
    ):
        require_origin(request)
        actor, registry = manager
        scopes = list(dict.fromkeys(str(scope) for scope in details.segmentos))
        if details.papel == "convidado_metricas" and config.metrics_dsn is None:
            raise HTTPException(409, "METRICAS_INDISPONIVEL")
        return access_management.invite(
            registry, actor, details.email.casefold(), scopes, details.papel
        )

    @app.post(
        "/api/central/v1/convites/aceitar", status_code=204, include_in_schema=False
    )
    def accept_invite(
        request: Request, details: InviteCode, identity: tuple[str, str] = signed_in
    ):
        require_origin(request)
        if config.super_admin is None or config.profiles_db is None:
            raise HTTPException(404, "CONVITES_INDISPONIVEIS")
        subject, email = identity
        access_management.accept(
            config.profiles_db,
            subject,
            email,
            details.codigo,
            bool(granted_segments(config.identities_file, subject)),
        )

    @app.post(
        "/api/central/v1/convites/cancelar", status_code=204, include_in_schema=False
    )
    def cancel_invite(
        request: Request, reference: AccessReference, manager: tuple[str, Path] = admin
    ):
        require_origin(request)
        actor, registry = manager
        access_management.cancel(registry, actor, reference.id)

    @app.post(
        "/api/central/v1/usuarios/papel", status_code=204, include_in_schema=False
    )
    def change_role(
        request: Request, change: RoleChange, manager: tuple[str, Path] = admin
    ):
        require_origin(request)
        actor, registry = manager
        if change.papel == "convidado_metricas" and config.metrics_dsn is None:
            raise HTTPException(409, "METRICAS_INDISPONIVEL")
        legacy_scopes = granted_segments(config.identities_file, change.id)
        access_management.set_role(
            registry, actor, change.id, change.papel,
            bool(legacy_scopes), legacy_scopes=legacy_scopes,
        )

    @app.post(
        "/api/central/v1/usuarios/revogar", status_code=204, include_in_schema=False
    )
    def revoke(
        request: Request, reference: AccessReference, manager: tuple[str, Path] = admin
    ):
        require_origin(request)
        actor, registry = manager
        access_management.revoke(
            registry,
            actor,
            reference.id,
            bool(granted_segments(config.identities_file, reference.id)),
        )

    @app.get("/api/central/v1/minha-conta", include_in_schema=False)
    def account(identity: Operator = hub_access):
        return {
            "nome": profile_name(config.profiles_db, identity.subject)
            if config.profiles_db
            else "",
            "email": identity.email,
            "nome_editavel": config.profiles_db is not None,
            "mfa_url": config.issuer + "/AddMfaDevice",
        }

    @app.put("/api/central/v1/minha-conta", include_in_schema=False)
    def rename(request: Request, profile: DisplayName, identity: Operator = hub_access):
        require_origin(request)
        if config.profiles_db is None:
            raise HTTPException(503, "PERFIL_CENTRAL_INDISPONIVEL")
        return {
            "nome": profile_name(config.profiles_db, identity.subject, profile.nome)
        }

    @app.get("/api/central/v1/documentacao/openapi.json", include_in_schema=False)
    def documentation(_allowed=hub_access, api: Literal["hub", "central"] = "hub"):
        return hub_openapi() if api == "hub" else app.openapi()

    @app.get(
        "/api/central/v1/infraestrutura",
        tags=["Infraestrutura"],
        summary="Consultar a situação da VPS",
        responses={**access_errors},
    )
    def infrastructure(_allowed=hub_access):
        return read_infrastructure(config.infrastructure_file)

    @app.get(
        "/api/central/v1/consumo",
        tags=["Consumo de APIs"],
        summary="Consultar tráfego e falhas por segmento",
        responses={**access_errors},
    )
    def consumption(
        request: Request,
        ambiente: Environment = "homologacao",
        segmento: Literal["FARMA", "PET"] | None = None,
        api: Literal["hub", "weni"] | None = None,
        antes: Annotated[int | None, Query(ge=1, le=2**53 - 1)] = None,
        so_erros: bool = False,
        identity: Operator = hub_access,
    ):
        dsn, allowed = destination(request, identity, ambiente)
        segment = segmento or allowed[0]
        if segment not in allowed:
            raise HTTPException(403, "SEGMENTO_NAO_AUTORIZADO")
        if not slots.acquire(blocking=False):
            raise HTTPException(503, "CENTRAL_OCUPADA")
        try:
            with read_cursor(dsn, segment) as db:
                return dict(
                    read_consumption(
                        db, segment, api=api, before=antes, only_errors=so_erros
                    ),
                    segmento=segment,
                    ambiente=ambiente,
                )
        except psycopg.Error:
            raise HTTPException(503, "LEITURA_CENTRAL_INDISPONIVEL") from None
        finally:
            slots.release()

    @app.get(
        "/api/central/v1/resumo",
        tags=["Operação"],
        summary="Consultar tarefas, eventos e processamento",
        openapi_extra={
            "parameters": [
                {
                    "in": "query",
                    "name": "segmento",
                    "schema": {"type": "string", "enum": ["FARMA", "PET"]},
                    "description": "Se omitido, usa o primeiro segmento autorizado.",
                }
            ]
        },
        responses={**access_errors, 422: {"description": "Segmento inválido"}},
    )
    def summary(
        request: Request,
        ambiente: Environment = "homologacao",
        identity: Operator = hub_access,
    ):
        params = request.query_params.multi_items()
        names = [name for name, _ in params]
        if len(set(names)) != len(names) or any(
            name not in {"segmento", "ambiente"} for name in names
        ):
            raise HTTPException(422, "CONSULTA_CENTRAL_INVALIDA")
        requested = request.query_params.get("segmento")
        if requested is not None and requested not in SEGMENTS:
            raise HTTPException(422, "SEGMENTO_DA_CONSULTA_INVALIDO")
        dsn, allowed = destination(request, identity, ambiente)
        segment = requested or allowed[0]
        if segment not in allowed:
            raise HTTPException(403, "SEGMENTO_NAO_AUTORIZADO")
        if not slots.acquire(blocking=False):
            raise HTTPException(503, "CENTRAL_OCUPADA")
        try:
            return {
                **read_summary(dsn, segment),
                "ambiente": ambiente,
                "metricas": {"habilitado": metrics_allowed(identity)},
                "integracoes": {"hub": "pronto", "processamento": ambiente},
                "segmentos_autorizados": allowed,
            }
        except psycopg.Error:
            raise HTTPException(503, "LEITURA_CENTRAL_INDISPONIVEL") from None
        finally:
            slots.release()

    return app
