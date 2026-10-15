"""Itens pendentes: a carga avança, a venda não, e a reconsulta recupera o pedido."""

import unittest
from copy import deepcopy
from datetime import datetime
from unittest.mock import Mock

from analytics import _sales_order_is_valid, build_bi_order_rows, normalize_contact
from farmalider_client import FarmaliderError
from looker_bi import SCHEMAS, build_looker_tables
from main import _completion_controls, build_orders
from observed_orders import revalidate_observed_orders
from pedido_utils import PENDING_ITEMS_STATUS
from recompra import propose
from tests.test_observed_orders import CAPTURED, memory_store, observed, response
from tests.test_recompra import NOW, STRUCTURE, fixture


class PendingOrderItemsTests(unittest.TestCase):
    contact = {"uuid": "u1", "fields": {"cpf": "52998224725"}}

    def build(self, *, payload=None, failure=None):
        payload = deepcopy(payload or response())
        customer = {
            "cliente": {"id": 99, "cpf": "52998224725"},
            "ultimoPedido": payload["capa"],
            "itens": payload.get("itens"),
        }
        farm = Mock()
        if failure:
            farm.get_pedido.side_effect = failure
        else:
            farm.get_pedido.return_value = payload
        return build_orders(
            [self.contact],
            rows_by_uuid={"u1": normalize_contact(self.contact, CAPTURED)},
            farm_client=farm,
            sync_time=CAPTURED,
            cliente_responses_by_cpf={"52998224725": customer},
        )

    def pending(self):
        payload = response()
        payload["itens"] = []
        orders, items, stats = self.build(payload=payload)
        return orders[0], items, stats

    def refresh(self, old, payload, **options):
        farm = Mock()
        farm.get_pedido.return_value = payload
        result = revalidate_observed_orders(
            [old],
            scoped_contact_uuids={"u1"},
            current_orders=[],
            current_items=[],
            farm_client=farm,
            captured_at=CAPTURED,
            **options,
        )
        return result, farm

    def test_pending_header_is_persisted_without_items_or_made_up_amounts(self):
        pending, items, stats = self.pending()
        store = memory_store([], [])
        written, _ = store.upsert_pharmacy_orders([pending], items)
        persisted = written.final_records[0]
        self.assertEqual(persisted["status_confirmacao"], PENDING_ITEMS_STATUS)
        self.assertEqual(persisted["pedido_chave"], "FARMALIDER:499")
        self.assertEqual(persisted["data_hora"], "2026-10-14T10:00:00-03:00")
        self.assertEqual(persisted["farmalider_cliente_id"], "99")
        self.assertEqual(persisted["valor_total_compra"], "")
        self.assertEqual(items, [])
        self.assertEqual((stats.api_errors, stats.pending_without_items), (0, 1))
        self.assertEqual(
            _completion_controls(datetime.fromisoformat(CAPTURED), api_errors=0)[0],
            "sucesso",
        )
        self.assertFalse(_sales_order_is_valid(persisted))

    def test_persisted_pending_order_can_be_recovered_even_after_a_new_latest_order(
        self,
    ):
        pending, _, _ = self.pending()
        store = memory_store([], [])
        written, _ = store.upsert_pharmacy_orders([pending], [])
        persisted = written.final_records[0]
        self.assertNotIn("_farmalider_itens_pendentes", persisted)
        # No current snapshot is needed: stored identity/date supplies the queue.
        refreshed, farm = self.refresh(persisted, response(status=2))
        farm.get_pedido.assert_called_once_with("499")
        self.assertEqual(refreshed.api_errors, 0)
        updated, items = store.upsert_pharmacy_orders(refreshed.orders, refreshed.items)
        self.assertEqual((updated.inserted, updated.updated), (0, 1))
        self.assertEqual(
            updated.final_records[0]["status_confirmacao"], "CONFIRMADO_API"
        )
        self.assertTrue(_sales_order_is_valid(updated.final_records[0]))
        self.assertEqual(len(items.final_records), 1)

    def test_repeat_empty_response_keeps_one_pending_record_and_does_not_block(self):
        pending, _, _ = self.pending()
        payload = response()
        payload["itens"] = []
        refreshed, _ = self.refresh(pending, payload)
        self.assertEqual(
            (refreshed.api_errors, refreshed.pending_without_items), (0, 1)
        )
        self.assertEqual(
            refreshed.orders[0]["status_confirmacao"], PENDING_ITEMS_STATUS
        )
        self.assertFalse(_sales_order_is_valid(refreshed.orders[0]))

    def test_requeries_only_through_day_twenty_including_completed_pending_orders(self):
        for day, calls in (("2026-09-25", 1), ("2026-09-24", 0)):
            with self.subTest(day=day):
                pending, _, _ = self.pending()
                pending["data_hora"] = day + "T10:00:00-03:00"
                result, farm = self.refresh(pending, response(status=2))
                self.assertEqual(farm.get_pedido.call_count, calls)
                self.assertEqual(result.skipped_outside_window, 1 - calls)

    def test_http_failures_malformed_items_and_unknown_states_still_block(self):
        for change, error in (
            ([], FarmaliderError("falha sintética")),
            ({}, None),
            ([{"quantidade": 0}], None),
        ):
            with self.subTest(change=change, error=type(error).__name__):
                payload = response()
                payload["itens"] = change
                _, _, stats = self.build(payload=payload, failure=error)
                self.assertEqual(stats.api_errors, 1)
                self.assertEqual(stats.pending_without_items, 0)
        payload = response(status=99)
        payload["itens"] = []
        self.assertEqual(self.build(payload=payload)[2].api_errors, 1)

    def test_wrong_owner_never_becomes_a_pending_authorized_order(self):
        pending, _, _ = self.pending()
        payload = response(owner=999)
        payload["itens"] = []
        result, _ = self.refresh(pending, payload)
        self.assertEqual(result.api_errors, 1)
        self.assertEqual(result.orders, [])

    def test_pending_history_preserves_old_amounts_but_is_excluded_from_all_bi_sales(
        self,
    ):
        old, old_items = observed()
        payload = response()
        payload["itens"] = []
        result, _ = self.refresh(old, payload, existing_items=old_items)
        pending = result.orders[0]
        self.assertEqual(pending["valor_total_compra"], old["valor_total_compra"])
        self.assertEqual(result.items, old_items)
        base = [normalize_contact(self.contact, CAPTURED)]
        self.assertEqual(
            build_bi_order_rows(base, result.orders, result.items, updated_at=CAPTURED),
            [],
        )
        tables = build_looker_tables(
            base,
            result.orders,
            result.items,
            snapshot_date="2026-10-15",
            updated_at=CAPTURED,
        )
        self.assertEqual(tables["BI_Itens"], [])
        self.assertEqual(tables["BI_Clientes_Vendas"], [])
        self.assertEqual(
            tables["BI_Publico"][0][
                SCHEMAS["BI_Publico"].index("compra_pendente_validacao")
            ],
            1,
        )

    def test_pending_order_cannot_schedule_recompra_even_with_old_items(self):
        contact, old, items = fixture(grouped=True)
        pending, _, _ = self.pending()
        pending["data_hora"] = old["data_hora"]
        plan = propose(contact, pending, items, STRUCTURE, now=NOW)
        self.assertNotEqual(plan["action"], "add")
        self.assertEqual(plan["action"], "remove")
