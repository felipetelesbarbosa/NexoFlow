"""Coleta diária independente de contatos e pedidos, com retomada local em SQLite."""

from __future__ import annotations

import argparse
import json
import sqlite3
from contextlib import closing
from datetime import UTC, date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

import requests

from ds_backend.contract import StorageError, digest
from project_paths import ROOT, load_private_settings
from runtime_profile import scoped_path, segment

ZONE = "America/Belem"
METRICS = ("conversas_weni", "resolvidas", "nao_resolvidas", "transferidas")
REMOTE = ("total_conversations", "resolved", "unresolved", "transferred_to_human")
URL = "https://insights-engine.weni.ai/v1/metrics/conversations/totals/"


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


def session_for(project):
    path = ROOT / "credentials/weni/FARMA/insights.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        token = data["access_token"]
        if (
            data["project_uuid"] != project
            or data["timezone"] != ZONE
            or data["segment"] != "FARMA"
            or not isinstance(token, str)
            or not token
            or not token.isascii()
            or not token.isprintable()
            or any(c.isspace() for c in token)
        ):
            raise ValueError
    except (OSError, TypeError, ValueError, KeyError):
        raise StorageError("DS_INSIGHTS_CREDENCIAL_PRIVADA") from None
    session = requests.Session()
    session.headers["Authorization"] = "Bearer " + token
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
    return conn


def collect(conn, session, project, first, last, *, refresh=False):
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
        metrics = fetch_day(session, project, day)
        with conn:
            conn.execute(
                """INSERT INTO dias VALUES(?,?,?,?) ON CONFLICT(projeto,dia)
                DO UPDATE SET consulta=excluded.consulta,valores=excluded.valores
                WHERE dias.consulta < excluded.consulta""",
                (project, day, started, json.dumps(metrics)),
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
    with session_for(project) as session, closing(cache()) as conn:
        return collect(conn, session, project, lo, hi, refresh=bool(start))


def publish(conn, client, project):
    count = 0
    for day, timestamp, raw, previous in conn.execute(
        """SELECT d.dia,d.consulta,d.valores,r.hash FROM dias d LEFT JOIN recibos r
        ON (r.projeto,r.dia,r.destino)=(d.projeto,d.dia,?) WHERE d.projeto=? ORDER BY d.dia""",
        (client.expected_target, project),
    ):
        payload = dict(
            project=project, day=day, observed=timestamp, metrics=json.loads(raw)
        )
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
        with session_for(project) as session:
            print(json.dumps(fetch_day(session, project, args.inicio)))
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
