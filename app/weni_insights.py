"""Coleta diária independente de contatos e pedidos, com retomada local em SQLite."""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from contextlib import closing
from datetime import UTC, date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

import requests

from config import WENI_EVENTS_API_URL
from ds_backend.contract import StorageError, digest
from project_paths import ROOT, load_private_settings
from runtime_profile import scoped_path, segment

ZONE = "America/Belem"
METRICS = ("conversas_weni", "resolvidas", "nao_resolvidas", "transferidas")
REMOTE = ("total_conversations", "resolved", "unresolved", "transferred_to_human")
URL = "https://insights-engine.weni.ai/v1/metrics/conversations/totals/"


PAGE_SIZE = 100
FLOWS = "WENI_FLOWS_V2"
INSIGHTS = "WENI_INSIGHTS"
CLASSIFICATION = {
    "resolved": "resolvidas",
    "unresolved": "nao_resolvidas",
    "Has Chat Room": "transferidas",
}


def origin_for(settings):
    return (
        FLOWS
        if getattr(settings, "WENI_INSIGHTS_CREDENTIAL_SOURCE", "perfil") == "perfil"
        else INSIGHTS
    )


def flows_get(session, url, params=None):
    """Repete apenas o GET da mesma página, sem consumir ou registrar os dados de erro."""
    for attempt in range(3):
        delay = 2**attempt
        try:
            response = session.get(
                url, params=params, timeout=(10, 60), allow_redirects=False
            )
            status = response.status_code
            if status == 200:
                try:
                    return response.json()
                except ValueError:
                    raise StorageError("DS_FLOWS_RESPOSTA_INCOMPLETA") from None
            error = f"DS_FLOWS_HTTP_{status}"
            if status not in (429, 500, 502, 503, 504):
                raise StorageError(error)
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                if (
                    not retry_after.isascii()
                    or not retry_after.isdecimal()
                    or len(retry_after) > 3
                    or int(retry_after) > 60
                ):
                    raise StorageError(error)
                delay = max(delay, int(retry_after))
        except (requests.Timeout, requests.ConnectionError):
            error = "DS_FLOWS_CONSULTA_INDISPONIVEL"
        except requests.RequestException:
            raise StorageError("DS_FLOWS_CONSULTA_INDISPONIVEL") from None
        if attempt == 2:
            raise StorageError(error)
        time.sleep(delay)
    raise AssertionError("tentativas esgotadas")


def verify_workspace(session, settings):
    org = flows_get(session, "https://flows.weni.ai/api/v2/org.json")
    if (
        not isinstance(org, dict)
        or org.get("name") != "Delivery FarmaLíder"
        or org.get("timezone") != ZONE
    ):
        raise StorageError("DS_FLOWS_PROJETO_DIVERGENTE")
    try:
        org_id = UUID(org["uuid"])
        pinned = getattr(settings, "WENI_FLOWS_ORG_UUID", "")
        if not org_id.int or (pinned and org_id != UUID(pinned)):
            raise ValueError
    except (KeyError, ValueError, TypeError, AttributeError):
        raise StorageError("DS_FLOWS_PROJETO_DIVERGENTE") from None


def flows_day(session, day):
    local = ZoneInfo(ZONE)
    start = datetime.combine(date.fromisoformat(day), datetime.min.time(), local)
    end = start + timedelta(days=1)
    params = dict(
        date_start=start.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        date_end=(end - timedelta(microseconds=1))
        .astimezone(UTC)
        .isoformat()
        .replace("+00:00", "Z"),
        key="conversation_classification",
        limit=PAGE_SIZE,
    )
    seen = {}
    offset = 0
    while True:
        page = flows_get(session, WENI_EVENTS_API_URL, {**params, "offset": offset})
        if not isinstance(page, list) or len(page) > PAGE_SIZE:
            raise StorageError("DS_FLOWS_RESPOSTA_INCOMPLETA")
        if not page:
            break
        before = len(seen)
        for row in page:
            try:
                if (
                    row["event_name"] != "weni_nexus_data"
                    or row["key"] != params["key"]
                ):
                    raise ValueError
                meta = row["metadata"]
                identity = UUID(meta["conversation_uuid"])
                metric = CLASSIFICATION[row["value"]]
                if not identity.int or meta["human_support"] is not (
                    metric == "transferidas"
                ):
                    raise ValueError
                event = datetime.fromisoformat(row["date"])
                closed = datetime.fromisoformat(meta["conversation_end_date"])
                if (
                    event.tzinfo is None
                    or not start <= event < end
                    or closed.tzinfo is None
                    or not start <= closed < end
                ):
                    raise ValueError
            except (KeyError, TypeError, ValueError, AttributeError):
                raise StorageError("DS_FLOWS_CLASSIFICACAO_INVALIDA") from None
            if seen.setdefault(identity, metric) != metric:
                raise StorageError("DS_FLOWS_CLASSIFICACAO_CONFLITANTE")
        if before == len(seen):
            raise StorageError("DS_FLOWS_PAGINA_SEM_PROGRESSO")
        offset += len(page)
    metrics = dict.fromkeys(METRICS, 0)
    for metric in seen.values():
        metrics[metric] += 1
    metrics["conversas_weni"] = len(seen)
    return metrics


