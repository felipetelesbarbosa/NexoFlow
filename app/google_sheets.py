from __future__ import annotations

import copy
import hashlib
import json
import logging
import math
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import gspread
from google.auth.exceptions import TransportError as GoogleAuthTransportError

if TYPE_CHECKING:
    from gspread.worksheet import Worksheet
from gspread.exceptions import APIError, SpreadsheetNotFound, WorksheetNotFound
from gspread.utils import ValueInputOption
from requests.exceptions import RequestException

from analytics import (
    BASE_COLUMNS,
    BI_ADS_COLUMNS,
    BI_CHANNEL_COLUMNS,
    BI_CONVERSION_COLUMNS,
    BI_ORDERS_COLUMNS,
    BI_SALES_COLUMNS,
    BI_STATUS_COLUMNS,
    BI_SUMMARY_COLUMNS,
    CONTROL_COLUMNS,
    EVENT_COLUMNS,
    HISTORY_COLUMNS,
    META_CAMPAIGN_COLUMNS,
    METRIC_COLUMNS,
    ORDER_COLUMNS,
    ORDER_ITEM_COLUMNS,
    SALES_METRIC_COLUMNS,
)
from config import (
    GOOGLE_CREDENTIALS_FILE,
    GOOGLE_SHEETS_APPEND_BATCH_SIZE,
    GOOGLE_SHEETS_CONNECT_TIMEOUT_SECONDS,
    GOOGLE_SHEETS_MAX_BATCH_PAYLOAD_BYTES,
    GOOGLE_SHEETS_PROGRESS_EVERY_RECORDS,
    GOOGLE_SHEETS_READ_MAX_RETRIES,
    GOOGLE_SHEETS_READ_TIMEOUT_SECONDS,
    GOOGLE_SHEETS_UPDATE_BATCH_SIZE,
    GOOGLE_SHEETS_WRITE_DELAY_SECONDS,
    GOOGLE_SHEETS_WRITE_MAX_RETRIES,
    SHEET_BASE_CONTATOS,
    SHEET_BI_ADS,
    SHEET_BI_CANAIS,
    SHEET_BI_CONVERSAO,
    SHEET_BI_PEDIDOS,
    SHEET_BI_RESUMO_DIARIO,
    SHEET_BI_STATUS,
    SHEET_BI_VENDAS,
    SHEET_CAMPANHAS_META,
    SHEET_CONTROLE,
    SHEET_EVENTOS,
    SHEET_HISTORICO,
    SHEET_ITENS_PEDIDOS,
    SHEET_METRICAS,
    SHEET_METRICAS_VENDAS,
    SHEET_PEDIDOS,
)
from geography import normalize_geography
from looker_bi import DATE_COLUMNS, TEXT_COLUMNS
from looker_bi import SCHEMAS as LOOKER_SCHEMAS
from network_diagnostics import classify_network_failure
from pharmacy_scope import (
    PharmacyScopePlan,
    filter_pharmacy_order,
    plan_pharmacy_scope,
    recalculate_scope_snapshots,
    sanitize_contact_order,
    sanitize_delivery_ticket,
    sanitize_order_record,
)
from product_scope import pharmacy_items
from proxy_config import refresh_network_route
from sheets_storage import STORAGE_SHEET, SheetsStorage
from task_progress import TaskProgress, request_progress


def column_letter(number: int) -> str:
    if number < 1:
        raise ValueError("number precisa ser maior ou igual a 1.")

    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


@dataclass
class UpsertResult:
    inserted: int
    updated: int
    unchanged: int
    changed_records: list[dict[str, str]]
    final_records: list[dict[str, str]]
    removed: int = 0


