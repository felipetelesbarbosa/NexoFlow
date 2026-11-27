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


def test_documentation_requires_operator_and_describes_each_authentication(
    setup, signing_key, monkeypatch
):
    _, client = setup
    path = "/api/central/v1/documentacao/openapi.json"

    def no_database(*_args, **_kwargs):
        pytest.fail("A documentação não deve abrir o PostgreSQL")

    monkeypatch.setattr(central.psycopg, "connect", no_database)
    assert client.get(path).status_code == 401
    assert (
        client.get(
            path, headers=assertion(token(signing_key, sub="sem-acesso"))
        ).status_code
        == 403
    )
    signed = assertion(token(signing_key))
    response = client.get(path, headers=signed)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    schema = response.json()
    assert schema["paths"]["/saude"]["get"].get("security") is None
    assert schema["paths"]["/tarefas"]["post"]["security"] == [{"TokenHub": []}]
    webhook = schema["paths"]["/v1/webhooks/weni/farma"]["post"]
    assert webhook["security"] == [{"TokenWebhookWeni": []}]
    assert {"200", "401", "409"} <= set(webhook["responses"])
    for value in ("f" * 32, "p" * 32, "w" * 32, "nexoflow_hub_hml"):
        assert value not in response.text

    central_schema = client.get(path, params={"api": "central"}, headers=signed).json()
    assert central_schema["paths"][PATH]["get"]["security"] == [{"SessaoCentral": []}]
    assert path not in central_schema["paths"]
    assert client.get("/openapi.json", headers=signed).status_code == 404


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

        def fetchone(self):
            return {"worker_estado": "sem_sinal"}

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
            "operacao": {"worker_estado": "sem_sinal"},
        }
        assert "REPEATABLE READ, READ ONLY" in statements[-5][0]
        for query, params in statements[-4:]:
            assert params == (segment,)
            if "set_config" not in query:
                assert "WHERE segmento=%s" in query
                if "central_operacao" not in query:
                    assert "LIMIT 50" in query
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


def test_infrastructure_is_authenticated_and_distinguishes_snapshot_states(
    setup, signing_key, tmp_path
):
    from dataclasses import replace
    from datetime import UTC, datetime, timedelta

    config, original = setup
    route = "/api/central/v1/infraestrutura"
    headers = assertion(token(signing_key))
    assert original.get(route, headers=headers).json()["estado"] == "aguardando_coleta"
    snapshot = tmp_path / "vps.json"
    client = TestClient(
        central.create_app(replace(config, infrastructure_file=snapshot))
    )
    assert client.get(route).status_code == 401
    assert client.post(route, headers=headers).status_code == 405
    assert client.get(route, headers=headers).json()["estado"] == "aguardando_coleta"

    values = {
        "hostname": "srv.example.test",
        "sistema": "Ubuntu",
        "estado": "running",
        "cidade": None,
        "pais": None,
        "ipv4": "192.0.2.1",
        "plano": "KVM 4",
        "nucleos": 4,
        "ram_bytes": None,
        "disco_bytes": None,
        "banda_bytes": None,
        "validade": None,
        "renovacao_automatica": True,
        "ultimo_backup_provedor": None,
        "metricas": None,
        "segredo_teste": "deve ser excluído",
    }
    for minutes, state in ((0, "disponivel"), (21, "desatualizado")):
        snapshot.write_text(
            json.dumps(
                dict(
                    values,
                    coletado_em=(
                        datetime.now(UTC) - timedelta(minutes=minutes)
                    ).isoformat(),
                )
            ),
            encoding="utf-8",
        )
        response = client.get(route, headers=headers)
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["estado"] == state
        assert response.json()["vps"]["ipv4"] == "192.0.2.1"
        assert "segredo_teste" not in response.json()["vps"]
    snapshot.write_text("incompleto", encoding="utf-8")
    assert client.get(route, headers=headers).json() == {
        "estado": "indisponivel",
        "vps": None,
    }
    config.identities_file.write_text("{}", encoding="utf-8")
    assert client.get(route, headers=headers).status_code == 403


