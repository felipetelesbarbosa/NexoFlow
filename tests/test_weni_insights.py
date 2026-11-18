"""Transporte de leitura do Insights, sem acesso de rede ou credenciais reais."""

import unittest
from unittest.mock import Mock

import requests

from ds_backend.contract import StorageError
from weni_insights import URL, fetch_day


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
