"""Aceite amostral do Noturno real FARMA. Não gera planos nem recibos READY."""

import os
from decimal import Decimal, InvalidOperation

from meta_ads_recovery import (
    observed_media_metrics,
    read_complete_rows,
    recover_direct_conversations,
)

from .real_read_transport import (
    ProbePending,
    ReadOnlySession,
    private_token,
    require_scope,
)

SCENARIO = "leitura_real_amostral"
DAYS = ("2026-11-07", "2026-11-09")
ACCOUNT = "898435729140540"
AD = "120250534034080073"


def probe_meta(client):
    """Ref. Windows 07 e 09/11; nunca utiliza o histórico de referência como fato."""
    account = client.account_details(ACCOUNT)
    if str(account.get("account_id")) != ACCOUNT or account.get("currency") != "BRL":
        raise ProbePending("CONTA_META_DIVERGENTE")
    catalog = {
        str(a["id"]): a
        for a in read_complete_rows(client.ads(ACCOUNT, limit=100, pages=None))
    }
    if AD not in catalog:
        raise ProbePending("ANUNCIO_REFERENCIA_AUSENTE")
    response = client.daily_insights(ACCOUNT, DAYS[0], DAYS[-1], pages=None)
    rows = [r for r in read_complete_rows(response) if str(r.get("ad_id")) == AD]
    if any(str(r.get("account_id")) != ACCOUNT for r in rows):
        raise ProbePending("CONTA_META_DIVERGENTE")
    reference = [
        {
            "conta_id": ACCOUNT,
            "anuncio_id": AD,
            "data": day,
            "segmento": "FARMA",
            "classificacao": "FARMA",
            "impressoes": "",
            "investimento_original": "0",
            "conversas_iniciadas_meta": "1",
        }
        for day in DAYS
    ]
    # Evidência agregada da campanha na referência Windows; só habilita a regra
    # de recuperação. Não integra fatos observados nem o resultado financeiro.
    reference.append(
        dict(
            reference[0],
            data="2026-11-01",
            impressoes="32365",
            investimento_original="199.78",
            conversas_iniciadas_meta="",
        )
    )
    recovered, report = recover_direct_conversations(
        client,
        ACCOUNT,
        reference,
        rows,
        ads=[catalog[AD]],
        since=DAYS[0],
        end=DAYS[-1],
        meta={
            "currency": account["currency"],
            "timezone_name": account["timezone_name"],
        },
        attribution=response["attribution"],
        api_version=response["api_version"],
        policy="aceite_amostral_farma_20261127",
    )
    out = []
    for day in DAYS:
        originals = [
            r for r in rows if r.get("date_start") == r.get("date_stop") == day
        ]
        direct = [r for r in recovered if r.get("date_start") == day]
        facts = direct or originals
        metric = observed_media_metrics(facts[0]) if len(facts) == 1 else None
        try:
            match = metric is not None and Decimal(
                metric["conversas_iniciadas_meta"]
            ) == Decimal("1")
        except (InvalidOperation, TypeError):
            match = False
        out.append(
            {
                "dia": day,
                "origem": "consulta_direta"
                if direct
                else "consulta_conta"
                if originals
                else "indisponivel",
                "metricas": metric,
                "paridade_referencia_windows": match,
            }
        )
    return {
        "estado": "amostra_validada"
        if all(r["paridade_referencia_windows"] for r in out)
        else "parcial",
        "fonte": "MetaAdsClient",
        "sintetico": False,
        "periodo": [DAYS[0], DAYS[-1]],
        "conta": ACCOUNT,
        "anuncio_referencia": AD,
        "recuperacao": report,
        "dias": out,
        "cobertura_integral": False,
        "consultas_http": client.metrics_snapshot().get("GET", 0),
    }


def meta_from_worker():
    require_scope()
    from meta_ads_client import MetaAdsClient
    from meta_ads_settings import MetaSettings

    if os.environ.get("HUB_META_ACCOUNT_ID") != ACCOUNT:
        raise ProbePending("CONTA_META_DIVERGENTE")
    token = private_token("HUB_META_TOKEN_FILE")
    version = os.environ.get("HUB_META_API_VERSION", "")
    session = ReadOnlySession(
        host="graph.facebook.com",
        port=443,
        path_allowed=lambda p: p.startswith("/" + version + "/"),
        proxy_var="HUB_META_PROXY_URL",
        proxy_expected="http://farma-meta-egress:3128",
    )
    try:
        with MetaAdsClient(
            MetaSettings(token, version, (ACCOUNT,)), session=session, max_attempts=2
        ) as client:
            return probe_meta(client)
    finally:
        session.close()