def test_collect_vps_only_uses_the_selected_inventory_and_last_24_hours():
    from datetime import UTC, datetime, timedelta
    from urllib.error import HTTPError

    from nexoflow_hub.collect_vps import collect

    now = datetime(2026, 11, 23, 19, tzinfo=UTC)
    vm = {
        "id": 99,
        "data_center_id": 2,
        "subscription_id": "assinatura-certa",
        "hostname": "vps.example.test",
        "state": "running",
        "cpus": 4,
        "memory": 16384,
        "disk": 204800,
        "bandwidth": 16384000,
        "ipv4": [{"address": "192.0.2.1"}],
        "template": {"name": "Ubuntu"},
    }
    components = {
        "/vps/v1/virtual-machines/99": vm,
        "/vps/v1/data-centers": [{"id": 2, "city": "Campinas", "location": "br"}],
        "/billing/v1/subscriptions": {
            "data": [
                {"id": "outra", "is_auto_renewed": False},
                {"id": "assinatura-certa", "is_auto_renewed": True, "valor": "privado"},
            ]
        },
        "/vps/v1/virtual-machines/99/backups": {
            "data": [
                {"created_at": "2026-11-19T12:00:01Z"},
                {"created_at": "2026-11-12T17:19:36Z"},
            ]
        },
        "/vps/v1/virtual-machines/99/metrics": {
            "cpu_usage": {
                "unit": "%",
                "usage": {
                    str(int(now.timestamp())): 0,
                    str(int((now - timedelta(hours=25)).timestamp())): 99,
                },
            },
            "ram_usage": {"unit": "bytes", "usage": {}},
        },
    }

    def get(path, params=None):
        if path.endswith("/metrics"):
            assert params == {
                "date_from": "2026-11-22T19:00:00+00:00",
                "date_to": "2026-11-23T19:00:00+00:00",
            }
        return components[path]

    vps = collect(get, 99, now)
    assert vps.pais == "BR"
    assert vps.ram_bytes == 16 * 1024**3
    assert vps.renovacao_automatica is True
    assert vps.validade is None
    assert vps.ultimo_backup_provedor == datetime(2026, 11, 19, 12, 0, 1, tzinfo=UTC)
    assert vps.metricas is not None and vps.metricas.cpu == [(now, 0)]
    assert vps.metricas.ram == []
    assert "privado" not in vps.model_dump_json()

    def limited(path, params=None):
        if path.startswith("/billing"):
            raise HTTPError("", 403, "sem acesso", {}, None)
        return get(path, params)

    assert collect(limited, 99, now).renovacao_automatica is None
    vm["id"] = 1
    with pytest.raises(ValueError, match="VPS_DIVERGENTE"):
        collect(get, 99, now)


def test_environment_uses_separate_grant_and_never_falls_back(
    setup, signing_key, tmp_path, monkeypatch
):
    from dataclasses import replace

    config, _ = setup
    grants = tmp_path / "producao.json"
    grants.write_text('{"operador-f":"PET"}')
    production = central.ProductionReader(
        "dbname=nexoflow_hub_prod user=hub_central_leitor", grants
    )
    client = TestClient(central.create_app(replace(config, production=production)))
    headers = {
        **assertion(token(signing_key)),
        "X-Central-Host": central.PRODUCTION_HOST,
    }
    path = "/api/central/v1/sessao"
    assert client.get(path, headers=headers).json()["ambientes"] == [
        "homologacao",
        "producao",
    ]
    alias = headers | {"X-Central-Host": "central-hml.nexoflowhub.com.br"}
    assert client.get(path, headers=alias).json()["ambientes"] == ["homologacao"]

    calls = []

    def summary(dsn, segment):
        calls.append((dsn, segment))
        return {"segmento": segment}

    @contextmanager
    def read_cursor(dsn, segment):
        calls.append((dsn, segment))
        yield object()

    monkeypatch.setattr(central, "read_summary", summary)
    monkeypatch.setattr(central, "read_cursor", read_cursor)
    monkeypatch.setattr(central, "read_consumption", lambda *_args, **_kwargs: {})
    for route in [PATH, "/api/central/v1/consumo"]:
        assert (
            client.get(route + "?ambiente=producao", headers=alias).status_code == 403
        )
        assert (
            client.get(
                route + "?ambiente=producao&segmento=FARMA", headers=headers
            ).status_code
            == 403
        )
        res = client.get(route + "?ambiente=producao", headers=headers)
        assert res.json()["ambiente"] == "producao"
        assert res.json()["segmento"] == "PET"
        assert calls[-1] == (production.dsn, "PET")
        res = client.get(route, headers=headers)
        assert res.json()["ambiente"] == "homologacao"
        assert calls[-1] == (config.dsn, "FARMA")

    grants.write_text("{}")
    assert client.get(PATH + "?ambiente=producao", headers=headers).status_code == 403
    assert len(calls) == 4
    with pytest.raises(ValueError, match="DESTINO_LEITURA_PROD"):
        central.ProductionReader(config.dsn, grants)


