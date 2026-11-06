"""PostgreSQL temporário real; mesma normalização Windows, nenhuma rede comercial."""

from copy import deepcopy
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from nexoflow_hub.api import create_app
from nexoflow_hub.history import (
    PgHistory,
    SyntheticHistorySource,
    run_history,
    validate_parameters,
)
from nexoflow_hub.store import Conflict, LostLease
from nexoflow_hub.worker import run_once
from test_hub import expire
from test_hub import settings as fixture_settings
from test_hub import store as fixture_store

from order_history import HistoryError, normalize_order

settings = fixture_settings
store = fixture_store


def parameters(**changes):
    return dict(
        inicio="2026-11-01",
        fim="2026-11-06",
        limite=100,
        max_paginas=2,
        modo="historica",
        reiniciar=False,
        quantidade_sintetica=205,
        **changes,
    )


def create(store, segment="PET", changes=None):
    return store.create(
        segment,
        "teste",
        uuid4().hex,
        "normal",
        history={**parameters(), **(changes or {})},
    )


@pytest.mark.parametrize("segment", ["FARMA", "PET"])
def test_budget_resume_and_official_identity_without_weni(store, segment):
    first = create(store, segment)
    run_once(store)
    result = store.get(segment, first["id"])
    assert result["estado"] == "parcial"
    assert result["resultado"]["received"] == 200
    second = create(store, segment)
    run_once(store)
    result = store.get(segment, second["id"])
    assert result["estado"] == "concluida"
    assert result["resultado"]["received"] == 205
    assert result["resultado"]["faturamento_centavos"] == 1640000
    with store.connect() as db:
        data = db.execute(
            "SELECT registro FROM hub.historico_pedidos WHERE segmento=%s", (segment,)
        ).fetchall()
        assert len(data) == 205
        assert all(r["registro"]["contact_uuid"] == "" for r in data)
        assert all(r["registro"]["owner"] == "10" for r in data)
        coverage = db.execute(
            "SELECT estado FROM hub.cobertura WHERE segmento=%s", (segment,)
        ).fetchone()
        assert coverage["estado"] == "incompleta"  # calendário ainda não demonstrado


@pytest.mark.parametrize("limit,pages", [(500, 3), (1000, 2)])
def test_1200_sizes_and_fencing(store, limit, pages):
    task = create(
        store,
        changes={"limite": limit, "max_paginas": 10, "quantidade_sintetica": 1200},
    )
    item = store.claim()
    with pytest.raises(SystemExit):
        run_history(store, item, interrupt_after=1)
    with store.connect() as db:
        count = db.execute("SELECT count(*) AS n FROM hub.historico_pedidos").fetchone()
        assert count["n"] == limit
    expire(store, item)
    replacement = store.claim()
    query = validate_parameters("PET", item["parametros"])
    with pytest.raises(LostLease):
        PgHistory(store, item).commit_page(
            query,
            2,
            SyntheticHistorySource(1200).get_pedidos_history(query, 2),
            now="2026-11-06T20:00:00-03:00",
            mode="historica",
            step=2,
        )
    run_history(store, replacement)
    result = store.get("PET", task["id"])["resultado"]
    assert result["received"] == 1200 and result["faturamento_centavos"] == 9600000
    assert len(store.checkpoints(replacement)) == pages + 1


