"""Integração real PostgreSQL isolada; nenhum serviço comercial é consultado."""

import contextlib
import io
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from nexoflow_hub.api import create_app
from nexoflow_hub.config import Settings
from nexoflow_hub.core import CONNECTORS, ContractPending, RealWriteBlocked, evaluate
from nexoflow_hub.store import Conflict, LostLease, Store
from nexoflow_hub.worker import run_once


@pytest.fixture
def settings():
    path = os.environ.get("HUB_TEST_DSN_FILE")
    if not path:
        pytest.fail(
            "HUB_TEST_DSN_FILE deve apontar para PostgreSQL temporário; não usar banco real"
        )
    return Settings(
        Path(path).read_text().strip(),
        {"FARMA": "F" * 40, "PET": "P" * 40},
        lease_seconds=5,
    )


@pytest.fixture
def store(settings):
    db = Store(settings)
    db.migrate()
    # Banco temporário exclusivo desta suíte. Não executar em paralelo com VPS.
    with db.connect() as connection:
        connection.execute(
            "TRUNCATE hub.api_requisicoes,hub.sinal_worker,hub.historico_ltv,hub.historico_revisoes,hub.historico_pendencias,hub.historico_pedidos,hub.historico_recebidos,hub.historico_janelas,hub.auditoria,hub.checkpoints,hub.tentativas,hub.coordenacao,hub.tarefas,hub.cobertura"
        )
    return db


def task(store, segment="FARMA", scenario="normal"):
    return store.create(segment, "teste", uuid4().hex, scenario)


def expire(store, item):
    with store.connect() as db:
        db.execute(
            "UPDATE hub.tarefas SET lease_ate=clock_timestamp()-interval '1 second' WHERE id=%s",
            (item["id"],),
        )
        db.execute(
            "UPDATE hub.coordenacao SET lease_ate=clock_timestamp()-interval '1 second' WHERE tarefa_id=%s",
            (item["id"],),
        )


def retry_now(store):
    with store.connect() as db:
        db.execute(
            "UPDATE hub.tarefas SET disponivel_em=clock_timestamp()-interval '1 second'"
        )


@pytest.mark.parametrize("segment,days", [("FARMA", 25), ("PET", 30)])
def test_native_rules(segment, days):
    normal = evaluate(segment, "normal")
    assert normal["venda"] and normal["recompra"]
    assert normal["dias_recompra"] == days
    assert normal["faturamento"] == "110.00"
    assert normal["frete"] == "10.00"
    assert normal["maioridade_exigida"] == (segment == "FARMA")
    assert not normal["venda_atribuida"]
    assert normal["anuncio_identificado"]
    for case in (
        "cancelado",
        "pagamento_cancelado",
        "itens_vazios",
        "sem_pedido",
        "segmento_desconhecido",
        "segmento_divergente",
    ):
        result = evaluate(segment, case)
        assert not result["venda"] and result["estado"] == "ignorado"
    for case in ("dados_incompletos", "identidade_divergente", "frete_divergente"):
        assert evaluate(segment, case)["estado"] == "pendente"
    for case in ("recusa", "optout", "retroativo", "compra_recente"):
        assert not evaluate(segment, case)["recompra"]


