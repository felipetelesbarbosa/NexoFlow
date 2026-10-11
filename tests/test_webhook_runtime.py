from __future__ import annotations

import copy
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from importlib.util import find_spec
from unittest.mock import MagicMock, patch

import tests  # noqa: F401 - prepara configuração fictícia antes dos imports.
from analytics import build_sales_metrics
from google_sheets import GoogleSheetsStore, UpsertResult
from webhook_runtime import shared_secret_matches

WEBHOOK_DEPENDENCIES_AVAILABLE = (
    find_spec("fastapi") is not None and find_spec("pydantic") is not None
)
if WEBHOOK_DEPENDENCIES_AVAILABLE:
    from fastapi import HTTPException

    import webhook_eventos
    import webhook_pedidos


def _upsert_result(
    records: list[dict[str, str]], *, inserted: int = 0, updated: int = 0
) -> UpsertResult:
    return UpsertResult(
        inserted=inserted,
        updated=updated,
        unchanged=0 if inserted or updated else 1,
        changed_records=records if inserted or updated else [],
        final_records=copy.deepcopy(records),
    )


@unittest.skipUnless(
    WEBHOOK_DEPENDENCIES_AVAILABLE,
    "Dependências opcionais ausentes; instale requirements-webhook.txt.",
)
class WebhookRuntimeTests(unittest.TestCase):
    secret = "segredo-fictício-UTF-8"

    def setUp(self) -> None:
        self.addCleanup(patch.stopall)
        patch.object(
            webhook_pedidos.secrets, "WEBHOOK_PEDIDOS_ENABLED", True, create=True
        ).start()
        patch.object(
            webhook_pedidos.secrets, "WEBHOOK_SHARED_SECRET", self.secret, create=True
        ).start()
        patch.object(webhook_eventos, "WEBHOOK_SHARED_SECRET", self.secret).start()
        self.store = MagicMock(spec=GoogleSheetsStore)
        self.orders = [
            {
                "pedido_chave": "pedido-ficticio",
                "contact_uuid": "contato-ficticio",
                "data": "2026-10-10",
                "valor_total_compra": "10.00",
                "valor_produtos": "10.00",
                "valor_frete": "0.00",
                "status_validacao": "OK",
                "status_confirmacao": "CONFIRMADO_API",
                "farmalider_status_pedido": "2",
                "farmalider_forma_pagamento": "1",
            }
        ]
        self.items = [
            {
                "pedido_chave": "pedido-ficticio",
                "item_chave": "item-ficticio",
                "data": "2026-10-10",
                "quantidade": "1",
            }
        ]
        self.store.upsert_orders_detailed.return_value = _upsert_result(self.orders)
        self.store.upsert_order_items_detailed.return_value = _upsert_result(self.items)
        self.order_factory = patch.object(
            webhook_pedidos, "GoogleSheetsStore", return_value=self.store
        ).start()
        self.event_factory = patch.object(
            webhook_eventos, "GoogleSheetsStore", return_value=self.store
        ).start()

    @staticmethod
    def order() -> webhook_pedidos.PedidoWebhook:
        return webhook_pedidos.PedidoWebhook(
            contact_uuid="contato-ficticio",
            ultimo_pedido={
                "data_hora": "2026-10-10T18:00:00Z",
                "valor_total_compra": 10,
                "produtos": [
                    {
                        "nome": "Produto fictício",
                        "quantidade": 1,
                        "valor_unitario": 10,
                        "valor_total": 10,
                    }
                ],
            },
        )

    @staticmethod
    def event() -> webhook_eventos.WeniAdEvent:
        return webhook_eventos.WeniAdEvent(
            contact_uuid="contato-ficticio",
            source_type="ad",
            source_id="anuncio-ficticio",
            ctwa_clid="clique-ficticio",
        )

    def test_secret_comparison_accepts_utf8_and_rejects_empty_missing_or_wrong(self):
        self.assertTrue(shared_secret_matches(self.secret, self.secret))
        for expected, supplied in (
            ("", ""),
            ("", self.secret),
            (self.secret, None),
            (self.secret, ""),
            (self.secret, "incorreto"),
        ):
            with self.subTest(expected=expected, supplied=supplied):
                self.assertFalse(shared_secret_matches(expected, supplied))

    def test_unauthorized_requests_never_construct_store(self):
        for supplied in (None, "incorreto"):
            for handler, body in (
                (webhook_pedidos.receive_order, self.order()),
                (webhook_eventos.receive_event, self.event()),
            ):
                with self.subTest(handler=handler.__name__, supplied=supplied):
                    with self.assertRaises(HTTPException) as caught:
                        handler(body, supplied)
                    self.assertEqual(caught.exception.status_code, 401)
        self.order_factory.assert_not_called()
        self.event_factory.assert_not_called()

    def test_disabled_or_unconfigured_orders_never_construct_store(self):
        with patch.object(webhook_pedidos.secrets, "WEBHOOK_PEDIDOS_ENABLED", False):
            with self.assertRaises(HTTPException) as caught:
                webhook_pedidos.receive_order(self.order(), self.secret)
            self.assertEqual(caught.exception.status_code, 503)
        with patch.object(webhook_pedidos.secrets, "WEBHOOK_SHARED_SECRET", ""):
            with self.assertRaises(HTTPException) as caught:
                webhook_pedidos.receive_order(self.order(), self.secret)
            self.assertEqual(caught.exception.status_code, 503)
        with patch.object(webhook_eventos, "WEBHOOK_SHARED_SECRET", ""):
            with self.assertRaises(HTTPException) as caught:
                webhook_eventos.receive_event(self.event(), "")
            self.assertEqual(caught.exception.status_code, 401)
        self.order_factory.assert_not_called()
        self.event_factory.assert_not_called()

    def test_orders_reuse_final_snapshots_without_redundant_reads(self):
        self.store.upsert_orders_detailed.return_value = _upsert_result(
            self.orders, inserted=1
        )
        self.store.upsert_order_items_detailed.return_value = _upsert_result(
            self.items, updated=1
        )
        response = webhook_pedidos.receive_order(self.order(), self.secret)
        self.assertEqual(response["orders_inserted"], 1)
        self.assertEqual(response["items_updated"], 1)
        self.store.replace_sales_metrics.assert_called_once_with(
            build_sales_metrics(self.orders, self.items)
        )
        self.store.load_order_records.assert_not_called()
        self.store.load_order_item_records.assert_not_called()

    def test_duplicate_order_still_checks_and_repairs_metrics(self):
        webhook_pedidos.receive_order(self.order(), self.secret)
        webhook_pedidos.receive_order(self.order(), self.secret)
        self.assertEqual(self.store.upsert_orders_detailed.call_count, 2)
        self.assertEqual(self.store.upsert_order_items_detailed.call_count, 2)
        self.assertEqual(self.store.replace_sales_metrics.call_count, 2)
        self.assertEqual(
            self.store.replace_sales_metrics.call_args_list[0],
            self.store.replace_sales_metrics.call_args_list[1],
        )

    def test_external_snapshot_change_recalculates_metrics(self):
        changed = copy.deepcopy(self.orders)
        changed[0]["valor_total_compra"] = "20.00"
        changed[0]["valor_produtos"] = "20.00"
        self.store.upsert_orders_detailed.side_effect = [
            _upsert_result(self.orders),
            _upsert_result(changed),
        ]
        with patch.object(
            webhook_pedidos, "build_sales_metrics", wraps=build_sales_metrics
        ) as calculate:
            webhook_pedidos.receive_order(self.order(), self.secret)
            webhook_pedidos.receive_order(self.order(), self.secret)
        self.assertEqual(calculate.call_count, 2)
        self.assertEqual(
            self.store.replace_sales_metrics.call_args.args[0],
            build_sales_metrics(changed, self.items),
        )

    def test_replay_repairs_failed_metrics_write(self):
        self.store.replace_sales_metrics.side_effect = [
            RuntimeError("falha fictícia de gravação"),
            None,
        ]
        with patch.object(
            webhook_pedidos, "build_sales_metrics", wraps=build_sales_metrics
        ) as calculate:
            with self.assertRaisesRegex(RuntimeError, "falha fictícia"):
                webhook_pedidos.receive_order(self.order(), self.secret)
            response = webhook_pedidos.receive_order(self.order(), self.secret)
        self.assertEqual(response["status"], "ok")
        self.assertEqual(calculate.call_count, 2)
        self.assertEqual(self.store.replace_sales_metrics.call_count, 2)

    def test_event_schema_mismatch_fails_before_store_even_without_assert(self):
        with patch.object(webhook_eventos, "EVENT_COLUMNS", ["incompatível"]):
            with self.assertRaises(HTTPException) as caught:
                webhook_eventos.receive_event(self.event(), self.secret)
        self.assertEqual(caught.exception.status_code, 500)
        self.event_factory.assert_not_called()

    def test_concurrent_duplicate_events_append_only_once_in_process(self):
        event_ids = set()
        start = threading.Barrier(2)

        def existing():
            snapshot = event_ids.copy()
            time.sleep(0.01)
            return snapshot

        def append(row):
            event_ids.add(row[0])

        def receive():
            start.wait(timeout=5)
            return webhook_eventos.receive_event(self.event(), self.secret)

        self.store.existing_event_ids.side_effect = existing
        self.store.append_event.side_effect = append
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(receive) for _ in range(2)]
            responses = [future.result(timeout=5) for future in futures]
        self.assertEqual(
            sorted(response["status"] for response in responses),
            ["created", "duplicate"],
        )
        self.store.append_event.assert_called_once()

    def test_external_event_is_detected_without_process_cache(self):
        self.store.existing_event_ids.return_value = {"clique-ficticio"}
        response = webhook_eventos.receive_event(self.event(), self.secret)
        self.assertEqual(response["status"], "duplicate")
        self.store.append_event.assert_not_called()

    def test_event_failed_write_propagates_and_replay_attempts_again(self):
        self.store.existing_event_ids.return_value = set()
        self.store.append_event.side_effect = [RuntimeError("falha fictícia"), None]
        with self.assertRaisesRegex(RuntimeError, "falha fictícia"):
            webhook_eventos.receive_event(self.event(), self.secret)
        response = webhook_eventos.receive_event(self.event(), self.secret)
        self.assertEqual(response["status"], "created")
        self.assertEqual(self.store.append_event.call_count, 2)


if __name__ == "__main__":
    unittest.main()
