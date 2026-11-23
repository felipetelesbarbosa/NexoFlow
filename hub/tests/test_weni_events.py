"""Contrato interno de homologação do webhook emitido pelo fluxo Weni."""

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from nexoflow_hub.api import create_app
from nexoflow_hub.config import Settings
from nexoflow_hub.store import Store

ROUTE = "/v1/webhooks/weni/farma"
TOKENS = {"FARMA": "f" * 40, "PET": "p" * 40}
WEBHOOK_TOKEN = "w" * 40
AUTH = {"Authorization": "Bearer " + WEBHOOK_TOKEN}
STANDALONE_DSN = "dbname=nexoflow_hub_hml_unit"


def event():
    return {
        "evento_id": str(uuid4()),
        "tipo": "atendimento_transferido",
        "ocorrido_em": "2026-11-23T08:15:00-03:00",
    }


def unit_app(token=WEBHOOK_TOKEN):
    return TestClient(
        create_app(Settings(STANDALONE_DSN, TOKENS, weni_farma_token=token))
    )


def test_disabled_webhook_and_rejection_of_reused_management_secret():
    assert unit_app(None).post(ROUTE, json=event(), headers=AUTH).status_code == 404
    with pytest.raises(ValueError, match="CHAVE_WEBHOOK"):
        unit_app(TOKENS["PET"])


def test_webhook_credential_is_separate_from_management_and_scoped_to_farma():
    client = unit_app()
    assert client.get("/tarefas", headers=AUTH).status_code == 401
    for token in (*TOKENS.values(), "", "invalid"):
        assert (
            client.post(
                ROUTE, json=event(), headers={"Authorization": "Bearer " + token}
            ).status_code
            == 401
        )
    assert (
        client.post("/v1/webhooks/weni/pet", json=event(), headers=AUTH).status_code
        == 404
    )


@pytest.mark.parametrize(
    "change",
    [
        {"evento_id": "001"},
        {"ocorrido_em": "2026-11-23T08:15:00"},
        {"ocorrido_em": "2026-11-31T11:15:00Z"},
        {"ocorrido_em": "2026-11-23T11:15:00+12:88"},
        {"ocorrido_em": 100},
        {"tipo": "mensagem"},
        {"segmento": "PET"},
        {"texto": "segredo-a-nao-exibir"},
    ],
)
def test_contract_accepts_only_the_three_documented_fields(change):
    response = unit_app().post(ROUTE, headers=AUTH, json=event() | change)
    assert response.status_code == 422
    assert response.json() == {"erro": "REQUISICAO_INVALIDA"}


def test_database_failure_returns_no_confirmation(monkeypatch):
    def unavailable(self):
        raise psycopg.OperationalError("falha simulada")

    monkeypatch.setattr(Store, "connect", unavailable)
    response = unit_app().post(ROUTE, headers=AUTH, json=event())
    assert response.status_code == 503
    assert response.json() == {"erro": "SERVICO_INDISPONIVEL"}


def test_postgres_concurrent_retries_recreate_client_and_conflict():
    dsn_file = Path(os.environ["HUB_TEST_DSN_FILE"])
    settings = Settings(
        dsn_file.read_text().strip(), TOKENS, weni_farma_token=WEBHOOK_TOKEN
    )
    store = Store(settings)
    store.migrate()
    client = TestClient(create_app(settings))
    payload = event()
    try:
        with ThreadPoolExecutor(max_workers=5) as pool:
            responses = list(
                pool.map(
                    lambda _: client.post(ROUTE, json=payload, headers=AUTH), range(8)
                )
            )
        assert all(response.status_code == 200 for response in responses)
        receipt = responses[0].json()
        assert receipt["estado"] == "CONFIRMADO" and receipt["recibo"]
        assert all(response.json() == receipt for response in responses)
        client = TestClient(create_app(settings))
        same_instant = payload | {"ocorrido_em": "2026-11-23T11:15:00Z"}
        assert client.post(ROUTE, json=same_instant, headers=AUTH).json() == receipt
        conflict = client.post(
            ROUTE, json=payload | {"ocorrido_em": "2026-11-23T11:16:00Z"}, headers=AUTH
        )
        assert conflict.status_code == 409
        with store.connect() as db:
            rows = db.execute(
                "SELECT recibo::text FROM hub.eventos_weni WHERE evento_id = %s",
                (payload["evento_id"],),
            ).fetchall()
            assert rows == [{"recibo": receipt["recibo"]}]
            with pytest.raises(
                psycopg.Error, match="ROLLBACK_EVENTOS_COM_DADOS_BLOQUEADO"
            ):
                db.execute(
                    (
                        Path(__file__).resolve().parents[1] / "migrations/003_down.sql"
                    ).read_bytes()
                )
            db.rollback()
    finally:
        with store.connect() as db:
            db.execute(
                "DELETE FROM hub.eventos_weni WHERE evento_id=%s",
                (payload["evento_id"],),
            )


def test_manual_n8n_example_replays_one_synthetic_occurrence():
    import json

    file = Path(__file__).resolve().parents[1] / "n8n/webhook-weni-farma-hml.json"
    workflow = json.loads(file.read_text())
    assert not workflow["active"]
    assert workflow["nodes"][0]["type"] == "n8n-nodes-base.manualTrigger"
    first, repeated = workflow["nodes"][1:3]
    assert first["parameters"] == repeated["parameters"]
    request = first["parameters"]
    assert request["url"] == "http://hub-api:8000" + ROUTE
    from nexoflow_hub.weni_events import FlowEvent

    FlowEvent.model_validate_json(request["jsonBody"])
    assert first["credentials"] == repeated["credentials"]
    assert (
        first["credentials"]["httpHeaderAuth"]["id"] == "CONFIGURAR_WEBHOOK_FARMA_HML"
    )