def test_noturno_api_reenvio_retomada_e_central(store, settings):
    from nexoflow_hub.central import read_summary
    from nexoflow_hub.contracts import NOTURNO_STAGES

    client = TestClient(create_app(settings))
    farma = {"Authorization": f"Bearer {settings.tokens['FARMA']}"}
    pet = {"Authorization": f"Bearer {settings.tokens['PET']}"}
    payload = {"segmento": "FARMA", "origem": "n8n", "chave": "noturno-teste"}

    first = client.post("/tarefas/noturno", headers=farma, json=payload)
    assert first.status_code == 202
    assert client.post("/tarefas/noturno", headers=farma, json=payload).json() == first.json()
    assert client.post("/tarefas", headers=farma, json=payload).status_code == 409
    assert client.post("/tarefas/noturno", headers=pet, json=payload).status_code == 403
    uid = first.json()["id"]
    stages_path = f"/tarefas/{uid}/etapas"
    assert client.get(stages_path, headers=pet).status_code == 404

    with pytest.raises(SystemExit) as interruption:
        run_once(store, interrupt_after=3)
    assert interruption.value.code == 75
    interrupted = store.get("FARMA", uid)
    steps_before = store.checkpoints(interrupted)
    assert list(steps_before) == [1, 2, 3]
    assert client.get(stages_path, headers=farma).json()["etapas"][3] == {
        "etapa": "recompra", "estado": "executando"
    }

    expire(store, interrupted)
    assert run_once(store)
    completed = store.get("FARMA", uid)
    assert completed["tentativa"] == 2
    assert {step: store.checkpoints(completed)[step] for step in steps_before} == steps_before
    result = client.get(f"/tarefas/{uid}/resultado", headers=farma).json()
    assert result["estado"] == "concluida"
    assert result["resultado"]["externas_gravacoes"] == 0
    assert result["resultado"]["sintetico"]
    stages = [{"etapa": stage, "estado": "concluida"} for stage in NOTURNO_STAGES]
    assert client.get(stages_path, headers=farma).json()["etapas"] == stages
    farma_summary = read_summary(settings.dsn, "FARMA")
    assert farma_summary["tarefas"][0]["etapas"] == stages
    assert read_summary(settings.dsn, "PET")["tarefas"] == []


@pytest.mark.parametrize(
    "scenario,state,checkpoints",
    [("resposta_incerta", "revisao_necessaria", 2),
     ("fonte_essencial_incompleta", "revisao_necessaria", 1),
     ("dados_incompletos", "parcial", 5),
     ("rede_temporaria", "aguardando", 2)],
)
def test_noturno_preserva_progresso_e_bloqueia_publicacao_incerta(
    store, scenario, state, checkpoints
):
    created = store.create("FARMA", "teste", uuid4().hex, scenario, noturno=True)
    assert run_once(store)
    result = store.get("FARMA", created["id"])
    assert result["estado"] == state
    assert len(store.checkpoints(result)) == checkpoints
    if state == "revisao_necessaria":
        assert result["erro"] == scenario.upper()
        assert not run_once(store)
    elif scenario == "dados_incompletos":
        assert result["resultado"]["etapas"]["analytics"]["cobertura_anuncios"] == "parcial"
        assert result["resultado"]["etapas"]["publicacao"]["recibo_simulado"]["state"] == "READY"
        assert result["resultado"]["pendencias"][0]["tratamento"] == "proxima_carga"
    else:
        retry_now(store)
        assert run_once(store)
        resumed = store.get("FARMA", created["id"])
        assert resumed["estado"] == "concluida"
        assert resumed["tentativa"] == 2


@pytest.mark.parametrize(
    "scenario,state,recovered",
    [("meta_recuperacao", "concluida", 2),
     ("meta_consulta_direta_falha", "parcial", 0)],
)
def test_noturno_meta_recuperacao_checkpoint_e_retomada(store, settings, scenario, state, recovered):
    client = TestClient(create_app(settings))
    headers = {"Authorization": f"Bearer {settings.tokens['FARMA']}"}
    payload = dict(segmento="FARMA", origem="teste", chave=uuid4().hex, cenario=scenario)
    response = client.post("/tarefas/noturno", json=payload, headers=headers)
    assert response.status_code == 202
    uid = response.json()["id"]
    with pytest.raises(SystemExit):
        run_once(store, interrupt_after=2)
    item = store.get("FARMA", uid)
    before = store.checkpoints(item)[2]
    assert before["meta_recuperacao"]["recuperadas"] == recovered
    expire(store, item)
    assert run_once(store)
    completed = store.get("FARMA", uid)
    assert store.checkpoints(completed)[2] == before
    result = client.get(f"/tarefas/{uid}/resultado", headers=headers).json()
    assert result["estado"] == state
    assert result["resultado"]["externas_gravacoes"] == 0
    assert result["resultado"]["etapas"]["analytics"] == before
    assert bool(result["resultado"]["pendencias"]) == (state == "parcial")
    assert client.post("/tarefas/noturno", json=payload, headers=headers).json() == response.json()
    assert not run_once(store)


