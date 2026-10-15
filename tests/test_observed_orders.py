"""Pedidos observados usam somente respostas fictícias e planilhas em memória."""

import unittest
from copy import deepcopy
from datetime import UTC, datetime
from unittest.mock import Mock

from analytics import (
    ORDER_COLUMNS,
    ORDER_ITEM_COLUMNS,
    SALES_METRIC_COLUMNS,
    _sales_order_is_valid,
    build_sales_metrics,
    normalize_contact,
)
from farmalider_client import (
    FarmaliderAuthError,
    FarmaliderError,
    FarmaliderUnavailableError,
)
from farmalider_integration import apply_pedido_api_confirmation
from google_sheets import GoogleSheetsStore
from main import (
    FarmaliderSettings,
    _completion_controls,
    build_orders,
    validate_contacts,
)
from observed_orders import revalidate_observed_orders
from tests.test_analytics_order_flow import MemoryWorksheet

CAPTURED = "2026-10-15T12:00:00-03:00"


def response(number=499, *, status=0, owner=99, payment=3, product="Produto humano"):
    return {
        "capa": {
            "id": number,
            "codCliente": owner,
            "emissao": "2026-10-14T10:00:00-03:00",
            "status": status,
            "formaPagamento": payment,
            "cancelamento": None,
            "frete": "5",
        },
        "itens": [
            {
                "codPedido": number,
                "codProduto": 7,
                "descricao": product,
                "quantidade": 2,
                "valor": "10",
                "total": "18",
            }
        ],
    }


def observed(number=499, **options):
    order, items = apply_pedido_api_confirmation(
        {
            "pedido_id": str(number),
            "contact_uuid": "u1",
            "cpf_normalizado": "52998224725",
            "cliente": "Cliente fictício",
            "origem_pedido": "FARMALIDER_PEDIDO_API",
            "primeiro_anuncio_id": "anuncio-ficticio",
        },
        [],
        response(number, **options),
        linked_cliente_id="99",
        confirmed_at="2026-10-14T14:00:00Z",
    )
    return (
        {column: order.get(column, "") for column in ORDER_COLUMNS},
        [
            {column: item.get(column, "") for column in ORDER_ITEM_COLUMNS}
            for item in items
        ],
    )


class Worksheet(MemoryWorksheet):
    def batch_clear(self, ranges):
        import re

        for cell_range in ranges:
            index = int(re.match(r"A(\d+):", cell_range)[1]) - 1
            self.values[index] = [""] * len(self.values[0])


def memory_store(orders, items):
    store = GoogleSheetsStore.__new__(GoogleSheetsStore)
    store.orders = Worksheet("Pedidos_FarmaLider", ORDER_COLUMNS)
    store.order_items = Worksheet("Itens_Pedidos_FarmaLider", ORDER_ITEM_COLUMNS)
    store.orders.values.extend(
        [[row.get(h, "") for h in ORDER_COLUMNS] for row in orders]
    )
    store.order_items.values.extend(
        [[row.get(h, "") for h in ORDER_ITEM_COLUMNS] for row in items]
    )
    store._read_with_retry = lambda label, operation: operation()
    store._write_with_retry = lambda label, operation: operation()
    return store


