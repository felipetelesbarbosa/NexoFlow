"""Concurrency, cooldown and early stopping for transient FarmaLíder errors."""

from __future__ import annotations

import logging
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from unittest.mock import Mock, patch

from farmalider_client import (
    FarmaliderClient,
    FarmaliderError,
    FarmaliderUnavailableError,
    RequestPermit,
)
from logging_config import BelemFormatter
from main import FarmaliderSettings, build_orders, validate_contacts


def response(status: int) -> Mock:
    result = Mock(status_code=status, headers={}, content=b"")
    result.json.return_value = {}
    return result


class FarmaliderRecoveryTests(unittest.TestCase):
    def test_server_backoff_respects_retry_after_and_never_removes_rest(self):
        client = FarmaliderClient("synthetic")
        try:
            failure = response(500)
            failure.headers["Retry-After"] = "0"
            self.assertEqual(
                [client._retry_delay(i, failure) for i in (1, 2, 3)], [5, 10, 20]
            )
            failure.headers["Retry-After"] = "60"
            self.assertEqual(client._retry_delay(1, failure), 60)
            failure.headers["Retry-After"] = "inf"
            self.assertEqual(client._retry_delay(1, failure), 5)
        finally:
            client.close()

    def test_recovery_ignores_old_requests_and_returns_gradually_to_normal(self):
        client = FarmaliderClient("synthetic")
        old = RequestPermit(0, 4)
        try:
            client._protect_after_failure(
                endpoint_label="cliente/cpf",
                diagnostic_ref="opaque-one",
                permit=old,
                delay=5,
                status_code=500,
            )
            for _ in range(20):
                client._mark_healthy(old, "cliente/cpf")
            self.assertEqual(client.metrics_snapshot()["concurrency_limit"], 1)
            current = RequestPermit(client._recovery_generation, 1)
            for _ in range(5):
                client._mark_healthy(current, "cliente/cpf")
            self.assertEqual(client.metrics_snapshot()["concurrency_limit"], 1)
            client._mark_healthy(current, "cliente/cpf")
            self.assertEqual(client.metrics_snapshot()["concurrency_limit"], 2)
            for _ in range(11):
                client._mark_healthy(current, "cliente/cpf")
            self.assertEqual(client.metrics_snapshot()["concurrency_limit"], 2)
            client._mark_healthy(current, "cliente/cpf")
            self.assertEqual(client.metrics_snapshot()["concurrency_limit"], 4)
            for _ in range(24):
                client._mark_healthy(current, "cliente/cpf")
            self.assertAlmostEqual(client.metrics_snapshot()["effective_delay_ms"], 10)
            client._protect_after_failure(
                endpoint_label="cliente/cpf",
                diagnostic_ref="opaque-two",
                permit=current,
                delay=5,
                status_code=500,
            )
            self.assertEqual(client.metrics_snapshot()["concurrency_limit"], 1)
        finally:
            client.close()

    def test_429_never_accelerates_a_slowed_client(self):
        client = FarmaliderClient("synthetic")
        try:
            with client._request_gate:
                client._effective_delay_seconds = 1
            client._protect_after_failure(
                endpoint_label="cliente/cpf",
                diagnostic_ref="opaque",
                permit=RequestPermit(0, 1),
                delay=0,
                status_code=429,
            )
            self.assertGreaterEqual(
                client.metrics_snapshot()["effective_delay_ms"], 1000
            )
        finally:
            client.close()

    def test_old_success_breaks_failure_sequence_without_unlocking_workers(self):
        client = FarmaliderClient("synthetic")
        try:
            old = RequestPermit(0, 4)
            client._protect_after_failure(
                endpoint_label="cliente/cpf",
                diagnostic_ref="opaque",
                permit=old,
                delay=0,
                status_code=500,
            )
            client._mark_healthy(old, "cliente/cpf")
            self.assertNotIn("cliente/cpf", client._route_failures)
            self.assertEqual(client.metrics_snapshot()["concurrency_limit"], 1)
        finally:
            client.close()

    def test_cooldown_applies_to_a_different_worker(self):
        client = FarmaliderClient("synthetic")
        try:
            client._protect_after_failure(
                endpoint_label="cliente/cpf",
                diagnostic_ref="opaque",
                permit=RequestPermit(0, 4),
                delay=0.08,
                status_code=500,
            )
            protected_at = time.monotonic()
            with client._request_gate:
                client._effective_delay_seconds = 0
            started = threading.Event()

            def enter():
                with client._request_slot("pedido"):
                    started.set()
                    return time.monotonic()

            with ThreadPoolExecutor(max_workers=1) as executor:
                pending = executor.submit(enter)
                self.assertFalse(started.wait(timeout=0.025))
                self.assertGreaterEqual(pending.result(timeout=2) - protected_at, 0.065)
            self.assertEqual(client._in_flight, 0)
        finally:
            client.close()

    def test_serial_recovery_does_not_overlap_requests(self):
        client = FarmaliderClient("synthetic")
        release = threading.Event()
        first_started = threading.Event()
        lock = threading.Lock()
        active = maximum = calls = 0

        def get(*args, **kwargs):
            nonlocal active, maximum, calls
            with lock:
                active += 1
                maximum = max(maximum, active)
                calls += 1
                first = calls == 1
            if first:
                first_started.set()
                if not release.wait(timeout=2):
                    raise AssertionError("test worker was not released")
            time.sleep(0.005)
            with lock:
                active -= 1
            return response(404)

        try:
            client._protect_after_failure(
                endpoint_label="cliente/cpf",
                diagnostic_ref="opaque",
                permit=RequestPermit(0, 4),
                delay=0,
                status_code=500,
            )
            with client._request_gate:
                client._effective_delay_seconds = 0
            with patch.object(client, "_get_session", return_value=Mock(get=get)):
                with ThreadPoolExecutor(max_workers=3) as executor:
                    futures = [
                        executor.submit(client.get_cliente_by_cpf, f"fixture-{i}")
                        for i in range(3)
                    ]
                    self.assertTrue(first_started.wait(timeout=1))
                    time.sleep(0.02)
                    self.assertEqual(calls, 1)
                    release.set()
                    for future in futures:
                        self.assertIsNone(future.result(timeout=2))
            self.assertEqual(maximum, 1)
            self.assertEqual(client._in_flight, 0)
        finally:
            release.set()
            client.close()

    def test_final_500_protects_the_next_customer(self):
        client = FarmaliderClient("synthetic")
        try:
            with (
                patch.object(client.session, "get", return_value=response(500)),
                patch("farmalider_client.FARMALIDER_MAX_RETRIES", 1),
            ):
                with self.assertRaises(FarmaliderError):
                    client.get_cliente_by_cpf("synthetic-customer")
            metrics = client.metrics_snapshot()
            self.assertEqual(metrics["concurrency_limit"], 1)
            self.assertGreater(metrics["cooldown_remaining_ms"], 4000)
            self.assertEqual(client._in_flight, 0)
        finally:
            client.close()

    def test_invalid_json_releases_the_slot_and_does_not_unlock_recovery(self):
        client = FarmaliderClient("synthetic")
        invalid = response(200)
        invalid.json.side_effect = ValueError("unsafe server content")
        try:
            with patch.object(
                client.session, "get", side_effect=[invalid, response(404)]
            ):
                with self.assertRaises(FarmaliderError):
                    client.get_cliente_by_cpf("synthetic-one")
                self.assertEqual(client._in_flight, 0)
                self.assertIsNone(client.get_cliente_by_cpf("synthetic-two"))
            self.assertEqual(client._in_flight, 0)
        finally:
            client.close()

    def test_systemic_5xx_stops_before_a_hundred_customers(self):
        with (
            patch("farmalider_client.FARMALIDER_REQUEST_DELAY_SECONDS", 0),
            patch("farmalider_client.FARMALIDER_RECOVERY_MAX_DELAY_SECONDS", 0),
            patch("farmalider_client.FARMALIDER_5XX_COOLDOWN_SECONDS", 0),
            patch("main.FARMALIDER_MAX_WORKERS", 1),
            patch("main.is_valid_cpf", return_value=True),
        ):
            client = FarmaliderClient("synthetic")
            get = Mock(return_value=response(500))
            try:
                rows = [
                    {"contact_uuid": f"fixture-{i}", "cpf": f"{i:011d}"}
                    for i in range(100)
                ]
                with patch.object(client, "_get_session", return_value=Mock(get=get)):
                    with self.assertRaises(FarmaliderUnavailableError):
                        validate_contacts(
                            rows,
                            farm_client=client,
                            farm_settings=FarmaliderSettings(True, "synthetic", False),
                            sync_time="2026-10-07T00:00:00+00:00",
                        )
                self.assertEqual(get.call_count, 12)
                self.assertEqual(
                    client.metrics_snapshot()["server_error_unique_queries"], 3
                )
                self.assertEqual(client.metrics_snapshot()["open_circuits"], 1)
                self.assertEqual(client._in_flight, 0)
            finally:
                client.close()

    def test_one_bad_customer_does_not_open_a_service_circuit(self):
        client = FarmaliderClient("synthetic")
        try:
            for _ in range(12):
                client._protect_after_failure(
                    endpoint_label="cliente/cpf",
                    diagnostic_ref="same-query",
                    permit=RequestPermit(client._recovery_generation, 1),
                    delay=0,
                    status_code=500,
                )
            self.assertEqual(client.metrics_snapshot()["open_circuits"], 0)
            client._mark_healthy(
                RequestPermit(client._recovery_generation, 1), "cliente/cpf"
            )
            self.assertNotIn("cliente/cpf", client._route_failures)
        finally:
            client.close()

    def test_order_pipeline_propagates_service_interruption(self):
        client = Mock()
        client.get_cliente_by_cpf.side_effect = FarmaliderUnavailableError(
            "circuit open"
        )
        contact = {"uuid": "fixture", "fields": {"cpf": "52998224725"}}
        with self.assertRaises(FarmaliderUnavailableError):
            build_orders(
                [contact],
                rows_by_uuid={"fixture": {}},
                farm_client=client,
                sync_time="2026-10-07T00:00:00+00:00",
            )

    def test_close_wakes_workers_waiting_for_a_slot(self):
        client = FarmaliderClient("synthetic")
        with client._request_gate:
            client._concurrency_limit = 1
        with ThreadPoolExecutor(max_workers=2) as executor:
            with client._request_slot("cliente/cpf"):
                waiting = executor.submit(client.get_cliente_by_cpf, "synthetic")
                closing = executor.submit(client.close)
                with self.assertRaises(FarmaliderUnavailableError):
                    waiting.result(timeout=2)
            closing.result(timeout=2)
        self.assertEqual(client._in_flight, 0)

    def test_cancel_stops_waiting_workers_without_waiting_for_active_requests(self):
        client = FarmaliderClient("synthetic")
        with client._request_gate:
            client._concurrency_limit = 1
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                with client._request_slot("cliente/cpf"):
                    waiting = executor.submit(client.get_cliente_by_cpf, "synthetic")
                    client.cancel_pending_requests()
                    with self.assertRaises(FarmaliderUnavailableError):
                        waiting.result(timeout=2)
                    self.assertEqual(client._in_flight, 1)
            self.assertEqual(client._in_flight, 0)
        finally:
            client.close()

    def test_diagnostics_accept_only_uuid_trace_headers(self):
        client = FarmaliderClient("synthetic")
        try:
            failure = response(500)
            failure.headers["X-Request-ID"] = "unsafe token or personal data"
            self.assertIn("trace_id=-", client._safe_server_error_summary(failure))
            failure.headers["X-Request-ID"] = "a9b5a7e1-fb2d-4c10-a322-fb05cdfc828a"
            self.assertIn(
                "trace_id=a9b5a7e1-fb2d-4c10-a322-fb05cdfc828a",
                client._safe_server_error_summary(failure),
            )
        finally:
            client.close()

    def test_logs_always_use_belem_utc_minus_three(self):
        record = logging.LogRecord("fixture", logging.INFO, "", 0, "message", (), None)
        record.created = datetime(2026, 10, 7, 4, 0, tzinfo=UTC).timestamp()
        record.msecs = 123
        formatted = BelemFormatter("%(asctime)s | %(message)s").format(record)
        self.assertEqual(formatted, "2026-10-07 01:00:00,123 -03:00 | message")


if __name__ == "__main__":
    unittest.main()
