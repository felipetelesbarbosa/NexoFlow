import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

import nexo_cli


class NexoCliTests(unittest.TestCase):
    def test_spreadsheet_load_commands_route_to_separate_targets(self):
        for args, expected in [
            (["weni", "planilhas"], "comandos/atualizar_weni_planilhas.bat"),
            (["analytics", "planilhas"], "comandos/executar_analytics_planilhas.bat"),
            (["analytics"], "NexoFlow Analytics.exe"),
        ]:
            with (
                self.subTest(args=args),
                patch("nexo_cli._run_windows_target", return_value=0) as runner,
            ):
                self.assertEqual(nexo_cli.run(args), 0)
                runner.assert_called_once_with(expected)

    def test_looker_routes_dates_to_the_sheet_rebuild(self):
        with patch("run_looker.run", return_value=0) as runner:
            self.assertEqual(
                nexo_cli.run(
                    ["looker", "--inicio", "2026-10-01", "--fim", "2026-10-11"]
                ),
                0,
            )
        runner.assert_called_once_with(
            ["--inicio", "2026-10-01", "--fim", "2026-10-11"]
        )

    def test_help_lists_friendly_commands(self) -> None:
        out = io.StringIO()
        with redirect_stdout(out):
            code = nexo_cli.run(["ajuda"])
        text = out.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("nexo status", text)
        self.assertIn("nexo api weni contato", text)
        self.assertIn("nexo api farmalider pedido", text)
        self.assertIn("nexo logs weni --seguir", text)

    def test_weni_contact_query_is_read_only(self) -> None:
        client = Mock()
        client.get_contact.return_value = {
            "uuid": "u1",
            "name": "Cliente",
            "urns": ["whatsapp:5591000000000"],
            "fields": {"cpf": "52998224725"},
        }
        out = io.StringIO()
        with (
            patch("nexo_cli._make_weni_client", return_value=client),
            redirect_stdout(out),
        ):
            code = nexo_cli.run(["api", "weni", "contato", "--uuid", "u1"])
        self.assertEqual(code, 0)
        client.get_contact.assert_called_once_with(uuid="u1", urn=None)
        client.update_contact_fields.assert_not_called()
        client.contact_group_action.assert_not_called()
        client.close.assert_called_once()

    def test_farmalider_order_query_uses_get_pedido(self) -> None:
        client = Mock()
        client.get_pedido.return_value = {"codigo": 123456, "status": "OK"}
        out = io.StringIO()
        with (
            patch("nexo_cli._make_farmalider_client", return_value=client),
            redirect_stdout(out),
        ):
            code = nexo_cli.run(["api", "farmalider", "pedido", "123456"])
        self.assertEqual(code, 0)
        client.get_pedido.assert_called_once_with("123456")
        client.close.assert_called_once()

    def test_weni_messages_passes_requested_limit(self) -> None:
        client = Mock()
        client.list_messages.return_value = []
        with (
            patch("nexo_cli._make_weni_client", return_value=client),
            redirect_stdout(io.StringIO()),
        ):
            code = nexo_cli.run(
                ["api", "weni", "mensagens", "--uuid", "u1", "--limite", "7"]
            )
        self.assertEqual(code, 0)
        client.list_messages.assert_called_once_with(contact="u1", urn=None, limit=7)


if __name__ == "__main__":
    unittest.main()
