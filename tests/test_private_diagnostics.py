import json
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock, patch

from farmalider_client import (
    FarmaliderClient,
    FarmaliderError,
    FarmaliderUnavailableError,
    RequestPermit,
)
from private_diagnostics import append_private_failure, sanitize_error_body

CPF = "52998224725"


def response(status, body=b'{"message":"Erro interno"}'):
    value = Mock(
        status_code=status, content=body, headers={"Content-Type": "application/json"}
    )
    value.json.return_value = {"segmento": "FARMA", "cliente": {"id": 1}}
    return value


class PrivateDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.folder = Path(self.directory.name)
        self.path_patch = patch(
            "private_diagnostics.private_diagnostic_directory", return_value=self.folder
        )
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)

    def client(self):
        client = FarmaliderClient("synthetic-private-token")
        self.addCleanup(client.close)
        return client

    def test_persistent_500_records_cpf_and_body_only_in_private_journal(self):
        client = self.client()
        raw = json.dumps(
            {
                "message": f"Erro {CPF}; token=synthetic-private-token; person@example.invalid",
                "cpf": CPF,
                "cliente": {"nome": "Private Name"},
                "token": "other-secret",
            }
        ).encode()
        with (
            patch.object(client.session, "get", return_value=response(500, raw)),
            patch.object(
                client,
                "_request_slot",
                side_effect=lambda _: nullcontext(RequestPermit(0, 4)),
            ),
            patch("farmalider_client.logging.warning") as warnings,
        ):
            with self.assertRaises(FarmaliderError):
                client.get_cliente_by_cpf(CPF)
        journal = next(self.folder.glob("*.jsonl"))
        record = json.loads(journal.read_text(encoding="utf-8"))
        self.assertEqual(record["cpf"], CPF)
        self.assertEqual(record["consulta_ref"], client.cpf_diagnostic_ref(CPF))
        self.assertEqual(record["status_http_5xx"], 500)
        self.assertEqual(record["tentativas_realizadas"], 4)
        self.assertTrue(record["horario"].endswith("-03:00"))
        self.assertEqual(record["resposta"]["campos_omitidos"], 3)
        private_text = journal.read_text(encoding="utf-8")
        for secret in (
            "synthetic-private-token",
            "other-secret",
            "person@example.invalid",
            "Private Name",
        ):
            self.assertNotIn(secret, private_text)
        public_text = "\n".join(
            call.args[0] % call.args[1:] for call in warnings.call_args_list
        )
        self.assertNotIn(CPF, public_text)
        self.assertNotIn("Erro " + CPF, public_text)

    def test_success_after_retry_does_not_record_private_failure(self):
        client = self.client()
        with (
            patch.object(
                client.session, "get", side_effect=[response(500), response(200)]
            ),
            patch.object(
                client,
                "_request_slot",
                side_effect=lambda _: nullcontext(RequestPermit(0, 4)),
            ),
        ):
            self.assertIn("cliente", client.get_cliente_by_cpf(CPF))
        self.assertEqual(list(self.folder.glob("*.jsonl")), [])

    def test_404_does_not_record_private_failure(self):
        client = self.client()
        with (
            patch.object(client.session, "get", return_value=response(404)),
            patch.object(
                client,
                "_request_slot",
                side_effect=lambda _: nullcontext(RequestPermit(0, 4)),
            ),
        ):
            self.assertIsNone(client.get_cliente_by_cpf(CPF))
        self.assertEqual(list(self.folder.glob("*.jsonl")), [])

    def test_reference_is_recorded_only_once_per_execution(self):
        client = self.client()
        with (
            patch.object(client.session, "get", return_value=response(500)),
            patch.object(
                client,
                "_request_slot",
                side_effect=lambda _: nullcontext(RequestPermit(0, 4)),
            ),
        ):
            for _ in range(2):
                with self.assertRaises(FarmaliderError):
                    client.get_cliente_by_cpf(CPF)
        self.assertEqual(
            len(
                next(self.folder.glob("*.jsonl"))
                .read_text(encoding="utf-8")
                .splitlines()
            ),
            1,
        )

    def test_operational_checkup_isolates_synthetic_customer_records(self):
        import private_diagnostics
        import run_checkup_tests

        captured = []

        def fake_run(suite):
            folder = private_diagnostics.private_diagnostic_directory()
            captured.append(folder)
            self.assertNotEqual(folder, self.folder)
            append_private_failure(
                execution_id="synthetic",
                reference="test",
                cpf=CPF,
                status=500,
                attempts=4,
                reason="test",
                environment="test",
                raw=b"{}",
                token="x",
                summary="test",
            )
            self.assertTrue(any(folder.glob("*.jsonl")))
            return Mock(**{"wasSuccessful.return_value": True})

        with (
            patch(
                "run_checkup_tests.unittest.defaultTestLoader.discover",
                return_value=unittest.TestSuite(),
            ),
            patch(
                "run_checkup_tests.unittest.TextTestRunner.run", side_effect=fake_run
            ),
        ):
            self.assertEqual(run_checkup_tests.main(), 0)
        self.assertFalse(captured[0].exists())
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_circuit_open_while_waiting_preserves_failed_query(self):
        client = self.client()
        with (
            patch.object(client.session, "get", return_value=response(500)),
            patch.object(
                client,
                "_request_slot",
                side_effect=[
                    nullcontext(RequestPermit(0, 4)),
                    FarmaliderUnavailableError("circuito"),
                ],
            ),
        ):
            with self.assertRaises(FarmaliderUnavailableError):
                client.get_cliente_by_cpf(CPF)
        record = json.loads(
            next(self.folder.glob("*.jsonl")).read_text(encoding="utf-8")
        )
        self.assertEqual(record["tentativas_realizadas"], 1)
        self.assertEqual(record["motivo_encerramento"], "circuito_aberto_na_fila")

    def test_failed_disk_write_does_not_mask_api_failure_or_leak_data(self):
        client = self.client()
        with (
            patch.object(client.session, "get", return_value=response(500)),
            patch.object(
                client,
                "_request_slot",
                side_effect=lambda _: nullcontext(RequestPermit(0, 4)),
            ),
            patch(
                "farmalider_client.append_private_failure",
                side_effect=PermissionError("secret disk detail"),
            ),
            patch("farmalider_client.logging.warning") as warnings,
        ):
            with self.assertRaisesRegex(FarmaliderError, "HTTP 500"):
                client.get_cliente_by_cpf(CPF)
        text = "\n".join(
            call.args[0] % call.args[1:] for call in warnings.call_args_list
        )
        self.assertNotIn("secret disk detail", text)
        self.assertNotIn(CPF, text)

    def test_body_limits_and_credentials_are_sanitized(self):
        raw = json.dumps(
            {
                "msg": 'https://user:pass@test.invalid/?token=x Bearer ABCDEF token="other-secret" 529.982.247-25 (91) 99999-0000',
                "code": 16899535009,
            }
        ).encode()
        text = json.dumps(sanitize_error_body(raw, "known-token"))
        for private in (
            "test.invalid",
            "ABCDEF",
            "other-secret",
            "529.982",
            "99999",
            "16899535009",
        ):
            self.assertNotIn(private, text)
        self.assertEqual(
            sanitize_error_body(b"x" * 4097, "x")["estado"], "omitido_por_tamanho"
        )
        self.assertEqual(
            sanitize_error_body(b"<html>secret</html>", "x")["estado"],
            "omitido_nao_json",
        )

    def test_invalid_identity_is_not_saved(self):
        path = append_private_failure(
            execution_id="test",
            reference="ref",
            cpf="not-a-cpf",
            status=500,
            attempts=4,
            reason="test",
            environment="test",
            raw=b"{}",
            token="x",
            summary="safe",
        )
        self.assertIsNone(path)
        self.assertEqual(list(self.folder.iterdir()), [])