def enabled(settings):
    return (
        segment() == "FARMA"
        and getattr(settings, "WENI_INSIGHTS_ENABLED", False) is True
    )


def options(settings):
    if not enabled(settings):
        raise StorageError("DS_INSIGHTS_DESABILITADO")
    try:
        project = str(UUID(settings.WENI_INSIGHTS_PROJECT_UUID))
        first = date.fromisoformat(settings.WENI_INSIGHTS_START_DATE)
    except (AttributeError, ValueError, TypeError):
        raise StorageError("DS_INSIGHTS_CONFIGURACAO") from None
    return project, first


def fetch_day(session, project, day):
    try:
        response = session.get(
            URL,
            params=dict(project_uuid=project, start_date=day, end_date=day),
            timeout=(10, 45),
            allow_redirects=False,
        )
        if response.status_code != 200:
            raise StorageError(f"DS_INSIGHTS_HTTP_{response.status_code}")
        body = response.json()
        if not isinstance(body, dict) or not all(k in body for k in REMOTE):
            raise ValueError
        values = [body[k]["value"] for k in REMOTE]
        if not all(type(v) is int and 0 <= v <= 2**31 - 1 for v in values):
            raise ValueError
        return dict(zip(METRICS, values, strict=True))
    except StorageError:
        raise
    except requests.RequestException:
        raise StorageError("DS_INSIGHTS_CONSULTA_INDISPONIVEL") from None
    except (TypeError, KeyError, ValueError):
        raise StorageError("DS_INSIGHTS_RESPOSTA_INCOMPLETA") from None


def session_for(settings, project):
    if not enabled(settings):
        raise StorageError("DS_INSIGHTS_DESABILITADO")
    source = getattr(settings, "WENI_INSIGHTS_CREDENTIAL_SOURCE", "perfil")
    try:
        if source == "perfil":
            token = settings.WENI_API_TOKEN
        elif source == "arquivo":
            path = ROOT / "credentials/weni/FARMA/insights.json"
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            if (
                data["project_uuid"] != project
                or data["timezone"] != ZONE
                or data["segment"] != "FARMA"
            ):
                raise ValueError
            token = data["access_token"]
        else:
            raise ValueError
        if (
            not isinstance(token, str)
            or not token
            or not token.isascii()
            or not token.isprintable()
            or any(c.isspace() for c in token)
        ):
            raise ValueError
    except (OSError, TypeError, ValueError, KeyError, AttributeError):
        raise StorageError("DS_INSIGHTS_CREDENCIAL_PRIVADA") from None
    session = requests.Session()
    session.headers["Authorization"] = (
        "Token " if source == "perfil" else "Bearer "
    ) + token
    return session


def cache():
    path = ROOT / scoped_path("logs/privado/weni_insights.sqlite")
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.execute("""CREATE TABLE IF NOT EXISTS dias(
        projeto TEXT NOT NULL, dia TEXT NOT NULL, consulta TEXT NOT NULL, valores TEXT NOT NULL,
        PRIMARY KEY(projeto,dia))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS recibos(
        destino TEXT NOT NULL, projeto TEXT NOT NULL, dia TEXT NOT NULL, hash TEXT NOT NULL,
        PRIMARY KEY(destino,projeto,dia))""")
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        if "origem" not in {row[1] for row in conn.execute("PRAGMA table_info(dias)")}:
            conn.execute(
                "ALTER TABLE dias ADD COLUMN origem TEXT NOT NULL DEFAULT 'WENI_INSIGHTS'"
            )
    return conn