class ObservedOrdersTests(unittest.TestCase):
    def run_refresh(self, orders, farm, **overrides):
        arguments = {
            "scoped_contact_uuids": {"u1"},
            "current_orders": [],
            "current_items": [],
            "farm_client": farm,
            "captured_at": CAPTURED,
        }
        arguments.update(overrides)
        return revalidate_observed_orders(orders, **arguments)

    def test_new_order_with_incomplete_official_items_keeps_checkpoint_partial(self):
        contact = {"uuid": "u1", "fields": {"cpf": "52998224725"}}
        for status in (0, 3):
            with self.subTest(status=status):
                incomplete = response(500, status=status)
                incomplete["itens"] = []
                farm = Mock()
                farm.get_pedido.return_value = incomplete
                orders, items, stats = build_orders(
                    [contact],
                    rows_by_uuid={"u1": normalize_contact(contact, CAPTURED)},
                    farm_client=farm,
                    sync_time=CAPTURED,
                    cliente_responses_by_cpf={
                        "52998224725": {
                            "cliente": {"id": 99, "cpf": "52998224725"},
                            "ultimoPedido": incomplete["capa"],
                            "itens": [],
                        }
                    },
                )
                self.assertEqual(
                    orders[0]["status_confirmacao"], "ERRO_ITENS_PEDIDO_API"
                )
                self.assertEqual(items, [])
                self.assertEqual(stats.api_errors, 1)
                result, controls = _completion_controls(
                    datetime.now(UTC), api_errors=stats.api_errors
                )
                self.assertEqual(result, "parcial")
                self.assertNotIn("ultima_sincronizacao_sucesso_utc", controls)

    def test_normal_identity_and_cpf_blocks_do_not_become_api_failures(self):
        from unittest.mock import patch

        contact = {"uuid": "u1", "fields": {"cpf": "0"}}
        for status in (
            "CPF_IDENTIDADE_DIVERGENTE",
            "CPF_IDENTIDADE_AMBIGUA",
            "CPF_NAO_INFORMADO",
            "CPF_REJEITADO_API",
            "CPF_NAO_ENCONTRADO",
        ):
            with (
                self.subTest(status=status),
                patch(
                    "main.resolve_contact_order",
                    return_value=(
                        {
                            "pedido_chave": "diagnostic",
                            "status_confirmacao": status,
                            "status_validacao": "ERRO",
                        },
                        [],
                    ),
                ),
            ):
                _, _, stats = build_orders(
                    [contact], rows_by_uuid={}, farm_client=Mock(), sync_time=CAPTURED
                )
                self.assertEqual(stats.api_errors, 0)

    def test_old_cancellation_and_new_latest_refresh_without_duplicate_get(self):
        old, old_items = observed()
        farm = Mock()
        farm.get_pedido.side_effect = lambda number: response(
            int(number), status=3 if str(number) == "499" else 0
        )
        contact = {"uuid": "u1", "fields": {"cpf": "52998224725"}}
        customer = {
            "cliente": {"id": 99, "cpf": "52998224725"},
            "ultimoPedido": response(500)["capa"],
            "itens": response(500)["itens"],
        }
        cache = {}
        current, current_items, _ = build_orders(
            [contact],
            rows_by_uuid={"u1": normalize_contact(contact, CAPTURED)},
            farm_client=farm,
            sync_time=CAPTURED,
            cliente_responses_by_cpf={"52998224725": customer},
            pedido_responses_by_id=cache,
        )
        refreshed = self.run_refresh(
            [old],
            farm,
            current_orders=current,
            current_items=current_items,
            pedido_responses_by_id=cache,
        )
        store = memory_store([old], old_items)
        orders, items = store.upsert_pharmacy_orders(refreshed.orders, refreshed.items)
        self.assertCountEqual(
            [call.args[0] for call in farm.get_pedido.call_args_list], ["499", "500"]
        )
        by_id = {row["pedido_id"]: row for row in orders.final_records}
        self.assertEqual(by_id["499"]["status_confirmacao"], "CANCELADO_API")
        self.assertFalse(_sales_order_is_valid(by_id["499"]))
        self.assertTrue(_sales_order_is_valid(by_id["500"]))
        sales = build_sales_metrics(orders.final_records, items.final_records)
        self.assertEqual(
            sum(row[SALES_METRIC_COLUMNS.index("pedidos")] for row in sales), 1
        )

    def test_wrong_owner_preserves_existing_order_and_items_and_checkpoint(self):
        old, old_items = observed()
        before = deepcopy(old)
        farm = Mock()
        farm.get_pedido.return_value = response(owner=999, status=3)
        result = self.run_refresh([old], farm)
        store = memory_store([old], old_items)
        orders, items = store.upsert_pharmacy_orders(result.orders, result.items)
        self.assertEqual(orders.final_records, [before])
        self.assertEqual(items.final_records, old_items)
        self.assertEqual(old, before)
        self.assertEqual(result.api_errors, 1)
        status, controls = _completion_controls(
            datetime.now(UTC), api_errors=result.api_errors
        )
        self.assertEqual(status, "parcial")
        self.assertNotIn("ultima_sincronizacao_sucesso_utc", controls)

    def test_api_errors_404_and_malformed_items_preserve_old_pairs(self):
        malformed = response()
        malformed["itens"] = []
        for error in (FarmaliderError("falha fictícia"), None, malformed):
            with self.subTest(error=type(error).__name__):
                old, old_items = observed()
                farm = Mock()
                if isinstance(error, Exception):
                    farm.get_pedido.side_effect = error
                else:
                    farm.get_pedido.return_value = error
                result = self.run_refresh([old], farm)
                self.assertEqual((result.orders, result.items), ([], []))
                self.assertEqual(result.api_errors, 1)
                store = memory_store([old], old_items)
                orders, items = store.upsert_pharmacy_orders(
                    result.orders, result.items
                )
                self.assertEqual(orders.final_records, [old])
                self.assertEqual(items.final_records, old_items)

    def test_response_cache_and_duplicate_keys_do_not_repeat_get(self):
        old, _ = observed()
        farm = Mock()
        result = self.run_refresh(
            [old, deepcopy(old)],
            farm,
            pedido_responses_by_id={"499": response(status=2)},
        )
        farm.get_pedido.assert_not_called()
        self.assertEqual(result.checked, 1)
        self.assertEqual(len(result.orders), 1)
        self.assertEqual(result.orders[0]["farmalider_status_pedido"], "2")

    def test_verified_incomplete_cancellation_withdraws_sale_preserving_previous_pair(
        self,
    ):
        cases = [response(status=3), response(status=0, payment=0), response(status=0)]
        cases[-1]["capa"]["cancelamento"] = "2026-10-15T10:00:00-03:00"
        for payload in cases:
            payload["itens"] = []
            with self.subTest(
                status=payload["capa"]["status"],
                payment=payload["capa"]["formaPagamento"],
            ):
                old, old_items = observed()
                farm = Mock()
                farm.get_pedido.return_value = payload
                result = self.run_refresh([old], farm, existing_items=old_items)
                self.assertEqual((result.api_errors, result.negative_headers), (1, 1))
                self.assertEqual(result.items, old_items)
                corrected = result.orders[0]
                self.assertEqual(corrected["status_confirmacao"], "CANCELADO_API")
                self.assertEqual(corrected["status_validacao"], "ERRO")
                for field in (
                    "data_hora",
                    "valor_total_compra",
                    "valor_total_faturamento",
                    "farmalider_frete",
                    "primeiro_anuncio_id",
                ):
                    self.assertEqual(corrected[field], old[field])
                store = memory_store([old], old_items)
                orders, items = store.upsert_pharmacy_orders(
                    result.orders, result.items
                )
                self.assertEqual(items.final_records, old_items)
                self.assertEqual(
                    build_sales_metrics(orders.final_records, items.final_records), []
                )
                status, controls = _completion_controls(
                    datetime.now(UTC), api_errors=result.api_errors
                )
                self.assertEqual(status, "parcial")
                self.assertNotIn("ultima_sincronizacao_sucesso_utc", controls)

    def test_incomplete_positive_response_never_restores_cancelled_sale(self):
        old, old_items = observed(status=3, payment=0)
        payload = response(status=2, payment=3)
        payload["itens"] = []
        farm = Mock()
        farm.get_pedido.return_value = payload
        result = self.run_refresh([old], farm, existing_items=old_items)
        self.assertEqual((result.orders, result.items), ([], []))
        self.assertEqual(result.api_errors, 1)
        self.assertEqual(result.negative_headers, 0)

    def test_failed_current_snapshot_cannot_overwrite_preserved_old_pair_or_cancellation(
        self,
    ):
        for status in (0, 3):
            with self.subTest(status=status):
                old, old_items = observed()
                contact = {"uuid": "u1", "fields": {"cpf": "52998224725"}}
                payload = response(status=status)
                payload["itens"] = []
                customer = {
                    "cliente": {"id": 99, "cpf": "52998224725"},
                    "ultimoPedido": payload["capa"],
                    "itens": [],
                }
                farm, cache = Mock(), {}
                farm.get_pedido.return_value = payload
                current, current_items, stats = build_orders(
                    [contact],
                    rows_by_uuid={"u1": normalize_contact(contact, CAPTURED)},
                    farm_client=farm,
                    sync_time=CAPTURED,
                    cliente_responses_by_cpf={"52998224725": customer},
                    pedido_responses_by_id=cache,
                )
                result = self.run_refresh(
                    [old],
                    farm,
                    existing_items=old_items,
                    current_orders=current,
                    current_items=current_items,
                    pedido_responses_by_id=cache,
                )
                store = memory_store([old], old_items)
                orders, items = store.upsert_pharmacy_orders(
                    result.orders, result.items
                )
                self.assertEqual(len(orders.final_records), 1)
                self.assertEqual(orders.final_records[0]["valor_total_compra"], "18.00")
                self.assertEqual(items.final_records, old_items)
                self.assertEqual(
                    _sales_order_is_valid(orders.final_records[0]), status == 0
                )
                self.assertGreater(stats.api_errors + result.api_errors, 0)
                farm.get_pedido.assert_called_once_with("499")

    def test_negative_header_from_wrong_customer_never_changes_old_sale(self):
        old, old_items = observed()
        payload = response(owner=999, status=3)
        payload["itens"] = []
        farm = Mock()
        farm.get_pedido.return_value = payload
        result = self.run_refresh([old], farm, existing_items=old_items)
        self.assertEqual((result.orders, result.items), ([], []))
        self.assertEqual(result.negative_headers, 0)
        self.assertTrue(_sales_order_is_valid(old))

    def test_current_load_attribution_and_items_take_precedence(self):
        old, _ = observed()
        current, current_items = observed(status=2)
        current["contact_uuid"] = "current-contact"
        current["primeiro_anuncio_id"] = "current-ad"
        result = self.run_refresh(
            [old],
            Mock(),
            current_orders=[current],
            current_items=current_items,
            pedido_responses_by_id={"499": response(status=2)},
        )
        self.assertEqual(result.orders, [current])
        self.assertEqual(result.items, current_items)

    def test_quarter_scope_excludes_orders_from_other_contacts(self):
        first, _ = observed()
        second, _ = observed(500)
        second["contact_uuid"] = "outside-quarter"
        farm = Mock()
        farm.get_pedido.return_value = response(status=2)
        result = self.run_refresh([first, second], farm)
        farm.get_pedido.assert_called_once_with("499")
        self.assertEqual([row["pedido_id"] for row in result.orders], ["499"])

    def test_all_documented_states_are_rechecked_and_cancelled_payment_restored(self):
        for state in (-2, -1, 0, 4, 1, 2, 3):
            with self.subTest(state=state):
                old, _ = observed(status=state, payment=0 if state == 3 else 3)
                farm = Mock()
                farm.get_pedido.return_value = response(status=2, payment=5)
                result = self.run_refresh([old], farm)
                farm.get_pedido.assert_called_once_with("499")
                self.assertTrue(_sales_order_is_valid(result.orders[0]))
                self.assertEqual(result.orders[0]["farmalider_forma_pagamento"], "5")
                self.assertEqual(
                    result.orders[0]["status_confirmacao"], "CONFIRMADO_API"
                )

    def test_unverified_legacy_orders_remain_pending_without_api_lookup(self):
        original, _ = observed()
        cases = [
            dict(original, status_confirmacao="NAO_CONFIRMADO"),
            dict(original, farmalider_cliente_id="0"),
            dict(original, pedido_id=""),
            dict(original, cpf_normalizado="0"),
        ]
        for old in cases:
            with self.subTest(old=old.get("status_confirmacao")):
                farm = Mock()
                result = self.run_refresh([old], farm)
                farm.get_pedido.assert_not_called()
                self.assertEqual(result.skipped_unverified, 1)
                self.assertEqual(result.orders, [])

    def test_invalid_cpf_previously_verified_keeps_identity_marker_and_attribution(
        self,
    ):
        old, _ = observed()
        old.update(
            cpf_normalizado="0",
            origem_pedido="FARMALIDER_PEDIDO_API_IDENTIDADE_VALIDADA",
        )
        farm = Mock()
        farm.get_pedido.return_value = response(status=2)
        result = self.run_refresh([old], farm)
        self.assertTrue(_sales_order_is_valid(result.orders[0]))
        for name in (
            "contact_uuid",
            "origem_pedido",
            "primeiro_anuncio_id",
            "cpf_normalizado",
        ):
            self.assertEqual(result.orders[0][name], old[name])

    def test_customer_ownership_is_revalidated_even_for_shared_cached_response(self):
        first, _ = observed()
        second = dict(
            first, pedido_chave="legacy-other-key", farmalider_cliente_id="100"
        )
        farm = Mock()
        result = self.run_refresh(
            [first, second], farm, pedido_responses_by_id={"499": response(status=2)}
        )
        farm.get_pedido.assert_not_called()
        self.assertEqual(result.api_errors, 1)
        self.assertEqual(len(result.orders), 1)
        self.assertEqual(result.orders[0]["farmalider_cliente_id"], "99")

    def test_authentication_and_open_circuit_abort_without_returning_partial_updates(
        self,
    ):
        old, _ = observed()
        for error in (FarmaliderAuthError, FarmaliderUnavailableError):
            with self.subTest(error=error.__name__):
                farm = Mock()
                farm.get_pedido.side_effect = error("falha fictícia")
                with self.assertRaises(error):
                    self.run_refresh([old], farm)
                farm.cancel_pending_requests.assert_called_once()

    def test_pharmacy_filter_recomputes_mixed_order_and_clears_stale_items(self):
        old, old_items = observed()
        old_items.append(
            dict(old_items[0], item_chave="stale-old-item", produto_ordem="3")
        )
        payload = response()
        payload["itens"].append(
            dict(
                payload["itens"][0],
                codProduto=8,
                descricao="Ração para cães",
                total="30",
            )
        )
        farm = Mock()
        farm.get_pedido.return_value = payload
        result = self.run_refresh([old], farm)
        store = memory_store([old], old_items)
        orders, items = store.upsert_pharmacy_orders(result.orders, result.items)
        self.assertEqual(orders.final_records[0]["valor_total_faturamento"], "18.00")
        self.assertEqual(orders.final_records[0]["farmalider_frete"], "0.00")
        self.assertEqual(
            [
                item["produto_nome"]
                for item in items.final_records
                if item["item_chave"]
            ],
            ["Produto humano"],
        )

    def test_rechecked_pet_only_order_is_removed_from_commercial_history(self):
        old, old_items = observed()
        farm = Mock()
        farm.get_pedido.return_value = response(product="Ração para cães")
        result = self.run_refresh([old], farm)
        store = memory_store([old], old_items)
        orders, items = store.upsert_pharmacy_orders(result.orders, result.items)
        self.assertFalse(any(row.get("pedido_chave") for row in orders.final_records))
        self.assertFalse(any(row.get("item_chave") for row in items.final_records))
        self.assertEqual(
            build_sales_metrics(orders.final_records, items.final_records), []
        )

    def test_legacy_join_key_survives_canonical_reconstruction(self):
        old, _ = observed()
        old["pedido_chave"] = "legacy-verified-order"
        farm = Mock()
        farm.get_pedido.return_value = response(status=2)
        result = self.run_refresh([old], farm)
        self.assertEqual(result.orders[0]["pedido_chave"], "legacy-verified-order")
        self.assertEqual(result.items[0]["pedido_chave"], "legacy-verified-order")

    def test_current_canonical_key_reuses_unique_legacy_key_without_duplicate_sale(
        self,
    ):
        old, old_items = observed()
        old["pedido_chave"] = "legacy-verified-order"
        for item in old_items:
            item["pedido_chave"] = old["pedido_chave"]
        current, current_items = observed(status=2)
        result = self.run_refresh(
            [old],
            Mock(),
            existing_items=old_items,
            current_orders=[current],
            current_items=current_items,
            pedido_responses_by_id={"499": response(status=2)},
        )
        store = memory_store([old], old_items)
        orders, items = store.upsert_pharmacy_orders(result.orders, result.items)
        self.assertEqual(
            [row["pedido_chave"] for row in orders.final_records],
            ["legacy-verified-order"],
        )
        self.assertEqual(
            sum(_sales_order_is_valid(row) for row in orders.final_records), 1
        )
        self.assertEqual(
            len([item for item in items.final_records if item["item_chave"]]), 1
        )

    def test_ambiguous_preexisting_official_keys_do_not_promote_duplicate_sale(self):
        old, _ = observed()
        other = dict(old, pedido_chave="legacy-other-key")
        current, items = observed(status=2)
        farm = Mock()
        result = self.run_refresh(
            [old, other], farm, current_orders=[current], current_items=items
        )
        farm.get_pedido.assert_not_called()
        self.assertEqual(result.ambiguous_orders, 1)
        self.assertEqual(result.api_errors, 1)
        self.assertEqual((result.orders, result.items), ([], []))

    def test_legacy_alias_outside_quarter_prevents_duplicate_for_shared_order(self):
        old, old_items = observed()
        old.update(
            pedido_chave="legacy-outside-quarter", contact_uuid="outside-quarter"
        )
        for item in old_items:
            item["pedido_chave"] = old["pedido_chave"]
        current, current_items = observed(status=2)
        farm = Mock()
        result = self.run_refresh(
            [old],
            farm,
            existing_items=old_items,
            current_orders=[current],
            current_items=current_items,
        )
        farm.get_pedido.assert_not_called()
        self.assertEqual(result.checked, 0)
        store = memory_store([old], old_items)
        orders, items = store.upsert_pharmacy_orders(result.orders, result.items)
        self.assertEqual(
            [row["pedido_chave"] for row in orders.final_records],
            ["legacy-outside-quarter"],
        )
        self.assertEqual(
            sum(_sales_order_is_valid(row) for row in orders.final_records), 1
        )
        self.assertEqual(
            len([item for item in items.final_records if item["item_chave"]]), 1
        )

    def test_cached_negative_current_header_updates_related_legacy_outside_quarter_without_get(
        self,
    ):
        old, old_items = observed()
        old.update(
            pedido_chave="legacy-outside-quarter", contact_uuid="outside-quarter"
        )
        for item in old_items:
            item["pedido_chave"] = old["pedido_chave"]
        payload = response(status=3)
        payload["itens"] = []
        current, current_items = apply_pedido_api_confirmation(
            {
                "pedido_id": "499",
                "pedido_chave": "failed-current",
                "contact_uuid": "u1",
                "farmalider_cliente_id": "99",
            },
            [],
            payload,
            linked_cliente_id="99",
            confirmed_at=CAPTURED,
        )
        farm = Mock()
        result = self.run_refresh(
            [old],
            farm,
            existing_items=old_items,
            current_orders=[current],
            current_items=current_items,
            pedido_responses_by_id={"499": payload},
        )
        farm.get_pedido.assert_not_called()
        store = memory_store([old], old_items)
        orders, items = store.upsert_pharmacy_orders(result.orders, result.items)
        self.assertEqual(len(orders.final_records), 1)
        self.assertFalse(_sales_order_is_valid(orders.final_records[0]))
        self.assertEqual(orders.final_records[0]["valor_total_compra"], "18.00")
        self.assertEqual(items.final_records, old_items)
        self.assertEqual((result.api_errors, result.negative_headers), (1, 1))

    def test_recheck_window_includes_day_twenty_and_excludes_day_twenty_one(self):
        for emitted, expected_queries in (
            ("2026-09-25T23:59:00-03:00", 1),
            ("2026-09-24T23:59:00-03:00", 0),
        ):
            with self.subTest(emitted=emitted):
                old, _ = observed()
                old["data_hora"] = emitted
                farm = Mock()
                farm.get_pedido.return_value = response(status=3)
                result = self.run_refresh([old], farm)
                self.assertEqual(farm.get_pedido.call_count, expected_queries)
                self.assertEqual(result.api_errors, 0)
                self.assertEqual(
                    result.skipped_outside_window, int(not expected_queries)
                )
                if expected_queries:
                    self.assertFalse(_sales_order_is_valid(result.orders[0]))

    def test_recheck_window_uses_belem_calendar_dates_at_utc_midnight(self):
        old, _ = observed()
        old["data_hora"] = "2026-09-24T23:00:00Z"
        farm = Mock()
        farm.get_pedido.return_value = response(status=3)
        result = self.run_refresh([old], farm, captured_at="2026-10-15T01:00:00Z")
        farm.get_pedido.assert_called_once_with("499")
        self.assertFalse(_sales_order_is_valid(result.orders[0]))

    def test_future_or_invalid_historical_dates_remain_pending_without_get(self):
        for emitted in ("2026-10-16T10:00:00-03:00", "data inválida", ""):
            with self.subTest(emitted=emitted):
                old, _ = observed()
                old["data_hora"] = emitted
                farm = Mock()
                result = self.run_refresh([old], farm)
                farm.get_pedido.assert_not_called()
                self.assertEqual(result.pending_dates, 1)
                self.assertEqual(result.orders, [])

    def test_fresh_cpf_lookup_discovers_new_id_even_when_both_orders_are_old(self):
        old, old_items = observed()
        old["data_hora"] = "2026-09-24T10:00:00-03:00"
        contact = {"uuid": "u1", "fields": {"cpf": "52998224725"}}
        farm = Mock()
        farm.metrics_snapshot.return_value = {
            "total_requests": 1,
            "retries": 0,
            "rate_limits": 0,
            "server_errors": 0,
            "max_response_ms": 1,
            "effective_delay_ms": 0,
        }
        for number in (499, 500):
            payload = response(number)
            payload["capa"]["emissao"] = old["data_hora"]
            customer = {
                "cliente": {"id": 99, "cpf": "52998224725"},
                "ultimoPedido": payload["capa"],
                "itens": payload["itens"],
            }
            farm.get_cliente_by_cpf.return_value = customer
            farm.get_pedido.return_value = payload
            row = normalize_contact(contact, CAPTURED)
            responses = {}
            validate_contacts(
                [row],
                farm_client=farm,
                farm_settings=FarmaliderSettings(True, "synthetic", False),
                sync_time=CAPTURED,
                cliente_responses_by_cpf=responses,
            )
            current, current_items, _ = build_orders(
                [contact],
                rows_by_uuid={"u1": row},
                farm_client=farm,
                sync_time=CAPTURED,
                cliente_responses_by_cpf=responses,
                existing_orders=[old],
            )
            if number == 499:
                self.assertEqual((current, current_items), ([], []))
                farm.get_pedido.assert_not_called()
            else:
                self.assertEqual(current[0]["pedido_id"], "500")
                farm.get_pedido.assert_called_once_with("500")
        self.assertEqual(farm.get_cliente_by_cpf.call_count, 2)

    def test_incomplete_cancellation_on_twentieth_day_withdraws_sale(self):
        old, old_items = observed()
        old["data_hora"] = "2026-09-25T10:00:00-03:00"
        payload = response(status=3)
        payload["itens"] = []
        farm = Mock()
        farm.get_pedido.return_value = payload
        result = self.run_refresh([old], farm, existing_items=old_items)
        self.assertEqual(result.negative_headers, 1)
        self.assertFalse(_sales_order_is_valid(result.orders[0]))

    def test_shared_order_alternate_weni_contact_does_not_requery_outside_twenty_days(
        self,
    ):
        old, _ = observed()
        old.update(
            contact_uuid="other-weni-contact", data_hora="2026-09-24T10:00:00-03:00"
        )
        contact = {
            "uuid": "u1",
            "name": "Nome diferente",
            "fields": {"cpf": "52998224725"},
        }
        payload = response()
        payload["capa"]["emissao"] = old["data_hora"]
        customer = {
            "cliente": {"id": 99, "cpf": "52998224725"},
            "ultimoPedido": payload["capa"],
            "itens": payload["itens"],
        }
        farm = Mock()
        current, items, stats = build_orders(
            [contact],
            rows_by_uuid={"u1": normalize_contact(contact, CAPTURED)},
            farm_client=farm,
            sync_time=CAPTURED,
            cliente_responses_by_cpf={"52998224725": customer},
            existing_orders=[old],
        )
        farm.get_pedido.assert_not_called()
        self.assertEqual((current, items, stats.api_errors), ([], [], 0))

    def test_progress_logs_do_not_expose_customer_data(self):
        old, _ = observed()
        old["cliente"] = "cliente-confidencial-ficticio"
        farm = Mock()
        farm.get_pedido.return_value = response(status=2)
        with self.assertLogs(level="INFO") as logs:
            self.run_refresh([old], farm)
        rendered = "\n".join(logs.output)
        self.assertIn("pedidos/s", rendered)
        self.assertIn("restante estimado=", rendered)
        self.assertIn("100%", rendered)
        self.assertNotIn(old["cliente"], rendered)
        self.assertNotIn(old["cpf_normalizado"], rendered)


if __name__ == "__main__":
    unittest.main()
