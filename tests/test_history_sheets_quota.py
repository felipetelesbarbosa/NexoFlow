"""Cotas Google simuladas; relógio virtual, HTTP/gspread reais, sem credenciais."""

import hashlib
import io
import json
import sqlite3
import tempfile
import threading
import unittest
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, redirect_stdout
from datetime import UTC, datetime
from email.utils import format_datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import unquote, urlsplit

import gspread
import requests
from google.auth.credentials import AnonymousCredentials
from requests.adapters import BaseAdapter

from history_sheets_quota import (
    QuotaAdapter,
    QuotaGate,
    google_store_type,
    request_kind,
)
from order_history import HistoryError
from order_history_sheets import SCHEMAS


class Clock:
    def __init__(self):
        self.value = 1000.0
        self.lock = threading.Lock()

    def now(self):
        with self.lock:
            return self.value

    def sleep(self, seconds):
        with self.lock:
            self.value += seconds


class Google(BaseAdapter):
    def __init__(self, clock):
        super().__init__()
        self.clock = clock
        self.recent = deque()
        self.calls = []
        self.errors = 0
        self.status = 200
        self.headers = {}
        self.failure = None
        self.closed = 0
        self.statuses = deque()

    def send(self, request, **kwargs):
        now = self.clock.now()
        self.calls.append((now, request, kwargs))
        if self.failure:
            raise self.failure
        while self.recent and now - self.recent[0] >= 60:
            self.recent.popleft()
        self.recent.append(now)
        status = self.statuses.popleft() if self.statuses else self.status
        if len(self.recent) > 60:
            status = 429
        self.errors += status == 429
        result = requests.Response()
        result.status_code = status
        result.request = request
        result.headers.update(self.headers)
        result._content = json.dumps(
            {"ok": True}
            if status == 200
            else {"error": {"code": status, "message": "private response payload"}}
        ).encode()
        return result

    def close(self):
        self.closed += 1


class BootstrapGoogle(Google):
    """Protocolo de abertura nativa via Spreadsheet/Worksheet reais."""

    def send(self, request, **kwargs):
        from sheets_continuation import ContinuationIndex
        from sheets_storage import STORAGE_SHEET, SheetsStorage

        response = super().send(request, **kwargs)
        if response.status_code != 200:
            return response
        path = unquote(urlsplit(request.url).path)
        book = path.split("/")[3]
        roots = dict(dashboard="dashboard", operacao="operations", historico="history")
        index = ContinuationIndex("dashboard", "FARMA", roots)
        if "/values/" in path:
            title = path.split("/values/")[1].split("!")[0].strip("'")
            values = (
                SheetsStorage("dashboard", "operations", "history").values()
                if title == STORAGE_SHEET
                else index.values()
            )
            data = dict(range=title, majorDimension="ROWS", values=values)
        else:
            sheets = []
            if book == "dashboard":
                for n, title in enumerate((STORAGE_SHEET, "NexoFlow_Continuidade"), 1):
                    sheets.append(
                        dict(
                            properties=dict(
                                sheetId=n,
                                title=title,
                                gridProperties=dict(rowCount=100, columnCount=3),
                            )
                        )
                    )
            data = dict(spreadsheetId=book, properties=dict(title=book), sheets=sheets)
        response._content = json.dumps(data).encode()
        return response


class LeaseGoogle(Google):
    def __init__(self, clock):
        super().__init__(clock)
        self.metadata = []

    def send(self, request, **kwargs):
        response = super().send(request, **kwargs)
        if request.method == "POST":
            for change in json.loads(request.body)["requests"]:
                if "createDeveloperMetadata" in change:
                    self.metadata.append(
                        change["createDeveloperMetadata"]["developerMetadata"]
                    )
                elif "deleteDeveloperMetadata" in change:
                    lookup = change["deleteDeveloperMetadata"]["dataFilter"][
                        "developerMetadataLookup"
                    ]
                    self.metadata = [
                        m
                        for m in self.metadata
                        if not all(m.get(k) == v for k, v in lookup.items())
                    ]
        response._content = json.dumps(
            dict(
                spreadsheetId="synthetic",
                properties=dict(title="synthetic"),
                developerMetadata=self.metadata,
            )
        ).encode()
        return response


class QuotaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "quota.sqlite"
        self.clock = Clock()

    def gate(self, **kwargs):
        return QuotaGate(
            self.path,
            user=kwargs.pop("user", "synthetic@example.invalid"),
            project=kwargs.pop("project", "synthetic-project"),
            now=self.clock.now,
            sleep=self.clock.sleep,
            **kwargs,
        )

    def session(self, *, paced=True):
        session = requests.Session()
        session.trust_env = False
        server = Google(self.clock)
        session.mount("https://", server)
        if paced:
            session.mount(
                "https://sheets.googleapis.com/", QuotaAdapter(server, self.gate())
            )
        self.addCleanup(session.close)
        return session, server

    def test_legacy_burst_reproduces_429_and_pacing_prevents_it(self):
        old, old_server = self.session(paced=False)
        for _ in range(70):
            old.get("https://sheets.googleapis.com/v4/spreadsheets/synthetic")
        self.assertEqual(old_server.errors, 10)
        session, server = self.session()
        with redirect_stdout(io.StringIO()):
            for _ in range(250):
                self.assertEqual(
                    session.get(
                        "https://sheets.googleapis.com/v4/spreadsheets/synthetic"
                    ).status_code,
                    200,
                )
        self.assertEqual(server.errors, 0)
        for i, (now, _, _) in enumerate(server.calls):
            self.assertLessEqual(
                sum(0 <= now - x[0] < 60 for x in server.calls[: i + 1]), 45
            )
        self.assertGreater(self.clock.now(), 1300)

    def test_two_gate_objects_share_budget_and_restart_preserves_cooldown(self):
        first, second = self.gate(), self.gate()
        self.assertEqual(first.acquire("read"), 1000)
        self.assertGreaterEqual(second.acquire("read"), 1000 + 60 / 45)
        first.cooldown("read", 80)
        before = self.clock.now()
        restarted = self.gate()
        with redirect_stdout(io.StringIO()):
            restarted.acquire("read")
        self.assertGreaterEqual(self.clock.now(), before + 80)
        with closing(sqlite3.connect(self.path)) as db:
            rows = db.execute("SELECT scope,kind FROM quota").fetchall()
        self.assertEqual(len(rows), 2)
        self.assertTrue(
            all(len(key) == 64 and "synthetic" not in key for key, _ in rows)
        )

    def test_read_write_budgets_independent_and_project_shared_across_users(self):
        first = self.gate()
        self.assertEqual(first.acquire("read"), 1000)
        self.assertEqual(first.acquire("write"), 1000)
        second = self.gate(user="other@example.invalid")
        self.assertEqual(second.acquire("read"), 1000.251)
        third = self.gate(user="other@example.invalid", project="other-project")
        self.assertEqual(third.acquire("read"), 1000.251)

    def test_concurrent_reservations_are_atomic_without_sleep_under_sqlite_lock(self):
        gates = [self.gate() for _ in range(4)]
        with redirect_stdout(io.StringIO()), ThreadPoolExecutor(max_workers=4) as pool:
            reserved = list(pool.map(lambda n: gates[n % 4].acquire("read"), range(32)))
        reserved.sort()
        self.assertEqual(len(set(reserved)), 32)
        self.assertTrue(
            all(
                b - a >= 60 / 45 - 1e-8
                for a, b in zip(reserved, reserved[1:], strict=False)
            )
        )
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone(), ("ok",))

    def test_429_updates_shared_cooldown_without_repeating_post(self):
        session, server = self.session()
        server.status = 429
        server.headers["Retry-After"] = "90"
        with self.assertLogs(level="WARNING") as logs:
            response = session.post(
                "https://sheets.googleapis.com/v4/spreadsheets/synthetic:batchUpdate",
                json={"requests": [{"private": "synthetic-customer"}]},
            )
        self.assertEqual(response.status_code, 429)
        self.assertEqual(len(server.calls), 1)
        self.assertNotIn("synthetic-customer", " ".join(logs.output))
        self.assertNotIn("private response", " ".join(logs.output))
        server.status = 200
        with redirect_stdout(io.StringIO()):
            self.gate().acquire("write")
        self.assertGreaterEqual(self.clock.now(), 1090)

    def test_http_date_retry_after_and_clock_validation(self):
        session, server = self.session()
        server.status = 429
        server.headers["Retry-After"] = format_datetime(
            datetime.fromtimestamp(1120, UTC), usegmt=True
        )
        with self.assertLogs(level="WARNING"):
            session.get("https://sheets.googleapis.com/v4/spreadsheets/synthetic")
        with redirect_stdout(io.StringIO()):
            self.gate().acquire("read")
        self.assertGreaterEqual(self.clock.now(), 1120)
        self.clock.value -= 10
        with self.assertRaisesRegex(HistoryError, "RELOGIO"):
            self.gate().acquire("read")

    def test_long_retry_after_stops_without_discarding_deadline(self):
        gate = self.gate()
        gate.cooldown("read", 600)
        with self.assertRaisesRegex(HistoryError, "PAUSA_LONGA"):
            gate.acquire("read")
        self.assertEqual(self.clock.now(), 1000)
        self.clock.value = 1600
        gate.acquire("read")

    def test_delegate_receives_exact_request_proxy_tls_and_timeout(self):
        server = Google(self.clock)
        adapter = QuotaAdapter(server, self.gate())
        request = requests.Request(
            "POST",
            "https://sheets.googleapis.com/v4/spreadsheets/synthetic:batchUpdate?token=synthetic",
            json={"requests": [{"preserved": "body"}]},
            headers={"Authorization": "Bearer synthetic"},
        ).prepare()
        options = dict(
            timeout=(10, 120),
            verify="trusted-ca.pem",
            cert="client.pem",
            proxies={"https": "http://synthetic.invalid:8020"},
            stream=True,
        )
        adapter.send(request, **options)
        self.assertIs(server.calls[0][1], request)
        self.assertEqual(server.calls[0][2], options)
        server.failure = requests.Timeout("synthetic uncertain write")
        with self.assertRaises(requests.Timeout):
            adapter.send(request, **options)
        self.assertEqual(len(server.calls), 2)
        adapter.close()
        self.assertEqual(server.closed, 0)

    def test_request_classification_includes_post_read_endpoints(self):
        for method, path, expected in (
            ("GET", "/v4/spreadsheets/id", "read"),
            ("HEAD", "/v4/spreadsheets/id", "read"),
            ("POST", "/v4/spreadsheets/id:getByDataFilter", "read"),
            ("POST", "/v4/spreadsheets/id/values:batchGetByDataFilter", "read"),
            ("POST", "/v4/spreadsheets/id/developerMetadata:search", "read"),
            ("POST", "/v4/spreadsheets/id:batchUpdate", "write"),
            ("PUT", "/v4/spreadsheets/id/values/A1", "write"),
            ("DELETE", "/v4/spreadsheets/id", "write"),
        ):
            with self.subTest(path=path):
                self.assertEqual(
                    request_kind(
                        requests.Request(
                            method, "https://sheets.googleapis.com" + path
                        ).prepare()
                    ),
                    expected,
                )

    def test_foreign_database_and_invalid_configuration_are_preserved(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("CREATE TABLE fact(value TEXT)")
            db.commit()
        before = self.path.read_bytes()
        with self.assertRaisesRegex(HistoryError, "ESTADO_INVALIDO"):
            self.gate()
        self.assertEqual(self.path.read_bytes(), before)
        for value in (0, 51, True, float("nan")):
            with self.assertRaises(HistoryError):
                self.gate(read_rpm=value)

    def test_factory_installs_before_first_gspread_read_and_preserves_schema_guard(
        self,
    ):
        session, server = self.session(paced=False)
        client = gspread.Client(auth=AnonymousCredentials(), session=session)
        client.http_client.auth = SimpleNamespace(
            service_account_email="synthetic@example.invalid",
            project_id="synthetic-project",
        )
        Store = google_store_type()
        store = Store.__new__(Store)
        store.client = client
        real_gate = QuotaGate

        def gate(path, **kwargs):
            self.assertEqual(
                path, Path(self.tmp.name) / "logs" / "privado" / "sheets_quota.sqlite"
            )
            return real_gate(path, **kwargs, now=self.clock.now, sleep=self.clock.sleep)

        with (
            patch("project_paths.ROOT", Path(self.tmp.name)),
            patch("history_sheets_quota.QuotaGate", side_effect=gate),
            redirect_stdout(io.StringIO()) as output,
        ):
            for _ in range(70):
                store._read_with_retry(
                    "conferir chamada sintética",
                    lambda: client.http_client.request(
                        "get", "https://sheets.googleapis.com/v4/spreadsheets/synthetic"
                    ),
                )
        self.assertEqual(server.errors, 0)
        self.assertEqual(len(server.calls), 70)
        self.assertEqual(output.getvalue().count("ritmo preventivo compartilhado"), 1)
        Store._native_meta_headers("Historico_Pedidos", SCHEMAS["Historico_Pedidos"])
        with self.assertRaisesRegex(HistoryError, "SCHEMA_HISTORICO_INVALIDO"):
            Store._native_meta_headers("Arbitraria", ["private"])

    def test_open_native_readonly_real_gspread_is_paced_from_first_http(self):
        from sheets_storage import SheetsStorage

        session = requests.Session()
        session.trust_env = False
        self.addCleanup(session.close)
        server = BootstrapGoogle(self.clock)
        session.mount("https://", server)
        client = gspread.Client(auth=AnonymousCredentials(), session=session)
        client.http_client.auth = SimpleNamespace(
            service_account_email="synthetic@example.invalid",
            project_id="synthetic-project",
        )
        Store = google_store_type()
        real_gate = QuotaGate

        def gate(path, **kwargs):
            return real_gate(path, **kwargs, now=self.clock.now, sleep=self.clock.sleep)

        with (
            patch("gspread.service_account", return_value=client),
            patch("project_paths.ROOT", Path(self.tmp.name)),
            patch("history_sheets_quota.QuotaGate", side_effect=gate),
            patch("runtime_profile.segment", return_value="FARMA"),
            patch("runtime_profile.validate_sheet_destinations"),
            patch(
                "sheets_storage.configured_storage",
                return_value=SheetsStorage("dashboard", "operations", "history"),
            ),
            redirect_stdout(io.StringIO()),
        ):
            store = Store.open_native_readonly("dashboard")
            self.addCleanup(store.close)
        self.assertEqual(len(server.calls), 9)
        self.assertTrue(all(r.method == "GET" for _, r, _ in server.calls))
        self.assertGreaterEqual(server.calls[1][0] - server.calls[0][0], 60 / 45 - 1e-8)
        self.assertIsInstance(
            session.get_adapter("https://sheets.googleapis.com/"), QuotaAdapter
        )
        self.assertEqual(store.native_meta_context.__self__, store)

    def test_store_retries_share_cooldown_and_auth_failure_is_not_retried(self):
        from gspread.exceptions import APIError

        session, server = self.session(paced=False)
        client = gspread.Client(auth=AnonymousCredentials(), session=session)
        client.http_client.auth = SimpleNamespace(
            service_account_email="synthetic@example.invalid",
            project_id="synthetic-project",
        )
        Store = google_store_type()
        store = Store.__new__(Store)
        store.client = client
        real_gate = QuotaGate

        def gate(path, **kwargs):
            return real_gate(path, **kwargs, now=self.clock.now, sleep=self.clock.sleep)

        server.statuses.extend((429, 429, 200))

        def call():
            return client.http_client.request(
                "get", "https://sheets.googleapis.com/v4/spreadsheets/synthetic"
            )

        with (
            patch("project_paths.ROOT", Path(self.tmp.name)),
            patch("history_sheets_quota.QuotaGate", side_effect=gate),
            patch("google_sheets.time.sleep", self.clock.sleep),
            patch("history_sheets_quota.random.uniform", return_value=0),
            redirect_stdout(io.StringIO()),
            self.assertLogs(level="WARNING"),
        ):
            self.assertEqual(
                store._read_with_retry(
                    "conferir intervalo sintético", call
                ).status_code,
                200,
            )
        self.assertEqual(len(server.calls), 3)
        self.assertGreaterEqual(server.calls[1][0] - server.calls[0][0], 65)
        self.assertGreaterEqual(server.calls[2][0] - server.calls[1][0], 65)
        server.status = 403
        before = len(server.calls)
        with self.assertRaises(APIError):
            store._read_with_retry("conferir intervalo sintético", call)
        self.assertEqual(len(server.calls), before + 1)

    def test_review_contract_files_remain_identical_to_public_29(self):
        # São os dez blobs LF da release c3da63d; impedir alteração acidental de
        # assinatura que prenderia a revisão comercial já parcialmente aplicada.
        hashes = {
            "history_publication.py": "da01cbc3986cf6b4539dda8e7ceec8fd0888b34dfa04489567f7f1528a29d20e",
            "history_reconciliation.py": "904b524632b14a25c33f3c24b871b6572f1292537c75ab913a4659318d572e34",
            "history_sheets_transport.py": "743647505e7eaf50057387349d67a0d353aa1bc4bc93994fce6869c945eab9c4",
            "history_capacity.py": "4c1d5253c7bac9d3839258d40a3d7486880c28e5dd9d8d351b2a89fc225bbcfb",
            "history_conference.py": "6e6b5f037b92dfe270ec5d1f39eb957dc0de9e5cf52dbe7dc0ec9e81c0df8a4f",
            "history_exclusions.py": "a9a25ec8d9c21699ba369acf9ea672290fd6c02bc72e06be02d2d5e9c02b29f6",
            "order_history_sheets.py": "60bf5fa1e887aecf812553b0312c7d785022852ac7c01b2d2b51793d00f8f014",
            "sheets_partitions.py": "b28ad57b991f6cfbd6c5bd913f8b39815b8151983521826a4d15037d9f8b24ed",
            "sheets_provisioning.py": "8a4a54193aa7355b432b19f211889036c1860f9a85cfd157ad173bff399b9945",
            "google_sheets.py": "834d30901ac0b0bff67b5ed746003e22a228099b38959e4fc31727311ccd9316",
        }
        root = Path(__file__).resolve().parents[1] / "app"
        for name, expected in hashes.items():
            with self.subTest(name=name):
                self.assertEqual(
                    hashlib.sha256(
                        (root / name).read_bytes().replace(b"\r\n", b"\n")
                    ).hexdigest(),
                    expected,
                )

    def test_direct_remote_lease_requests_use_the_same_session_budget(self):
        from sheets_continuation import SheetsLease

        session = requests.Session()
        session.trust_env = False
        self.addCleanup(session.close)
        server = LeaseGoogle(self.clock)
        gate = self.gate()
        session.mount("https://", server)
        session.mount("https://sheets.googleapis.com/", QuotaAdapter(server, gate))
        client = gspread.Client(auth=AnonymousCredentials(), session=session)
        book = client.open_by_key("synthetic")
        lease = SheetsLease(book, now=self.clock.now, sleep=self.clock.sleep)
        lease.require()
        self.assertIsNotNone(lease.value)
        lease.release()
        self.assertFalse(server.metadata)
        self.assertEqual(gate.calls, {"read": 3, "write": 2})
        self.assertEqual(len(server.calls), 5)
