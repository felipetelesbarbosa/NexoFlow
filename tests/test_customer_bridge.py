"""Cadastro e histórico reversos com APIs simuladas e banco privado temporário."""

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from customer_discovery import CreationSession, build_new_customer_plans
from customer_observations import acknowledge, history_rows, record_directory
from farmalider_customers import CustomerDirectory
from tests.test_farmalider_customers import CPF, customer_snapshot
from weni_update import (
    REQUIRED_ORDER_FIELDS,
    UpdateStats,
    audit_plans,
    load_review_snapshot,
    write_review_snapshot,
)

NOW = "2026-10-29T10:00:00-03:00"


def farm_for(payload):
    from runtime_profile import segment

    directory = CustomerDirectory([payload], segment=segment())
    return SimpleNamespace(
        customer_directory=directory,
        get_cliente_by_cpf=lambda cpf: directory.latest_by_cpf(cpf),
        get_pedido=lambda code: directory.order_by_id(str(code)),
    )


class CustomerBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        patcher = patch("customer_observations.DB_ROOT", Path(self.temp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.payload = customer_snapshot()
        self.farm = farm_for(self.payload)
        self.fields = REQUIRED_ORDER_FIELDS | {
            "cpf",
            "genero",
            "idade",
            "cep",
            "cidade",
            "estado",
            "bairro",
            "email",
            "origem_contato",
        }

    def plans(self, contacts=None):
        return build_new_customer_plans(
            self.farm, contacts or [], captured_at=NOW, available_fields=self.fields
        )[0]

    def weni(self):
        w = Mock()
        w.list_contacts.return_value = []
        w.get_contact.return_value = None
        w.create_contact.side_effect = lambda **kw: {"uuid": "created-1", **kw}
        return w

    def test_dry_run_includes_valid_order_without_groups_or_consent(self):
        plan = self.plans()[0]
        audit_plans([plan], opt_out_group_available=True)
        self.assertEqual(plan.fields["cpf"], CPF)
        self.assertEqual(plan.fields["pedido_id"], "8")
        self.assertFalse(plan.group_actions)
        self.assertNotIn("opt_in_lgpd", plan.fields)
        self.assertNotIn("marketing_opt_in", plan.fields)
        path = Path(self.temp.name) / "review.json"
        write_review_snapshot(
            [plan], UpdateStats(), full=False, json_path=path, captured_at_utc=NOW
        )
        restored, _, _ = load_review_snapshot(full=False, json_path=path)
        self.assertEqual(restored[0].guards, plan.guards)
        data = json.loads(path.read_text())
        data["plans"][0]["guards"]["__new_api_customer"]["name"] = "Alterado"
        path.write_text(json.dumps(data))
        with self.assertRaises(RuntimeError):
            load_review_snapshot(full=False, json_path=path)

    def test_cpf_or_phone_already_present_prevents_duplicate(self):
        for fields, urns in (({"cpf": CPF}, []), ({}, ["tel:+5591987654321"])):
            self.assertFalse(
                self.plans([{"uuid": "existing", "fields": fields, "urns": urns}])
            )

    def test_invalid_cpf_and_ambiguous_api_customers_are_not_self_validated(self):
        for payloads in (
            [customer_snapshot(cpf=123)],
            [customer_snapshot(), customer_snapshot(id=18)],
        ):
            self.farm.customer_directory = CustomerDirectory(payloads)
            self.assertFalse(self.plans())

    def test_creation_is_idempotent_and_retry_after_unknown_post_is_blocked(self):
        plan = self.plans()[0]
        w = self.weni()
        session = CreationSession(w, self.farm)
        self.assertEqual(session.apply(plan), ("created", "created-1"))
        self.assertEqual(session.apply(plan)[0], "already_exists")
        self.assertEqual(w.create_contact.call_count, 1)
        # Nem outra sessão com leitura atrasada pode repetir uma criação confirmada.
        with self.assertRaises(RuntimeError):
            CreationSession(w, self.farm).apply(plan)
        self.assertEqual(w.create_contact.call_count, 1)

    def test_timeout_after_server_commit_is_reconciled_without_new_post(self):
        plan = self.plans()[0]
        w = self.weni()
        w.create_contact.side_effect = RuntimeError("Timeout sintético")
        with self.assertRaises(RuntimeError):
            CreationSession(w, self.farm).apply(plan)
        with self.assertRaises(RuntimeError):
            CreationSession(w, self.farm).apply(plan)
        self.assertEqual(w.create_contact.call_count, 1)
        w.list_contacts.return_value = [{"uuid": "created-1", "fields": {"cpf": CPF}}]
        self.assertEqual(CreationSession(w, self.farm).apply(plan)[0], "already_exists")

    def test_api_change_after_review_blocks_only_creation(self):
        plan = self.plans()[0]
        w = self.weni()
        changed = deepcopy(self.payload)
        changed["ultimoPedido"]["status"] = 3
        self.farm.customer_directory = CustomerDirectory([changed])
        with self.assertRaises(RuntimeError):
            CreationSession(w, self.farm).apply(plan)
        w.create_contact.assert_not_called()

    def test_customer_without_phone_can_be_created_without_fabricated_urn(self):
        self.farm = farm_for(customer_snapshot(celular=None))
        plan = self.plans()[0]
        w = self.weni()
        CreationSession(w, self.farm).apply(plan)
        self.assertEqual(w.create_contact.call_args.kwargs["urns"], [])

    def test_journal_keeps_two_orders_and_relinks_after_contact_creation(self):
        record_directory(self.farm.customer_directory, NOW)
        second = deepcopy(self.payload)
        second["ultimoPedido"]["id"] = 9
        second["itens"][0]["codPedido"] = 9
        record_directory(CustomerDirectory([second]), NOW)
        orders, items, receipts = history_rows([], [], captured_at=NOW)
        self.assertEqual({o["pedido_id"] for o in orders}, {"8", "9"})
        self.assertEqual(len(items), 2)
        self.assertTrue(all(not o["contact_uuid"] for o in orders))
        acknowledge(receipts)
        self.assertFalse(history_rows([], [], captured_at=NOW)[0])
        contact = {
            "uuid": "created-1",
            "name": "Pessoa Sintética",
            "fields": {"cpf": CPF},
        }
        orders, _, receipts = history_rows([contact], orders, captured_at=NOW)
        self.assertEqual({o["contact_uuid"] for o in orders}, {"created-1"})
        acknowledge(receipts)
        self.assertFalse(history_rows([contact], orders, captured_at=NOW)[0])

    def test_old_financials_preserved_but_first_discovery_keeps_old_order(self):
        record_directory(self.farm.customer_directory, NOW)
        orders, _, _ = history_rows([], [], captured_at=NOW)
        self.assertEqual(len(orders), 1)
        original = dict(orders[0], valor_total_compra="77.00")
        replay, _, _ = history_rows([], [original], captured_at=NOW)
        self.assertEqual(replay[0]["valor_total_compra"], "77.00")

    def test_history_invalid_cpf_requires_independent_weni_identity(self):
        invalid = CustomerDirectory([customer_snapshot(cpf=123)])
        record_directory(invalid, NOW)
        self.assertFalse(history_rows([], [], captured_at=NOW)[0])
        contact = {"uuid": "existing", "name": "Pessoa", "fields": {"cpf": "123"}}
        orders, _, _ = history_rows([contact], [], captured_at=NOW)
        self.assertEqual(len(orders), 1)
        self.assertTrue(orders[0]["origem_pedido"].endswith("_IDENTIDADE_VALIDADA"))

    def test_rejected_creation_can_retry_but_unknown_outcome_cannot(self):
        from weni_client import WeniError

        plan = self.plans()[0]
        w = self.weni()
        w.create_contact.side_effect = WeniError(
            "Campo inválido sintético", status_code=400
        )
        with self.assertRaises(WeniError):
            CreationSession(w, self.farm).apply(plan)
        w.create_contact.side_effect = lambda **kw: {"uuid": "created-1", **kw}
        self.assertEqual(CreationSession(w, self.farm).apply(plan)[0], "created")

    def test_history_reaches_sheets_and_buyer_kpis_without_weni_contact(self):
        from analytics import build_bi_summary_record
        from tests.test_pharmacy_scope import store_fixture

        record_directory(self.farm.customer_directory, NOW)
        orders, items, receipts = history_rows([], [], captured_at=NOW)
        store = store_fixture()
        result, details = store.upsert_pharmacy_orders(orders, items)
        self.assertEqual(len(result.final_records), 1)
        summary = build_bi_summary_record(
            [],
            result.final_records,
            details.final_records,
            snapshot_date="2026-10-29",
            updated_at=NOW,
        )
        self.assertEqual(summary["clientes_compradores_total"], 1)
        acknowledge(receipts)
        result2, _ = store.upsert_pharmacy_orders(orders, items)
        self.assertEqual(len(result2.final_records), 1)

    def test_creation_post_timeout_has_only_one_attempt(self):
        import requests

        from weni_client import WeniClient, WeniError

        client = WeniClient("synthetic")
        self.addCleanup(client.close)
        client._profile_verified = True
        with patch.object(
            client.session, "request", side_effect=requests.ReadTimeout("sintético")
        ) as request:
            with self.assertRaises(WeniError):
                client.create_contact(name="Pessoa", urns=[], fields={"cpf": CPF})
            self.assertEqual(request.call_count, 1)

    def test_copied_database_from_other_segment_is_refused(self):
        from customer_observations import connect

        record_directory(self.farm.customer_directory, NOW)
        with connect() as db:
            db.execute("UPDATE profile SET segment='PET'")
        with self.assertRaises(ValueError):
            history_rows([], [], captured_at=NOW)

    def test_current_status_wins_and_first_capture_is_preserved(self):
        from customer_observations import merge_history

        old = {
            "pedido_chave": "x",
            "capturado_em": "2026-10-01T10:00:00-03:00",
            "farmalider_status_pedido": "2",
        }
        current = {
            "pedido_chave": "x",
            "capturado_em": NOW,
            "farmalider_status_pedido": "3",
        }
        orders, items = merge_history([current], [], [dict(old)], [], [old])
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0]["farmalider_status_pedido"], "3")
        self.assertEqual(orders[0]["capturado_em"], old["capturado_em"])

    def test_creation_conflict_does_not_cancel_other_reviewed_updates(self):
        from weni_update import (
            REQUIRED_MULTICHANNEL_FIELDS,
            ContactUpdatePlan,
            run_update,
        )

        plan = self.plans()[0]
        other = ContactUpdatePlan(
            contact_uuid="other", fields={"idade": 25}, previous={"idade": None}
        )
        review = Path(self.temp.name) / "review.json"
        write_review_snapshot(
            [plan, other],
            UpdateStats(),
            full=False,
            json_path=review,
            captured_at_utc=NOW,
        )
        changed = deepcopy(self.payload)
        changed["ultimoPedido"]["status"] = 3
        farm = farm_for(changed)
        w = self.weni()
        w.list_fields.return_value = [
            {"key": k} for k in self.fields | REQUIRED_MULTICHANNEL_FIELDS
        ]
        w.list_groups.return_value = []
        w.get_contact.side_effect = lambda **kw: (
            {"uuid": "other", "fields": {}} if kw.get("uuid") == "other" else None
        )
        with (
            patch("weni_update.WeniClient", return_value=w),
            patch("weni_update._open_farmalider", return_value=farm),
            patch("weni_update._load_state", return_value={}),
            patch("weni_update._save_state"),
            patch("weni_update._append_audit"),
        ):
            # run_update encerra o cliente API no finally.
            farm.close = lambda: None
            stats = run_update(apply=True, require_review=review)
        self.assertEqual(stats.contacts_failed, 1)
        self.assertEqual(stats.contacts_updated, 1)
        w.create_contact.assert_not_called()
        w.update_contact_fields.assert_called_once_with("other", {"idade": 25})

    def test_farma_does_not_import_customer_with_only_pet_products(self):
        payload = customer_snapshot()
        payload["itens"][0]["descricao"] = "Ração para cães 2KG"
        self.farm = farm_for(payload)
        self.assertFalse(self.plans())

    def test_cancelled_order_does_not_become_a_sale_in_history(self):
        from analytics import build_bi_summary_record

        payload = customer_snapshot()
        payload["ultimoPedido"]["status"] = 3
        record_directory(CustomerDirectory([payload]), NOW)
        orders, items, _ = history_rows([], [], captured_at=NOW)
        self.assertEqual(orders[0]["status_confirmacao"], "CANCELADO_API")
        summary = build_bi_summary_record(
            [], orders, items, snapshot_date="2026-10-29", updated_at=NOW
        )
        self.assertEqual(summary["pedidos_total"], 0)
