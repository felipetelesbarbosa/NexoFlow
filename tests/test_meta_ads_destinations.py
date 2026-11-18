import unittest
from datetime import datetime
from uuid import UUID

from meta_ads_destinations import reference
from meta_ads_model import build_native_tables
from tests import test_meta_ads_model as fixtures

ORG, PROJECT, CHANNEL = [str(UUID(int=i)) for i in (11, 12, 13)]
PHONES = {"+550000000001": "WA_1", "+550000000002": "WA_2"}
NOW = "2026-11-05T00:00:00+00:00"


def config():
    return dict(
        segment="FARMA",
        source="WENI_CX_PROJECT_WABAS",
        flows_org=ORG,
        cx_project=PROJECT,
        waba="00001",
        phones=PHONES,
        observed=NOW,
        bindings=[],
    )


def proof(kind, **fields):
    return dict(
        kind=kind,
        source="META_AD_DESTINATION_HISTORY"
        if kind == "ad"
        else "WENI_META_CHANNEL_HISTORY",
        observed=NOW,
        ref="teste",
        **{"from": "2026-11-01T00:00:00-03:00", "until": "2026-11-10T00:00:00-03:00"},
        **fields,
    )


def build(doc, events, channels, day="2026-11-03"):
    import json

    fixture = fixtures.NativeMetaModelTests()
    fixture.setUp()
    args = fixture.args
    fact = dict(fixture.fact, adset_id="77", date_start=day, date_stop=day)
    args.update(
        facts=[fact], evidence=events, updated_at=NOW, destination=reference(doc)
    )
    args["coverage"]["channel_addresses"] = channels
    t = build_native_tables(**args)
    raw = t["Meta_Ads_Diario"][0]
    return t["BI_Meta_Resultados"][0], json.loads(raw["payload_api_json"])[
        "nf_destino_v1"
    ]


class DestinationsTests(unittest.TestCase):
    def test_received_two_phones_dedup_conflict_and_unknown_history(self):
        e = dict(
            segment="FARMA",
            event_id="1",
            ad_id="20",
            date="2026-11-03T10:00:00-03:00",
            conversation_id="one",
            channel_uuid=CHANNEL,
        )
        other = str(UUID(int=14))
        events = [e, e, dict(e, event_id="2", channel_uuid=other)]
        channels = {CHANNEL: ["0002"], other: ["0003"]}
        doc = config()
        metric, a = build(doc, events, channels)
        assert a["eventos"] == {"VIGENCIA_DESCONHECIDA": 2}
        assert (
            metric["investimento_original"] == "12.50"
            and metric["investimento_atribuivel"] == ""
        )
        for channel, phone, pid in zip(channels, PHONES, ("0002", "0003"), strict=True):
            doc["bindings"].append(
                proof(
                    "channel",
                    channel=channel,
                    phone=phone,
                    phone_id=pid,
                    waba=doc["waba"],
                )
            )
        metric, a = build(doc, events, channels)
        assert (
            a["eventos"] == {"WA_1": 1, "WA_2": 1}
            and len(a["conversas_distintas_privadas"]) == 1
        )
        assert metric["eventos_ctwa"] == 2
        doc["bindings"][0]["until"] = "2026-11-02T00:00:00-03:00"
        assert build(doc, events, channels)[1]["eventos"] == {
            "WA_2": 1,
            "VIGENCIA_DESCONHECIDA": 1,
        }
        assert build(config(), events, {})[1]["eventos"] == {"CANAL_AUSENTE": 2}
        doc["bindings"].append(dict(doc["bindings"][1], phone=next(iter(PHONES))))
        assert build(doc, events, channels)[1]["eventos"]["CONFLITO"] == 1

    def test_configured_full_scope_zero_events_and_mixed_delivery(self):
        doc = config()
        ad = proof("ad", account="10", ad="20", adset="77", receivers=list(PHONES))
        doc["bindings"] = [ad]
        m, a = build(doc, [], {})
        assert (
            m["classificacao"] == "FARMA"
            and m["investimento_atribuivel"] == "12.50"
            and a["eventos"] == {}
        )
        ad["receivers"].append("DESCONHECIDO")
        assert build(doc, [], {})[0]["investimento_atribuivel"] == ""
        ad["receivers"] = ["DIRECT_FARMA"]
        with self.assertRaises(ValueError):
            reference(doc)
        ad["exclusive_ig_id"] = "00099"
        assert build(doc, [], {})[1]["configurado"] == "FARMA"
        fixture = fixtures.NativeMetaModelTests()
        fixture.setUp()
        event = dict(fixture.event, channel_uuid=CHANNEL)
        m, a = build(doc, [event, dict(event, segment="PET")], {})
        assert (
            a["configurado"] == "COMPARTILHADO" and m["investimento_atribuivel"] == ""
        )
        assert (
            build(doc, [], {}, datetime.fromisoformat(NOW).date().isoformat())[1][
                "cobertura"
            ]
            == "PARCIAL"
        )

    def test_changed_distribution_of_same_total_blocks_publication(self):
        import json
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace

        from tests import test_meta_ads_native as native

        graph = native.Client(accounts=("10",))
        graph.destination_adsets = graph.adsets
        original = graph.daily_insights

        def insights(*args, **kwargs):
            resp = original(*args, **kwargs)
            resp["dados"] = [
                dict(
                    r,
                    ad_id=ad,
                    actions=[
                        {"action_type": "messaging_conversation_started_7d", "value": n}
                    ],
                )
                for r in resp["dados"]
                for ad, n in (("11", "20"), ("22", "50"))
            ]
            return resp

        graph.daily_insights = insights
        store = native.Store()
        store.client = SimpleNamespace(
            config={"environment": "homologacao", "segment": "FARMA"}
        )
        store.get_control = lambda key: ""
        events = [
            dict(
                segment="FARMA",
                event_id=str(i),
                channel_uuid=CHANNEL,
                ad_id=ad,
                date=native.NOW.isoformat(),
            )
            for i, ad in enumerate(["11", "22", "22"])
        ]
        control = dict(
            inicio="2026-11-04",
            fim="2026-11-04",
            conta_id="10",
            moeda="BRL",
            eventos_por_anuncio={"11": 2, "22": 1},
            conversas_meta=70,
        )
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "destinos.json"
            p.write_text(json.dumps(dict(config(), controle=control)), encoding="utf-8")
            result = native.NativeSyncTests().run_sync(
                store,
                graph,
                Path(tmp),
                apply=True,
                settings=dict(
                    META_ADS_ENABLED=True,
                    META_ADS_DESTINOS_FILE=str(p),
                    WENI_INSIGHTS_PROJECT_UUID=PROJECT,
                    META_ADS_START_DATE=control["inicio"],
                    META_ADS_END_DATE=control["fim"],
                ),
                collector=lambda *a, **kw: (
                    events,
                    dict(segments={"FARMA": True, "PET": True}, channel_addresses={}),
                ),
            )
        self.assertEqual(result["status"], "controle_por_anuncio_divergente")
        self.assertEqual(
            [r["eventos_ctwa"] for r in result["controle_referencia"]], [1, 2]
        )
        self.assertEqual(store.writes, 0)