def weni_from_worker():
    require_scope()
    from weni_client import WeniClient

    client = WeniClient(
        private_token("HUB_WENI_FLOWS_READ_TOKEN_FILE"), retry_mutations=False
    )
    original = client.session
    try:
        session = ReadOnlySession(
            host="flows.weni.ai",
            port=443,
            path_allowed=lambda p: (
                p
                in {
                    "/api/v2/org.json",
                    "/api/v2/contacts.json",
                    "/api/v2/messages.json",
                    "/api/v2/groups.json",
                }
            ),
            proxy_var="HUB_SOURCE_PROXY_URL",
            proxy_expected="http://farma-fontes-egress:3128",
        )
        session.headers.update(original.headers)
        client.session = session
        probe = client.test_update_access("Opt-Out LGPD")
        return {
            "estado": "amostra_validada" if probe["opt_out_group_found"] else "parcial",
            "fonte": "WeniClient",
            "sintetico": False,
            "contatos_amostra": probe["sample_contacts"],
            "mensagens_amostra": probe["sample_messages"],
            "grupo_opt_out_confirmado": probe["opt_out_group_found"],
            "cobertura_integral": False,
        }
    finally:
        original.close()
        client.close()


def safe_source(fn):
    # Não publicar exceções, URLs, corpo de respostas, CPFs ou token.
    try:
        return fn()
    except ProbePending as exc:
        return {"estado": "pendente", "motivo": str(exc)}
    except Exception as exc:
        code = getattr(exc, "status_code", None)
        return {
            "estado": "pendente",
            "motivo": "LEITURA_NAO_CONFIRMADA",
            "http": code if type(code) is int and 400 <= code <= 599 else None,
        }


def collect_sources():
    require_scope()
    from .farma_read_probe import run_from_worker

    # Meta primeiro: evidência independente não fica bloqueada por Farma/Weni.
    return {
        "meta": safe_source(meta_from_worker),
        "weni": safe_source(weni_from_worker),
        "farmalider": safe_source(lambda: run_from_worker(DAYS[0], DAYS[-1])),
    }


def run_noturno_probe(store, task):
    """Mesmo dispatch do Noturno; confirma só pré-requisitos, sem adaptar escritas.

    A leitura amostral não confirma etapas comerciais. Nenhum checkpoint de
    plano/publicação é criado; a próxima etapa permanece Atualização Weni.
    """
    from pathlib import Path
    from threading import Event, Thread

    from .store import LostLease

    if task["segmento"] != "FARMA":
        raise ValueError("SEGMENTO_INVALIDO")

    stopped, lost = Event(), Event()

    def heartbeat():
        while not stopped.wait(min(5.0, store.settings.lease_seconds / 3)):
            try:
                store.renew_lease(task)
                Path("/tmp/hub-worker-heartbeat").touch()
            except Exception:
                lost.set()
                return

    store.renew_lease(task)
    thread = Thread(target=heartbeat, name="nf-real-read-lease", daemon=True)
    thread.start()
    try:
        try:
            sources = collect_sources()
        except ProbePending:
            sources = {
                n: {"estado": "pendente", "motivo": "ESCOPO_FARMA_HML_OBRIGATORIO"}
                for n in ("meta", "weni", "farmalider")
            }
    finally:
        stopped.set()
        thread.join()
    if lost.is_set():
        raise LostLease("LEASE_PERDIDO")

    pending = [
        {
            "fonte": n,
            "motivo": "FONTE_ESSENCIAL_INCOMPLETA",
            "tratamento": "validar_cobertura_integral_e_planos",
        }
        for n in ("weni", "farmalider")
    ]
    if sources["meta"].get("estado") != "amostra_validada":
        pending.append(
            {
                "fonte": "anuncios",
                "motivo": "COBERTURA_PARCIAL",
                "tratamento": "verificar_meta",
            }
        )
    # Sempre revisão: a amostra não prova a cobertura/planos do Noturno inteiro.
    store.finish(
        task,
        "revisao_necessaria",
        error="FONTE_ESSENCIAL_INCOMPLETA",
        result={
            "modo": SCENARIO,
            "periodo_referencia": list(DAYS),
            "fontes": sources,
            "primeira_etapa_pendente": "atualizacao_weni",
            "externas_gravacoes": 0,
            "publicacoes": 0,
            "etapas": {
                name: {
                    "estado": "nao_executada",
                    "motivo": "AMOSTRA_NAO_CONFIRMA_PLANO",
                }
                for name in (
                    "atualizacao_weni",
                    "analytics",
                    "publicacao",
                    "recompra",
                    "analytics_final",
                )
            },
            "pendencias": pending,
        },
    )
