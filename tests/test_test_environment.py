"""A suíte não consulta configuração ou rede da máquina operacional."""

import socket
import sys
import unittest

from tests import settings


class TestEnvironmentTests(unittest.TestCase):
    def test_secrets_are_synthetic_and_do_not_have_a_source_file(self):
        self.assertIs(sys.modules["secrets_config"], settings)
        self.assertFalse(hasattr(settings, "__file__"))
        self.assertEqual(settings.WENI_API_TOKEN, "TOKEN_SINTETICO_WENI")
        self.assertEqual(settings.PROXY_MODE, "off")

    def test_unmocked_network_connection_is_blocked(self):
        with socket.socket() as connection:
            with self.assertRaisesRegex(RuntimeError, "Use mocks"):
                connection.connect(("127.0.0.1", 1))

    def test_unmocked_nonblocking_network_connection_is_blocked(self):
        with socket.socket() as connection:
            with self.assertRaisesRegex(RuntimeError, "Use mocks"):
                connection.connect_ex(("127.0.0.1", 1))
