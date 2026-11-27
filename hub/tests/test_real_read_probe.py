import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import requests
from nexoflow_hub.noturno import run_noturno
from nexoflow_hub.real_read_probe import (
    ACCOUNT,
    AD,
    DAYS,
    SCENARIO,
    collect_sources,
    probe_meta,
    safe_source,
)
from nexoflow_hub.real_read_transport import (
    ProbePending,
    ReadOnlySession,
    require_scope,
)

ATTR = {
    "mode": "explicit_windows",
    "action_report_time": "impression",
    "action_attribution_windows": ["7d_click", "1d_view"],
}
SCOPE = {
    "HUB_AMBIENTE": "homologacao",
    "HUB_ESCRITA_REAL": "false",
    "NEXOFLOW_PERFIL": "FARMA",
    "HUB_REAL_READ_PROBE_ENABLED": "true",
    "WENI_PROXY_ACTIVE": "0",
}


class Meta:
    def __init__(self, wrong=False):
        self.direct = []
        self.wrong = wrong

    def account_details(self, account):
        return {
            "account_id": account,
            "currency": "BRL",
            "timezone_name": "America/Noronha",
        }

    def ads(self, account, **kw):
        return {"dados": [{"id": AD}], "parcial": False}

    def daily_insights(self, account, start, end, *, pages, ad_id=None):
        rows = []
        if ad_id:
            self.direct.append(start)
            rows = [
                {
                    "account_id": "999999" if self.wrong else ACCOUNT,
                    "ad_id": ad_id,
                    "date_start": start,
                    "date_stop": end,
                    "spend": "0.00",
                    "actions": [
                        {
                            "action_type": "messaging_conversation_started_7d",
                            "value": "1",
                        }
                    ],
                }
            ]
        return {
            "dados": rows,
            "parcial": False,
            "attribution": ATTR,
            "api_version": "v26.0",
            "time_increment": 1,
        }

    def metrics_snapshot(self):
        return {"GET": 3 + len(self.direct)}


class FakeStore:
    settings = SimpleNamespace(lease_seconds=30)

    def renew_lease(self, task):
        pass

    def finish(self, task, state, **kw):
        self.result = (state, kw)


class RealReadTests(unittest.TestCase):
    def test_real_adapter_uses_shared_recovery(self):
        m = Meta()
        out = probe_meta(m)
        self.assertEqual(m.direct, list(DAYS))
        self.assertEqual(
            out["recuperacao"], {"linhas_omitidas": 2, "consultas": 2, "recuperadas": 2}
        )
        self.assertEqual(out["estado"], "amostra_validada")
        self.assertFalse(out["cobertura_integral"])
        for d in out["dias"]:
            self.assertEqual(d["metricas"]["conversas_iniciadas_meta"], "1.00")
            self.assertEqual(d["metricas"]["impressoes"], "")
            self.assertEqual(d["metricas"]["ctr_pct"], "")
            self.assertEqual(d["metricas"]["cpm"], "")

    def test_missing_data_not_filled_from_reference(self):
        out = probe_meta(Meta(wrong=True))
        self.assertEqual(out["estado"], "parcial")
        self.assertEqual(out["recuperacao"]["recuperadas"], 0)
        self.assertTrue(all(d["metricas"] is None for d in out["dias"]))

    def test_scope_fails_closed(self):
        with patch.dict(os.environ, {**SCOPE, "NEXOFLOW_PERFIL": "PET"}, clear=True):
            with self.assertRaises(ProbePending):
                require_scope()

    def test_transport_refuses_write_wrong_destination_and_http(self):
        with patch.dict(os.environ, {"P": "http://farma-fontes-egress:3128"}):
            with ReadOnlySession(
                host="api.farmalider.net.br",
                port=3200,
                path_allowed=lambda p: p == "/farmalider/api/Delivery/pedidos/farma",
                proxy_var="P",
                proxy_expected="http://farma-fontes-egress:3128",
            ) as s:
                with patch("requests.Session.send") as mocked:
                    for method, url in [
                        (
                            "POST",
                            "https://api.farmalider.net.br:3200/farmalider/api/Delivery/pedidos/farma",
                        ),
                        (
                            "GET",
                            "http://api.farmalider.net.br:3200/farmalider/api/Delivery/pedidos/farma",
                        ),
                        (
                            "GET",
                            "https://api.farmalider.net.br:3200/farmalider/api/Delivery/pedidos/pet",
                        ),
                        (
                            "GET",
                            "https://api.farmalider.net.br/farmalider/api/Delivery/pedidos/farma",
                        ),
                    ]:
                        with self.assertRaises(ProbePending):
                            s.send(requests.Request(method, url).prepare())
                    mocked.assert_not_called()
                    good = requests.Request(
                        "GET",
                        "https://api.farmalider.net.br:3200/farmalider/api/Delivery/pedidos/farma",
                    ).prepare()
                    s.send(
                        good,
                        proxies={"https": "http://wrong.invalid"},
                        allow_redirects=True,
                    )
                    self.assertEqual(
                        mocked.call_args.kwargs["proxies"],
                        {"https": "http://farma-fontes-egress:3128"},
                    )
                    self.assertFalse(mocked.call_args.kwargs["allow_redirects"])
                    self.assertTrue(mocked.call_args.kwargs["verify"])

    def test_pending_farma_does_not_block_meta(self):
        with (
            patch.dict(os.environ, SCOPE, clear=True),
            patch(
                "nexoflow_hub.real_read_probe.meta_from_worker",
                return_value={"estado": "amostra_validada"},
            ),
            patch(
                "nexoflow_hub.real_read_probe.weni_from_worker",
                return_value={"estado": "amostra_validada"},
            ),
        ):
            sources = collect_sources()
        self.assertEqual(sources["meta"]["estado"], "amostra_validada")
        self.assertEqual(sources["farmalider"]["motivo"], "CREDENCIAL_NAO_PROVISIONADA")

    def test_exception_details_do_not_escape(self):
        def failure():
            raise ValueError("https://example.invalid/?token=fixture_secret")

        self.assertEqual(
            safe_source(failure),
            {"estado": "pendente", "motivo": "LEITURA_NAO_CONFIRMADA", "http": None},
        )

    def test_noturno_route_never_uses_fixture_or_publisher(self):
        st = FakeStore()
        with patch(
            "nexoflow_hub.real_read_probe.collect_sources",
            return_value={
                "meta": {"estado": "amostra_validada"},
                "weni": {"estado": "amostra_validada"},
                "farmalider": {"estado": "pendente"},
            },
        ):
            run_noturno(st, {"cenario": SCENARIO, "segmento": "FARMA"})
        state, data = st.result
        self.assertEqual(state, "revisao_necessaria")
        out = data["result"]
        self.assertEqual(out["externas_gravacoes"], 0)
        self.assertEqual(out["publicacoes"], 0)
        self.assertEqual(out["fontes"]["meta"]["estado"], "amostra_validada")
        self.assertTrue(
            all(e["estado"] == "nao_executada" for e in out["etapas"].values())
        )

    def test_pet_task_never_collects(self):
        with patch("nexoflow_hub.real_read_probe.collect_sources") as collect:
            with self.assertRaises(ValueError):
                run_noturno(FakeStore(), {"cenario": SCENARIO, "segmento": "PET"})
            collect.assert_not_called()