def test_migration_and_empty_rollback(store):
    assert store.ready()
    store.migrate()
    store.migrate(down=True)
    store.migrate(target=3)
    previous = task(store)
    store.migrate()
    assert store.ready()
    assert store.get("FARMA", previous["id"]) == previous
    with pytest.raises(Conflict, match="ROLLBACK_COM_DADOS"):
        store.migrate(down=True)


def test_central_sinal_worker_e_fila_por_segmento(store):
    def operation(segment):
        with store.connect() as db:
            db.execute("SELECT set_config('nexoflow.segmento', %s, true)", (segment,))
            rows = db.execute("SELECT * FROM hub.central_operacao").fetchall()
            assert len(rows) == 1 and rows[0]["segmento"] == segment
            return rows[0]

    initial = operation("PET")
    assert initial["worker_estado"] == "sem_sinal"
    assert initial["worker_ultimo_ciclo_em"] is None
    assert initial["fila_espera_segundos"] is None
    assert initial["ultima_conclusao_em"] is None

    completed = task(store)
    assert run_once(store)
    running = task(store)
    assert store.claim()["id"] == running["id"]
    expire(store, running)
    ready = task(store)
    waiting = task(store)
    task(store, "PET")
    with store.connect() as db:
        db.execute(
            "UPDATE hub.tarefas SET disponivel_em=now()-interval '2 minutes' WHERE id=%s",
            (ready["id"],),
        )
        db.execute(
            "UPDATE hub.tarefas SET estado='aguardando', disponivel_em=now()+interval '2 minutes' WHERE id=%s",
            (waiting["id"],),
        )
    store.signal_worker_cycle()
    farma = operation("FARMA")
    pet = operation("PET")
    assert farma["worker_estado"] == pet["worker_estado"] == "ativo"
    assert farma["worker_ultimo_ciclo_em"] == pet["worker_ultimo_ciclo_em"]
    assert farma["fila_prontas"] == pet["fila_prontas"] == 1
    assert farma["fila_espera_segundos"] >= 120
    assert farma["fila_em_espera"] == farma["fila_leases_expirados"] == 1
    assert pet["fila_em_espera"] == pet["fila_leases_expirados"] == 0
    assert (
        farma["ultima_conclusao_em"]
        == store.get("FARMA", completed["id"])["atualizada_em"]
    )
    assert pet["ultima_conclusao_em"] is None
    with store.connect() as db:
        db.execute("UPDATE hub.sinal_worker SET ciclo_em=now()-interval '31 seconds'")
    assert operation("FARMA")["worker_estado"] == "sinal_atrasado"
    store.signal_worker_cycle()
    assert operation("FARMA")["worker_estado"] == "ativo"


def test_queue_idempotency_payload_conflict_and_segments(store):
    def create(_):
        return store.create("FARMA", "n8n", "same-key", "normal")["id"]

    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(create, range(16)))
    assert len(set(ids)) == 1
    assert store.create("PET", "n8n", "same-key", "normal")["id"] != ids[0]
    assert store.get("PET", ids[0]) is None
    with pytest.raises(Conflict):
        store.create("FARMA", "n8n", "same-key", "cancelado")


def test_unknown_internal_scenario_never_reports_normal_success(store):
    with pytest.raises(ValueError, match="CENARIO_NAO_HABILITADO"):
        store.create("FARMA", "teste", "unknown", "inexistente")
    with pytest.raises(ValueError, match="CENARIO_NAO_HABILITADO"):
        evaluate("FARMA", "inexistente")


