import json
import os

import pytest

from ds_backend.contract import StorageError
from integrations.datastudio.admin import grants, update_farma_report
from integrations.datastudio.meta_destinations import PERIOD
from integrations.datastudio.reader import Reader
from tests.datastudio.test_contract import row
from tests.datastudio.test_ds_database import DSN, batch, begin, finish, store  # noqa: F401

pytestmark = pytest.mark.skipif(
    not os.getenv("NEXOFLOW_DATASTUDIO_TEST_DSN"), reason="PostgreSQL isolado"
)


def test_two_stage_population_shared_grain_and_lost_ack(store):  # noqa: F811
    with store.connect() as conn:
        grants(conn, "FARMA")
    rev = begin(store)
    b = []
    d = []
    for idx, (ad, day, impressions, cost, orders, revenue, ctwa) in enumerate(
        [
            ("001", 1, 5, 12, 0, 0, 1),
            ("001", 2, 0, 0, 2, 48, 1),
            ("002", 1, 0, 0, 10, 300, 0),
        ]
    ):
        key = str(idx)
        b.append(
            row(
                "BI_Meta_Resultados",
                chave=key,
                segmento="FARMA",
                classificacao="FARMA",
                conta_id="0001",
                anuncio_id=ad,
                data=f"2026-11-0{day}",
                moeda="BRL",
                moeda_receita="BRL",
                fuso="America/Belem",
                politica_atribuicao="A",
                impressoes=impressions,
                investimento_original=cost,
                investimento_atribuivel=cost,
                pedidos_confirmados=orders,
                receita_confirmada=revenue,
                eventos_ctwa=ctwa,
                conversas_iniciadas_meta=3,
            )
        )
        audit = dict(
            cobertura="COMPLETA",
            configurado="FARMA",
            eventos={"WA_1": ctwa},
            conversas_distintas_privadas=["same"] if ctwa else [],
        )
        d.append(
            row(
                "Meta_Ads_Diario",
                chave=key,
                segmento="FARMA",
                payload_api_json=json.dumps({"nf_destino_v1": audit}),
            )
        )
    receipt = batch(store, rev, "BI_Meta_Resultados", b)
    assert store.batch(rev, receipt["id"], "BI_Meta_Resultados", b) == receipt
    batch(store, rev, "Meta_Ads_Diario", d)
    finish(store, rev)
    update_farma_report(store, rev, destinations=True)
    update_farma_report(store, rev, destinations=True)
    with store.connect() as conn:
        conn.execute("CREATE ROLE nf_test_aggregate_only NOLOGIN")
        conn.execute("GRANT USAGE ON SCHEMA farma TO nf_test_aggregate_only")
        conn.execute(
            "GRANT SELECT ON farma.ds_catalogo_destinos_meta TO nf_test_aggregate_only"
        )
        conn.execute(
            "GRANT EXECUTE ON FUNCTION farma.ds_veiculacao_meta_v1(date,date,boolean) TO nf_test_aggregate_only"
        )
        conn.execute("SET LOCAL ROLE nf_test_aggregate_only")
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM farma.ds_catalogo_destinos_meta"
            ).fetchone()["n"]
            > 0
        )
        assert (
            conn.execute(
                "SELECT sum(anuncios) AS n FROM farma.ds_veiculacao_meta_v1('2026-11-01','2026-11-02',true)"
            ).fetchone()["n"]
            == 1
        )
        assert not conn.execute(
            "SELECT has_table_privilege(current_user,'farma.nf_atuais','SELECT') AS raw"
        ).fetchone()["raw"]
        assert not conn.execute(
            "SELECT has_table_privilege(current_user,'farma.ds_destino_meta_base_v1','SELECT') AS raw"
        ).fetchone()["raw"]
        conn.rollback()
    reader = Reader(DSN, "homologacao", "FARMA")
    fields = [
        "anuncios",
        "eventos_ctwa",
        "wa_1",
        "pendentes",
        "conversas_meta",
        "conversas_weni",
        "cpa",
        "roas",
    ]
    for name in PERIOD:
        r = reader.query(name, fields, "2026-11-01", "2026-11-02", [], {})
        from decimal import Decimal

        assert [Decimal(str(x)) for x in r["rows"][0]] == [1, 2, 2, 0, 6, 1, 6, 4]
        assert (
            reader.query(name, fields, "2026-11-02", "2026-11-02", [], {})["rows"] == []
        )
    with pytest.raises(StorageError):
        reader.query(PERIOD[0], ["contact_uuid"], "2026-11-01", "2026-11-02", [], {})


def test_native_postgres_with_lost_batch_response(store, tmp_path, monkeypatch):  # noqa: F811
    import requests
    from fastapi.testclient import TestClient

    import meta_ads_sheets
    from ds_backend.adapter import PostgresStore
    from ds_backend.client import Client
    from integrations.datastudio.api import create_app
    from meta_ads_native import sync_native_meta
    from tests.test_meta_ads_destinations import PROJECT, config
    from tests.test_meta_ads_native import NOW
    from tests.test_meta_ads_native import Client as Graph

    cfg = dict(
        endpoint="https://test.invalid",
        segment="FARMA",
        environment="homologacao",
        api_token="synthetic-homologation-token-123456789",
        access_client_id="test",
        access_client_secret="test",
        protocol="nexoflow_datastudio_1",
    )
    web = TestClient(create_app(store, cfg["api_token"]))

    class Session:
        headers = {}
        lost = False

        def request(self, method, url, **kwargs):
            path = url.removeprefix(cfg["endpoint"])
            r = web.request(method, path, headers=self.headers, json=kwargs.get("json"))
            if path == "/v1/lotes" and r.status_code == 200 and not self.lost:
                self.lost = True
                raise requests.ConnectionError()
            return r

    monkeypatch.setattr(meta_ads_sheets, "PRIVATE_ROOT", tmp_path)
    p = tmp_path / "destinos.json"
    p.write_text(json.dumps(config()))
    session = Session()
    client = Client(cfg, session=session)
    graph = Graph()
    graph.destination_adsets = graph.adsets
    event = dict(
        date=NOW.isoformat(),
        segment="FARMA",
        ad_id="123",
        event_id="event",
        channel_uuid="channel",
    )

    def collect(*args, **kwargs):
        return [event], dict(segments=dict(FARMA=True, PET=True), channel_addresses={})

    finish(store, begin(store))
    for apply in [False, True, True]:
        target = PostgresStore(client, readonly=not apply)
        report = sync_native_meta(
            target,
            dict(
                META_ADS_ENABLED=True,
                META_ADS_DESTINOS_FILE=str(p),
                WENI_INSIGHTS_PROJECT_UUID=PROJECT,
            ),
            "FARMA",
            [],
            [],
            [],
            now=NOW,
            apply=apply,
            state_dir=tmp_path,
            client_factory=lambda: graph,
            evidence_collector=collect,
        )
        assert not report["partial"], report
        if apply:
            assert target.finish(complete=True)["state"] == "READY"
        else:
            assert store.info()["version"] == 1
    assert session.lost
    assert len(store.rows("BI_Meta_Resultados")["rows"]) == 4
    assert len(store.rows("Controle")["rows"]) == 1
    assert report["summary"]["updated"] == 0