class GoogleSheetsStore:
    SCHEMA_CONTROL_KEY = "_schema_fingerprint"
    SCHEMA_HEADERS_CONTROL_KEY = "_schema_headers_layout"

    def __init__(
        self,
        spreadsheet_id: str,
        *,
        validate_structure: bool = False,
    ):
        from runtime_profile import segment

        if segment() == "PET":
            from project_paths import load_private_settings

            if spreadsheet_id != getattr(
                load_private_settings(), "GOOGLE_SPREADSHEET_ID", ""
            ):
                raise ValueError("Dashboard não pertence ao perfil PET.")
        if not GOOGLE_CREDENTIALS_FILE.exists():
            raise FileNotFoundError(
                f"Credencial Google não encontrada: {GOOGLE_CREDENTIALS_FILE}"
            )

        self.client = gspread.service_account(filename=str(GOOGLE_CREDENTIALS_FILE))
        self.client.set_timeout(
            (
                float(GOOGLE_SHEETS_CONNECT_TIMEOUT_SECONDS),
                float(GOOGLE_SHEETS_READ_TIMEOUT_SECONDS),
            )
        )

        try:
            self.book = self._read_with_retry(
                "abrir a planilha",
                lambda: self.client.open_by_key(spreadsheet_id),
            )
        except SpreadsheetNotFound as exc:
            raise RuntimeError(
                "A planilha Google não foi encontrada. "
                "Confirme o ID e compartilhe a planilha com o client_email "
                "da Service Account como Editor."
            ) from exc

        self._last_write_started_at = 0.0
        self._headers_cache: dict[str, list[str]] = {}
        self._control_values_cache: list[list[str]] | None = None
        self._read_requests = 0
        self._write_requests = 0
        self._hub_id = spreadsheet_id
        self._storage_books: dict[str, Any] = {}
        self._storage_layout: SheetsStorage | None = None
        self._initialize_structure(validate_structure=validate_structure)

    def close(self) -> None:
        self.client.http_client.session.close()

    @staticmethod
    def _schema_map() -> dict[str, list[str]]:
        return {
            SHEET_BASE_CONTATOS: BASE_COLUMNS,
            SHEET_HISTORICO: HISTORY_COLUMNS,
            SHEET_METRICAS: METRIC_COLUMNS,
            SHEET_EVENTOS: EVENT_COLUMNS,
            SHEET_CAMPANHAS_META: META_CAMPAIGN_COLUMNS,
            SHEET_PEDIDOS: ORDER_COLUMNS,
            SHEET_ITENS_PEDIDOS: ORDER_ITEM_COLUMNS,
            SHEET_METRICAS_VENDAS: SALES_METRIC_COLUMNS,
            SHEET_BI_RESUMO_DIARIO: BI_SUMMARY_COLUMNS,
            SHEET_BI_CANAIS: BI_CHANNEL_COLUMNS,
            SHEET_BI_CONVERSAO: BI_CONVERSION_COLUMNS,
            SHEET_BI_VENDAS: BI_SALES_COLUMNS,
            SHEET_BI_ADS: BI_ADS_COLUMNS,
            SHEET_BI_PEDIDOS: BI_ORDERS_COLUMNS,
            SHEET_BI_STATUS: BI_STATUS_COLUMNS,
            SHEET_CONTROLE: CONTROL_COLUMNS,
            **LOOKER_SCHEMAS,
        }

    @classmethod
    def schema_fingerprint(cls) -> str:
        payload = json.dumps(
            cls._schema_map(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _control_value_from_values(
        values: list[list[str]],
        key: str,
    ) -> str:
        for row in values[1:]:
            if len(row) >= 2 and row[0] == key:
                return row[1]
        return ""

    def _assign_sheet_handles(self, sheets_by_title: dict[str, Any]) -> bool:
        required = {
            "base": SHEET_BASE_CONTATOS,
            "history": SHEET_HISTORICO,
            "metrics": SHEET_METRICAS,
            "events": SHEET_EVENTOS,
            "meta_campaigns": SHEET_CAMPANHAS_META,
            "orders": SHEET_PEDIDOS,
            "order_items": SHEET_ITENS_PEDIDOS,
            "sales_metrics": SHEET_METRICAS_VENDAS,
            "bi_summary": SHEET_BI_RESUMO_DIARIO,
            "bi_channels": SHEET_BI_CANAIS,
            "bi_conversion": SHEET_BI_CONVERSAO,
            "bi_sales": SHEET_BI_VENDAS,
            "bi_ads": SHEET_BI_ADS,
            "bi_orders": SHEET_BI_PEDIDOS,
            "bi_status": SHEET_BI_STATUS,
            "control": SHEET_CONTROLE,
        }
        required.update({"looker_" + title: title for title in LOOKER_SCHEMAS})
        if any(title not in sheets_by_title for title in required.values()):
            return False
        for attribute, title in required.items():
            setattr(self, attribute, sheets_by_title[title])
        return True

    def _initialize_structure(self, *, validate_structure: bool) -> None:
        # Uma listagem resolve os handles de todas as abas de uma vez.
        # Nas execuções normais, um fingerprint evita reler 9 cabeçalhos
        # e reenviar operações de formatação sem necessidade.
        worksheets = self._read_with_retry(
            "listar abas da planilha",
            self.book.worksheets,
        )
        storage_sheet = next(
            (ws for ws in worksheets if ws.title == STORAGE_SHEET), None
        )
        if storage_sheet is None:
            from runtime_profile import segment

            if segment() == "PET":
                raise ValueError(
                    "O Dashboard PET precisa do mapa NexoFlow_Arquivos antes da carga."
                )
        if storage_sheet is not None:
            values = self._read_with_retry(
                "ler configuração dos arquivos Google Sheets",
                lambda: storage_sheet.get("A1:B5"),
            )
            layout = SheetsStorage.from_values(values, self._hub_id)
            from runtime_profile import validate_sheet_destinations

            validate_sheet_destinations(
                layout.dashboard, layout.operations, layout.history
            )
            books = {layout.dashboard: self.book}
            for role, book_id in (
                ("operação", layout.operations),
                ("histórico", layout.history),
            ):
                books[book_id] = self._read_with_retry(
                    f"abrir arquivo de {role}",
                    lambda book_id=book_id: self.client.open_by_key(book_id),
                )
            self._storage_layout = layout
            self._storage_books = books
            worksheets = [
                ws
                for ws in worksheets
                if layout.destination(ws.title) == layout.dashboard
            ]
            for book_id in (layout.operations, layout.history):
                worksheets.extend(
                    ws
                    for ws in self._read_with_retry(
                        "listar abas do arquivo separado", books[book_id].worksheets
                    )
                    if layout.destination(ws.title) == book_id
                )
            logging.info(
                "Google Sheets: operação, histórico e dashboard em arquivos separados."
            )
        sheets_by_title = {ws.title: ws for ws in worksheets}
        if storage_sheet is not None:
            required_data = {
                SHEET_BASE_CONTATOS,
                SHEET_HISTORICO,
                SHEET_PEDIDOS,
                SHEET_ITENS_PEDIDOS,
                SHEET_CONTROLE,
            }
            missing = sorted(required_data - sheets_by_title.keys())
            if missing:
                raise RuntimeError(
                    "Arquivos separados sem as abas essenciais: "
                    + ", ".join(missing)
                    + ". Confira a migração; nenhuma estrutura vazia foi criada."
                )
        self._known_sheets = sheets_by_title
        expected = self.schema_fingerprint()
        stored = ""

        if self._assign_sheet_handles(sheets_by_title):
            control_values = self._read_with_retry(
                "ler aba Controle para validar fingerprint",
                self.control.get_all_values,
            )
            self._control_values_cache = [list(row) for row in control_values]
            stored = self._control_value_from_values(
                control_values,
                self.SCHEMA_CONTROL_KEY,
            )
            saved_layout = self._control_value_from_values(
                control_values, self.SCHEMA_HEADERS_CONTROL_KEY
            )
            try:
                layout = json.loads(saved_layout) if saved_layout else {}
                schema = self._schema_map()
                layout_valid = isinstance(layout, dict) and all(
                    isinstance(layout.get(title), list)
                    and all(isinstance(header, str) for header in layout[title])
                    and len(layout[title]) == len(set(layout[title]))
                    and set(headers).issubset(layout[title])
                    for title, headers in schema.items()
                )
            except (ValueError, TypeError):
                layout, layout_valid = {}, False
            if not validate_structure and stored == expected and layout_valid:
                # O fingerprint só é gravado após a estrutura ter sido validada.
                # Portanto, em execuções normais podemos reutilizar o schema local
                # sem reler cabeçalhos redundantes da API.
                # Migrações acrescentam colunas no fim da aba existente. A
                # ordem física validada pode diferir da declaração local.
                self._headers_cache = {
                    title: list(layout[title]) for title in self._schema_map()
                }
                logging.info(
                    "Google Sheets: estrutura compatível pelo fingerprint; "
                    "checagem completa de cabeçalhos ignorada."
                )
                return

        self.ensure_structure(existing_sheets=sheets_by_title)
        serialized_layout = json.dumps(
            self._headers_cache, ensure_ascii=False, sort_keys=True
        )
        if (
            stored != expected
            or self._control_value_from_values(
                self._control_values_cache or [], self.SCHEMA_HEADERS_CONTROL_KEY
            )
            != serialized_layout
        ):
            self.set_controls(
                {
                    self.SCHEMA_CONTROL_KEY: expected,
                    self.SCHEMA_HEADERS_CONTROL_KEY: serialized_layout,
                }
            )
        logging.info(
            "Google Sheets: estrutura completa validada (fingerprint=%s).",
            expected,
        )

    @staticmethod
    def now_iso() -> str:
        return datetime.now(UTC).isoformat(timespec="seconds")

    def _wait_before_write(self) -> None:
        """Mantém uma cadência segura entre requisições de escrita."""
        delay = max(0.0, float(GOOGLE_SHEETS_WRITE_DELAY_SECONDS))
        now = time.monotonic()

        if self._last_write_started_at > 0 and delay > 0:
            elapsed = now - self._last_write_started_at
            if elapsed < delay:
                time.sleep(delay - elapsed)

        self._last_write_started_at = time.monotonic()

    @staticmethod
    def _api_status_code(exc: APIError) -> int | None:
        response = getattr(exc, "response", None)
        return getattr(response, "status_code", None)

    @staticmethod
    def _retry_after_seconds(exc: APIError) -> float | None:
        response = getattr(exc, "response", None)
        headers = getattr(response, "headers", None)
        if not headers:
            return None

        value = headers.get("Retry-After")
        if not value:
            return None

        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _retryable_status(status: int | None) -> bool:
        return status == 429 or (status is not None and 500 <= status < 600)

    def _read_with_retry(self, description: str, func):
        """Executa leitura com retry de rede/autenticação, 429 e erros 5xx."""
        with request_progress("Google Sheets: " + description):
            attempts = max(1, int(GOOGLE_SHEETS_READ_MAX_RETRIES))

            for attempt in range(1, attempts + 1):
                attempt_started = time.monotonic()
                try:
                    self._read_requests = getattr(self, "_read_requests", 0) + 1
                    result = func()
                    elapsed = time.monotonic() - attempt_started
                    if attempt > 1:
                        logging.info(
                            "Google Sheets: leitura recuperada em %s na tentativa %s/%s "
                            "(%.1fs).",
                            description,
                            attempt,
                            attempts,
                            elapsed,
                        )
                    return result
                except APIError as exc:
                    elapsed = time.monotonic() - attempt_started
                    status = self._api_status_code(exc)
                    if not self._retryable_status(status) or attempt >= attempts:
                        raise

                    retry_after = self._retry_after_seconds(exc)
                    if status == 429:
                        wait = retry_after if retry_after is not None else 5.0
                    else:
                        wait = (
                            retry_after
                            if retry_after is not None
                            else min(
                                2**attempt,
                                30,
                            )
                        )

                    logging.warning(
                        "Google Sheets respondeu HTTP %s após %.1fs durante %s. "
                        "Tentativa %s/%s. Aguardando %.1f s.",
                        status,
                        elapsed,
                        description,
                        attempt,
                        attempts,
                        wait,
                    )
                    time.sleep(wait)
                except (RequestException, GoogleAuthTransportError) as exc:
                    elapsed = time.monotonic() - attempt_started
                    failure = classify_network_failure(exc)
                    if not failure.retryable or attempt >= attempts:
                        raise

                    refresh_network_route(
                        reason=f"falha recuperável no Google Sheets ({description})"
                    )
                    wait = min(2**attempt, 30)
                    logging.warning(
                        "Google Sheets teve falha de rede/timeout após %.1fs durante %s: %s. "
                        "Tentativa %s/%s. Aguardando %.1f s.",
                        elapsed,
                        description,
                        failure.summary,
                        attempt,
                        attempts,
                        wait,
                    )
                    time.sleep(wait)

            raise RuntimeError("Retry de leitura Google Sheets esgotado.")

    @staticmethod
    def _should_log_progress(processed: int, total: int) -> bool:
        if total <= 0 or processed <= 0:
            return False
        step = max(1, int(GOOGLE_SHEETS_PROGRESS_EVERY_RECORDS))
        return processed >= total or processed % step == 0

    @staticmethod
    def _progress_percent(processed: int, total: int) -> float:
        if total <= 0:
            return 100.0
        return min(100.0, (processed / total) * 100.0)

    @staticmethod
    def _payload_size_bytes(item: Any) -> int:
        return len(
            json.dumps(
                item,
                ensure_ascii=False,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        )

    @classmethod
    def _adaptive_batches(
        cls,
        items: list[Any],
        *,
        max_items: int,
        max_bytes: int | None = None,
    ) -> list[list[Any]]:
        if not items:
            return []
        item_limit = max(1, int(max_items))
        byte_limit = max(1024, int(max_bytes or GOOGLE_SHEETS_MAX_BATCH_PAYLOAD_BYTES))
        batches: list[list[Any]] = []
        current: list[Any] = []
        current_bytes = 2

        for item in items:
            item_bytes = cls._payload_size_bytes(item) + 1
            if current and (
                len(current) >= item_limit or current_bytes + item_bytes > byte_limit
            ):
                batches.append(current)
                current = []
                current_bytes = 2
            current.append(item)
            current_bytes += item_bytes

        if current:
            batches.append(current)
        return batches

    def request_stats(self) -> dict[str, int]:
        return {
            "reads": int(self._read_requests),
            "writes": int(self._write_requests),
            "total": int(self._read_requests + self._write_requests),
        }

    def _write_with_retry(self, description: str, func):
        """Executa escrita com retry de rede/autenticação, 429 e erros 5xx."""
        with request_progress("Google Sheets: " + description):
            attempts = max(1, int(GOOGLE_SHEETS_WRITE_MAX_RETRIES))

            for attempt in range(1, attempts + 1):
                self._wait_before_write()

                try:
                    self._write_requests = getattr(self, "_write_requests", 0) + 1
                    return func()
                except APIError as exc:
                    status = self._api_status_code(exc)
                    if not self._retryable_status(status) or attempt >= attempts:
                        raise

                    retry_after = self._retry_after_seconds(exc)

                    if status == 429:
                        wait = retry_after if retry_after is not None else 65.0
                    else:
                        wait = (
                            retry_after
                            if retry_after is not None
                            else min(
                                2**attempt,
                                30,
                            )
                        )

                    logging.warning(
                        "Google Sheets respondeu HTTP %s durante %s. "
                        "Tentativa %s/%s. Aguardando %.1f s.",
                        status,
                        description,
                        attempt,
                        attempts,
                        wait,
                    )
                    time.sleep(wait)
                except (RequestException, GoogleAuthTransportError) as exc:
                    failure = classify_network_failure(exc)
                    if not failure.retryable or attempt >= attempts:
                        raise

                    refresh_network_route(
                        reason=f"falha recuperável na escrita Google Sheets ({description})"
                    )
                    wait = min(2**attempt, 30)
                    logging.warning(
                        "Google Sheets teve falha de rede/timeout durante escrita %s: %s. "
                        "Tentativa %s/%s. Aguardando %.1f s.",
                        description,
                        failure.summary,
                        attempt,
                        attempts,
                        wait,
                    )
                    time.sleep(wait)

            raise RuntimeError("Retry de escrita Google Sheets esgotado.")

    def _read_header_bounded(
        self,
        ws: Worksheet,
        expected_headers: list[str],
        *,
        description: str | None = None,
    ) -> list[str]:
        """Lê somente a faixa de cabeçalho necessária, nunca a linha inteira A1:1."""
        expected_count = max(1, len(expected_headers))
        # Dá uma pequena margem para colunas legadas/manuais sem pedir a linha
        # inteira do Sheets, que pode resultar em uma leitura muito mais cara.
        sheet_cols = int(getattr(ws, "col_count", expected_count) or expected_count)
        read_count = max(expected_count, min(sheet_cols, expected_count + 64))
        last_col = column_letter(read_count)
        values = self._read_with_retry(
            description or f"ler cabeçalho de {ws.title}",
            lambda: ws.get(f"A1:{last_col}1"),
        )
        if not values:
            return []
        first_row = values[0] if isinstance(values[0], list) else values
        headers = [str(value) for value in first_row]
        while headers and headers[-1] == "":
            headers.pop()
        return headers

    def _book_for_title(self, title: str):
        layout = getattr(self, "_storage_layout", None)
        if layout is None:
            return self.book
        return self._storage_books[layout.destination(title)]

    def _get_or_create_sheet(
        self,
        title: str,
        headers: list[str],
        rows: int = 1000,
        *,
        existing_sheets: dict[str, Any] | None = None,
    ) -> Worksheet:
        ws = (existing_sheets or {}).get(title)
        created = False
        structure_changed = False

        if ws is None:
            try:
                ws = self._read_with_retry(
                    f"localizar aba {title}",
                    lambda title=title: self._book_for_title(title).worksheet(title),
                )
            except WorksheetNotFound:
                ws = self._write_with_retry(
                    f"criação da aba {title}",
                    lambda: self._book_for_title(title).add_worksheet(
                        title=title,
                        rows=rows,
                        cols=max(len(headers), 5),
                    ),
                )
                created = True

        current = self._read_header_bounded(
            ws,
            headers,
            description=f"ler cabeçalho limitado de {ws.title}",
        )

        if not current:
            last_col = column_letter(len(headers))
            self._write_with_retry(
                f"cabeçalho em {title}",
                lambda: ws.update(
                    range_name=f"A1:{last_col}1",
                    values=[headers],
                    value_input_option=ValueInputOption.raw,
                ),
            )
            structure_changed = True
        else:
            # Migração não destrutiva: mantém colunas antigas e acrescenta novas.
            missing = [header for header in headers if header not in current]
            if missing:
                new_headers = current + missing
                if ws.col_count < len(new_headers):
                    self._write_with_retry(
                        f"resize de colunas em {title}",
                        lambda: ws.resize(cols=len(new_headers)),
                    )
                last_col = column_letter(len(new_headers))
                self._write_with_retry(
                    f"migração de cabeçalho em {title}",
                    lambda: ws.update(
                        range_name=f"A1:{last_col}1",
                        values=[new_headers],
                        value_input_option=ValueInputOption.raw,
                    ),
                )
                structure_changed = True

        # Evita uma escrita de freeze em toda execução. Só formata quando
        # a aba é criada ou realmente teve a estrutura alterada.
        if created or structure_changed:
            self._write_with_retry(
                f"freeze do cabeçalho em {title}",
                lambda: ws.freeze(rows=1),
            )

        final_headers = (
            list(headers)
            if not current
            else (current + [h for h in headers if h not in current])
        )
        if not hasattr(self, "_headers_cache"):
            self._headers_cache = {}
        self._headers_cache[title] = final_headers
        return ws

    def ensure_structure(
        self,
        *,
        existing_sheets: dict[str, Any] | None = None,
    ) -> None:
        self.base = self._get_or_create_sheet(
            SHEET_BASE_CONTATOS, BASE_COLUMNS, existing_sheets=existing_sheets
        )
        self.history = self._get_or_create_sheet(
            SHEET_HISTORICO, HISTORY_COLUMNS, existing_sheets=existing_sheets
        )
        self.metrics = self._get_or_create_sheet(
            SHEET_METRICAS, METRIC_COLUMNS, existing_sheets=existing_sheets
        )
        self.events = self._get_or_create_sheet(
            SHEET_EVENTOS, EVENT_COLUMNS, existing_sheets=existing_sheets
        )
        self.meta_campaigns = self._get_or_create_sheet(
            SHEET_CAMPANHAS_META,
            META_CAMPAIGN_COLUMNS,
            existing_sheets=existing_sheets,
        )
        self.orders = self._get_or_create_sheet(
            SHEET_PEDIDOS, ORDER_COLUMNS, existing_sheets=existing_sheets
        )
        self.order_items = self._get_or_create_sheet(
            SHEET_ITENS_PEDIDOS,
            ORDER_ITEM_COLUMNS,
            existing_sheets=existing_sheets,
        )
        self.sales_metrics = self._get_or_create_sheet(
            SHEET_METRICAS_VENDAS,
            SALES_METRIC_COLUMNS,
            existing_sheets=existing_sheets,
        )
        self.bi_summary = self._get_or_create_sheet(
            SHEET_BI_RESUMO_DIARIO, BI_SUMMARY_COLUMNS, existing_sheets=existing_sheets
        )
        self.bi_channels = self._get_or_create_sheet(
            SHEET_BI_CANAIS, BI_CHANNEL_COLUMNS, existing_sheets=existing_sheets
        )
        self.bi_conversion = self._get_or_create_sheet(
            SHEET_BI_CONVERSAO, BI_CONVERSION_COLUMNS, existing_sheets=existing_sheets
        )
        self.bi_sales = self._get_or_create_sheet(
            SHEET_BI_VENDAS, BI_SALES_COLUMNS, existing_sheets=existing_sheets
        )
        self.bi_ads = self._get_or_create_sheet(
            SHEET_BI_ADS, BI_ADS_COLUMNS, existing_sheets=existing_sheets
        )
        self.bi_orders = self._get_or_create_sheet(
            SHEET_BI_PEDIDOS, BI_ORDERS_COLUMNS, existing_sheets=existing_sheets
        )
        self.bi_status = self._get_or_create_sheet(
            SHEET_BI_STATUS,
            BI_STATUS_COLUMNS,
            rows=100,
            existing_sheets=existing_sheets,
        )
        self.control = self._get_or_create_sheet(
            SHEET_CONTROLE,
            CONTROL_COLUMNS,
            rows=100,
            existing_sheets=existing_sheets,
        )

        for title, headers in LOOKER_SCHEMAS.items():
            setattr(
                self,
                "looker_" + title,
                self._get_or_create_sheet(
                    title,
                    headers,
                    existing_sheets=existing_sheets,
                ),
            )

    @staticmethod
    def _values_to_records(values: list[list[str]]) -> list[dict[str, str]]:
        if len(values) <= 1:
            return []
        headers = values[0]
        records = []
        for row in values[1:]:
            padded = row + [""] * (len(headers) - len(row))
            records.append(dict(zip(headers, padded, strict=False)))
        return records

    def load_base_snapshot(
        self,
    ) -> tuple[list[list[str]], list[dict[str, str]], set[str]]:
        started = time.monotonic()
        logging.info("Google Sheets: pré-carregando Base_Contatos completa...")
        values = self._read_with_retry(
            "ler Base_Contatos",
            self.base.get_all_values,
        )
        records = self._values_to_records(values)
        uuids = {
            str(row.get("contact_uuid") or "").strip()
            for row in records
            if str(row.get("contact_uuid") or "").strip()
        }
        logging.info(
            "Google Sheets: Base_Contatos pré-carregada: %s registro(s) em %.2fs.",
            len(records),
            time.monotonic() - started,
        )
        return values, records, uuids

    def load_base_records(self) -> list[dict[str, str]]:
        _, records, _ = self.load_base_snapshot()
        return records

    def load_base_uuids(self) -> set[str]:
        # Mantido para compatibilidade com CLI/testes antigos. O fluxo principal
        # usa load_base_snapshot para evitar uma segunda leitura da planilha.
        headers = getattr(self, "_headers_cache", {}).get(
            SHEET_BASE_CONTATOS,
            BASE_COLUMNS,
        )
        if "contact_uuid" not in headers:
            raise RuntimeError("A aba Base_Contatos não possui a coluna contact_uuid.")
        column = headers.index("contact_uuid") + 1
        values = self._read_with_retry(
            "ler UUIDs da Base_Contatos",
            lambda: self.base.col_values(column),
        )
        return {value.strip() for value in values[1:] if value.strip()}

    def load_order_records(self) -> list[dict[str, str]]:
        values = self._read_with_retry(
            "ler Pedidos_FarmaLider",
            self.orders.get_all_values,
        )
        return self._values_to_records(values)

    def load_order_item_records(self) -> list[dict[str, str]]:
        values = self._read_with_retry(
            "ler Itens_Pedidos_FarmaLider",
            self.order_items.get_all_values,
        )
        return self._values_to_records(values)

    def sales_metric_row_count(self) -> int:
        values = self._read_with_retry(
            "ler Metricas_Vendas",
            self.sales_metrics.get_all_values,
        )
        return max(0, len(values) - 1)

    @staticmethod
    def _record_changed(
        current_row: list[Any],
        merged_row: list[Any],
        headers: list[str],
        *,
        ignore_compare_fields: set[str] | None = None,
    ) -> bool:
        ignored = ignore_compare_fields or set()
        for index, header in enumerate(headers):
            if header in ignored:
                continue
            current = "" if current_row[index] is None else str(current_row[index])
            merged = "" if merged_row[index] is None else str(merged_row[index])
            if isinstance(merged_row[index], (int, float)) and not isinstance(
                merged_row[index], bool
            ):
                from analytics import _to_decimal

                try:
                    if _to_decimal(current, header) == _to_decimal(merged, header):
                        continue
                except ValueError:
                    pass
            if current != merged:
                return True
        return False

    @staticmethod
    def _validated_table_values(values, title):
        """Remove só padding vazio; dados sem cabeçalho exigem reparação."""
        if not values:
            return []
        headers = list(values[0])
        while headers and headers[-1] in ("", None):
            headers.pop()
        if not headers or any(not str(name).strip() for name in headers):
            raise RuntimeError(f"Google Sheets: cabeçalho inválido em {title}.")
        if len(set(headers)) != len(headers):
            raise RuntimeError(f"Google Sheets: cabeçalho duplicado em {title}.")
        width = len(headers)
        if any(
            any(cell not in ("", None) for cell in row[width:]) for row in values[1:]
        ):
            raise RuntimeError(
                f"Google Sheets: {title} contém dados fora das colunas do cabeçalho. "
                "A gravação foi bloqueada para evitar deslocamentos e duplicatas; "
                "repare a tabela antes de repetir a carga."
            )
        return [headers, *[list(row[:width]) for row in values[1:]]]

    def _append_keyed_batch(
        self, ws, batch, headers, key_name, value_input_option, *, start_row=None
    ):
        if not batch:
            return None
        key_index = headers.index(key_name)
        if start_row is None:
            values = self._validated_table_values(
                self._read_with_retry(
                    f"localizar novas linhas em {ws.title}", ws.get_all_values
                ),
                ws.title,
            )
            if values and values[0] != headers:
                raise RuntimeError("Schema mudou antes da escrita; reexecute a carga.")
            start_row = max(2, len(values) + 1)
        if start_row < 2:
            raise ValueError("Novos registros não podem sobrescrever o cabeçalho.")
        self._reserve_table_rows(ws, start_row + len(batch) - 1)
        cell_range = (
            f"A{start_row}:{column_letter(len(headers))}{start_row + len(batch) - 1}"
        )
        attempted = False

        def write():
            nonlocal attempted
            if attempted:
                values = self._validated_table_values(
                    self._read_with_retry(
                        f"confirmar inserções em {ws.title}", ws.get_all_values
                    ),
                    ws.title,
                )
                if not values or values[0] != headers:
                    raise RuntimeError(
                        "Schema mudou durante a confirmação de escrita; reexecute a carga."
                    )
                for position, row in enumerate(batch, start=start_row - 1):
                    current = values[position] if position < len(values) else []
                    if len(current) > key_index and str(current[key_index]) not in (
                        "",
                        str(row[key_index]),
                    ):
                        raise RuntimeError(
                            "Destino das novas linhas mudou; interrompido para preservar outros registros."
                        )
            attempted = True
            # values.append chooses its own logical table and can start to the
            # right when empty columns split old rows. Fixed coordinates are
            # deterministic, fit the reserved grid, and are safe after timeout.
            return ws.update(
                range_name=cell_range,
                values=copy.deepcopy(batch),
                value_input_option=value_input_option,
            )

        return self._write_with_retry(f"gravar novas linhas em {ws.title}", write)

    def _append_history_batch(self, batch, *, start_row=None):
        if not batch:
            return None
        if start_row is None:
            values = self._read_with_retry(
                "localizar novas linhas do histórico", self.history.get_all_values
            )
            start_row = max(2, len(values) + 1)
        self._reserve_table_rows(self.history, start_row + len(batch) - 1)
        width = max(map(len, batch))
        cell_range = f"A{start_row}:{column_letter(width)}{start_row + len(batch) - 1}"
        return self._write_with_retry(
            "gravar novas linhas em Historico_Alteracoes",
            lambda: self.history.update(
                range_name=cell_range,
                values=copy.deepcopy(batch),
                value_input_option=ValueInputOption.raw,
            ),
        )

    def _reserve_table_rows(self, ws, required_rows: int) -> None:
        """Reserve only the rows needed, before changing existing records."""
        current_rows = ws.row_count
        if required_rows <= current_rows:
            return
        logging.info(
            "Google Sheets: %s - reservando exatamente %s linha(s) adicionais.",
            ws.title,
            required_rows - current_rows,
        )
        try:
            self._write_with_retry(
                f"reservar linhas em {ws.title}",
                lambda: ws.resize(rows=required_rows),
            )
        except APIError as exc:
            if "number of cells" in str(exc).lower():
                raise RuntimeError(
                    f"Google Sheets: capacidade insuficiente para ampliar {ws.title}. "
                    "Nenhuma gravação desta tabela foi iniciada. Libere células vazias "
                    "ou arquive o histórico antes de retomar; os dados existentes foram preservados."
                ) from exc
            raise

    def _upsert_records_detailed(
        self,
        ws,
        records: list[dict[str, Any]],
        key_name: str,
        *,
        existing_values: list[list[str]] | None = None,
        ignore_compare_fields: set[str] | None = None,
        value_input_option: str = "RAW",
        preserve_types: bool = False,
    ) -> UpsertResult:
        # Consolida a carga antes de agendar writes: duas entradas da mesma
        # chave não podem atualizar uma linha futura ainda aguardando append.
        # Campos posteriores prevalecem, como nas atualizações sequenciais.
        unique_records: dict[str, dict[str, str]] = {}
        for record in records:
            key = str(record.get(key_name) or "").strip()
            if key:
                unique_records[key] = {**unique_records.get(key, {}), **record}
        if len(unique_records) < len(records):
            logging.info(
                "Google Sheets: %s - entradas consolidadas por chave (%s → %s).",
                ws.title,
                len(records),
                len(unique_records),
            )
        records = list(unique_records.values())
        if existing_values is None:
            logging.info(
                "Google Sheets: %s - lendo base atual para comparar %s registro(s)...",
                ws.title,
                len(records),
            )
            read_started = time.monotonic()
            values = self._read_with_retry(
                f"ler {ws.title} para upsert",
                ws.get_all_values,
            )
            logging.info(
                "Google Sheets: %s - leitura concluída: %s linha(s) em %.2fs.",
                ws.title,
                max(0, len(values) - 1),
                time.monotonic() - read_started,
            )
        else:
            values = [list(row) for row in existing_values]
            logging.info(
                "Google Sheets: %s - reutilizando snapshot em memória (%s linha(s)); nova leitura dispensada.",
                ws.title,
                max(0, len(values) - 1),
            )

        if not values:
            headers = list(getattr(self, "_headers_cache", {}).get(ws.title, []))
            values = [headers]
        else:
            headers = list(values[0])
        if key_name not in headers:
            raise RuntimeError(f"A aba {ws.title} não possui a chave {key_name!r}.")

        values = self._validated_table_values(values, ws.title)
        headers = list(values[0])
        stage_started = time.monotonic()
        key_col = headers.index(key_name)
        existing: dict[str, tuple[int, list[str]]] = {}
        final_rows: list[list[str]] = []

        for row_number, row in enumerate(values[1:], start=2):
            padded = [str(value) if value is not None else "" for value in row] + [
                ""
            ] * (len(headers) - len(row))
            padded = padded[: len(headers)]
            final_rows.append(padded)
            key = padded[key_col].strip()
            if key:
                existing[key] = (row_number, padded)

        updates: list[dict[str, Any]] = []
        appends: list[list[Any]] = []
        changed_records: list[dict[str, str]] = []
        inserted = 0
        updated = 0
        unchanged = 0
        last_col = column_letter(len(headers))

        for record in records:
            key = str(record.get(key_name, "")).strip()
            if not key:
                continue

            if key in existing:
                row_number, current_row = existing[key]
                merged = current_row[:]
                for index, header in enumerate(headers):
                    if header in record:
                        value = record.get(header, "")
                        merged[index] = (
                            ""
                            if value is None
                            else (value if preserve_types else str(value))
                        )
                if not self._record_changed(
                    current_row,
                    merged,
                    headers,
                    ignore_compare_fields=ignore_compare_fields,
                ):
                    unchanged += 1
                    continue
                updates.append(
                    {
                        "range": f"A{row_number}:{last_col}{row_number}",
                        "values": [merged],
                    }
                )
                final_rows[row_number - 2] = merged
                changed_records.append(dict(zip(headers, merged, strict=False)))
                updated += 1
            else:
                appended = [
                    ""
                    if record.get(header, "") is None
                    else (
                        record.get(header, "")
                        if preserve_types
                        else str(record.get(header, ""))
                    )
                    for header in headers
                ]
                appends.append(appended)
                final_rows.append(appended)
                existing[key] = (len(final_rows) + 1, appended)
                changed_records.append(dict(zip(headers, appended, strict=False)))
                inserted += 1

        if appends:
            self._reserve_table_rows(ws, len(values) + len(appends))

        update_batches = self._adaptive_batches(
            updates,
            max_items=GOOGLE_SHEETS_UPDATE_BATCH_SIZE,
        )
        append_batches = self._adaptive_batches(
            appends,
            max_items=GOOGLE_SHEETS_APPEND_BATCH_SIZE,
        )
        logging.info(
            "Google Sheets: %s - plano pronto: atualizações=%s | inserções=%s | sem mudança=%s | lotes=%s+%s.",
            ws.title,
            len(updates),
            len(appends),
            unchanged,
            len(update_batches),
            len(append_batches),
        )

        with TaskProgress(
            f"Google Sheets: {ws.title} - gravação confirmada",
            len(updates) + len(appends),
            unit="linhas",
        ) as progress:
            if update_batches:
                logging.info(
                    "Google Sheets: %s - enviando %s atualização(ões) em batches adaptativos (até %.1f MB).",
                    ws.title,
                    len(updates),
                    GOOGLE_SHEETS_MAX_BATCH_PAYLOAD_BYTES / 1_000_000,
                )
            for batch in update_batches:
                self._write_with_retry(
                    f"batch_update em {ws.title}",
                    lambda batch=batch: ws.batch_update(
                        copy.deepcopy(batch),
                        value_input_option=value_input_option,
                    ),
                )
                progress.advance(len(batch))

            if append_batches:
                logging.info(
                    "Google Sheets: %s - enviando %s nova(s) linha(s) em batches adaptativos.",
                    ws.title,
                    len(appends),
                )
            next_row = len(values) + 1
            for batch in append_batches:
                self._append_keyed_batch(
                    ws, batch, headers, key_name, value_input_option, start_row=next_row
                )
                next_row += len(batch)
                progress.advance(len(batch))

        logging.info(
            "Google Sheets: %s concluída em %.2fs | inseridos=%s | atualizados=%s | sem mudança=%s.",
            ws.title,
            time.monotonic() - stage_started,
            inserted,
            updated,
            unchanged,
        )
        return UpsertResult(
            inserted=inserted,
            updated=updated,
            unchanged=unchanged,
            changed_records=changed_records,
            final_records=[dict(zip(headers, row, strict=False)) for row in final_rows],
        )

    def upsert_contacts_detailed(
        self,
        contacts: list[dict[str, str]],
        *,
        existing_values: list[list[str]] | None = None,
    ) -> UpsertResult:
        return self._upsert_records_detailed(
            self.base,
            [
                sanitize_contact_order(normalize_geography(record))
                for record in contacts
            ],
            "contact_uuid",
            existing_values=existing_values,
            ignore_compare_fields={
                "sincronizado_em",
                "farmalider_cliente_consultado_em",
            },
        )

    def upsert_contacts(
        self,
        contacts: list[dict[str, str]],
    ) -> tuple[int, int]:
        result = self.upsert_contacts_detailed(contacts)
        return result.inserted, result.updated

    def upsert_orders_detailed(
        self,
        orders: list[dict[str, str]],
        *,
        items: list[dict[str, str]] | None = None,
    ) -> UpsertResult:
        if items is not None:
            orders = plan_pharmacy_scope(orders, items).orders
        else:
            orders = [
                filtered
                for record in orders
                if (filtered := sanitize_order_record(record)) is not None
            ]
        return self._upsert_records_detailed(
            self.orders,
            orders,
            "pedido_chave",
            ignore_compare_fields={"capturado_em", "farmalider_confirmado_em"},
        )

    def upsert_orders(
        self,
        orders: list[dict[str, str]],
    ) -> tuple[int, int]:
        result = self.upsert_orders_detailed(orders)
        return result.inserted, result.updated

    def upsert_order_items_detailed(
        self,
        items: list[dict[str, str]],
    ) -> UpsertResult:
        # A carga de itens contém o snapshot completo de cada pedido resolvido.
        # Uma correção da API pode reduzir a lista; um upsert sozinho deixaria
        # posições antigas somando unidades e valores nos indicadores.
        active_keys: dict[str, set[str]] = {}
        for item in items:
            order_key = str(item.get("pedido_chave") or "").strip()
            item_key = str(item.get("item_chave") or "").strip()
            if not order_key or not item_key:
                raise ValueError("Snapshot de itens sem identidade do pedido ou item.")
            active_keys.setdefault(order_key, set()).add(item_key)
        items = pharmacy_items(items)
        retained_keys: dict[str, set[str]] = {}
        for item in items:
            order_key = str(item.get("pedido_chave") or "").strip()
            retained_keys.setdefault(order_key, set()).add(str(item["item_chave"]))
        for key in active_keys:
            active_keys[key] = retained_keys.get(key, set())
        result = self._upsert_records_detailed(
            self.order_items,
            items,
            "item_chave",
            ignore_compare_fields={"capturado_em"},
        )
        stale_indexes = [
            index
            for index, record in enumerate(result.final_records)
            if record.get("pedido_chave") in active_keys
            and record.get("item_chave") not in active_keys[record["pedido_chave"]]
        ]
        if stale_indexes:
            headers = getattr(self, "_headers_cache", {}).get(
                self.order_items.title, ORDER_ITEM_COLUMNS
            )
            last_col = column_letter(len(headers))
            ranges = [f"A{index + 2}:{last_col}{index + 2}" for index in stale_indexes]
            # Limpar valores de linhas específicas é idempotente e não desloca
            # os demais pedidos, inclusive quando há retry da requisição.
            for start in range(0, len(ranges), 100):
                batch = ranges[start : start + 100]
                self._write_with_retry(
                    "reconciliar itens removidos dos pedidos atualizados",
                    lambda batch=batch: self.order_items.batch_clear(batch),
                )
            stale = set(stale_indexes)
            result.final_records = [
                record
                for index, record in enumerate(result.final_records)
                if index not in stale
            ]
            result.removed = len(stale_indexes)
            logging.info(
                "Google Sheets: %s item(ns) antigos removidos dos pedidos atualizados.",
                result.removed,
            )
        return result

    def upsert_order_items(
        self,
        items: list[dict[str, str]],
    ) -> tuple[int, int]:
        result = self.upsert_order_items_detailed(items)
        return result.inserted, result.updated

    def append_history(
        self,
        contacts: list[dict[str, str]],
        existing_uuids_before_sync: set[str],
    ) -> None:
        if not contacts:
            return

        stage_started = time.monotonic()
        logging.info(
            "Google Sheets: Historico_Alteracoes - preparando %s registro(s).",
            len(contacts),
        )
        headers = getattr(self, "_headers_cache", {}).get(
            SHEET_HISTORICO,
            HISTORY_COLUMNS,
        )
        logging.info(
            "Google Sheets: Historico_Alteracoes - usando schema já validado "
            "(%s colunas); leitura redundante de cabeçalho dispensada.",
            len(headers),
        )
        logging.info("Google Sheets: Historico_Alteracoes - montando linhas...")
        sync_time = self.now_iso()
        rows = []

        for contact in contacts:
            contact = sanitize_contact_order(normalize_geography(contact))
            uuid = contact.get("contact_uuid", "")
            action = "Atualizado" if uuid in existing_uuids_before_sync else "Inserido"
            record = {
                "acao": action,
                "sincronizado_em": sync_time,
            }
            record.update(contact)
            rows.append([record.get(header, "") for header in headers])

        batches = self._adaptive_batches(
            rows,
            max_items=GOOGLE_SHEETS_APPEND_BATCH_SIZE,
        )
        logging.info(
            "Google Sheets: Historico_Alteracoes - enviando %s linha(s) em %s batch(es) adaptativo(s).",
            len(rows),
            len(batches),
        )
        first_column = self._read_with_retry(
            "localizar fim do histórico", lambda: self.history.col_values(1)
        )
        next_row = max(2, len(first_column) + 1)
        self._reserve_table_rows(self.history, next_row + len(rows) - 1)
        with TaskProgress(
            "Google Sheets: Historico_Alteracoes - gravação confirmada",
            len(rows),
            unit="linhas",
        ) as progress:
            for batch in progress.track(batches, weight=len):
                self._append_history_batch(batch, start_row=next_row)
                next_row += len(batch)
        logging.info(
            "Google Sheets: Historico_Alteracoes concluída em %.2fs.",
            time.monotonic() - stage_started,
        )

    @staticmethod
    def _normalize_table(values: list[list[Any]]) -> list[list[str]]:
        normalized: list[list[str]] = []
        for row in values:
            cells = ["" if value is None else str(value) for value in row]
            while cells and cells[-1] == "":
                cells.pop()
            normalized.append(cells)
        while normalized and not normalized[-1]:
            normalized.pop()
        return normalized

    def _replace_table(
        self,
        ws,
        headers: list[str],
        rows: list[list[Any]],
        *,
        value_input_option: str = "RAW",
        force: bool = False,
    ) -> bool:
        data = [headers] + rows
        current = self._read_with_retry(
            f"ler {ws.title} antes de substituir tabela",
            ws.get_all_values,
        )
        if not force and self._normalize_table(current) == self._normalize_table(data):
            logging.info(
                "Google Sheets: %s sem alterações; escrita ignorada.",
                ws.title,
            )
            return False

        with TaskProgress(
            f"Google Sheets: {ws.title} - gravação confirmada", len(data), unit="linhas"
        ) as progress:
            last_col = column_letter(len(headers))
            last_row = max(len(data), 1)
            if ws.row_count < last_row or ws.col_count < len(headers):
                self._write_with_retry(
                    f"resize em {ws.title}",
                    lambda: ws.resize(
                        rows=max(ws.row_count, last_row),
                        cols=max(ws.col_count, len(headers)),
                    ),
                )
            offset = 1
            batches = self._adaptive_batches(
                data, max_items=GOOGLE_SHEETS_APPEND_BATCH_SIZE
            )
            for batch in batches:
                first, last = offset, offset + len(batch) - 1
                self._write_with_retry(
                    f"update em {ws.title}",
                    lambda batch=batch, first=first, last=last: ws.update(
                        range_name=f"A{first}:{last_col}{last}",
                        values=batch,
                        value_input_option=value_input_option,
                    ),
                )
                progress.advance(len(batch))
                offset = last + 1
            # Gravar antes de limpar: uma falha inicial não deve apagar a tabela
            # anterior. Limpar só o excedente após todos os lotes concluírem.
            obsolete = []
            if len(current) > len(data):
                obsolete.append(
                    f"A{len(data) + 1}:{column_letter(ws.col_count)}{len(current)}"
                )
            old_width = max((len(row) for row in current), default=0)
            if old_width > len(headers):
                obsolete.append(
                    f"{column_letter(len(headers) + 1)}1:{column_letter(old_width)}{len(data)}"
                )
            if obsolete:
                self._write_with_retry(
                    f"limpar excedente em {ws.title}", lambda: ws.batch_clear(obsolete)
                )
        return True

    def replace_metrics(self, rows: list[list[Any]]) -> None:
        self._replace_table(self.metrics, METRIC_COLUMNS, rows)

    def replace_sales_metrics(self, rows: list[list[Any]]) -> None:
        self._replace_table(self.sales_metrics, SALES_METRIC_COLUMNS, rows)

    @staticmethod
    def _typed_bi_rows(headers: list[str], rows: list[list[Any]]) -> list[list[Any]]:
        from datetime import date

        typed = []
        for row in rows:
            values = []
            for header, value in zip(headers, row, strict=True):
                if isinstance(value, float) and not math.isfinite(value):
                    raise ValueError("Medida BI não finita; gravação interrompida.")
                if header in DATE_COLUMNS | {"data_snapshot"} and value not in (
                    "",
                    None,
                ):
                    value = (date.fromisoformat(str(value)) - date(1899, 12, 30)).days
                values.append("" if value is None else value)
            typed.append(values)
        return typed

    def _format_bi_columns(
        self, ws, headers: list[str], *, text_columns: set[str]
    ) -> None:
        formats = []
        for index, header in enumerate(headers, 1):
            if header in text_columns:
                continue
            letter = column_letter(index)
            formats.append(
                {
                    "range": f"{letter}2:{letter}{max(2, ws.row_count)}",
                    "format": {
                        "numberFormat": {
                            "type": "DATE"
                            if header in DATE_COLUMNS | {"data_snapshot"}
                            else "NUMBER",
                            "pattern": "yyyy-mm-dd"
                            if header in DATE_COLUMNS | {"data_snapshot"}
                            else "0.########",
                        }
                    },
                }
            )
        if formats:
            self._write_with_retry(
                f"tipos numéricos em {ws.title}", lambda: ws.batch_format(formats)
            )

    def migrate_bi_summary_numbers(self) -> None:
        from analytics import _to_decimal

        # Migração única: recuperar os valores monetários visíveis que o Sheets
        # interpretou como yyyy.mm; preservar as linhas históricas da base.
        revision = "_bi_numeric_revision"
        if self.get_control(revision) != "2":
            old = self._read_with_retry(
                "migrar números de BI_Resumo_Diario", self.bi_summary.get_all_values
            )
            headers = list(old[0]) if old else BI_SUMMARY_COLUMNS[:]
            rows = []
            for previous in self._values_to_records(old):
                if not previous.get("data"):
                    continue
                converted = []
                for header in headers:
                    value = previous.get(header, "")
                    if (
                        header in set(BI_SUMMARY_COLUMNS) - {"data", "atualizado_em"}
                        and value != ""
                    ):
                        value = float(_to_decimal(value, header))
                    converted.append(value)
                rows.append(converted)
            self._replace_summary_atomically(
                headers, self._typed_bi_rows(headers, rows)
            )
            self._headers_cache[self.bi_summary.title] = headers[:]
            self.set_controls({revision: "2"})

    def _replace_summary_atomically(self, headers, rows):
        # Valores e formatos mudam na mesma transação. Se a migração falhar,
        # uma retomada não pode interpretar números novos com formatos antigos.
        ws = self.bi_summary
        data = [headers, *rows]
        requests = []
        if ws.row_count < len(data) or ws.col_count < len(headers):
            requests.append(
                {
                    "updateSheetProperties": {
                        "properties": {
                            "sheetId": ws.id,
                            "gridProperties": {
                                "rowCount": max(ws.row_count, len(data)),
                                "columnCount": max(ws.col_count, len(headers)),
                            },
                        },
                        "fields": "gridProperties.rowCount,gridProperties.columnCount",
                    }
                }
            )
        requests.append(
            {
                "updateCells": {
                    "range": {
                        "sheetId": ws.id,
                        "startRowIndex": 0,
                        "endRowIndex": max(ws.row_count, len(data)),
                        "startColumnIndex": 0,
                        "endColumnIndex": len(headers),
                    },
                    "rows": [
                        {
                            "values": [
                                {
                                    "userEnteredValue": {
                                        "numberValue"
                                        if isinstance(value, (int, float))
                                        else "stringValue": value
                                    }
                                }
                                for value in row
                            ]
                        }
                        for row in data
                    ],
                    "fields": "userEnteredValue",
                }
            }
        )
        for index, header in enumerate(headers):
            if header not in BI_SUMMARY_COLUMNS or header == "atualizado_em":
                continue
            is_date = header in DATE_COLUMNS
            requests.append(
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": ws.id,
                            "startRowIndex": 1,
                            "endRowIndex": max(ws.row_count, len(data)),
                            "startColumnIndex": index,
                            "endColumnIndex": index + 1,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "numberFormat": {
                                    "type": "DATE" if is_date else "NUMBER",
                                    "pattern": "yyyy-mm-dd"
                                    if is_date
                                    else "0.########",
                                }
                            }
                        },
                        "fields": "userEnteredFormat.numberFormat",
                    }
                }
            )
        self._write_with_retry(
            "migração financeira atômica em BI_Resumo_Diario",
            lambda: self.book.batch_update(copy.deepcopy({"requests": requests})),
        )

    def upsert_bi_summary(self, record: dict[str, Any]) -> UpsertResult:
        self.migrate_bi_summary_numbers()
        return self._upsert_records_detailed(
            self.bi_summary,
            [record],
            "data",
            ignore_compare_fields={"atualizado_em"},
            preserve_types=True,
            value_input_option="USER_ENTERED",
        )

    def replace_looker_tables(self, tables: dict[str, list[list[Any]]]) -> None:
        if set(tables) != set(LOOKER_SCHEMAS):
            raise ValueError("Conjunto de tabelas comerciais BI incompleto.")
        prepared = {
            title: self._typed_bi_rows(headers, tables[title])
            for title, headers in LOOKER_SCHEMAS.items()
        }
        for title, headers in LOOKER_SCHEMAS.items():
            ws = getattr(self, "looker_" + title)
            values = prepared[title]
            self._replace_table(ws, headers, values, force=True)
            self._format_bi_columns(ws, headers, text_columns=TEXT_COLUMNS)
            logging.info(
                "Google Sheets: %s atualizada (%s registro(s)).", title, len(values)
            )

    def upsert_bi_channels(self, records: list[dict[str, Any]]) -> UpsertResult:
        return self._upsert_records_detailed(
            self.bi_channels,
            records,
            "chave",
            ignore_compare_fields={"atualizado_em"},
            preserve_types=True,
            value_input_option="USER_ENTERED",
        )

    def upsert_bi_conversion(self, records: list[dict[str, Any]]) -> UpsertResult:
        return self._upsert_records_detailed(
            self.bi_conversion,
            records,
            "chave",
            ignore_compare_fields={"atualizado_em"},
            preserve_types=True,
            value_input_option="USER_ENTERED",
        )

    def _replace_typed_bi(self, ws, headers, rows, *, text_columns):
        values = self._typed_bi_rows(headers, rows)
        self._replace_table(ws, headers, values, force=True)
        self._format_bi_columns(ws, headers, text_columns=text_columns)

    def replace_bi_sales(self, rows: list[list[Any]]) -> None:
        self._replace_typed_bi(
            self.bi_sales, BI_SALES_COLUMNS, rows, text_columns={"atualizado_em"}
        )

    def replace_bi_ads(self, rows: list[list[Any]]) -> None:
        self._replace_typed_bi(
            self.bi_ads,
            BI_ADS_COLUMNS,
            rows,
            text_columns=set(BI_ADS_COLUMNS[1:7]) | {"atualizado_em"},
        )

    def replace_bi_orders(self, rows: list[list[Any]]) -> None:
        numeric = {
            "pedido_valor",
            "pedido_frete",
            "pedido_faturamento_total",
            "idade",
            "venda_valida",
        }
        self._replace_typed_bi(
            self.bi_orders,
            BI_ORDERS_COLUMNS,
            rows,
            text_columns=set(BI_ORDERS_COLUMNS) - numeric - {"data"},
        )

    def replace_bi_status(self, row: list[Any]) -> None:
        self._replace_typed_bi(
            self.bi_status,
            BI_STATUS_COLUMNS,
            [row],
            text_columns=set(BI_STATUS_COLUMNS[:4]),
        )

    def upsert_delivery_tickets(self, records: list[dict[str, Any]]) -> UpsertResult:
        # Optional source: existing installations do not create these tabs until the Delivery command runs.
        from delivery_tickets import TICKET_COLUMNS

        ws = self._get_or_create_sheet("Tickets_Delivery_Weni", TICKET_COLUMNS)
        return self._upsert_records_detailed(
            ws,
            [
                sanitize_delivery_ticket(
                    record,
                    excluded_keys=getattr(self, "_pharmacy_excluded_keys", set()),
                    retained_by_key=getattr(self, "_pharmacy_orders_by_key", {}),
                )
                for record in records
            ],
            "ticket_uuid",
            ignore_compare_fields={"atualizado_em"},
            value_input_option=ValueInputOption.raw,
        )

    def refresh_delivery_bi(
        self, orders: list[dict[str, str]] | None = None, *, create: bool = True
    ) -> None:
        from delivery_tickets import (
            DELIVERY_ORDER_COLUMNS,
            TICKET_COLUMNS,
            build_delivery_order_records,
        )

        known = getattr(self, "_known_sheets", {})
        if not create and not all(
            title in known for title in ("Tickets_Delivery_Weni", "BI_Delivery_Pedidos")
        ):
            return
        tickets_ws = self._get_or_create_sheet(
            "Tickets_Delivery_Weni", TICKET_COLUMNS, existing_sheets=known
        )
        tickets = self._values_to_records(
            self._read_with_retry("ler tickets Delivery", tickets_ws.get_all_values)
        )
        records = build_delivery_order_records(
            tickets,
            self.load_order_records() if orders is None else orders,
            updated_at=self.now_iso(),
        )
        ws = self._get_or_create_sheet(
            "BI_Delivery_Pedidos", DELIVERY_ORDER_COLUMNS, existing_sheets=known
        )
        # A numeric sale flag and order value become numeric cells; ISO dates remain stable for Data Studio parsing.
        rows = [
            [record.get(column, "") for column in DELIVERY_ORDER_COLUMNS]
            for record in records
        ]
        self._replace_table(
            ws, DELIVERY_ORDER_COLUMNS, rows, value_input_option="USER_ENTERED"
        )

    def get_control(self, key: str) -> str:
        values = self._control_values_cache
        if values is None:
            values = self._read_with_retry(
                "ler aba Controle",
                self.control.get_all_values,
            )
            self._control_values_cache = [list(row) for row in values]
        for row in values[1:]:
            if len(row) >= 2 and row[0] == key:
                return row[1]
        return ""

    def set_controls(self, mapping: dict[str, str]) -> None:
        values = self._control_values_cache
        if values is None:
            values = self._read_with_retry(
                "ler aba Controle",
                self.control.get_all_values,
            )
            values = [list(row) for row in values]
            self._control_values_cache = values
        index: dict[str, int] = {}

        for row_number, row in enumerate(values[1:], start=2):
            if row:
                index[row[0]] = row_number

        updates: list[dict[str, Any]] = []
        appends: list[list[str]] = []
        now = self.now_iso()

        for key, value in mapping.items():
            row = [key, value, now]
            if key in index:
                updates.append(
                    {
                        "range": f"A{index[key]}:C{index[key]}",
                        "values": [row],
                    }
                )
            else:
                appends.append(row)

        if updates:
            self._write_with_retry(
                "batch_update em Controle",
                lambda updates=updates: self.control.batch_update(
                    copy.deepcopy(updates),
                    value_input_option=ValueInputOption.raw,
                ),
            )

        if appends:
            self._append_keyed_batch(
                self.control,
                appends,
                CONTROL_COLUMNS,
                "chave",
                ValueInputOption.raw,
                start_row=len(values) + 1,
            )

        # Atualiza o cache local sem nova leitura da API.
        cached = [list(row) for row in values]
        cached_index = {row[0]: idx for idx, row in enumerate(cached) if row}
        for key, value in mapping.items():
            row = [key, value, now]
            if key in cached_index:
                cached[cached_index[key]] = row
            else:
                cached.append(row)
        self._control_values_cache = cached

    def append_event(self, row: list[Any]) -> None:
        self._append_keyed_batch(
            self.events, [row], EVENT_COLUMNS, "event_id", ValueInputOption.raw
        )

    def existing_event_ids(self) -> set[str]:
        values = self._read_with_retry(
            "ler IDs de Eventos_Anuncios",
            lambda: self.events.col_values(1),
        )
        return set(values[1:]) if len(values) > 1 else set()

    def _clear_scope_records(
        self, ws, records: list[dict[str, Any]], key_name: str, keys: set[str]
    ) -> None:
        if not keys:
            return
        headers = getattr(self, "_headers_cache", {}).get(ws.title)
        if headers is None:
            values = self._read_with_retry(
                f"ler cabeçalho de {ws.title} para limpeza", ws.get_all_values
            )
            headers = list(values[0]) if values else []
        if not headers:
            raise ValueError(f"Cabeçalho ausente em {ws.title} para limpeza segura.")
        last_col = column_letter(len(headers))
        ranges = [
            f"A{index + 2}:{last_col}{index + 2}"
            for index, record in enumerate(records)
            if str(record.get(key_name) or "") in keys
        ]
        with TaskProgress(
            f"Google Sheets: {ws.title} - exclusão de itens pet confirmada",
            len(ranges),
            unit="linhas",
        ) as progress:
            for start in range(0, len(ranges), 100):
                batch = ranges[start : start + 100]
                self._write_with_retry(
                    f"limpar registros fora do escopo da farmácia em {ws.title}",
                    lambda batch=batch: ws.batch_clear(batch),
                )
                progress.advance(len(batch))

    def _sanitize_scope_rows(
        self, ws, sanitizer, *, values=None, value_input_option=ValueInputOption.raw
    ) -> int:
        """Atualiza somente linhas alteradas, preservando posições e colunas."""
        if values is None:
            values = self._read_with_retry(
                f"ler {ws.title} para saneamento da farmácia", ws.get_all_values
            )
        if not values:
            return 0
        headers = list(values[0])
        last_col = column_letter(len(headers))
        updates = []
        with TaskProgress(
            f"Google Sheets: {ws.title} - análise de produtos",
            len(values) - 1,
            unit="registros",
        ) as preparation:
            for index, cells in enumerate(preparation.track(values[1:]), start=2):
                padded = list(cells[: len(headers)]) + [""] * max(
                    0, len(headers) - len(cells)
                )
                current = dict(zip(headers, padded, strict=True))
                updated = sanitizer(current)
                row = [updated.get(header, "") for header in headers]
                if row != padded:
                    updates.append(
                        {"range": f"A{index}:{last_col}{index}", "values": [row]}
                    )
        batches = self._adaptive_batches(
            updates, max_items=GOOGLE_SHEETS_UPDATE_BATCH_SIZE
        )
        with TaskProgress(
            f"Google Sheets: {ws.title} - saneamento confirmado",
            len(updates),
            unit="linhas",
        ) as progress:
            for batch in batches:
                self._write_with_retry(
                    f"sanear recorte da farmácia em {ws.title}",
                    lambda batch=batch: ws.batch_update(
                        copy.deepcopy(batch), value_input_option=value_input_option
                    ),
                )
                progress.advance(len(batch))
        return len(updates)

    def resanitize_pharmacy_bi_snapshots(
        self,
        contacts: list[dict[str, Any]],
        orders: list[dict[str, Any]],
        items: list[dict[str, Any]],
    ) -> dict[str, int]:
        """Corrige snapshots antigos de vendas preservando dados de contatos."""
        summary_values = self._read_with_retry(
            "ler snapshots de resumo para recorte da farmácia",
            self.bi_summary.get_all_values,
        )
        conversion_values = self._read_with_retry(
            "ler snapshots de conversão para recorte da farmácia",
            self.bi_conversion.get_all_values,
        )
        summaries, conversions = recalculate_scope_snapshots(
            self._values_to_records(summary_values),
            self._values_to_records(conversion_values),
            contacts,
            orders,
            items,
        )
        summary_iterator = iter(summaries)
        conversion_iterator = iter(conversions)
        return {
            "resumos_saneados": self._sanitize_scope_rows(
                self.bi_summary,
                lambda _: next(summary_iterator),
                values=summary_values,
                value_input_option=ValueInputOption.user_entered,
            ),
            "conversoes_saneadas": self._sanitize_scope_rows(
                self.bi_conversion,
                lambda _: next(conversion_iterator),
                values=conversion_values,
                value_input_option=ValueInputOption.user_entered,
            ),
        }

    def reconcile_pharmacy_scope(
        self,
        *,
        base_records: list[dict[str, Any]] | None = None,
        order_records: list[dict[str, Any]] | None = None,
        item_records: list[dict[str, Any]] | None = None,
        include_history: bool = True,
    ) -> PharmacyScopePlan:
        """Limpa fontes do Sheets; o chamador recalcula todas as tabelas de BI.

        O plano é inteiramente calculado antes da primeira escrita. Limpezas
        são idempotentes, não deslocam linhas nem removem contatos.
        """
        orders = self.load_order_records() if order_records is None else order_records
        items = self.load_order_item_records() if item_records is None else item_records
        contacts = self.load_base_records() if base_records is None else base_records
        plan = plan_pharmacy_scope(orders, items, contacts)
        # Corrigir totais antes de limpar os itens evita recalcular uma venda
        # mista usando o total antigo na próxima execução após interrupção.
        if plan.changed_orders:
            self._upsert_records_detailed(
                self.orders,
                plan.changed_orders,
                "pedido_chave",
                ignore_compare_fields={"capturado_em", "farmalider_confirmado_em"},
            )
        self._clear_scope_records(
            self.orders, orders, "pedido_chave", plan.removed_order_keys
        )
        self._clear_scope_records(
            self.order_items, items, "item_chave", plan.removed_item_keys
        )
        if plan.changed_contacts:
            self.upsert_contacts_detailed(plan.changed_contacts)
        if include_history:
            plan.history_changed = self._sanitize_scope_rows(
                self.history, sanitize_contact_order
            )
        known = getattr(self, "_known_sheets", {})
        if "Tickets_Delivery_Weni" in known:
            changed_by_key = {
                str(order.get("pedido_chave") or ""): order
                for order in plan.changed_orders
            }

            def sanitize_ticket(record):
                key = str(record.get("pedido_chave") or "")
                result = dict(record)
                if key in plan.removed_order_keys:
                    result["resultado_validacao"] = "FORA_ESCOPO_FARMACIA"
                    result["vinculo_atendimento"] = "FORA_ESCOPO_FARMACIA"
                    for field in (
                        "pedido_chave",
                        "pedido_id",
                        "pedido_data",
                        "pedido_status",
                        "pedido_valor",
                    ):
                        result[field] = ""
                elif key in changed_by_key:
                    result["pedido_valor"] = changed_by_key[key]["valor_total_compra"]
                return result

            plan.tickets_changed = self._sanitize_scope_rows(
                known["Tickets_Delivery_Weni"], sanitize_ticket
            )
        logging.info("Google Sheets: recorte da farmácia concluído: %s.", plan.counts())
        return plan

    def upsert_pharmacy_orders(
        self, orders: list[dict[str, Any]], items: list[dict[str, Any]]
    ) -> tuple[UpsertResult, UpsertResult]:
        """Grava um snapshot pareado, filtrando antes de enviar ao Google."""
        by_order: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            by_order.setdefault(str(item.get("pedido_chave") or ""), []).append(item)
        retained_orders = []
        retained_items = []
        excluded_keys: set[str] = set()
        for order in orders:
            key = str(order.get("pedido_chave") or "")
            filtered, human_items = filter_pharmacy_order(order, by_order.get(key, []))
            if filtered is None:
                excluded_keys.add(key)
                continue
            retained_orders.append(filtered)
            retained_items.extend(human_items)
        if excluded_keys:
            old_orders = self.load_order_records()
            old_items = self.load_order_item_records()
            self._clear_scope_records(
                self.orders, old_orders, "pedido_chave", excluded_keys
            )
            self._clear_scope_records(
                self.order_items,
                old_items,
                "item_chave",
                {
                    str(item.get("item_chave") or "")
                    for item in old_items
                    if str(item.get("pedido_chave") or "") in excluded_keys
                },
            )
        order_result = self.upsert_orders_detailed(retained_orders)
        item_result = self.upsert_order_items_detailed(retained_items)
        if item_result.removed:
            # O upsert remove registros obsoletos de seu resultado em memória.
            # Reconciliações posteriores usam índices físicos; linhas limpas
            # continuam na aba e precisam permanecer no snapshot recebido.
            item_result.final_records = self.load_order_item_records()
        self._pharmacy_excluded_keys = (
            getattr(self, "_pharmacy_excluded_keys", set()) | excluded_keys
        ) - {str(order.get("pedido_chave") or "") for order in retained_orders}
        by_key = getattr(self, "_pharmacy_orders_by_key", {}).copy()
        by_key.update(
            {str(order.get("pedido_chave") or ""): order for order in retained_orders}
        )
        for key in self._pharmacy_excluded_keys:
            by_key.pop(key, None)
        self._pharmacy_orders_by_key = by_key
        return order_result, item_result


# NexoFlow 1.5.3