def test_concurrent_workers_single_owner_per_segment(store):
    for _ in range(5):
        task(store)
        task(store, "PET")
    with ThreadPoolExecutor(max_workers=8) as pool:
        claimed = [t for t in pool.map(lambda _: store.claim(), range(8)) if t]
    assert len(claimed) == 2
    assert {t["segmento"] for t in claimed} == {"FARMA", "PET"}


def test_checkpoint_restart_fencing_and_no_duplicate_effect(store):
    item = task(store)
    with pytest.raises(SystemExit):
        run_once(store, interrupt_after=1)
    old = store.get("FARMA", item["id"])
    expire(store, old)
    resumed = store.claim()
    assert resumed["id"] == item["id"] and resumed["tentativa"] == 2
    with pytest.raises(LostLease):
        store.checkpoint(old, 2, {"antigo": True})
    saved = store.checkpoints(resumed)
    assert set(saved) == {1}
    store.checkpoint(resumed, 2, {"estado": "validado"})
    store.checkpoint(resumed, 2, {"estado": "validado"})
    with pytest.raises(Conflict):
        store.checkpoint(resumed, 2, {"estado": "outro"})
    store.finish(resumed, "concluida", result={"confirmado": True})
    assert store.claim() is None
    with store.connect() as db:
        assert (
            db.execute("SELECT count(*) AS n FROM hub.checkpoints").fetchone()["n"] == 2
        )
        assert (
            db.execute(
                "SELECT count(*) AS n FROM hub.auditoria WHERE evento='ETAPA_CONFIRMADA'"
            ).fetchone()["n"]
            == 2
        )


@pytest.mark.parametrize(
    "scenario,status",
    [
        ("normal", "concluida"),
        ("dados_incompletos", "parcial"),
        ("autenticacao", "falhou"),
        ("resposta_incerta", "revisao_necessaria"),
    ],
)
def test_worker_results_and_no_reapplication(store, scenario, status):
    item = task(store, scenario=scenario)
    assert run_once(store)
    result = store.get("FARMA", item["id"])
    assert result["estado"] == status
    if result["resultado"]:
        assert result["resultado"]["externas_gravacoes"] == 0
    assert not run_once(store)


def test_network_retry_keeps_checkpoint_and_recovers(store):
    item = task(store, scenario="rede_temporaria")
    run_once(store)
    assert store.get("FARMA", item["id"])["estado"] == "aguardando"
    retry_now(store)
    run_once(store)
    result = store.get("FARMA", item["id"])
    assert result["estado"] == "concluida" and result["tentativa"] == 2
    assert len(store.checkpoints(item)) == 2


def test_attempt_exhaustion_after_interruptions(store):
    item = task(store)
    for _ in range(3):
        current = store.claim()
        expire(store, current)
    assert store.claim() is None
    assert store.get("FARMA", item["id"])["estado"] == "falhou"


def test_atomic_checkpoint_rollback(store):
    task(store)
    current = store.claim()
    with pytest.raises(psycopg.Error):
        with store.connect() as db:
            store.fenced(db, current)
            db.execute(
                "INSERT INTO hub.checkpoints(segmento,tarefa_id,etapa,resultado) VALUES(%s,%s,1,'{}')",
                (current["segmento"], current["id"]),
            )
            db.execute("SELECT 1/0")
    assert store.checkpoints(current) == {}


