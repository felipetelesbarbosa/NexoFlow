"""Ensaio fechado FARMA: só dados sintéticos, persistência via checkpoint do worker."""

from meta_ads_destinations import reconcile_conversation_days
from meta_ads_recovery import (
    MetaReadError,
    merge_observations,
    observed_media_metrics,
    recover_direct_conversations,
)

DAYS = ("2026-11-07", "2026-11-09")
ACCOUNT = "99900001"  # identificadores fictícios, nunca usados em HTTP
AD = "99900002"
META = {"currency": "BRL", "timezone_name": "America/Belem"}
ATTRIBUTION = {
    "mode": "explicit_windows",
    "action_report_time": "impression",
    "action_attribution_windows": ["7d_click", "1d_view"],
}
API_VERSION = "v26.0"
POLICY = "fixture_v1"


def _row(day, spend):
    return {
        "account_id": ACCOUNT,
        "ad_id": AD,
        "date_start": day,
        "date_stop": day,
        "spend": spend,
        "clicks": "5",
        "actions": [
            {"action_type": "messaging_conversation_started_7d", "value": "1"},
        ],
    }


def _fact(row):
    return dict(row, **META, attribution_policy=POLICY)


def _summary(fact):
    return {
        "segmento": "FARMA",
        "classificacao": "FARMA",
        "conta_id": fact["account_id"],
        "anuncio_id": fact["ad_id"],
        "data": fact["date_start"],
        **observed_media_metrics(fact),
    }


class FixtureMetaRead:
    def __init__(self, *, fail_days=()):
        self.fail_days = frozenset(fail_days)
        self.reads = []

    def daily_insights(self, account, start, end, *, pages, ad_id):
        if (account, ad_id, pages) != (ACCOUNT, AD, 1) or start != end or start not in DAYS:
            raise AssertionError("CONSULTA_FIXTURE_FORA_DO_ESCOPO")
        self.reads.append(start)
        if start in self.fail_days:
            raise MetaReadError("REDE_FIXTURE", retryable=True)
        return {
            "dados": [_row(start, "10.00" if start == DAYS[0] else "12.50")],
            "parcial": False,
            "time_increment": 1,
            "attribution": ATTRIBUTION,
            "api_version": API_VERSION,
        }


def run_meta_recovery(client):
    # Revisão anterior sintética com valores distintos para tornar o teste
    # de conservação observável, inclusive investimento e impressões.
    previous = [
        _fact(dict(_row(day, "9.00"), impressions="100"))
        for day in DAYS
    ]
    published = [_summary(fact) for fact in previous]
    account_response = []  # ambos os dias omitidos na consulta por conta
    recovered, report = recover_direct_conversations(
        client, ACCOUNT, published, account_response,
        ads=[{"id": AD}], since=DAYS[0], end=DAYS[-1],
        meta=META, attribution=ATTRIBUTION, api_version=API_VERSION, policy=POLICY,
    )
    refreshed = account_response + recovered
    merged = merge_observations(previous, refreshed)
    unresolved = [
        entry for entry in reconcile_conversation_days(
            published, [_summary(fact) for fact in merged], refreshed,
            {ACCOUNT: (DAYS[0], DAYS[-1])},
        )
        if entry["acao"] == "PENDENTE_HISTORICO"
    ]
    recovered_days = {row["date_start"] for row in recovered}
    return {
        "fonte": "fixture",
        "regra": "meta_ads_recovery.recover_direct_conversations",
        "sintetico": True,
        **report,
        "cobertura": "parcial" if unresolved else "completa",
        "pendencias": [entry["data"] for entry in unresolved],
        "linhas": [
            dict(_summary(fact),
                 origem="consulta_direta" if fact["date_start"] in recovered_days
                 else "historico_preservado")
            for fact in merged
        ],
    }


def evaluate_meta_fixture(scenario):
    if scenario not in {"meta_recuperacao", "meta_consulta_direta_falha"}:
        raise ValueError("CENARIO_META_NAO_HABILITADO")
    client = FixtureMetaRead(
        fail_days=DAYS if scenario == "meta_consulta_direta_falha" else (),
    )
    result = run_meta_recovery(client)
    result["dias_consultados"] = client.reads
    return result
