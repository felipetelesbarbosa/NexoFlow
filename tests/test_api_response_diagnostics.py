"""HTTP 200, segmentação e criação Weni: regressões sem chamadas reais."""

import json
import unittest
from unittest.mock import Mock, patch

import requests

from farmalider_client import FarmaliderClient, FarmaliderLookupError
from main import FarmaliderSettings, _query_cliente, validate_contacts
from recompra import build_plans
from recompra_profiles import PetRecompraClient
from tests.test_farmalider_customers import CPF, customer_snapshot
from tests.test_recompra import NOW, STRUCTURE, fixture
from weni_client import WeniClient, WeniError


class ApiResponseDiagnosticsTests(unittest.TestCase):
    def test_http_200_empty_customer_list_is_absence_not_api_failure(self):
        for cls in (FarmaliderClient, PetRecompraClient):
            client = cls("TOKEN_SINTETICO")
            self.addCleanup(client.close)
            with patch.object(client, "_request_json", return_value=[]):
                self.assertIsNone(client.get_cliente_by_cpf(CPF))

    def test_segment_validation_reports_explicit_reason_without_accepting_other_base(
        self,
    ):
        for cls, accepted, rejected in (
            (FarmaliderClient, "FARMA", "PET"),
            (PetRecompraClient, "PET", "FARMA"),
        ):
            client = cls("TOKEN_SINTETICO")
            self.addCleanup(client.close)
            for marker, expected in (
                (rejected, "CPF_FORA_SEGMENTO_API"),
                (None, "ERRO_SEGMENTO_NAO_CONFIRMADO_API"),
            ):
                payload = customer_snapshot()
                payload["ultimoPedido"].pop("segmento", None)
                if marker:
                    payload["ultimoPedido"]["segmento"] = marker
                with patch.object(client, "_request_json", return_value=payload):
                    with self.assertRaises(FarmaliderLookupError) as raised:
                        client.get_cliente_by_cpf(CPF)
                    self.assertEqual(raised.exception.code, expected)
                    self.assertNotIn(CPF, str(raised.exception))
            payload["ultimoPedido"]["segmento"] = accepted
            with patch.object(client, "_request_json", return_value=payload):
                self.assertIsNotNone(client.get_cliente_by_cpf(CPF))

    def test_json_decode_error_after_http200_is_not_reported_as_http_failure(self):
        client = FarmaliderClient("TOKEN_SINTETICO")
        self.addCleanup(client.close)
        response = requests.Response()
        response.status_code = 200
        response._content = b"<html>not json</html>"
        with patch.object(client.session, "get", return_value=response):
            with self.assertRaises(FarmaliderLookupError) as raised:
                client.get_cliente_by_cpf(CPF)
            self.assertEqual(raised.exception.code, "ERRO_JSON_CLIENTE_API")
            self.assertEqual(client.metrics_snapshot()["responses_200"], 1)

    def test_analytics_preserves_typed_incomplete_response(self):
        farm = Mock()
        farm.get_cliente_by_cpf.side_effect = FarmaliderLookupError(
            "ERRO_SEGMENTO_NAO_CONFIRMADO_API"
        )
        self.assertEqual(
            _query_cliente(CPF, farm)[0], "ERRO_SEGMENTO_NAO_CONFIRMADO_API"
        )

    def test_recompra_pet_keeps_failed_contact_pending_without_admission(self):
        farm = Mock()
        farm.get_cliente_by_cpf.side_effect = FarmaliderLookupError(
            "ERRO_SEGMENTO_NAO_CONFIRMADO_API"
        )
        structure = {**STRUCTURE, "segment": "PET"}
        plans = build_plans(
            [fixture()[0]], farm, structure, {"schema": 1, "contacts": {}}, now=NOW
        )
        self.assertEqual(plans[0]["reason"], "ERRO_SEGMENTO_NAO_CONFIRMADO_API")
        self.assertFalse(plans[0]["action"] == "add")

    def test_analytics_many_failures_are_logged_by_batch_without_contact_spam(self):
        from tests.test_farmalider_server_errors import NEW_TIME

        rows = [{"contact_uuid": "contact-one", "cpf": CPF}]
        farm = Mock()
        farm.get_cliente_by_cpf.side_effect = FarmaliderLookupError(
            "ERRO_SEGMENTO_NAO_CONFIRMADO_API"
        )
        farm.metrics_snapshot.return_value = {
            "total_requests": 1,
            "retries": 0,
            "rate_limits": 0,
            "server_errors": 0,
            "max_response_ms": 0,
            "effective_delay_ms": 0,
            "responses_200": 1,
            "responses_404": 0,
        }
        with patch("main.logging.info") as logs:
            stats = validate_contacts(
                rows,
                existing_by_uuid={},
                farm_settings=FarmaliderSettings(True, "SINTETICO", False),
                farm_client=farm,
                sync_time=NEW_TIME,
            )
        text = "\n".join(call.args[0] % call.args[1:] for call in logs.call_args_list)
        self.assertEqual(stats.api_errors, 1)
        self.assertIn("resultado do lote", text)
        self.assertNotIn("falha para", text)
        self.assertNotIn(CPF, text)

    def test_recompra_reuses_definitive_segment_failure_only_within_execution(self):
        from recompra import RecompraReadCache

        farm = Mock()
        farm.get_cliente_by_cpf.side_effect = FarmaliderLookupError(
            "CPF_FORA_SEGMENTO_API"
        )
        reads = RecompraReadCache(farm)
        for _ in range(2):
            with self.assertRaises(FarmaliderLookupError):
                reads.get_cliente_by_cpf(CPF)
        self.assertEqual(farm.get_cliente_by_cpf.call_count, 1)
        with self.assertRaises(FarmaliderLookupError):
            RecompraReadCache(farm).get_cliente_by_cpf(CPF)
        self.assertEqual(farm.get_cliente_by_cpf.call_count, 2)

    def test_weni_validation_diagnostics_do_not_echo_phone_token_or_person(self):
        response = requests.Response()
        response.status_code = 400
        response._content = json.dumps(
            {
                "urns": ["URN belongs to another contact: whatsapp:5591999999999"],
                "fields": [
                    "Invalid contact field key: pedido_id; private-name; secret-token"
                ],
            }
        ).encode()
        client = WeniClient("SINTETICO")
        client._profile_verified = True
        self.addCleanup(client.close)
        with patch.object(client.session, "request", return_value=response) as call:
            with self.assertRaises(WeniError) as raised:
                client.create_contact(
                    name="Pessoa",
                    urns=["whatsapp:5591999999999"],
                    fields={"pedido_id": "123", "pedido_valor": 9.99},
                )
        self.assertEqual(call.call_count, 1)
        self.assertEqual(
            call.call_args.kwargs["json"]["fields"]["pedido_valor"], "9.99"
        )
        self.assertIn("TELEFONE_JA_CADASTRADO", str(raised.exception))
        self.assertIn("pedido_id", raised.exception.validation["fields"])
        for sensitive in ("5591999999999", "private-name", "secret-token"):
            self.assertNotIn(sensitive, str(raised.exception))
