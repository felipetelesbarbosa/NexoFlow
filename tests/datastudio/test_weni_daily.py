"""Weni simulada, SQLite real, API de publicação/leitura e PostgreSQL descartável."""

from contextlib import closing
from datetime import date
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import weni_insights as weni
from ds_backend.client import Client
from ds_backend.contract import PROTOCOL, StorageError
from integrations.datastudio.admin import grants
from integrations.datastudio.api import create_app
from integrations.datastudio.reader import Reader
from integrations.datastudio.store import Store
from integrations.datastudio.weni_daily import COLUMNS, TABLE, install, put
from tests.datastudio.test_ds_database import DSN, begin, finish
from tests.datastudio.test_ds_database import store as store

pytestmark = pytest.mark.skipif(not DSN, reason="Requer PostgreSQL sintético")


def test_collect_publish_replay_correct_and_read(store, tmp_path, monkeypatch):
    monkeypatch.setattr(weni, "ROOT", tmp_path)
    monkeypatch.setenv("NEXOFLOW_PERFIL", "FARMA")
    project = str(uuid4())
    with store.connect() as conn:
        grants(conn, "FARMA")
    install(store, project)
    install(store, project)
    with pytest.raises(StorageError, match="PROJETO_DIVERGENTE"):
        install(store, str(uuid4()))
    with store.connect() as conn:
        access = conn.execute("""
            SELECT has_table_privilege('nf_ds_farma_read','farma.ds_bi_weni_conversas_diarias','SELECT') AS view_ok,
                has_table_privilege('nf_ds_farma_read','farma.nf_weni_dias','SELECT') AS raw_read,
                has_table_privilege('nf_ds_farma_publish','farma.nf_weni_dias','DELETE') AS remove,
                has_table_privilege('nf_ds_farma_publish','farma.nf_weni_projeto','UPDATE') AS switch_project
        """).fetchone()
        assert access == dict(
            view_ok=True, raw_read=False, remove=False, switch_project=False
        )
    base = begin(store)
    finish(store, base)
    reader = Reader(DSN, "homologacao", "FARMA")
    auth = "synthetic-service-only" * 2
    api = TestClient(create_app(store, auth))
    read = TestClient(
        create_app(reader, auth, reader=True),
        headers={"Authorization": "Bearer " + auth},
    )

    class Transport:
        headers = {}

        def request(self, method, url, *, json, timeout, allow_redirects):
            return api.request(method, url, json=json, headers=self.headers)

    client = Client(
        dict(
            endpoint="https://testserver",
            environment="homologacao",
            segment="FARMA",
            protocol=PROTOCOL,
            api_token=auth,
            access_client_id="synthetic",
            access_client_secret="synthetic",
        ),
        session=Transport(),
    )

    def query(end):
        return read.post(
            "/v1/consulta",
            json=dict(
                table=TABLE,
                fields=COLUMNS,
                start="2026-01-01",
                end=end,
                filters=[],
                aggregation={},
            ),
        )

    http = Mock()
    metrics = dict(zip(weni.REMOTE, ({"value": v} for v in (5, 2, 2, 1)), strict=True))
    zero = {k: {"value": 0} for k in weni.REMOTE}
    http.get.side_effect = [
        Mock(status_code=200, json=lambda: metrics),
        Mock(status_code=429),
        Mock(status_code=200, json=lambda: zero),
    ]
    a, b = date(2026, 1, 1), date(2026, 1, 2)
    with closing(weni.cache()) as db:
        with pytest.raises(StorageError, match="429"):
            weni.collect(db, http, project, a, b)
        # Simula a perda do recibo após o COMMIT remoto.
        actual = client.call

        def lose(path, data):
            actual(path, data)
            raise StorageError("DS_RESPOSTA_NAO_CONFIRMADA_RETOMAR")

        monkeypatch.setattr(client, "call", lose)
        with pytest.raises(StorageError, match="RETOMAR"):
            weni.publish(db, client, project)
        assert db.execute("SELECT count(*) FROM recibos").fetchone()[0] == 0
    with closing(weni.cache()) as db:
        monkeypatch.setattr(client, "call", actual)
        assert weni.publish(db, client, project) == 1
        assert (
            query(b.isoformat()).json()["error"] == "DS_INSIGHTS_COBERTURA_INCOMPLETA"
        )
        assert weni.collect(db, http, project, a, b) == 1
        assert weni.collect(db, http, project, a, b) == 0
        assert weni.publish(db, client, project) == 1
        assert weni.publish(db, client, project) == 0
        assert http.get.call_count == 3
        saved = db.execute(
            "SELECT consulta FROM dias WHERE dia=?", (a.isoformat(),)
        ).fetchone()[0]
        http.get.side_effect = [
            Mock(status_code=200, json=lambda: {"resolved": {"value": 2}})
        ]
        with pytest.raises(StorageError, match="INCOMPLETA"):
            weni.collect(db, http, project, a, a, refresh=True)
        assert weni.publish(db, client, project) == 0
        assert sorted(query(b.isoformat()).json()["rows"]) == [
            ["2026-01-01", "FARMA", 5, 2, 2, 1, "WENI_INSIGHTS", "America/Belem"],
            ["2026-01-02", "FARMA", 0, 0, 0, 0, "WENI_INSIGHTS", "America/Belem"],
        ]
        metrics["total_conversations"]["value"] = 6
        metrics["resolved"]["value"] = 3
        http.get.side_effect = [Mock(status_code=200, json=lambda: metrics)]
        assert weni.collect(db, http, project, a, a, refresh=True) == 1
        assert weni.publish(db, client, project) == 1
        assert weni.publish(db, client, project) == 0
        assert sorted(query(b.isoformat()).json()["rows"])[0][2:6] == [6, 3, 2, 1]
        args = (
            project,
            a.isoformat(),
            saved,
            dict(zip(weni.METRICS, (5, 2, 2, 1), strict=True)),
        )
        with pytest.raises(StorageError, match="SUPERADO"):
            put(store, *args)
        with pytest.raises(StorageError, match="SEGMENTO"):
            put(Store(DSN, "homologacao", "PET"), *args)
        with pytest.raises(StorageError, match="PROJETO_DIVERGENTE"):
            put(store, str(uuid4()), *args[1:])
        from tests.test_weni_insights import event, ok

        flows = Mock()
        flows.get.side_effect = [ok([event(20, "Has Chat Room")]), ok([])]
        assert (
            weni.collect(db, flows, project, b, b, origin=weni.FLOWS, refresh=True) == 1
        )
        assert weni.publish(db, client, project) == 1
        assert weni.publish(db, client, project) == 0
        observed_rows = sorted(query(b.isoformat()).json()["rows"])
        assert observed_rows[0][-2] == "WENI_INSIGHTS"
        assert observed_rows[1][2:] == [1, 0, 0, 1, "WENI_FLOWS_V2", "America/Belem"]
        assert store.inspect(base)["state"] == "READY"