def test_self_service_name_uses_signed_subject_and_same_origin(
    setup, signing_key, tmp_path
):
    from dataclasses import replace

    config, _ = setup
    settings = replace(config, profiles_db=tmp_path / "perfis.sqlite3")
    client = TestClient(central.create_app(settings))
    route = "/api/central/v1/minha-conta"
    assert client.get(route).status_code == 401

    headers = {
        **assertion(token(signing_key)),
        "X-Central-Host": central.PRODUCTION_HOST,
        "Origin": "https://" + central.PRODUCTION_HOST,
    }
    assert (
        client.put(
            route,
            json={"nome": "Outro"},
            headers=headers | {"Origin": "https://outro.example"},
        ).status_code
        == 403
    )
    assert (
        client.put(
            route,
            json={"nome": "Outro", "email": "outro@example.invalid"},
            headers=headers,
        ).status_code
        == 422
    )
    assert client.put(route, json={"nome": "  "}, headers=headers).status_code == 422
    assert (
        client.put(route, json={"nome": "Fábio\nSilva"}, headers=headers).status_code
        == 422
    )
    assert client.put(
        route, json={"nome": "  Fábio Silva  "}, headers=headers
    ).json() == {"nome": "Fábio Silva"}

    reloaded = TestClient(central.create_app(settings))
    assert reloaded.get(route, headers=headers).json() == {
        "nome": "Fábio Silva",
        "email": "operador@example.invalid",
        "nome_editavel": True,
        "mfa_url": "https://ensaio.cloudflareaccess.com/AddMfaDevice",
    }
    other = assertion(
        token(signing_key, sub="operador-p", email="pessoa-p@example.invalid")
    )
    assert reloaded.get(route, headers=other).json()["nome"] == ""


