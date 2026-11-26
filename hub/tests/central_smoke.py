"""Ensaio da Central no projeto Docker descartável de run_docker_hml."""

from __future__ import annotations

import json
import re
import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import jwt
import psycopg
from cryptography.hazmat.primitives.asymmetric import rsa

ISSUER = "https://homologacao-sintetica.cloudflareaccess.com"
AUDIENCE = "central-de-operacoes-hml"
SUMMARY = "/api/central/v1/resumo"
CONSUMPTION = "/api/central/v1/consumo"
INFRASTRUCTURE = "/api/central/v1/infraestrutura"
OPENAPI = "/api/central/v1/documentacao/openapi.json"
EVENT = "/v1/webhooks/weni/farma"


def prepare(secret_dir):
    """Gera material exclusivo do ensaio, sem chaves ou serviços externos."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update(kid="hml", alg="RS256", use="sig")
    password = secrets.token_hex(32)
    files = {
        "central_password": password,
        "central_dsn": f"host=postgres-hml dbname=nexoflow_hub_hml user=hub_central_leitor password={password}",
        "central_jwks.json": json.dumps({"keys": [jwk]}),
        "central_identidades.json": json.dumps(
            {
                "operator-farma": "FARMA",
                "operator-pet": "PET",
                "operator-ambos": ["FARMA", "PET"],
            }
        ),
        "weni_farma": secrets.token_hex(32),
    }
    for name, content in files.items():
        path = secret_dir / name
        path.write_text(content, encoding="utf-8")
        # O diretório pai privado é 0700; o Compose monta só os arquivos de cada serviço.
        path.chmod(0o644)
    return key


def access_header(key, subject):
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "iss": ISSUER,
            "aud": [AUDIENCE],
            "sub": subject,
            "email": subject + "@hml.invalid",
            "type": "app",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        key,
        algorithm="RS256",
        headers={"kid": "hml"},
    )
    return {"Cf-Access-Jwt-Assertion": token}


def assert_reader_grants(reader_dsn):
    with psycopg.connect(reader_dsn, connect_timeout=4) as db:
        role = db.execute(
            "SELECT rolname, rolsuper, rolcreaterole, rolcreatedb, rolbypassrls "
            "FROM pg_roles WHERE rolname=current_user"
        ).fetchone()
        assert role == ("hub_central_leitor", False, False, False, False)
        for view in (
            "hub.central_tarefas",
            "hub.central_eventos",
            "hub.central_operacao",
            "hub.central_api_requisicoes",
        ):
            assert db.execute(
                "SELECT has_table_privilege(%s, 'SELECT')", (view,)
            ).fetchone() == (True,)
            assert db.execute(
                "SELECT has_table_privilege(%s, 'INSERT,UPDATE,DELETE')", (view,)
            ).fetchone() == (False,)
        for table in (
            "hub.tarefas",
            "hub.eventos_weni",
            "hub.checkpoints",
            "hub.sinal_worker",
            "hub.api_requisicoes",
        ):
            assert db.execute(
                "SELECT has_table_privilege(%s, 'SELECT,INSERT,UPDATE,DELETE')",
                (table,),
            ).fetchone() == (False,)


def verify(*, web_ip, api_ip, pg_ip, secret_dir, key, farma_id, pet_id, wait):
    """Usa o IP privado dos contêineres sintéticos no Docker Linux local."""
    reader_dsn = (
        (secret_dir / "central_dsn")
        .read_text()
        .replace("host=postgres-hml", "host=" + pg_ip)
    )
    assert_reader_grants(reader_dsn)
    web = "http://" + web_ip + ":8080"
    api = "http://" + api_ip + ":8000"
    farma = access_header(key, "operator-farma")
    pet = access_header(key, "operator-pet")
    both = access_header(key, "operator-ambos")
    hook = {"Authorization": "Bearer " + (secret_dir / "weni_farma").read_text()}
    event = {
        "evento_id": str(uuid4()),
        "tipo": "atendimento_transferido",
        "ocorrido_em": "2026-11-23T08:15:00-03:00",
    }
    with httpx.Client(trust_env=False, timeout=4) as client:
        wait(
            lambda: client.get(web + SUMMARY, headers=farma).status_code == 200,
            "central_api_via_origem_do_frontend",
        )
        page = client.get(web + "/")
        assert (
            page.status_code == 200
            and "<script" in page.text
            and "text/html" in page.headers["content-type"]
        )
        assets = re.findall(r'(?:href|src)="(/assets/[A-Za-z0-9_.-]+)"', page.text)
        assert any(path.endswith(".js") for path in assets)
        assert any(path.endswith(".css") for path in assets)
        for path in assets:
            asset = client.get(web + path)
            assert asset.status_code == 200 and len(asset.content) > 0
            assert "text/html" not in asset.headers.get("content-type", "")
        assert client.get(web + SUMMARY).status_code == 401
        assert client.get(web + INFRASTRUCTURE).status_code == 401
        assert client.get(web + OPENAPI).status_code == 401
        contract = client.get(web + OPENAPI, headers=farma)
        assert contract.status_code == 200
        assert contract.json()["paths"][EVENT]["post"]["security"] == [
            {"TokenWebhookWeni": []}
        ]
        swagger = client.get(web + "/swagger.html")
        assert swagger.status_code == 200
        assert "/assets/swagger-ui-bundle.js" in swagger.text
        assert client.get(web + "/assets/swagger-ui-bundle.js").status_code == 200
        infrastructure = client.get(web + INFRASTRUCTURE, headers=farma)
        assert infrastructure.status_code == 200
        assert infrastructure.json() == {"estado": "aguardando_coleta", "vps": None}
        assert (
            client.get(
                web + SUMMARY, params={"segmento": "PET"}, headers=farma
            ).status_code
            == 403
        )
        assert (
            client.get(
                web + SUMMARY, headers=access_header(key, "sem-acesso")
            ).status_code
            == 403
        )
        assert client.post(api + EVENT, json=event).status_code == 401
        integration = {"Authorization": "Bearer " + (secret_dir / "farma").read_text()}
        assert client.post(api + EVENT, json=event, headers=integration).status_code == 401
        request = {
            "segmento": "FARMA", "origem": "n8n", "chave": "ensaio-docker",
            "cenario": "dados_incompletos",
        }
        created = client.post(api + "/tarefas/noturno", json=request, headers=integration)
        assert created.status_code == 202
        noturno_id = created.json()["id"]
        replay = client.post(api + "/tarefas/noturno", json=request, headers=integration)
        assert replay.status_code == 202 and replay.json()["id"] == noturno_id
        task_url = api + "/tarefas/" + noturno_id
        wait(
            lambda: client.get(task_url, headers=integration).json()["estado"] == "parcial",
            "noturno_api_worker_com_pendencia_isolada",
        )
        stages = client.get(task_url + "/etapas", headers=integration).json()["etapas"]
        assert len(stages) == 5 and all(stage["estado"] == "concluida" for stage in stages)
        accepted = client.post(api + EVENT, json=event, headers=hook)
        assert accepted.status_code == 200 and accepted.json()["estado"] == "CONFIRMADO"
        again = client.post(api + EVENT, json=event, headers=hook)
        assert again.status_code == 200 and again.json() == accepted.json()
        assert client.get(web + CONSUMPTION).status_code == 401
        assert (
            client.get(
                web + CONSUMPTION, headers=farma, params={"segmento": "PET"}
            ).status_code
            == 403
        )

        def logged():
            logged_response = client.get(
                web + CONSUMPTION, headers=farma, params={"api": "weni"}
            )
            assert logged_response.status_code == 200
            data = logged_response.json()
            return len(data["requisicoes"]) == 2 and all(
                item["endpoint"] == "/v1/webhooks/weni/farma"
                and item["corpo"] == {"tipo": "atendimento_transferido"}
                and item["http"] == 200
                for item in data["requisicoes"]
            )

        wait(logged, "consumo_central_reenvio_weni_com_detalhe_sanitizado")
        assert (
            client.get(web + CONSUMPTION, headers=pet, params={"api": "weni"}).json()[
                "requisicoes"
            ]
            == []
        )
        changed = dict(event, ocorrido_em="2026-11-23T08:16:00-03:00")
        assert client.post(api + EVENT, json=changed, headers=hook).status_code == 409
        for segment, credentials, granted, params in (
            ("FARMA", farma, ["FARMA"], {}),
            ("PET", pet, ["PET"], {}),
            ("FARMA", both, ["FARMA", "PET"], {}),
            ("PET", both, ["FARMA", "PET"], {"segmento": "PET"}),
        ):
            response = client.get(web + SUMMARY, headers=credentials, params=params)
            assert response.status_code == 200
            summary = response.json()
            assert (
                summary["segmento"] == segment and summary["ambiente"] == "homologacao"
            )
            assert summary["segmentos_autorizados"] == granted
            assert summary["metricas"] == {"habilitado": False}
            operation = summary["operacao"]
            assert operation["worker_estado"] == "ativo"
            assert operation["worker_ultimo_ciclo_em"]
            assert operation["ultima_conclusao_em"]
            task_ids = {item["id"] for item in summary["tarefas"]}
            assert (str(farma_id) in task_ids) == (segment == "FARMA")
            assert (str(pet_id) in task_ids) == (segment == "PET")
            assert (noturno_id in task_ids) == (segment == "FARMA")
            for task in summary["tarefas"]:
                visible = {"id", "estado", "criado_em", "atualizado_em"}
                if task["id"] == noturno_id:
                    assert task["tipo"] == "noturno" and task["etapas"] == stages
                    visible |= {"tipo", "etapas"}
                assert set(task) == visible
            events = [
                item
                for item in summary["eventos"]
                if item["tipo"] == event["tipo"]
                and datetime.fromisoformat(item["ocorrido_em"])
                == datetime.fromisoformat(event["ocorrido_em"])
            ]
            assert len(events) == (1 if segment == "FARMA" else 0)
            for item in summary["eventos"]:
                assert set(item) == {"tipo", "ocorrido_em", "recebido_em"}
    print(
        '{"teste":"central_isolamento_evento_idempotente_e_metricas_desabilitado","estado":"aprovado"}',
        flush=True,
    )
