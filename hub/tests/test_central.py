"""Central de Operações: autenticação individual e consulta isolada por segmento."""

from __future__ import annotations

import json
import time
from contextlib import contextmanager

import jwt
import psycopg
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from nexoflow_hub import central


@pytest.fixture(scope="module")
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def setup(tmp_path, signing_key):
    identities = tmp_path / "escopos.json"
    identities.write_text(json.dumps({"operador-f": "FARMA", "operador-p": "PET"}))
    jwks = tmp_path / "jwks.json"
    key = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(signing_key.public_key()))
    jwks.write_text(json.dumps({"keys": [dict(key, kid="hml", use="sig")]}))
    config = central.CentralSettings(
        "dbname=nexoflow_hub_hml user=hub_central_leitor",
        "https://ensaio.cloudflareaccess.com",
        "aud-central",
        jwks,
        identities,
    )
    return config, TestClient(central.create_app(config))


def token(key, *, kid="hml", **claims):
    now = int(time.time())
    payload = {
        "iss": "https://ensaio.cloudflareaccess.com",
        "aud": ["aud-central"],
        "exp": now + 600,
        "iat": now - 10,
        "type": "app",
        "sub": "operador-f",
        "email": "operador@example.invalid",
    }
    return jwt.encode(payload | claims, key, algorithm="RS256", headers={"kid": kid})


PATH = "/api/central/v1/resumo"


def assertion(value):
    return {"Cf-Access-Jwt-Assertion": value}


def test_real_signature_and_database_scope(setup, signing_key, monkeypatch):
    config, client = setup
    statements = []

    class DB:
        @contextmanager
        def cursor(self, *, row_factory):
            yield self

        def execute(self, query, params=()):
            statements.append((query, params))
            return self

        def fetchall(self):
            return []

    @contextmanager
    def connect(dsn, **options):
        assert (
            dsn == config.dsn
            and "default_transaction_read_only=on" in options["options"]
        )
        yield DB()

    monkeypatch.setattr(central.psycopg, "connect", connect)
    for grant, selected, segment in [
        ("FARMA", None, "FARMA"),
        (["PET"], "PET", "PET"),
        (["PET", "FARMA"], None, "PET"),
        (["PET", "FARMA"], "FARMA", "FARMA"),
    ]:
        config.identities_file.write_text(json.dumps({"operador-f": grant}))
        headers = assertion(token(signing_key))
        response = client.get(
            PATH, params={"segmento": selected} if selected else {}, headers=headers
        )
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store"
        assert response.json() == {
            "segmento": segment,
            "segmentos_autorizados": [grant] if isinstance(grant, str) else grant,
            "ambiente": "homologacao",
            "metricas": {"habilitado": False},
            "tarefas": [],
            "integracoes": {"hub": "pronto", "processamento": "homologacao"},
            "eventos": [],
        }
        assert "REPEATABLE READ, READ ONLY" in statements[-4][0]
        for query, params in statements[-3:]:
            assert params == (segment,)
            if "set_config" not in query:
                assert "WHERE segmento=%s" in query and "LIMIT 50" in query
        assert client.post(PATH, headers=headers).status_code == 405
        assert client.get("/tarefas", headers=headers).status_code == 404

    # A retirada de uma marca entra em vigor ainda com a mesma asserção assinada.
    operations = len(statements)
    config.identities_file.write_text('{"operador-f":["PET"]}')
    assert client.get(PATH + "?segmento=FARMA", headers=headers).status_code == 403
    assert len(statements) == operations
    config.identities_file.write_text("{}")
    assert client.get(PATH, headers=headers).status_code == 403


@pytest.mark.parametrize(
    "claims",
    [
        {"aud": "outra-aplicacao"},
        {"iss": "https://outra.cloudflareaccess.com"},
        {"exp": 10},
        {"nbf": int(time.time()) + 3600},
        {"iat": int(time.time()) + 3600},
        {"type": "org"},
        {"common_name": "servico"},
        {"email": ""},
        {"kid": "unknown"},
    ],
)
def test_denies_invalid_claims(setup, signing_key, claims):
    _, client = setup
    response = client.get(PATH, headers=assertion(token(signing_key, **claims)))
    assert response.status_code == 401
    assert response.headers["Cache-Control"] == "no-store"


def test_denies_unsigned_or_wrong_signer_and_headers(setup, signing_key):
    _, client = setup
    assert (
        client.get(
            PATH, headers={"Cf-Access-Authenticated-User-Email": "x"}
        ).status_code
        == 401
    )
    assert (
        client.get(
            PATH, headers={"Authorization": "Bearer " + token(signing_key)}
        ).status_code
        == 401
    )
    different_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert client.get(PATH, headers=assertion(token(different_key))).status_code == 401
    unsigned = jwt.encode(
        {"sub": "operador-f"}, None, algorithm="none", headers={"kid": "hml"}
    )
    assert client.get(PATH, headers=assertion(unsigned)).status_code == 401


def test_connection_failure_and_broken_configuration_are_sanitized(
    setup, signing_key, monkeypatch
):
    config, client = setup

    def fail(*args, **kwargs):
        raise psycopg.OperationalError("DADO_INTERNO")

    monkeypatch.setattr(central.psycopg, "connect", fail)
    headers = assertion(token(signing_key))
    response = client.get(PATH, headers=headers)
    assert response.status_code == 503
    assert "DADO_INTERNO" not in response.text
    assert "eventos" not in response.json()
    config.identities_file.write_text('{"operador-f":"FARMA", "operador-f":"PET"}')
    assert client.get(PATH, headers=headers).status_code == 503
    config.jwks_file.unlink()
    assert client.get(PATH, headers=headers).status_code == 503


@pytest.mark.parametrize(
    "dsn",
    [
        "dbname=nexoflow_datastudio user=hub_central_leitor",
        "dbname=nexoflow_hub_hml user=bootstrap_hml",
    ],
)
def test_rejects_wrong_database_or_publisher_role(tmp_path, dsn):
    with pytest.raises(ValueError, match="DESTINO_LEITURA_HML"):
        central.CentralSettings(
            dsn, "https://ensaio.cloudflareaccess.com", "aud", tmp_path, tmp_path
        )


@pytest.mark.parametrize(
    "query",
    [
        "?segmento=",
        "?segmento",
        "?segmento=farma",
        "?segmento=OUTRO",
        "?extra=PET",
        "?segmento=FARMA&segmento=FARMA",
        "?segmento=PET&extra=FARMA",
        "?segmento=FARMA&segmento=PET",
    ],
)
def test_invalid_query_stops_before_database(setup, signing_key, query, monkeypatch):
    _, client = setup
    monkeypatch.setattr(
        central, "read_summary", lambda *_: pytest.fail("consulta indevida")
    )
    assert (
        client.get(PATH + query, headers=assertion(token(signing_key))).status_code
        == 422
    )


@pytest.mark.parametrize(
    "grant", [[], ["PET", "PET"], ["FARMA", "OUTRO"], [{}], 7, None]
)
def test_invalid_grant_never_permits_default_or_requested_scope(
    setup, signing_key, grant, monkeypatch
):
    config, client = setup
    monkeypatch.setattr(
        central, "read_summary", lambda *_: pytest.fail("consulta indevida")
    )
    config.identities_file.write_text(json.dumps({"operador-f": grant}))
    for query in ("", "?segmento=FARMA"):
        assert (
            client.get(PATH + query, headers=assertion(token(signing_key))).status_code
            == 403
        )