def test_api_authenticated_segment_scopes_and_n8n_contract(store, settings):
    client = TestClient(create_app(settings))
    assert client.get("/saude").json()["escrita_real"] is False
    assert client.get("/prontidao").status_code == 401
    headers = {"Authorization": "Bearer " + settings.tokens["FARMA"]}
    assert client.get("/prontidao", headers=headers).status_code == 200
    body = {
        "segmento": "FARMA",
        "origem": "n8n",
        "chave": "n8n-event-1",
        "cenario": "normal",
    }
    response = client.post("/tarefas", json=body, headers=headers)
    assert response.status_code == 202
    uid = response.json()["id"]
    assert client.post("/tarefas", json=body, headers=headers).json()["id"] == uid
    assert (
        client.post(
            "/tarefas", json={**body, "cenario": "recusa"}, headers=headers
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/tarefas", json={**body, "segmento": "PET"}, headers=headers
        ).status_code
        == 403
    )
    assert (
        client.get(
            f"/tarefas/{uid}",
            headers={"Authorization": "Bearer " + settings.tokens["PET"]},
        ).status_code
        == 404
    )
    assert (
        client.get(
            "/tarefas", headers={"Authorization": "Bearer " + settings.tokens["PET"]}
        ).json()
        == []
    )
    assert (
        client.post(
            "/tarefas",
            json={**body, "endpoint": "https://example.invalid"},
            headers=headers,
        ).status_code
        == 422
    )
    assert (
        client.post("/tarefas", content=b"x" * 4097, headers=headers).status_code == 413
    )
    run_once(store)
    result = client.get(f"/tarefas/{uid}/resultado", headers=headers).json()
    assert result["estado"] == "concluida" and result["resultado"]["sintetico"]
    assert client.get(f"/tarefas/{uid}/erros", headers=headers).json()["erro"] is None


def test_logs_and_api_never_echo_tokens_or_error_input(store, settings):
    task(store)
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        run_once(store)
    assert settings.tokens["FARMA"] not in output.getvalue()
    assert "52998224725" not in output.getvalue()
    client = TestClient(create_app(settings))
    reply = client.post(
        "/tarefas",
        json={"token": "PRIVATE_MARKER"},
        headers={"Authorization": "Bearer " + settings.tokens["FARMA"]},
    )
    assert "PRIVATE_MARKER" not in reply.text
    for connector in CONNECTORS.values():
        with pytest.raises(RealWriteBlocked):
            connector.write()
        with pytest.raises(ContractPending):
            connector.read()


def test_settings_refuse_other_databases_and_production(settings, monkeypatch):
    with pytest.raises(ValueError, match="BANCO_HOMOLOGACAO"):
        Settings("dbname=n8n", settings.tokens)
    with pytest.raises(ValueError):
        Settings(settings.dsn, {"FARMA": "F" * 40, "PET": "F" * 40})
    monkeypatch.setenv("HUB_ESCRITA_REAL", "true")
    with pytest.raises(ValueError, match="OPERACAO_REAL"):
        Settings.load()


def test_n8n_exports_are_inactive_and_match_api_contract():
    from nexoflow_hub.api import TaskRequest

    for segment in ("farma", "pet"):
        path = (
            Path(__file__).resolve().parents[1] / "n8n" / f"homologacao-{segment}.json"
        )
        workflow = json.loads(path.read_text())
        assert workflow["active"] is False
        assert workflow["settings"]["executionTimeout"] == 120
        http_nodes = [
            n for n in workflow["nodes"] if n["type"].endswith(".httpRequest")
        ]
        assert len(http_nodes) == 3
        for node in http_nodes:
            assert "http://hub-api:8000/" in node["parameters"]["url"]
            assert (
                node["credentials"]["httpHeaderAuth"]["id"]
                == "CONFIGURAR_" + segment.upper()
            )
        create = next(n for n in http_nodes if n["name"] == "Criar tarefa")
        assert (
            TaskRequest.model_validate(
                json.loads(create["parameters"]["jsonBody"])
            ).segmento
            == segment.upper()
        )
        assert not any("webhook" in n["type"].lower() for n in workflow["nodes"])


def test_noturno_n8n_observes_all_worker_stages():
    from nexoflow_hub.contracts import NOTURNO_STAGES

    workflow = json.loads(
        (Path(__file__).resolve().parents[1] / "n8n" / "noturno-farma-hml.json").read_text()
    )
    assert workflow["active"] is False
    assert workflow["settings"]["timezone"] == "America/Belem"
    assert workflow["settings"]["executionTimeout"] == 120
    nodes = {node["id"]: node for node in workflow["nodes"]}
    assert [node for node in nodes.values() if "Trigger" in node["type"]] == [nodes["manual"]]
    assert nodes["create"]["parameters"]["url"].endswith("/tarefas/noturno")
    for stage in NOTURNO_STAGES:
        node = nodes[stage]
        assert node["parameters"]["url"].endswith("/etapas")
        assert node["credentials"]["httpHeaderAuth"]["id"] == "CONFIGURAR_FARMA"
        verified = nodes[f"{stage}_verificar"]
        outputs = workflow["connections"][verified["name"]]["main"]
        assert outputs[0][0]["node"] == nodes["blocked"]["name"]
        assert outputs[2][0]["node"] == nodes[f"{stage}_aguardar"]["name"]