def test_super_admin_invites_and_revokes_central_access(
    setup, signing_key, tmp_path, monkeypatch
):
    from dataclasses import replace

    config, _ = setup
    settings = replace(
        config, profiles_db=tmp_path / "perfis.sqlite3", super_admin="operador-f"
    )
    client = TestClient(central.create_app(settings))
    prefix = "/api/central/v1"
    origin = {
        "X-Central-Host": central.PRODUCTION_HOST,
        "Origin": "https://" + central.PRODUCTION_HOST,
    }
    manager = origin | assertion(token(signing_key))
    invited = origin | assertion(
        token(signing_key, sub="novato", email="novo@example.invalid")
    )
    viewer = origin | assertion(token(signing_key, sub="operador-p"))
    wrong = origin | assertion(
        token(signing_key, sub="novato", email="outro@example.invalid")
    )
    request = {"email": "Novo@Example.invalid", "segmentos": ["PET"]}

    assert client.get(prefix + "/usuarios", headers=viewer).status_code == 403
    assert (
        client.post(prefix + "/convites", headers=viewer, json=request).status_code
        == 403
    )
    assert client.get(prefix + "/sessao", headers=manager).json()["gerencia_usuarios"]
    assert (
        client.get(prefix + "/sessao", headers=viewer).json()["gerencia_usuarios"]
        is False
    )
    assert (
        client.post(
            prefix + "/convites",
            headers=manager | {"Origin": "https://outro.example"},
            json=request,
        ).status_code
        == 403
    )

    issued = client.post(prefix + "/convites", headers=manager, json=request)
    assert issued.status_code == 201
    invite = issued.json()
    assert (
        client.post(prefix + "/convites", headers=manager, json=request).status_code
        == 409
    )
    roster = client.get(prefix + "/usuarios", headers=manager)
    assert invite["codigo"] not in roster.text
    assert roster.json()["convites"][0]["estado"] == "pendente"

    code = {"codigo": invite["codigo"]}
    assert (
        client.post(prefix + "/convites/aceitar", headers=wrong, json=code).status_code
        == 403
    )
    assert client.get(prefix + "/minha-conta", headers=invited).status_code == 403
    assert (
        client.post(
            prefix + "/convites/aceitar", headers=invited, json=code
        ).status_code
        == 204
    )
    assert (
        client.post(
            prefix + "/convites/aceitar", headers=invited, json=code
        ).status_code
        == 403
    )
    assert client.get(prefix + "/minha-conta", headers=invited).status_code == 200
    assert client.get(PATH + "?segmento=FARMA", headers=invited).status_code == 403
    assert client.get(PATH + "?ambiente=producao", headers=invited).status_code == 403
    assert client.get(prefix + "/usuarios", headers=invited).status_code == 403

    for subject, credentials in [("novato", invited), ("operador-p", viewer)]:
        assert (
            client.post(
                prefix + "/usuarios/revogar", headers=manager, json={"id": subject}
            ).status_code
            == 204
        )
        assert (
            client.get(prefix + "/minha-conta", headers=credentials).status_code == 403
        )
    assert (
        client.post(
            prefix + "/usuarios/revogar", headers=manager, json={"id": "operador-f"}
        ).status_code
        == 409
    )
    assert client.get(prefix + "/usuarios", headers=manager).status_code == 200

    cancelled = client.post(prefix + "/convites", headers=manager, json=request).json()
    assert (
        client.post(
            prefix + "/convites/cancelar", headers=manager, json={"id": cancelled["id"]}
        ).status_code
        == 204
    )
    assert (
        client.post(
            prefix + "/convites/aceitar",
            headers=invited,
            json={"codigo": cancelled["codigo"]},
        ).status_code
        == 403
    )

    expiring = client.post(prefix + "/convites", headers=manager, json=request).json()
    monkeypatch.setattr(
        central.access_management, "time", lambda: expiring["expira_em"]
    )
    assert (
        client.post(
            prefix + "/convites/aceitar",
            headers=invited,
            json={"codigo": expiring["codigo"]},
        ).status_code
        == 403
    )
    assert (
        client.get(prefix + "/usuarios", headers=manager).json()["convites"][0][
            "estado"
        ]
        == "expirado"
    )


def test_metrics_pilot_requires_owner_farma_and_pinned_read(
    setup, signing_key, tmp_path, monkeypatch
):
    from dataclasses import replace
    from datetime import date
    from uuid import UUID

    config, existing = setup
    secrets = assertion(token(signing_key))
    route = "/api/central/v1/metricas/vendas"
    query = {"inicio": "2026-11-01", "fim": "2026-11-03", "revisao": str(UUID(int=5))}
    assert existing.get(route, params=query, headers=secrets).status_code == 403
    dsn = "dbname=nexoflow_datastudio user=nf_metricas_farma_leitor"
    settings = replace(
        config,
        profiles_db=tmp_path / "perfis.sqlite3",
        super_admin="operador-f",
        metrics_dsn=dsn,
    )
    client = TestClient(central.create_app(settings))
    other = assertion(token(signing_key, sub="operador-p"))
    assert client.get(route, params=query).status_code == 401
    assert client.get(route, params=query, headers=other).status_code == 403
    assert (
        "metricas_farma"
        not in client.get("/api/central/v1/sessao", headers=other).json()
    )
    assert client.get("/api/central/v1/sessao", headers=secrets).json()[
        "metricas_farma"
    ]

    calls = []

    def read(target, start, end, expected):
        calls.append((target, start, end, expected))
        return central.metricas.SalesReport(
            revisao=UUID(int=5),
            versao=14,
            inicio=start,
            fim=end,
            totais=central.metricas.SalesTotals(),
            dias=[],
        )

    monkeypatch.setattr(central.metricas, "read_sales", read)
    assert (
        client.get(
            route, params={**query, "fim": "2025-04-01"}, headers=secrets
        ).status_code
        == 422
    )
    assert (
        client.get(
            route, params={**query, "fim": "2028-04-01"}, headers=secrets
        ).status_code
        == 422
    )
    result = client.get(route, params=query, headers=secrets)
    assert result.status_code == 200
    assert result.json()["dias"] == []
    assert calls == [(dsn, date(2026, 11, 1), date(2026, 11, 3), UUID(int=5))]
    assert result.headers["Cache-Control"] == "no-store"
    settings.identities_file.write_text('{"operador-f": "PET"}')
    assert client.get(route, params=query, headers=secrets).status_code == 403
    assert len(calls) == 1
    with pytest.raises(ValueError, match="DESTINO_METRICAS_FARMA_INVALIDO"):
        replace(settings, metrics_dsn=config.dsn)