def test_same_order_ids_isolated_and_api_contract(store, settings):
    api = TestClient(create_app(settings))
    body = dict(segmento="PET", chave=uuid4().hex, **parameters())
    response = api.post(
        "/tarefas/historico",
        json=body,
        headers={"Authorization": "Bearer " + settings.tokens["PET"]},
    )
    assert response.status_code == 202
    assert (
        api.post(
            "/tarefas/historico",
            json=body,
            headers={"Authorization": "Bearer " + settings.tokens["FARMA"]},
        ).status_code
        == 403
    )
    assert (
        api.post(
            "/tarefas/historico",
            json=dict(body, token="forbidden"),
            headers={"Authorization": "Bearer " + settings.tokens["PET"]},
        ).status_code
        == 422
    )
    assert (
        api.post(
            "/tarefas/historico",
            json=body,
            headers={"Authorization": "Bearer " + settings.tokens["PET"]},
        ).json()["id"]
        == response.json()["id"]
    )
    changed = dict(body, limite=500)
    assert (
        api.post(
            "/tarefas/historico",
            json=changed,
            headers={"Authorization": "Bearer " + settings.tokens["PET"]},
        ).status_code
        == 409
    )
    create(store, "FARMA", {"max_paginas": 10})
    run_once(store)
    run_once(store)
    with store.connect() as db:
        segments = db.execute(
            "SELECT DISTINCT segmento FROM hub.historico_pedidos"
        ).fetchall()
        assert {r["segmento"] for r in segments} == {"FARMA", "PET"}


def test_page_rollback_payload_pending_and_reconcile(store):
    task = create(store, changes={"quantidade_sintetica": 1})
    task = store.claim()
    query = validate_parameters("PET", task["parametros"])
    history = PgHistory(store, task)
    history.begin(query)
    page = SyntheticHistorySource(1).get_pedidos_history(query, 1)
    bad = deepcopy(page)
    bad["totalRegistros"] = 2
    with pytest.raises(HistoryError):
        history.commit_page(
            query, 1, bad, now="2026-11-06T20:00:00-03:00", mode="historica", step=1
        )
    assert not store.checkpoints(task)
    assert history.totals()["pedidos_validos"] == 0
    expected = normalize_order(page["pedidos"][0], "PET", "2026-11-06T20:00:00-03:00")
    history.commit_page(
        query, 1, page, now="2026-11-06T20:00:00-03:00", mode="historica", step=1
    )
    with store.connect() as db:
        actual = db.execute("SELECT registro FROM hub.historico_pedidos").fetchone()[
            "registro"
        ]
        assert actual == expected
    with pytest.raises(Conflict):
        store.migrate(down=True)


def test_upgrade_existing_v1_preserves_tasks_and_rollback_refuses_history(store):
    # Banco desta fixture é descartável; não há dados comerciais.
    store.migrate(down=True)
    store.migrate(target=1)
    normal = store.create("FARMA", "teste", uuid4().hex, "normal")
    store.migrate()
    assert store.ready()
    assert store.get("FARMA", normal["id"])["tipo"] == "avaliacao"
    run_once(store)
    create(store)
    run_once(store)
    with pytest.raises(Conflict):
        store.migrate(down=True)


def test_incremental_window_and_recheck_completed_window(store):
    from datetime import UTC, datetime, timedelta

    from pedido_utils import business_order_datetime

    current = business_order_datetime(datetime.now(UTC)).date()
    changes = dict(
        modo="incremental",
        inicio=(current - timedelta(days=20)).isoformat(),
        fim=current.isoformat(),
        quantidade_sintetica=1,
    )
    with pytest.raises(HistoryError, match="INCREMENTAL_USA"):
        validate_parameters("PET", {**parameters(), **changes, "inicio": "2020-01-01"})
    # A retomada usa o dia de criação da tarefa, mesmo após mudar o calendário.
    old = {**parameters(), "modo": "incremental", "inicio": "2026-10-17"}
    assert validate_parameters("PET", old, reference="2026-11-06T23:30:00-03:00")
    first = create(store, changes=changes)
    run_once(store)
    assert store.get("PET", first["id"])["estado"] == "concluida"
    second = create(store, changes=changes)
    run_once(store)
    assert store.get("PET", second["id"])["estado"] == "concluida"
    with store.connect() as db:
        assert (
            db.execute("SELECT count(*) AS n FROM hub.historico_pedidos").fetchone()[
                "n"
            ]
            == 1
        )
        assert (
            db.execute(
                "SELECT count(*) AS n FROM hub.checkpoints WHERE tarefa_id=%s",
                (second["id"],),
            ).fetchone()["n"]
            >= 1
        )
