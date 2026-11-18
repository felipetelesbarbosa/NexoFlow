"""Transporte de leitura do Insights, sem acesso de rede ou credenciais reais."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests

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
                    session.headers["Authorization"], "Bearer synthetic-flow"
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