def test_admin_requires_active_farma_and_cannot_manage_users(
    setup, signing_key, tmp_path, monkeypatch
):
    from dataclasses import replace
    from uuid import UUID

    config, _ = setup
    readers = tmp_path / "leitores.json"
    readers.write_text('{"convidado-f": true, "operador-p": true}')
    settings = replace(
        config,
        profiles_db=tmp_path / "perfis.sqlite3",
        super_admin="operador-f",
        metrics_dsn="dbname=nexoflow_datastudio user=nf_metricas_farma_leitor",
        metrics_readers_file=readers,
    )
    client = TestClient(central.create_app(settings))
    prefix = "/api/central/v1"
    route = prefix + "/metricas/vendas"
    query = {"inicio": "2026-11-01", "fim": "2026-11-03"}
    origin = {
        "X-Central-Host": central.PRODUCTION_HOST,
        "Origin": "https://" + central.PRODUCTION_HOST,
    }
    manager = origin | assertion(token(signing_key))
    invited = origin | assertion(
        token(signing_key, sub="convidado-f", email="leitor@example.invalid")
    )
    pet = assertion(token(signing_key, sub="operador-p"))

    def read(_dsn, start, end, _revision):
        return central.metricas.SalesReport(
            revisao=UUID(int=5),
            versao=14,
            inicio=start,
            fim=end,
            totais=central.metricas.SalesTotals(),
            dias=[],
        )

    monkeypatch.setattr(central.metricas, "read_sales", read)
    assert client.get(route, params=query, headers=invited).status_code == 403
    assert client.get(route, params=query, headers=pet).status_code == 403

    request = {"email": "leitor@example.invalid", "segmentos": ["FARMA", "PET"], "papel": "admin"}
    invite = client.post(prefix + "/convites", headers=manager, json=request)
    assert invite.status_code == 201
    accepted = client.post(
        prefix + "/convites/aceitar", headers=invited,
        json={"codigo": invite.json()["codigo"]},
    )
    assert accepted.status_code == 204
    assert client.get(prefix + "/sessao", headers=invited).json() == {
        "ambientes": ["homologacao"], "metricas_farma": True,
        "gerencia_usuarios": False, "papel": "admin",
    }
    assert client.get(route, params=query, headers=invited).status_code == 200
    assert client.get(prefix + "/usuarios", headers=invited).status_code == 403
    assert client.post(prefix + "/convites", headers=invited, json=request).status_code == 403
    assert client.post(
        prefix + "/usuarios/papel", headers=invited,
        json={"id": "convidado-f", "papel": "admin"},
    ).status_code == 403
    assert client.post(
        prefix + "/usuarios/revogar", headers=invited, json={"id": "operador-p"}
    ).status_code == 403
    assert client.post(
        prefix + "/convites/cancelar", headers=invited, json={"id": invite.json()["id"]}
    ).status_code == 403
    assert client.get(PATH + "?ambiente=producao", headers=invited).status_code == 403
    monkeypatch.setattr(central, "read_summary", lambda _dsn, seg: {"segmento": seg})
    for seg in ("FARMA", "PET"):
        response = client.get(PATH, headers=invited, params={"segmento": seg})
        assert response.status_code == 200 and response.json()["segmento"] == seg

    readers.write_text("{}")
    assert client.get(route, params=query, headers=invited).status_code == 200
    # O papel é explícito; um arquivo legado não reativa Métricas depois da redução.
    readers.write_text('{"convidado-f": true}')
    demoted = client.post(
        prefix + "/usuarios/papel", headers=manager,
        json={"id": "convidado-f", "papel": "convidado"},
    )
    assert demoted.status_code == 204
    assert client.get(route, params=query, headers=invited).status_code == 403
    assert client.get(prefix + "/minha-conta", headers=invited).status_code == 200
    assert client.get(prefix + "/sessao", headers=invited).json()["papel"] == "convidado"
    assert client.post(
        prefix + "/usuarios/papel", headers=manager,
        json={"id": "convidado-f", "papel": "admin"},
    ).status_code == 204
    assert client.get(route, params=query, headers=invited).status_code == 200
    assert client.post(
        prefix + "/usuarios/papel", headers=manager,
        json={"id": "operador-f", "papel": "convidado"},
    ).status_code == 409
    assert client.post(
        prefix + "/usuarios/papel", headers=manager,
        json={"id": "convidado-f", "papel": "super_admin"},
    ).status_code == 422
    assert client.post(
        prefix + "/usuarios/papel", headers=manager,
        json={"id": "sem-acesso", "papel": "admin"},
    ).status_code == 404
    assert client.get(prefix + "/sessao", headers=manager).json()["papel"] == "super_admin"
    assert client.get(prefix + "/usuarios", headers=manager).status_code == 200

    revoked = client.post(
        prefix + "/usuarios/revogar", headers=manager, json={"id": "convidado-f"},
    )
    assert revoked.status_code == 204
    assert client.get(route, params=query, headers=invited).status_code == 403
    assert client.post(
        prefix + "/usuarios/papel", headers=manager,
        json={"id": "convidado-f", "papel": "admin"},
    ).status_code == 404
    # Reaceite com convite padrão não reaproveita o papel anterior.
    guest_invite = client.post(
        prefix + "/convites", headers=manager,
        json={"email": "leitor@example.invalid", "segmentos": ["FARMA"]},
    )
    assert guest_invite.status_code == 201
    assert client.post(
        prefix + "/convites/aceitar", headers=invited,
        json={"codigo": guest_invite.json()["codigo"]},
    ).status_code == 204
    assert client.get(prefix + "/sessao", headers=invited).json()["papel"] == "convidado"
    assert client.get(route, params=query, headers=invited).status_code == 403


