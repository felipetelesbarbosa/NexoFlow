import os
import threading
from pathlib import Path
import unittest
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

from requests.exceptions import RequestException

import config
from farmalider_client import FarmaliderClient, FarmaliderError
from google_sheets import GoogleSheetsStore
from main import (
    FarmaliderSettings,
    _format_ms_as_seconds,
    split_contacts,
    validate_contacts,
)


def _ico_images(path: Path) -> list[bytes]:
    data = path.read_bytes()
    if data[:4] != b"\x00\x00\x01\x00":
        raise AssertionError(f"ICO inválido: {path}")
    count = int.from_bytes(data[4:6], "little")
    images: list[bytes] = []
    for index in range(count):
        entry = 6 + (16 * index)
        size = int.from_bytes(data[entry + 8:entry + 12], "little")
        offset = int.from_bytes(data[entry + 12:entry + 16], "little")
        images.append(data[offset:offset + size])
    return images


class CurrentIntegrationTests(unittest.TestCase):
    def tearDown(self) -> None:
        os.environ.pop("WENI_PROXY_ACTIVE", None)

    def test_proxy_uses_internal_url(self) -> None:
        os.environ["WENI_PROXY_ACTIVE"] = "1"
        self.assertEqual(
            config.farmalider_api_base_url(),
            "https://api.farmalider.net.br/farmalider",
        )

    def test_direct_uses_external_port_3200(self) -> None:
        os.environ["WENI_PROXY_ACTIVE"] = "0"
        self.assertEqual(
            config.farmalider_api_base_url(),
            "https://api.farmalider.net.br:3200/farmalider",
        )

    def test_farmalider_delay_is_valid(self) -> None:
        self.assertGreaterEqual(config.FARMALIDER_REQUEST_DELAY_SECONDS, 0.0)
        self.assertLess(
            config.FARMALIDER_REQUEST_DELAY_SECONDS,
            config.FARMALIDER_REQUEST_TIMEOUT_SECONDS,
        )

    def test_farmalider_latency_log_is_formatted_in_seconds(self) -> None:
        self.assertEqual(_format_ms_as_seconds(0), "0.00s")
        self.assertEqual(_format_ms_as_seconds(42), "0.04s")
        self.assertEqual(_format_ms_as_seconds(21630), "21.63s")

    def test_farmalider_slow_request_threshold_is_safe(self) -> None:
        self.assertGreater(config.FARMALIDER_SLOW_REQUEST_SECONDS, 0.0)
        self.assertLess(
            config.FARMALIDER_SLOW_REQUEST_SECONDS,
            config.FARMALIDER_REQUEST_TIMEOUT_SECONDS,
        )

    def test_farmalider_concurrency_settings_are_safe(self) -> None:
        self.assertGreaterEqual(config.FARMALIDER_MAX_WORKERS, 1)
        self.assertLessEqual(config.FARMALIDER_MAX_WORKERS, 16)
        self.assertGreaterEqual(
            config.FARMALIDER_BATCH_SIZE,
            config.FARMALIDER_MAX_WORKERS,
        )
        self.assertGreaterEqual(config.FARMALIDER_PARALLEL_MIN_CPFS, 1)
        self.assertLessEqual(
            config.FARMALIDER_PARALLEL_MIN_CPFS,
            config.FARMALIDER_BATCH_SIZE,
        )
        self.assertGreater(config.FARMALIDER_429_COOLDOWN_SECONDS, 0)
        self.assertGreaterEqual(
            config.FARMALIDER_MAX_ADAPTIVE_DELAY_SECONDS,
            config.FARMALIDER_REQUEST_DELAY_SECONDS,
        )

    def test_farmalider_uses_query_token_without_bearer(self) -> None:
        os.environ["WENI_PROXY_ACTIVE"] = "1"
        client = FarmaliderClient("abc123")
        response = Mock()
        response.status_code = 404
        try:
            with patch.object(client.session, "get", return_value=response) as get:
                result = client.get_cliente_by_cpf("52998224725")
            self.assertIsNone(result)
            self.assertEqual(get.call_args.kwargs["params"], {"token": "abc123"})
            self.assertNotIn("Authorization", client.session.headers)
        finally:
            client.close()

    def test_contact_with_only_cpf_is_processed(self) -> None:
        contact = {
            "uuid": "u1",
            "fields": {"cpf": "529.982.247-25"},
        }
        relevant, with_cpf, to_process = split_contacts([contact])
        self.assertEqual(relevant, [])
        self.assertEqual(len(with_cpf), 1)
        self.assertEqual(len(to_process), 1)

    def test_farmalider_uses_one_session_per_worker_thread(self) -> None:
        client = FarmaliderClient("abc123")
        barrier = threading.Barrier(4)

        def session_id() -> int:
            session = client.session
            barrier.wait(timeout=2)
            return id(session)

        try:
            with ThreadPoolExecutor(max_workers=4) as executor:
                ids = list(executor.map(lambda _: session_id(), range(4)))
            self.assertEqual(len(set(ids)), 4)
        finally:
            client.close()

    def test_farmalider_429_is_counted_and_retried(self) -> None:
        client = FarmaliderClient("abc123")
        response_429 = Mock(status_code=429, headers={})
        response_404 = Mock(status_code=404, headers={})

        try:
            with (
                patch.object(
                    client.session,
                    "get",
                    side_effect=[response_429, response_404],
                ),
                patch("farmalider_client.FARMALIDER_429_COOLDOWN_SECONDS", 0),
                patch("farmalider_client.logging.warning"),
            ):
                result = client.get_cliente_by_cpf("52998224725")

            metrics = client.metrics_snapshot()
            self.assertIsNone(result)
            self.assertEqual(metrics["rate_limits"], 1)
            self.assertEqual(metrics["retries"], 1)
            self.assertEqual(metrics["total_requests"], 2)
        finally:
            client.close()

    def test_farmalider_tracks_slow_requests_and_p95(self) -> None:
        client = FarmaliderClient("abc123")
        try:
            threshold = config.FARMALIDER_SLOW_REQUEST_SECONDS
            with patch("farmalider_client.logging.warning"):
                client._record_request(
                    threshold * 1.5,
                    status_code=200,
                    endpoint_label="cliente/cpf",
                )
            client._record_request(
                max(0.001, threshold / 10),
                status_code=404,
                endpoint_label="cliente/cpf",
            )
            metrics = client.metrics_snapshot()
            self.assertEqual(metrics["slow_requests"], 1)
            self.assertGreater(metrics["p95_response_ms"], 0)
            self.assertGreaterEqual(
                metrics["max_response_ms"],
                metrics["p95_response_ms"],
            )
        finally:
            client.close()

    def test_google_sheets_schema_fingerprint_exists(self) -> None:
        fingerprint = GoogleSheetsStore.schema_fingerprint()
        self.assertEqual(len(fingerprint), 16)
        self.assertTrue(all(ch in "0123456789abcdef" for ch in fingerprint))

    def test_google_sheets_read_retry_handles_network_failure(self) -> None:
        from requests.exceptions import Timeout

        store = GoogleSheetsStore.__new__(GoogleSheetsStore)
        operation = Mock(side_effect=[Timeout("simulado"), ["ok"]])
        with (
            patch("google_sheets.GOOGLE_SHEETS_READ_MAX_RETRIES", 2),
            patch("google_sheets.time.sleep") as sleep_mock,
        ):
            result = store._read_with_retry("leitura simulada", operation)

        self.assertEqual(result, ["ok"])
        self.assertEqual(operation.call_count, 2)
        sleep_mock.assert_called_once_with(2)

    def test_google_sheets_retryable_statuses_cover_transient_errors(self) -> None:
        self.assertTrue(GoogleSheetsStore._retryable_status(429))
        self.assertTrue(GoogleSheetsStore._retryable_status(500))
        self.assertTrue(GoogleSheetsStore._retryable_status(503))
        self.assertTrue(GoogleSheetsStore._retryable_status(504))
        self.assertFalse(GoogleSheetsStore._retryable_status(400))
        self.assertFalse(GoogleSheetsStore._retryable_status(403))

    def test_google_sheets_progress_logs_every_configured_step_and_final(self) -> None:
        with patch("google_sheets.GOOGLE_SHEETS_PROGRESS_EVERY_RECORDS", 5000):
            self.assertFalse(GoogleSheetsStore._should_log_progress(500, 12000))
            self.assertTrue(GoogleSheetsStore._should_log_progress(5000, 12000))
            self.assertTrue(GoogleSheetsStore._should_log_progress(10000, 12000))
            self.assertTrue(GoogleSheetsStore._should_log_progress(12000, 12000))

    def test_google_sheets_write_retry_handles_network_failure(self) -> None:
        from requests.exceptions import Timeout

        store = GoogleSheetsStore.__new__(GoogleSheetsStore)
        store._last_write_started_at = 0.0
        operation = Mock(side_effect=[Timeout("simulado"), "ok"])
        with (
            patch("google_sheets.GOOGLE_SHEETS_WRITE_MAX_RETRIES", 2),
            patch("google_sheets.GOOGLE_SHEETS_WRITE_DELAY_SECONDS", 0),
            patch("google_sheets.time.sleep") as sleep_mock,
        ):
            result = store._write_with_retry("escrita simulada", operation)

        self.assertEqual(result, "ok")
        self.assertEqual(operation.call_count, 2)
        sleep_mock.assert_called_once_with(2)

    def test_google_sheets_header_read_uses_bounded_range(self) -> None:
        store = GoogleSheetsStore.__new__(GoogleSheetsStore)
        ws = Mock()
        ws.title = "Teste"
        ws.col_count = 1000
        ws.get.return_value = [["a", "b"]]
        store._read_with_retry = lambda _description, func: func()

        headers = store._read_header_bounded(ws, ["a", "b"])

        self.assertEqual(headers, ["a", "b"])
        requested_range = ws.get.call_args.args[0]
        self.assertTrue(requested_range.startswith("A1:"))
        self.assertTrue(requested_range.endswith("1"))
        self.assertNotEqual(requested_range, "A1:1")

    def test_google_sheets_load_base_uuids_reads_only_first_column(self) -> None:
        store = GoogleSheetsStore.__new__(GoogleSheetsStore)
        store.base = Mock()
        store.base.row_values.return_value = ["contact_uuid", "nome"]
        store.base.col_values.return_value = [
            "contact_uuid",
            "u1",
            "u2",
            "u1",
            "",
        ]
        self.assertEqual(store.load_base_uuids(), {"u1", "u2"})
        store.base.row_values.assert_not_called()
        store.base.col_values.assert_called_once_with(1)

    def test_google_sheets_append_history_uses_validated_schema_without_header_read(self) -> None:
        store = GoogleSheetsStore.__new__(GoogleSheetsStore)
        store.history = Mock()
        store._headers_cache = {
            "Historico_Alteracoes": ["acao", "sincronizado_em", "contact_uuid"]
        }
        store._last_write_started_at = 0.0
        with (
            patch("google_sheets.GOOGLE_SHEETS_APPEND_BATCH_SIZE", 1000),
            patch("google_sheets.GOOGLE_SHEETS_WRITE_DELAY_SECONDS", 0),
        ):
            store.append_history(
                [{"contact_uuid": "u1"}],
                existing_uuids_before_sync=set(),
            )

        store.history.row_values.assert_not_called()
        store.history.append_rows.assert_called_once()
        rows = store.history.append_rows.call_args.args[0]
        self.assertEqual(rows[0][0], "Inserido")
        self.assertEqual(rows[0][2], "u1")

    def test_google_sheets_batch_update_retry_uses_fresh_payload(self) -> None:
        store = GoogleSheetsStore.__new__(GoogleSheetsStore)
        store.base = Mock()
        store.base.title = "Base_Contatos"
        store._last_write_started_at = 0.0
        store._read_requests = 0
        store._write_requests = 0
        seen_ranges: list[str] = []

        def mutate_like_gspread(payload, **kwargs):
            current_range = payload[0]["range"]
            seen_ranges.append(current_range)
            # Worksheet.batch_update normaliza a faixa adicionando o nome da aba
            # no próprio payload recebido. Se o mesmo objeto for reutilizado em
            # um retry, o prefixo será aplicado de novo.
            payload[0]["range"] = f"'{store.base.title}'!{current_range}"
            if len(seen_ranges) == 1:
                raise RequestException("proxy transitório")
            return {"ok": True}

        store.base.batch_update.side_effect = mutate_like_gspread
        existing_values = [
            ["contact_uuid", "nome"],
            ["u1", "Maria"],
        ]

        with patch("google_sheets.time.sleep", return_value=None):
            result = store.upsert_contacts_detailed(
                [{"contact_uuid": "u1", "nome": "Joana"}],
                existing_values=existing_values,
            )

        self.assertEqual(result.updated, 1)
        self.assertEqual(seen_ranges, ["A2:B2", "A2:B2"])

    def test_google_sheets_adaptive_batches_respect_payload_limit(self) -> None:
        items = [["x" * 400] for _ in range(10)]
        batches = GoogleSheetsStore._adaptive_batches(
            items,
            max_items=100,
            max_bytes=1000,
        )
        self.assertGreater(len(batches), 1)
        self.assertEqual(sum(len(batch) for batch in batches), 10)

    def test_google_sheets_upsert_skips_technical_timestamp_only_changes(self) -> None:
        store = GoogleSheetsStore.__new__(GoogleSheetsStore)
        store.base = Mock()
        store.base.title = "Base_Contatos"
        store._headers_cache = {
            "Base_Contatos": ["contact_uuid", "nome", "sincronizado_em", "farmalider_cliente_consultado_em"]
        }
        store._last_write_started_at = 0.0
        store._read_requests = 0
        store._write_requests = 0
        values = [
            ["contact_uuid", "nome", "sincronizado_em", "farmalider_cliente_consultado_em"],
            ["u1", "Maria", "old", "old"],
        ]
        result = store.upsert_contacts_detailed(
            [{
                "contact_uuid": "u1",
                "nome": "Maria",
                "sincronizado_em": "new",
                "farmalider_cliente_consultado_em": "new",
            }],
            existing_values=values,
        )
        self.assertEqual(result.updated, 0)
        self.assertEqual(result.unchanged, 1)
        self.assertEqual(result.changed_records, [])
        store.base.batch_update.assert_not_called()

    def test_google_sheets_sales_metric_row_count(self) -> None:
        store = GoogleSheetsStore.__new__(GoogleSheetsStore)
        store.sales_metrics = Mock()
        store.sales_metrics.get_all_values.return_value = [
            ["data", "pedidos"],
            ["2026-09-30", "1"],
            ["2026-10-01", "2"],
        ]
        self.assertEqual(store.sales_metric_row_count(), 2)

    def test_google_sheets_does_not_rewrite_equal_metrics_table(self) -> None:
        store = GoogleSheetsStore.__new__(GoogleSheetsStore)
        ws = Mock()
        ws.title = "Metricas_Diarias"
        ws.get_all_values.return_value = [
            ["data", "tipo_atribuicao", "anuncio_id", "anuncio_titulo", "contatos"],
            ["2026-09-30", "Primeiro", "1", "Teste", "2"],
        ]
        changed = store._replace_table(
            ws,
            ["data", "tipo_atribuicao", "anuncio_id", "anuncio_titulo", "contatos"],
            [["2026-09-30", "Primeiro", "1", "Teste", 2]],
        )
        self.assertFalse(changed)
        ws.clear.assert_not_called()
        ws.update.assert_not_called()

    def test_validate_contacts_reuses_recent_farmalider_cache_incrementally(self) -> None:
        farm = Mock()
        settings = FarmaliderSettings(enabled=True, token="x", use_hml=False)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        rows = [{"contact_uuid": "u1", "cpf": "52998224725"}]
        existing = {
            "u1": {
                "contact_uuid": "u1",
                "cpf": "52998224725",
                "cpf_normalizado": "52998224725",
                "farmalider_cliente_status": "CPF_CONFIRMADO",
                "farmalider_cliente_id": "123",
                "farmalider_cliente_nome": "Maria",
                "farmalider_cliente_consultado_em": now,
            }
        }
        stats = validate_contacts(
            rows,
            farm_client=farm,
            farm_settings=settings,
            sync_time=now,
            existing_by_uuid=existing,
            reuse_existing=True,
        )
        self.assertEqual(stats.cache_reused, 1)
        self.assertEqual(stats.unique_queries, 0)
        self.assertEqual(rows[0]["farmalider_cliente_status"], "CPF_CONFIRMADO")
        farm.get_cliente_by_cpf.assert_not_called()

    def test_validate_contacts_aborts_on_high_unrecovered_error_rate(self) -> None:
        class FailingClient:
            def get_cliente_by_cpf(self, cpf: str):
                raise FarmaliderError("falha simulada")

            def metrics_snapshot(self):
                return {
                    "total_requests": 2,
                    "retries": 0,
                    "rate_limits": 0,
                    "server_errors": 0,
                    "network_errors": 0,
                    "average_response_ms": 1.0,
                    "max_response_ms": 1.0,
                    "effective_delay_ms": 10.0,
                }

        rows = [
            {"contact_uuid": "u1", "cpf": "52998224725"},
            {"contact_uuid": "u2", "cpf": "16899535009"},
        ]

        with (
            patch("main.FARMALIDER_BATCH_SIZE", 2),
            patch("main.FARMALIDER_MAX_WORKERS", 2),
            patch("main.FARMALIDER_BATCH_ERROR_ABORT_MIN_ERRORS", 1),
            patch("main.FARMALIDER_BATCH_ERROR_ABORT_RATE", 0.5),
        ):
            with self.assertRaises(FarmaliderError):
                validate_contacts(
                    rows,
                    farm_client=FailingClient(),  # type: ignore[arg-type]
                    farm_settings=FarmaliderSettings(True, "token", False),
                    sync_time="2026-09-30T21:00:00+00:00",
                )

    def test_validate_contacts_queries_each_unique_cpf_once(self) -> None:
        class FakeClient:
            def __init__(self) -> None:
                self.calls: list[str] = []
                self.lock = threading.Lock()

            def get_cliente_by_cpf(self, cpf: str):
                with self.lock:
                    self.calls.append(cpf)
                return {
                    "id": int(cpf[-4:]),
                    "cpf": int(cpf),
                    "nome": f"Cliente {cpf[-4:]}",
                }

            def metrics_snapshot(self):
                return {
                    "total_requests": len(self.calls),
                    "retries": 0,
                    "rate_limits": 0,
                    "server_errors": 0,
                    "network_errors": 0,
                    "average_response_ms": 1.0,
                    "max_response_ms": 1.0,
                    "effective_delay_ms": 10.0,
                }

        rows = [
            {"contact_uuid": "u1", "cpf": "529.982.247-25"},
            {"contact_uuid": "u2", "cpf": "52998224725"},
            {"contact_uuid": "u3", "cpf": "168.995.350-09"},
        ]
        fake = FakeClient()
        stats = validate_contacts(
            rows,
            farm_client=fake,  # type: ignore[arg-type]
            farm_settings=FarmaliderSettings(True, "token", False),
            sync_time="2026-09-30T21:00:00+00:00",
        )

        self.assertEqual(set(fake.calls), {"52998224725", "16899535009"})
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(stats.unique_queries, 2)
        self.assertEqual(stats.confirmed, 3)
        self.assertTrue(
            all(row["farmalider_cliente_status"] == "CPF_CONFIRMADO" for row in rows)
        )


    def test_safe_launcher_batch_gates_each_stage(self) -> None:
        root = Path(__file__).resolve().parents[1]
        text = (root / "executar_carga_segura.bat").read_text(encoding="utf-8")
        self.assertIn("call \"%~dp0check-up.bat\"", text)
        self.assertIn("call \"%~dp0testar_conexoes.bat\"", text)
        self.assertIn("call \"%~dp0executar_manual.bat\"", text)
        self.assertGreaterEqual(text.count("if not \"%RC%\"==\"0\""), 3)

    def test_individual_batches_support_launcher_mode_and_exit_codes(self) -> None:
        root = Path(__file__).resolve().parents[1]
        checkup = (root / "check-up.bat").read_text(encoding="utf-8")
        conexoes = (root / "testar_conexoes.bat").read_text(encoding="utf-8")
        manual = (root / "executar_manual.bat").read_text(encoding="utf-8")
        self.assertIn("NEXOFLOW_LAUNCHER", checkup)
        self.assertIn("NEXOFLOW_LAUNCHER", conexoes)
        self.assertIn("NEXOFLOW_LAUNCHER", manual)
        self.assertIn("exit /b %EXIT_CODE%", conexoes)
        self.assertIn("exit /b %EXIT_CODE%", manual)

    def test_windows_launcher_exists(self) -> None:
        root = Path(__file__).resolve().parents[1]
        launcher = root / "NexoFlow Analytics.exe"
        self.assertTrue(launcher.exists())
        self.assertGreater(launcher.stat().st_size, 1024)
        data = launcher.read_bytes()
        self.assertTrue(data.startswith(b"MZ"))
        self.assertIn(b"NexoFlowOperationLock", data)
        self.assertIn(b'requestedExecutionLevel level="asInvoker"', data)
        self.assertIn(b".rsrc", data)
        self.assertIn(b"NexoFlowNativeLauncher=1.0", data)
        self.assertIn(b"CreateProcessW", data)
        self.assertNotIn(b"\x00system\x00", data)
        self.assertNotIn(b"powershell.exe", data)
        self.assertNotIn(b"-ExecutionPolicy", data)
        self.assertIn("Grupo Líder".encode("utf-16le"), data)


    def test_setup_failure_keeps_diagnostics_visible(self) -> None:
        root = Path(__file__).resolve().parents[1]
        setup_go = (root / "native_launcher" / "setup.go").read_text(encoding="utf-8")
        install = (root / "installer" / "install.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("if rc != 0", setup_go)
        self.assertIn("waitEnter()", setup_go)
        self.assertIn("NexoFlow-Setup.log", setup_go)
        self.assertIn("Start-Transcript", install)
        self.assertIn("NexoFlow-Setup.log", install)
        self.assertIn("Stop-InstalledNexoFlowProcesses", install)
        self.assertIn("taskkill.exe", install)
        self.assertIn("function Remove-DirectoryWithRetry", install)
        self.assertIn("function Stage-ExistingInstall", install)
        self.assertIn("function Restore-PreviousInstall", install)
        self.assertIn("$attempt -le $Attempts", install)
        self.assertIn("Ensure-Administrator", install)
        self.assertIn("-Verb RunAs", install)

    def test_windows_uninstaller_is_script_based_and_self_elevates(self) -> None:
        root = Path(__file__).resolve().parents[1]
        uninstaller = root / "installer" / "uninstall.ps1"
        wrapper = root / "desinstalar_nexoflow.cmd"
        self.assertTrue(uninstaller.exists())
        self.assertTrue(wrapper.exists())
        text = uninstaller.read_text(encoding="utf-8-sig")
        wrapper_text = wrapper.read_text(encoding="utf-8")
        self.assertIn("function Ensure-Administrator", text)
        self.assertIn("-Verb RunAs", text)
        self.assertIn("NexoFlow-Uninstall-Stage2.ps1", text)
        self.assertIn("installer\\uninstall.ps1", wrapper_text)
        optional_exe = root / "NexoFlow Uninstall.exe"
        if optional_exe.exists():
            data = optional_exe.read_bytes()
            self.assertTrue(data.startswith(b"MZ"))
            self.assertIn(b"NexoFlowNativeLauncher=1.0", data)
            self.assertIn("1.0.0.0".encode("utf-16le"), data)

    def test_installer_repairs_and_validates_required_components(self) -> None:
        root = Path(__file__).resolve().parents[1]
        install = (root / "installer" / "install.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("function Ensure-InstalledPayloadFile", install)
        self.assertIn("Write-Step 'Validando componentes instalados'", install)
        self.assertIn("Get-Sha256File -Path $target", install)
        self.assertIn("Restaurando a partir do payload validado", install)
        for name in (
            "NexoFlow Analytics.exe",
            "NexoFlow Weni.exe",
            "NexoFlow Terminal.exe",
            "installer\\uninstall.ps1",
            "desinstalar_nexoflow.cmd",
        ):
            self.assertIn(name, install)
        self.assertIn("function Install-OptionalUninstaller", install)
        self.assertIn("NexoFlow Uninstall.exe", install)
        self.assertIn("A instalação continuará normalmente", install)
        required_line = "foreach ($requiredFile in @('NexoFlow Analytics.exe','NexoFlow Weni.exe','NexoFlow Terminal.exe','installer\\uninstall.ps1','desinstalar_nexoflow.cmd'))"
        self.assertIn(required_line, install)
        self.assertNotIn("'NexoFlow Uninstall.exe')) {\n        Ensure-InstalledPayloadFile", install)
        self.assertIn("Verifique antivírus/EDR e tente novamente", install)

    def test_installer_lifecycle_preserves_private_data(self) -> None:
        root = Path(__file__).resolve().parents[1]
        install = (root / "installer" / "install.ps1").read_text(encoding="utf-8")
        uninstall = (root / "installer" / "uninstall.ps1").read_text(encoding="utf-8")
        for value in ("secrets_config.py", "credentials", "logs"):
            self.assertIn(value, install)
            self.assertIn(value, uninstall)
        self.assertIn("payload manifest.json", install)
        self.assertIn("function Get-Sha256File", install)
        self.assertIn("CurrentVersion\\Uninstall\\NexoFlow", install)
        self.assertIn("NexoFlow Analytics.lnk", install)
        # O fluxo atual aceita Python 3.11+ e inclui o instalador 3.14.8 como
        # fallback local. O teste antigo ainda exigia o identificador WinGet
        # Python.Python.3.12, que foi removido deliberadamente do instalador.
        self.assertNotIn("Python.Python.3.12", install)
        self.assertIn("python-3.14.8-amd64.exe", install)
        self.assertIn("python3.14.exe", install)
        self.assertIn("pythoncore-*-64", install)
        self.assertIn("pymanager.exe", install)
        self.assertIn("list --format=exe", install)
        self.assertIn("NEXOFLOW_PYTHON_EXE", install)
        self.assertIn("Get-CompatiblePython", install)
        self.assertIn("Get-Command $commandName -All", install)
        self.assertIn("sys.executable", install)
        self.assertIn("Python 3.11 ou superior", install)
        self.assertIn("Confirm-PythonInstall", install)
        self.assertIn("Install-PythonIfNeeded", install)
        self.assertIn("Start-Process -FilePath $BundledPythonInstaller", install)
        self.assertIn("NÃO instalará Python 3.12", install)
        self.assertIn("NÃO usará WinGet", install)
        self.assertIn("Documentacao NexoFlow.html", install)
        self.assertIn("NexoFlow Data", uninstall)
        self.assertIn("YesNoCancel", uninstall)
        self.assertIn("Get-CimInstance Win32_Process", uninstall)
        self.assertIn("Stop-Process", uninstall)
        self.assertIn("Remove-InstallDirectory", uninstall)
        self.assertIn("Processos do NexoFlow que estiverem em execucao serao encerrados", uninstall)
        self.assertNotIn("-WindowStyle Hidden", uninstall)
        self.assertIn("NexoFlow-Uninstall-Stage2.ps1", uninstall)
        self.assertNotIn(r"cmd\.exe|powershell\.exe|pwsh\.exe", uninstall)
        self.assertIn("Set-Location -LiteralPath $tempWorkingDir", uninstall)
        self.assertIn("-WorkingDirectory $tempWorkingDir", uninstall)
        self.assertIn("$attempt -le 60", uninstall)
        self.assertIn("attrib.exe -R -S -H", uninstall)
        self.assertIn("NexoFlow Weni.lnk", uninstall)
        self.assertIn("NexoFlow Terminal.lnk", uninstall)
        self.assertIn("NexoFlow Console.lnk", uninstall)
        self.assertIn("$uninstallCommand = '\"' + $powershellExe", install)
        self.assertIn("installer\\uninstall.ps1", install)
        self.assertIn("-Verb RunAs", uninstall)
        self.assertNotIn("start \"\" /wait /D", install)
        self.assertNotIn("cd /d \"\"{0}\"\" &&", install)


    def test_powershell_installer_scripts_are_utf8_bom(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for relative in ("installer/install.ps1", "installer/uninstall.ps1"):
            data = (root / relative).read_bytes()
            self.assertTrue(data.startswith(b"\xef\xbb\xbf"), relative)

    def test_windows_icon_assets_exist(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for name in ("NexoFlow.ico", "NexoFlow_Weni.ico", "NexoFlow_Terminal.ico", "installer.ico", "uninstaller.ico"):
            icon = root / "assets" / name
            self.assertTrue(icon.exists(), name)
            self.assertGreater(icon.stat().st_size, 1024)
            data = icon.read_bytes()
            self.assertEqual(data[:4], b"\x00\x00\x01\x00")

    def test_operational_documentation_is_installed_at_root(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.assertTrue((root / "Documentacao NexoFlow.md").exists())
        self.assertTrue((root / "Documentacao NexoFlow.html").exists())

    def test_main_has_clear_execution_summary(self) -> None:
        root = Path(__file__).resolve().parents[1]
        text = (root / "main.py").read_text(encoding="utf-8")
        self.assertIn("Weni: recebidos=%s", text)
        self.assertIn("CPFs válidos únicos para consulta=%s", text)
        self.assertIn("Resumo da execução:", text)
        self.assertIn("Sincronização concluída com sucesso em %.2fs.", text)

    def test_installer_bat_supports_noninteractive_setup(self) -> None:
        root = Path(__file__).resolve().parents[1]
        text = (root / "instalar.bat").read_text(encoding="utf-8")
        self.assertIn("NEXOFLOW_INSTALLER", text)
        self.assertIn("where python.exe", text)
        self.assertIn("where python3.14.exe", text)
        self.assertIn("where py.exe", text)
        self.assertIn("sys.version_info >= (3,11)", text)
        self.assertIn("struct.calcsize('P')*8 == 64", text)


    def test_update_weni_launcher_and_batches_exist(self) -> None:
        root = Path(__file__).resolve().parents[1]
        launcher = root / "NexoFlow Weni.exe"
        self.assertTrue(launcher.exists())
        data = launcher.read_bytes()
        self.assertTrue(data.startswith(b"MZ"))
        self.assertIn(b"NexoFlowOperationLock", data)
        self.assertIn(b"atualizar_weni.bat", data)
        self.assertIn(b'requestedExecutionLevel level="asInvoker"', data)
        self.assertNotIn(b"powershell.exe", data)
        self.assertNotIn(b"-ExecutionPolicy", data)
        for name in (
            "atualizar_weni.bat",
            "atualizar_weni_dry_run.bat",
            "atualizar_weni_carga_completa.bat",
            "testar_update_weni.bat",
            "run_update_weni.py",
            "weni_update.py",
            "contact_enrichment.py",
        ):
            self.assertTrue((root / name).exists(), name)


    def test_update_weni_executable_embeds_dedicated_icon(self) -> None:
        root = Path(__file__).resolve().parents[1]
        launcher = (root / "NexoFlow Weni.exe").read_bytes()
        update_images = _ico_images(root / "assets" / "NexoFlow_Weni.ico")
        analytics_images = _ico_images(root / "assets" / "NexoFlow.ico")
        self.assertTrue(update_images)
        for image in update_images:
            self.assertIn(image, launcher)
        for image in analytics_images:
            self.assertNotIn(image, launcher)


    def test_terminal_executable_embeds_dedicated_icon(self) -> None:
        root = Path(__file__).resolve().parents[1]
        launcher = (root / "NexoFlow Terminal.exe").read_bytes()
        terminal_images = _ico_images(root / "assets" / "NexoFlow_Terminal.ico")
        analytics_images = _ico_images(root / "assets" / "NexoFlow.ico")
        self.assertTrue(terminal_images)
        for image in terminal_images:
            self.assertIn(image, launcher)
        for image in analytics_images:
            self.assertNotIn(image, launcher)

    def test_update_weni_executable_has_icon_revision_marker(self) -> None:
        root = Path(__file__).resolve().parents[1]
        data = (root / "NexoFlow Weni.exe").read_bytes()
        self.assertIn(b"NexoFlowWeniIconRevision=1.0", data)

    def test_installer_refreshes_windows_icon_cache(self) -> None:
        root = Path(__file__).resolve().parents[1]
        install = (root / "installer" / "install.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("function Refresh-NexoFlowIconCache", install)
        self.assertIn("SHChangeNotify", install)
        self.assertIn("-ClearIconCache", install)
        self.assertIn("-show", install)
        self.assertIn("Refresh-NexoFlowIconCache -Executables @($updateExe, $terminalExe)", install)

    def test_update_weni_safe_batch_has_mandatory_audit_before_apply(self) -> None:
        root = Path(__file__).resolve().parents[1]
        text = (root / "atualizar_weni.bat").read_text(encoding="utf-8")
        self.assertIn("check-up.bat", text)
        self.assertIn("testar_update_weni.bat", text)
        self.assertIn("run_update_weni.py --dry-run", text)
        self.assertIn("run_update_weni.py --apply", text)
        self.assertIn("Digite ATUALIZAR", text)
        self.assertLess(
            text.index("run_update_weni.py --dry-run"),
            text.index("run_update_weni.py --apply"),
        )

    def test_full_update_requires_human_review_snapshot(self) -> None:
        root = Path(__file__).resolve().parents[1]
        text = (root / "atualizar_weni_carga_completa.bat").read_text(encoding="utf-8")
        self.assertIn("--review-out", text)
        self.assertIn("weni_update_review_full.txt", text)
        self.assertIn("notepad.exe", text)
        self.assertIn("CARGA COMPLETA REVISADA", text)
        self.assertIn("--require-review", text)
        self.assertLess(text.index("--review-out"), text.index("--require-review"))

    def test_nexoflow_terminal_uses_project_proxy_without_exporting_api_tokens(self) -> None:
        root = Path(__file__).resolve().parents[1]
        terminal = (root / "NexoFlow Terminal.exe").read_bytes()
        runner = (root / "run_terminal.py").read_text(encoding="utf-8")
        self.assertTrue(terminal.startswith(b"MZ"))
        self.assertIn(b"run_terminal.py", terminal)
        self.assertIn(b"NexoFlowTerminalIconRevision=1.0", terminal)
        self.assertIn(b'requestedExecutionLevel level="asInvoker"', terminal)
        self.assertIn("configure_proxy()", runner)
        self.assertIn("HTTP_PROXY", runner)
        self.assertIn("HTTPS_PROXY", runner)
        self.assertIn("NEXOFLOW_HOME", runner)
        self.assertIn("NEXOFLOW_TERMINAL", runner)
        self.assertIn("VIRTUAL_ENV", runner)
        self.assertNotIn("WENI_API_TOKEN]", runner)
        self.assertNotIn("FARMALIDER_API_TOKEN]", runner)

    def test_distribution_hardening_avoids_unnecessary_shell_patterns(self) -> None:
        root = Path(__file__).resolve().parents[1]
        shortcut = (root / "criar_atalho_desktop.bat").read_text(encoding="utf-8")
        uninstall = (root / "installer" / "uninstall.ps1").read_text(encoding="utf-8")
        install = (root / "installer" / "install.ps1").read_text(encoding="utf-8")
        self.assertNotIn("-ExecutionPolicy Bypass -Command", shortcut)
        self.assertNotIn("-WindowStyle Hidden", uninstall)
        self.assertIn("NexoFlow-Uninstall-Stage2.ps1", uninstall)
        self.assertNotIn("cmd.exe /d /s /c start", install)
        for name in ("NexoFlow Analytics.exe", "NexoFlow Weni.exe", "NexoFlow Terminal.exe"):
            data = (root / name).read_bytes()
            self.assertIn(b"NexoFlowNativeLauncher=1.0", data)
            self.assertIn(b"CreateProcessW", data)
            self.assertNotIn(b"\x00system\x00", data)
        optional_exe = root / "NexoFlow Uninstall.exe"
        if optional_exe.exists():
            data = optional_exe.read_bytes()
            self.assertIn(b"NexoFlowNativeLauncher=1.0", data)
            self.assertNotIn(b"NexoFlowNativeLauncher=6.", data)
        self.assertTrue((root / "installer" / "uninstall.ps1").exists())
        self.assertTrue((root / "desinstalar_nexoflow.cmd").exists())

    def test_installer_and_uninstaller_cover_update_weni(self) -> None:
        root = Path(__file__).resolve().parents[1]
        install = (root / "installer" / "install.ps1").read_text(encoding="utf-8")
        uninstall = (root / "installer" / "uninstall.ps1").read_text(encoding="utf-8")
        self.assertIn("NexoFlow Weni.exe", install)
        self.assertIn("NexoFlow Weni.lnk", install)
        self.assertIn("NexoFlow Terminal.exe", install)
        self.assertIn("NexoFlow Terminal.lnk", install)
        self.assertIn("NexoFlow_Terminal.ico", install)
        self.assertIn("NexoFlow Weni.lnk", uninstall)
        self.assertIn("NexoFlow Terminal.lnk", uninstall)
        self.assertIn("NexoFlow Console.lnk", uninstall)
        self.assertIn("NexoFlow - Update Weni.lnk", install)
        self.assertIn("NexoFlow Console.lnk", install)
        self.assertIn("$AppVersion = '1.0'", install)
        self.assertIn("${exePath}: $($_.Exception.Message)", install)
        self.assertNotIn("$exePath: $($_.Exception.Message)", install)


    def test_weni_update_tests_do_not_read_operational_state(self) -> None:
        root = Path(__file__).resolve().parents[1]
        tests = (root / "tests" / "test_weni_update.py").read_text(encoding="utf-8")
        self.assertIn('patch(', tests)
        self.assertIn('"weni_update._load_state"', tests)
        self.assertIn('side_effect=lambda *args, **kwargs: {}', tests)

    def test_checkup_suppresses_expected_test_noise_without_hiding_failures(self) -> None:
        root = Path(__file__).resolve().parents[1]
        batch = (root / "check-up.bat").read_text(encoding="utf-8")
        runner = (root / "run_checkup_tests.py").read_text(encoding="utf-8")
        self.assertIn("run_checkup_tests.py", batch)
        self.assertIn("logging.disable(logging.CRITICAL)", runner)
        self.assertIn('warnings.simplefilter("ignore")', runner)
        self.assertIn("TextTestRunner(verbosity=0)", runner)
        self.assertIn("result.wasSuccessful()", runner)


    def test_batch_files_are_cmd_compatible_without_utf8_bom(self) -> None:
        root = Path(__file__).resolve().parents[1]
        batch_files = sorted(root.glob("*.bat"))
        self.assertTrue(batch_files)
        offenders = [p.name for p in batch_files if p.read_bytes().startswith(b"\xef\xbb\xbf")]
        self.assertEqual([], offenders, f"BATs com UTF-8 BOM quebram @echo/cmd.exe: {offenders}")

    def test_nexo_cmd_is_cmd_compatible_without_utf8_bom(self) -> None:
        root = Path(__file__).resolve().parents[1]
        command = root / "nexo.cmd"
        self.assertTrue(command.exists())
        self.assertFalse(command.read_bytes().startswith(b"\xef\xbb\xbf"))
        self.assertIn("nexo_cli.py", command.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
