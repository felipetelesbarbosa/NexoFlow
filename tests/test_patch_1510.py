"""Contratos FARMA e rejeição terminal de segmento, sem APIs reais."""

import unittest
from unittest.mock import Mock

from farmalider_client import FarmaliderLookupError
from recompra import campaign_fields, inspect_structure, propose
from tests.test_recompra import NOW, STRUCTURE, fixture
from tests.test_recompra_prevention import weni_fixture
from weni_update import ContactUpdatePlan, _apply_purchase_candidate


class Patch1510Tests(unittest.TestCase):
    def test_farma_structure_accepts_actual_fields_without_ultima_compra(self):
        client, _ = weni_fixture("FARMA", [])
        fields = [f for f in client.list_fields() if f["key"] != "ultima_compra"]
        fields.append({"key": "ultimo_pedido", "value_type": "text"})
        client.list_fields.return_value = fields
        self.assertFalse(inspect_structure(client, segment="FARMA")["errors"])
        self.assertIn("ultimo_pedido", campaign_fields("FARMA"))
        self.assertNotIn("ultima_compra", campaign_fields("FARMA"))

    def test_farma_order_id_is_text_and_date_remains_pedido_data(self):
        contact, order, items = fixture(24)
        plan = propose(contact, order, items, STRUCTURE, now=NOW)
        self.assertEqual(plan["fields"].get("ultimo_pedido"), order["pedido_id"])
        self.assertEqual(plan["fields"]["pedido_data"], order["data_hora"])
        self.assertNotIn("ultima_compra", plan["fields"])
        update = ContactUpdatePlan("u1")
        _apply_purchase_candidate(
            update,
            contact,
            farm_client=Mock(),
            captured_at=NOW.isoformat(),
            resolved_order=(order, items),
            available_weni_fields=campaign_fields("FARMA"),
        )
        self.assertEqual(update.fields.get("ultimo_pedido"), order["pedido_id"])

    def test_unconfirmed_segment_is_invalid_without_query_pending(self):
        from recompra_review_audit import has_incomplete_query

        error = FarmaliderLookupError("ERRO_SEGMENTO_NAO_CONFIRMADO_API")
        self.assertEqual(error.code, "PEDIDO_SEGMENTO_INVALIDO_API")
        for grouped in (False, True):
            contact, _, _ = fixture(24, grouped=grouped)
            plan = propose(
                contact, {"status_confirmacao": error.code}, [], STRUCTURE, now=NOW
            )
            self.assertFalse(has_incomplete_query(plan))
            self.assertEqual(plan["action"], "remove" if grouped else "")
            self.assertFalse(plan["fields"])

    def test_invalid_segment_does_not_block_analytics_or_fall_back_to_old_order(self):
        from contextlib import closing
        from unittest.mock import patch

        from farmalider_client import FarmaliderClient
        from farmalider_integration import resolve_contact_order
        from main import FarmaliderSettings, _completion_controls, validate_contacts
        from recompra_profiles import PetRecompraClient
        from tests.test_farmalider_customers import CPF, customer_snapshot

        for cls in (FarmaliderClient, PetRecompraClient):
            for marker in (None, "DESCONHECIDO"):
                with (
                    self.subTest(client=cls.__name__, marker=marker),
                    closing(cls("synthetic")) as farm,
                ):
                    payload = customer_snapshot()
                    payload["ultimoPedido"]["segmento"] = marker
                    contact = {
                        "uuid": "c1",
                        "name": "Pessoa",
                        "fields": {
                            "cpf": CPF,
                            "pedido_id": "111",
                            "ultimo_pedido": "111",
                        },
                    }
                    with (
                        patch.object(farm, "_request_json", return_value=payload),
                        patch.object(farm, "get_pedido") as get_order,
                    ):
                        rows = [{"contact_uuid": "c1", "cpf": CPF}]
                        statuses = {}
                        stats = validate_contacts(
                            rows,
                            farm_client=farm,
                            farm_settings=FarmaliderSettings(True, "synthetic", False),
                            sync_time=NOW.isoformat(),
                            cliente_lookup_status_by_cpf=statuses,
                        )
                        self.assertEqual(stats.api_errors, 0)
                        self.assertEqual(
                            rows[0]["farmalider_cliente_status"],
                            "PEDIDO_SEGMENTO_INVALIDO_API",
                        )
                        order, items = resolve_contact_order(
                            contact,
                            farm_client=farm,
                            captured_at=NOW.isoformat(),
                            cliente_lookup_status="PEDIDO_SEGMENTO_INVALIDO_API",
                        )
                        self.assertEqual(
                            order["status_confirmacao"], "PEDIDO_SEGMENTO_INVALIDO_API"
                        )
                        self.assertFalse(items)
                        get_order.assert_not_called()
                        self.assertEqual(
                            _completion_controls(NOW, api_errors=stats.api_errors)[0],
                            "sucesso",
                        )

    def test_creation_diagnostics_distinguish_local_revalidation_from_weni_rejection(
        self,
    ):
        import tempfile
        from copy import deepcopy
        from pathlib import Path
        from unittest.mock import patch

        from customer_discovery import CreationSession, build_new_customer_plans
        from tests.test_customer_bridge import farm_for
        from tests.test_farmalider_customers import customer_snapshot
        from weni_client import WeniError
        from weni_update import REQUIRED_ORDER_FIELDS, UpdateStats, _apply_creation

        with (
            tempfile.TemporaryDirectory() as folder,
            patch("customer_observations.DB_ROOT", Path(folder)),
        ):
            payload = customer_snapshot()
            farm = farm_for(payload)
            plan = build_new_customer_plans(
                farm,
                [],
                captured_at=NOW.isoformat(),
                available_fields=REQUIRED_ORDER_FIELDS | {"cpf"},
            )[0][0]
            weni = Mock()
            weni.list_contacts.return_value = []
            weni.get_contact.return_value = None
            session = CreationSession(weni, farm)
            changed = deepcopy(farm.customer_directory.snapshots)
            farm.customer_directory.snapshots.clear()
            stats = UpdateStats()
            with patch("weni_update._append_audit") as audit:
                _apply_creation(session, plan, stats)
                self.assertEqual(
                    stats.creation_pending, {"FONTE_ALTERADA_APOS_REVISAO": 1}
                )
                self.assertEqual(audit.call_args.args[0]["stage"], "revalidar_fonte")
                weni.create_contact.assert_not_called()
            farm.customer_directory.snapshots.update(changed)
            weni.create_contact.side_effect = WeniError(
                "sintético",
                status_code=400,
                validation={"reason": "TELEFONE_OU_URN_INVALIDO", "fields": ["urns"]},
            )
            stats = UpdateStats()
            with patch("weni_update._append_audit") as audit:
                _apply_creation(session, plan, stats)
                self.assertEqual(
                    stats.creation_pending,
                    {"WENI_HTTP_400_TELEFONE_OU_URN_INVALIDO": 1},
                )
                self.assertEqual(audit.call_args.args[0]["stage"], "criar_contato")
                self.assertEqual(audit.call_args.args[0]["http_status"], 400)

    def test_individual_order_without_segment_or_with_foreign_segment_is_invalid(self):
        from contextlib import closing
        from unittest.mock import patch

        from farmalider_client import FarmaliderClient
        from farmalider_integration import apply_pedido_api_confirmation
        from recompra_profiles import PetRecompraClient
        from tests.test_farmalider_customers import customer_snapshot

        for cls, foreign in ((FarmaliderClient, "PET"), (PetRecompraClient, "FARMA")):
            for marker in (None, foreign, "DESCONHECIDO"):
                with (
                    self.subTest(client=cls.__name__, marker=marker),
                    closing(cls("synthetic")) as farm,
                ):
                    snapshot = customer_snapshot()
                    snapshot["ultimoPedido"]["segmento"] = marker
                    raw = {"capa": snapshot["ultimoPedido"], "itens": snapshot["itens"]}
                    with patch.object(farm, "_request_json", return_value=raw):
                        response = farm.get_pedido(8)
                    order, items = apply_pedido_api_confirmation(
                        {"pedido_id": "8"},
                        [],
                        response,
                        linked_cliente_id="17",
                        confirmed_at=NOW.isoformat(),
                    )
                    self.assertEqual(
                        order["status_confirmacao"], "PEDIDO_SEGMENTO_INVALIDO_API"
                    )
                    self.assertFalse(items)

    def test_null_individual_order_does_not_revive_snapshot(self):
        from farmalider_integration import resolve_contact_order
        from tests.test_customer_bridge import farm_for
        from tests.test_farmalider_customers import customer_snapshot

        farm = farm_for(customer_snapshot())
        farm.get_pedido = Mock(return_value={"_nexoflow_no_order": True})
        contact, _, _ = fixture(24)
        self.assertEqual(
            resolve_contact_order(
                contact, farm_client=farm, captured_at=NOW.isoformat()
            ),
            (None, []),
        )

    def test_http200_null_order_is_distinct_from_malformed_json_and_404(self):
        from contextlib import closing
        from unittest.mock import patch

        import requests

        from farmalider_client import FarmaliderClient, FarmaliderError

        for status, content in ((200, b"null"), (404, b""), (200, b"{broken")):
            with (
                self.subTest(status=status, content=content),
                closing(FarmaliderClient("synthetic")) as farm,
            ):
                response = requests.Response()
                response.status_code = status
                response._content = content
                with patch.object(farm.session, "get", return_value=response):
                    if content == b"{broken":
                        with self.assertRaises(FarmaliderError):
                            farm.get_pedido("8")
                    elif status == 404:
                        self.assertIsNone(farm.get_pedido("8"))
                    else:
                        self.assertEqual(
                            farm.get_pedido("8"), {"_nexoflow_no_order": True}
                        )

    def test_weni_global_validation_message_is_preserved_with_known_values_hidden(self):
        import json

        import requests

        from weni_client import WeniClient

        response = requests.Response()
        response.status_code = 400
        response._content = json.dumps(
            {
                "detail": "Cannot create contact Pessoa Sintetica, whatsapp:5591999999999, cpf 52998224725, token secret-synthetic. Check URN scheme."
            }
        ).encode()
        response.headers["X-Request-ID"] = "12345678-1234-1234-1234-123456789012"
        summary = WeniClient._validation_summary(
            response,
            {
                "name": "Pessoa Sintetica",
                "urns": ["whatsapp:5591999999999"],
                "fields": {"cpf": "52998224725"},
            },
            sensitive_values=("secret-synthetic",),
        )
        self.assertEqual(summary["reason"], "VALIDACAO_REJEITADA")
        self.assertIn("Check URN scheme", summary["messages"][0])
        self.assertEqual(len(summary["response_sha256"]), 64)
        self.assertEqual(summary["request_id"], response.headers["X-Request-ID"])
        for private in (
            "Pessoa",
            "Sintetica",
            "5591999999999",
            "52998224725",
            "secret-synthetic",
        ):
            self.assertNotIn(private, str(summary))

    def test_customer_directory_membership_does_not_prove_unmarked_individual_order(
        self,
    ):
        from contextlib import closing
        from unittest.mock import patch

        from farmalider_client import FarmaliderClient, FarmaliderLookupError
        from farmalider_customers import CustomerDirectory
        from tests.test_farmalider_customers import CPF, customer_snapshot

        snapshot = customer_snapshot()
        with closing(FarmaliderClient("synthetic")) as farm:
            farm.customer_directory = CustomerDirectory([snapshot["cliente"]])
            snapshot["ultimoPedido"].pop("segmento", None)
            with patch.object(farm, "_request_json", return_value=snapshot):
                with self.assertRaises(FarmaliderLookupError) as raised:
                    farm.get_cliente_by_cpf(CPF)
                self.assertEqual(raised.exception.code, "PEDIDO_SEGMENTO_INVALIDO_API")

    def test_official_textual_order_id_remains_a_locator_and_not_purchase_evidence(
        self,
    ):
        from farmalider_integration import _ultimo_pedido_locator_id

        for value in ("123", 123, {"value": "123"}, '{"pedido_id":"123"}'):
            self.assertEqual(_ultimo_pedido_locator_id({"ultimo_pedido": value}), "123")
        for value in ("0", "-1", "1.2", True, None, "not-an-id"):
            self.assertEqual(_ultimo_pedido_locator_id({"ultimo_pedido": value}), "")