def test_telemetria_registra_tentativas_e_nunca_guarda_urls_ou_corpos_privados(store):
    from nexoflow_hub.api_observability import read_consumption

    client = TestClient(create_app(store.settings))
    farma = {"Authorization": "Bearer " + store.settings.tokens["FARMA"]}
    pet = {"Authorization": "Bearer " + store.settings.tokens["PET"]}
    body = {"segmento": "FARMA", "chave": "CHAVE_PRIVADA", "origem": "teste"}
    first = client.post("/tarefas?token=NUNCA_GUARDAR", json=body, headers=farma)
    assert first.status_code == 202
    uid = first.json()["id"]
    assert (
        client.get(f"/tarefas/{uid}?cpf=NUNCA_GUARDAR", headers=farma).status_code
        == 200
    )
    assert (
        client.post(
            "/tarefas", json={**body, "cpf": "NUNCA_GUARDAR"}, headers=farma
        ).status_code
        == 422
    )
    assert client.get(f"/tarefas/{uid}", headers=pet).status_code == 404
    assert client.get("/tarefas").status_code == 401
    assert client.get("/saude").status_code == 200

    def history(segment, **options):
        with store.connect() as db:
            db.execute("SELECT set_config('nexoflow.segmento', %s, true)", (segment,))
            return read_consumption(db, segment, api="hub", **options)

    farma_log = history("FARMA")
    assert [(r["total"], r["sucesso"], r["erros"]) for r in farma_log["resumo"]] == [
        (3, 2, 1)
    ]
    items = farma_log["requisicoes"]
    assert items[0]["erro"] == "REQUISICAO_INVALIDA" and items[0]["corpo"] is None
    assert items[1]["endpoint"] == "/tarefas/{uid}"
    assert items[2]["corpo"] == {"origem": "teste", "cenario": "normal"}
    assert items[2]["duracao_ms"] >= 0
    errors = history("FARMA", only_errors=True)["requisicoes"]
    assert errors == [items[0]]
    assert history("PET")["requisicoes"][0]["erro"] == "TAREFA_NAO_ENCONTRADA"
    public = str(farma_log)
    assert all(
        s not in public
        for s in ("NUNCA_GUARDAR", "CHAVE_PRIVADA", uid, "Authorization")
    )

    with store.connect() as db:
        for _ in range(50):
            db.execute(
                """INSERT INTO hub.api_requisicoes(segmento, api, metodo, endpoint, http, duracao_ms)
                   VALUES('FARMA','hub','GET','/tarefas',200,1)"""
            )
    page = history("FARMA")
    assert len(page["requisicoes"]) == 50 and page["proximo"] is not None
    assert history("FARMA", before=page["proximo"])["requisicoes"] == items


def test_falha_no_log_nao_muda_a_resposta_da_api(store, monkeypatch, caplog):
    from nexoflow_hub import api_observability

    def unavailable(*args, **kwargs):
        raise RuntimeError("NAO_EXIBIR_ERRO_BRUTO")

    monkeypatch.setattr(api_observability, "save", unavailable)
    client = TestClient(create_app(store.settings))
    response = client.get(
        "/tarefas",
        headers={"Authorization": "Bearer " + store.settings.tokens["FARMA"]},
    )
    assert response.status_code == 200
    assert "TELEMETRIA_API_INDISPONIVEL" in caplog.text
    assert "NAO_EXIBIR_ERRO_BRUTO" not in caplog.text
