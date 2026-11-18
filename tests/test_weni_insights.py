"""Transporte de leitura do Insights, sem acesso de rede ou credenciais reais."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import UUID

import requests

import weni_insights as daily
from ds_backend.contract import StorageError
from weni_insights import URL, fetch_day, session_for


class InsightsTransportTests(unittest.TestCase):
    def test_erros_transitorios_e_acesso_nao_se_tornam_zero(self):
        session = Mock()
        for status in (302, 401, 403, 429, 503):
            with self.subTest(status=status):
                session.get.return_value = Mock(status_code=status)
                with self.assertRaisesRegex(StorageError, f"DS_INSIGHTS_HTTP_{status}"):
                    fetch_day(session, "project", "2026-01-02")
                session.get.assert_called_with(
                    URL,
                    params=dict(
                        project_uuid="project",
                        start_date="2026-01-02",
                        end_date="2026-01-02",
                    ),
                    timeout=(10, 45),
                    allow_redirects=False,
                )
        session.get.side_effect = requests.Timeout("private transport detail")
        with self.assertRaisesRegex(
            StorageError, "^DS_INSIGHTS_CONSULTA_INDISPONIVEL$"
        ):
            fetch_day(session, "project", "2026-01-02")

    def test_usa_token_do_perfil_sem_arquivo_e_separa_a_credencial_dedicada(self):
        settings = SimpleNamespace(
            WENI_INSIGHTS_ENABLED=True, WENI_API_TOKEN="synthetic-flow"
        )
        project = "synthetic-project"
        with (
            tempfile.TemporaryDirectory() as folder,
            patch("weni_insights.ROOT", Path(folder)),
            patch.dict("os.environ", {"NEXOFLOW_PERFIL": "FARMA"}),
        ):
            with session_for(settings, project) as session:
                self.assertEqual(
                    session.headers["Authorization"], "Token synthetic-flow"
                )
            settings.WENI_INSIGHTS_CREDENTIAL_SOURCE = "arquivo"
            with self.assertRaisesRegex(StorageError, "CREDENCIAL_PRIVADA"):
                session_for(settings, project)
            path = Path(folder) / "credentials/weni/FARMA/insights.json"
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps(
                    dict(
                        project_uuid=project,
                        timezone="America/Belem",
                        segment="FARMA",
                        access_token="synthetic-insights",
                    )
                )
            )
            with session_for(settings, project) as session:
                self.assertEqual(
                    session.headers["Authorization"], "Bearer synthetic-insights"
                )
            with self.assertRaisesRegex(StorageError, "CREDENCIAL_PRIVADA"):
                session_for(settings, "other-project")
            with patch.dict("os.environ", {"NEXOFLOW_PERFIL": "PET"}):
                with self.assertRaisesRegex(StorageError, "DESABILITADO"):
                    session_for(settings, project)


def event(number, label="resolved", stamp="2026-01-02T13:00:00Z"):
    return dict(
        event_name="weni_nexus_data",
        key="conversation_classification",
        date=stamp,
        value=label,
        metadata=dict(
            conversation_uuid=str(UUID(int=number)),
            human_support=label == "Has Chat Room",
            conversation_end_date=stamp,
        ),
    )


def ok(value):
    return Mock(status_code=200, json=lambda: value)


class FlowsDailyTests(unittest.TestCase):
    def test_paginacao_retentativa_utc_deduplicacao_e_transferencia(self):
        session = Mock()
        offsets = []
        replies = iter(
            [
                ok([event(1), event(1)]),
                requests.Timeout(),
                ok([event(2, "Has Chat Room"), event(3, "unresolved")]),
                ok([]),
            ]
        )

        def get(url, *, params, timeout, allow_redirects):
            self.assertEqual(url, daily.WENI_EVENTS_API_URL)
            self.assertFalse(allow_redirects)
            self.assertEqual(params["date_start"], "2026-01-02T03:00:00Z")
            self.assertEqual(params["date_end"], "2026-01-03T02:59:59.999999Z")
            self.assertEqual(params["key"], "conversation_classification")
            offsets.append(params["offset"])
            response = next(replies)
            if isinstance(response, Exception):
                raise response
            return response

        session.get.side_effect = get
        with patch("weni_insights.time.sleep") as wait:
            self.assertEqual(
                daily.flows_day(session, "2026-01-02"),
                dict(zip(daily.METRICS, [3, 1, 1, 1], strict=True)),
            )
        self.assertEqual(offsets, [0, 2, 2, 4])
        wait.assert_called_once()
        session.get.side_effect = [ok([])]
        self.assertEqual(
            daily.flows_day(session, "2026-01-02"), dict.fromkeys(daily.METRICS, 0)
        )

    def test_incomplete_pages_do_not_replace_or_create_a_day(self):
        from contextlib import closing
        from datetime import date

        day = date(2026, 1, 2)
        bad_support = event(2)
        bad_support["metadata"]["human_support"] = True
        cross_day = event(2)
        cross_day["metadata"]["conversation_end_date"] = "2026-01-02T02:59:59Z"
        with (
            tempfile.TemporaryDirectory() as folder,
            patch("weni_insights.ROOT", Path(folder)),
            closing(daily.cache()) as conn,
        ):
            session = Mock()
            session.get.side_effect = [ok([event(1)]), ok([])]
            daily.collect(conn, session, "project", day, day, origin=daily.FLOWS)
            saved = conn.execute("SELECT * FROM dias").fetchall()
            for second in (
                [event(1, "unresolved")],
                [event(1)],
                [event(2, "new_class")],
                [bad_support],
                [cross_day],
                {},
                [dict(key="invalid")],
            ):
                with self.subTest(second=second):
                    session.get.side_effect = [ok([event(1)]), ok(second)]
                    with self.assertRaises(StorageError):
                        daily.collect(
                            conn,
                            session,
                            "project",
                            day,
                            day,
                            refresh=True,
                            origin=daily.FLOWS,
                        )
                    self.assertEqual(
                        conn.execute("SELECT * FROM dias").fetchall(), saved
                    )
            for code in (401, 403, 429, 503):
                session.get.side_effect = [ok([event(1)])] + [
                    Mock(status_code=code, headers={}) for _ in range(3)
                ]
                with (
                    patch("weni_insights.time.sleep"),
                    self.assertRaisesRegex(StorageError, f"DS_FLOWS_HTTP_{code}"),
                ):
                    daily.collect(
                        conn,
                        session,
                        "project",
                        day,
                        day,
                        refresh=True,
                        origin=daily.FLOWS,
                    )
                self.assertEqual(conn.execute("SELECT * FROM dias").fetchall(), saved)

    def test_org_perfil_fuso_e_pin(self):
        session = Mock()
        uid = str(UUID(int=99))
        for name, zone, pin, accepted in [
            ("Delivery FarmaLíder", daily.ZONE, uid, True),
            ("Delivery FarmaLíder", daily.ZONE, "", True),
            ("Delivery Pets Líder", daily.ZONE, uid, False),
            ("Delivery FarmaLíder", "UTC", uid, False),
            ("Delivery FarmaLíder", daily.ZONE, str(UUID(int=98)), False),
        ]:
            session.get.return_value = ok(dict(name=name, timezone=zone, uuid=uid))
            settings = SimpleNamespace(WENI_FLOWS_ORG_UUID=pin)
            if accepted:
                daily.verify_workspace(session, settings)
            else:
                with self.assertRaisesRegex(StorageError, "PROJETO_DIVERGENTE"):
                    daily.verify_workspace(session, settings)

    def test_cache_anterior_preserva_origem_e_recibo(self):
        from contextlib import closing

        with (
            tempfile.TemporaryDirectory() as folder,
            patch("weni_insights.ROOT", Path(folder)),
        ):
            parent = Path(folder) / "logs/privado"
            parent.mkdir(parents=True)
            with closing(sqlite3.connect(parent / "weni_insights.sqlite")) as old, old:
                old.execute(
                    "CREATE TABLE dias(projeto,dia,consulta,valores,PRIMARY KEY(projeto,dia))"
                )
                old.execute("INSERT INTO dias VALUES('p','2026-01-02','stamp','{}')")
                old.execute(
                    "CREATE TABLE recibos(destino,projeto,dia,hash,PRIMARY KEY(destino,projeto,dia))"
                )
                fingerprint = daily.digest(
                    dict(project="p", day="2026-01-02", observed="stamp", metrics={})
                )
                old.execute(
                    "INSERT INTO recibos VALUES('dest','p','2026-01-02',?)",
                    (fingerprint,),
                )
            with closing(daily.cache()) as db:
                client = Mock(expected_target="dest")
                self.assertEqual(daily.publish(db, client, "p"), 0)
                client.call.assert_not_called()