def test_role_migration_preserves_old_profiles_invites_and_revocations(
    setup, signing_key, tmp_path
):
    import sqlite3
    from dataclasses import replace

    config, _ = setup
    db_path = tmp_path / "perfis.sqlite3"
    with sqlite3.connect(db_path) as db:
        db.executescript("""
            CREATE TABLE central_members (subject TEXT PRIMARY KEY, email TEXT,
              scopes TEXT NOT NULL, revoked INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE central_invites (id TEXT PRIMARY KEY, digest TEXT NOT NULL UNIQUE,
              email TEXT NOT NULL, scopes TEXT NOT NULL, expires_at INTEGER NOT NULL,
              status TEXT NOT NULL DEFAULT 'pendente');
            CREATE TABLE profiles (subject TEXT PRIMARY KEY, name TEXT NOT NULL);
            INSERT INTO central_members VALUES ('ja-aceito','leitor@example.invalid','["FARMA"]',0);
            INSERT INTO central_members VALUES ('revogado','r@example.invalid','["FARMA"]',1);
            INSERT INTO central_invites VALUES ('antigo','digest','leitor@example.invalid','["FARMA"]',9999999999,'aceito');
            INSERT INTO profiles VALUES ('ja-aceito','Nome preservado');
        """)
    readers = tmp_path / "leitores.json"
    readers.write_text('{"ja-aceito": true, "revogado": true}')
    settings = replace(
        config, profiles_db=db_path, super_admin="operador-f",
        metrics_dsn="dbname=nexoflow_datastudio user=nf_metricas_farma_leitor",
        metrics_readers_file=readers,
    )
    client = TestClient(central.create_app(settings))
    prefix = "/api/central/v1"
    signed = assertion(token(signing_key, sub="ja-aceito", email="leitor@example.invalid"))
    assert client.get(prefix + "/sessao", headers=signed).json()["papel"] == "admin"
    assert client.get(prefix + "/minha-conta", headers=signed).json()["nome"] == "Nome preservado"
    manager = assertion(token(signing_key))
    overview = client.get(prefix + "/usuarios", headers=manager).json()
    assert overview["convites"][0]["estado"] == "aceito"
    assert overview["convites"][0]["papel"] == "convidado"
    assert all(u["id"] != "revogado" for u in overview["usuarios"])
    assert client.get(
        prefix + "/sessao", headers=assertion(token(signing_key, sub="revogado"))
    ).status_code == 403