def collect(conn, session, project, first, last, *, refresh=False, origin=INSIGHTS):
    count = 0
    while first <= last:
        day = first.isoformat()
        first += timedelta(days=1)
        if (
            not refresh
            and conn.execute(
                "SELECT 1 FROM dias WHERE projeto=? AND dia=?", (project, day)
            ).fetchone()
        ):
            continue
        started = datetime.now(UTC).isoformat(timespec="microseconds")
        metrics = (
            flows_day(session, day)
            if origin == FLOWS
            else fetch_day(session, project, day)
        )
        with conn:
            conn.execute(
                """INSERT INTO dias (projeto,dia,consulta,valores,origem) VALUES(?,?,?,?,?) ON CONFLICT(projeto,dia)
                DO UPDATE SET consulta=excluded.consulta,valores=excluded.valores,origem=excluded.origem
                WHERE dias.consulta < excluded.consulta""",
                (project, day, started, json.dumps(metrics), origin),
            )
        count += 1
    return count


def collect_configured(settings, start=None, end=None):
    project, first = options(settings)
    yesterday = datetime.now(ZoneInfo(ZONE)).date() - timedelta(days=1)
    if bool(start) != bool(end):
        raise StorageError("DS_INSIGHTS_PERIODO_INVALIDO")
    lo, hi = (
        (date.fromisoformat(start), date.fromisoformat(end))
        if start and end
        else (first, yesterday)
    )
    if lo < first or hi > yesterday or (start and lo > hi):
        raise StorageError("DS_INSIGHTS_PERIODO_INVALIDO")
    with session_for(settings, project) as session, closing(cache()) as conn:
        origin = origin_for(settings)
        if origin == FLOWS:
            verify_workspace(session, settings)
        return collect(
            conn, session, project, lo, hi, refresh=bool(start), origin=origin
        )


def publish(conn, client, project):
    count = 0
    for day, timestamp, raw, origin, previous in conn.execute(
        """SELECT d.dia,d.consulta,d.valores,d.origem,r.hash FROM dias d LEFT JOIN recibos r
        ON (r.projeto,r.dia,r.destino)=(d.projeto,d.dia,?) WHERE d.projeto=? ORDER BY d.dia""",
        (client.expected_target, project),
    ):
        payload = dict(
            project=project, day=day, observed=timestamp, metrics=json.loads(raw)
        )
        if origin == FLOWS:
            payload["origin"] = origin
        elif origin != INSIGHTS:
            raise StorageError("DS_INSIGHTS_ORIGEM_DIVERGENTE")
        fingerprint = digest(payload)
        if fingerprint == previous:
            continue
        ack = client.call("/v1/weni/conversas-diarias", payload)
        if ack != dict(
            state="CONFIRMADO", hash=fingerprint, target=client.expected_target
        ):
            raise StorageError("DS_INSIGHTS_RECIBO_DIVERGENTE")
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO recibos VALUES(?,?,?,?)",
                (client.expected_target, project, day, fingerprint),
            )
        count += 1
    return count


def publish_configured(settings, client):
    project, _ = options(settings)
    with closing(cache()) as conn:
        return publish(conn, client, project)


def main(argv=None):
    from ds_backend.client import Client
    from ds_backend.client import enabled as postgres
    from proxy_config import configure_proxy

    parser = argparse.ArgumentParser(
        description="Consulta Insights FARMA e publicação de dias confirmados"
    )
    parser.add_argument("acao", choices=("conferir-acesso", "coletar", "publicar"))
    parser.add_argument("--inicio")
    parser.add_argument("--fim")
    args = parser.parse_args(argv)
    configure_proxy()
    settings = load_private_settings()
    project, _ = options(settings)
    if args.acao == "conferir-acesso":
        if (
            not args.inicio
            or args.fim
            or date.fromisoformat(args.inicio) >= datetime.now(ZoneInfo(ZONE)).date()
        ):
            parser.error("Informe um dia encerrado em --inicio.")
        with session_for(settings, project) as session:
            if origin_for(settings) == FLOWS:
                verify_workspace(session, settings)
                metrics = flows_day(session, args.inicio)
            else:
                metrics = fetch_day(session, project, args.inicio)
            print(json.dumps(metrics))
    elif args.acao == "coletar":
        print("Dias consultados:", collect_configured(settings, args.inicio, args.fim))
    else:
        if args.inicio or args.fim or not postgres(settings):
            parser.error("A publicação exige backend postgres e usa os dias guardados.")
        with closing(Client.from_settings(settings)) as client:
            print("Recibos confirmados:", publish_configured(settings, client))


if __name__ == "__main__":
    try:
        main()
    except StorageError as error:
        print("[PENDÊNCIA]", error)
        raise SystemExit(3) from None
