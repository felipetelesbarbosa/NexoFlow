import json
import os
from decimal import Decimal

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
            ("001", 3, 5, 2, 0, 0, 0),
            ("002", 4, 5, 2, 0, 0, 0),
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
                conversas_iniciadas_meta={3: None, 4: 0}.get(day, 3),
            )
        )
        audit = dict(
            cobertura="COMPLETA",
            configurado="FARMA",
            eventos={"WA_1": ctwa},
            conversas_distintas_privadas=["same"] if ctwa else [],
        )
        payload = {"nf_destino_v1": audit}
        if ad == "001" and day in (1, 2):
            payload["nf_atribuicao_comercial_v1"] = dict(
                pedidos_conversa_anuncio=day - 1,
                receita_conversa_anuncio=48 * (day - 1),
                pedidos_apos_conversa_7d=day,
                receita_apos_conversa_7d=10 * day,
                novos_clientes_anuncio=day - 1,
                cobertura_comercial=True,
            )
        d.append(
            row(
                "Meta_Ads_Diario",
                chave=key,
                segmento="FARMA",
                campanha_nome={1: "Campanha anterior", 2: "Campanha atual"}.get(day),
                payload_api_json=json.dumps(payload),
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
    commercial_fields = [
        "pedidos_conversa_anuncio",
        "pedidos_apos_conversa_7d",
        "cac_novos_clientes",
        "cpa_conversa_anuncio",
        "roas_conversa_anuncio",
        "dias_comerciais_parciais",
    ]
    for period_table in PERIOD:
        for end, expected in (
            ("2026-11-02", [1, 3, 12, 12, 4, 0]),
            ("2026-11-03", [1, 3, None, None, None, 1]),
        ):
            actual = reader.query(
                period_table, commercial_fields, "2026-11-01", end, [], {}
            )["rows"][0]
            assert [None if x is None else Decimal(str(x)) for x in actual] == expected
    assert reader.query(
        PERIOD[0], ["anuncio_id", "campanha_nome"], "2026-11-01", "2026-11-03", [], {}
    )["rows"] == [["001", "Campanha atual"]]
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
        assert [Decimal(str(x)) for x in r["rows"][0]] == [1, 2, 2, 0, 6, 1, 6, 4]
        assert (
            reader.query(name, fields, "2026-11-02", "2026-11-02", [], {})["rows"] == []
        )
        coverage_fields = [
            "conversas_meta",
            "conversas_meta_informadas",
            "fatos_sem_metrica_meta",
        ]
        for start, end, expected in [
            ("2026-11-01", "2026-11-03", [None, Decimal(6), 1]),
            ("2026-11-03", "2026-11-03", [None, None, 1]),
            ("2026-11-04", "2026-11-04", [Decimal(0), Decimal(0), 0]),
        ]:
            actual = reader.query(name, coverage_fields, start, end, [], {})["rows"][0]
            assert [None if v is None else Decimal(str(v)) for v in actual] == expected
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
    original_insights = graph.daily_insights
    values = {f"2026-11-0{day}": str(day) for day in range(1, 5)}

    def insights(*args, **kwargs):
        response = original_insights(*args, **kwargs)
        response["dados"] = [
            dict(
                row,
                actions=[
                    {
                        "action_type": "messaging_conversation_started_7d",
                        "value": values[row["date_start"]],
                    }
                ],
            )
            for row in response["dados"]
            if row["date_start"] in values
        ]
        return response

    graph.daily_insights = insights
    event = dict(
        date=NOW.isoformat(),
        segment="FARMA",
        ad_id="123",
        event_id="event",
        channel_uuid="channel",
    )

    def collect(*args, **kwargs):
        return [event], dict(segments=dict(FARMA=True, PET=True), channel_addresses={})

    def collect_metrics(target, apply):
        return sync_native_meta(
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

    finish(store, begin(store))
    for apply in [False, True, True]:
        target = PostgresStore(client, readonly=not apply)
        report = collect_metrics(target, apply)
        assert not report["partial"], report
        if apply:
            assert target.finish(complete=True)["state"] == "READY"
        else:
            assert store.info()["version"] == 1
    assert session.lost
    assert len(store.rows("BI_Meta_Resultados")["rows"]) == 4
    assert len(store.rows("Controle")["rows"]) == 1
    assert report["summary"]["updated"] == 0

    ready = store.info()["version"]
    with store.connect() as conn:
        grants(conn, "FARMA")
        revision = str(
            conn.execute(
                "SELECT execucao FROM controle.nf_publicacoes WHERE segmento='FARMA'"
            ).fetchone()["execucao"]
        )
    update_farma_report(store, revision, destinations=True)
    reader = Reader(DSN, "homologacao", "FARMA")

    def published():
        rows = reader.query(
            PERIOD[1], ["conversas_meta"], "2026-11-01", "2026-11-04", [], {}
        )["rows"]
        return Decimal(rows[0][0])

    assert published() == 10
    del values["2026-11-02"]
    pending = PostgresStore(client, purpose="meta")
    rejected = collect_metrics(pending, True)
    assert rejected["status"] == "conversas_meta_pendentes"
    assert not rejected["applied"]
    assert store.info()["version"] == ready
    assert published() == 10
    assert store.abort(pending.revision)["state"] == "ABORTADA"

    values["2026-11-02"] = "0"
    recovered = PostgresStore(client, purpose="meta")
    corrected = collect_metrics(recovered, True)
    assert corrected["applied"], corrected
    assert recovered.finish(complete=True)["state"] == "READY"
    assert published() == 8
