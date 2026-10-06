from __future__ import annotations

from dataclasses import dataclass
import copy
from datetime import datetime, timezone
import hashlib
import json
import logging
import time
from typing import TYPE_CHECKING, Any

import gspread

if TYPE_CHECKING:
    from gspread.worksheet import Worksheet
from gspread.exceptions import APIError, SpreadsheetNotFound, WorksheetNotFound
from requests.exceptions import RequestException

from analytics import (
    BASE_COLUMNS,
    BI_ADS_COLUMNS,
    BI_CHANNEL_COLUMNS,
    BI_CONVERSION_COLUMNS,
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
        if not GOOGLE_CREDENTIALS_FILE.exists():
            raise FileNotFoundError(
                f"Credencial Google não encontrada: {GOOGLE_CREDENTIALS_FILE}"
            )

        self.client = gspread.service_account(
            filename=str(GOOGLE_CREDENTIALS_FILE)
        )
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
        self._initialize_structure(validate_structure=validate_structure)

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
            SHEET_BI_STATUS: BI_STATUS_COLUMNS,
            SHEET_CONTROLE: CONTROL_COLUMNS,
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
            "bi_status": SHEET_BI_STATUS,
            "control": SHEET_CONTROLE,
        }
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
        sheets_by_title = {ws.title: ws for ws in worksheets}
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
            saved_layout = self._control_value_from_values(control_values, self.SCHEMA_HEADERS_CONTROL_KEY)
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
                self._headers_cache = {title: list(layout[title]) for title in self._schema_map()}
                logging.info(
                    "Google Sheets: estrutura compatível pelo fingerprint; "
                    "checagem completa de cabeçalhos ignorada."
                )
                return

        self.ensure_structure(existing_sheets=sheets_by_title)
        serialized_layout = json.dumps(self._headers_cache, ensure_ascii=False, sort_keys=True)
        if stored != expected or self._control_value_from_values(self._control_values_cache or [], self.SCHEMA_HEADERS_CONTROL_KEY) != serialized_layout:
            self.set_controls({self.SCHEMA_CONTROL_KEY: expected, self.SCHEMA_HEADERS_CONTROL_KEY: serialized_layout})
        logging.info(
            "Google Sheets: estrutura completa validada "
            "(fingerprint=%s).",
            expected,
        )

    @staticmethod
    def now_iso() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

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
        return status == 429 or (
            status is not None and 500 <= status < 600
        )

    def _read_with_retry(self, description: str, func):
        """Executa leitura com timeout/retry para rede, 429 e erros 5xx."""
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
                    wait = retry_after if retry_after is not None else min(
                        2 ** attempt,
                        30,
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
            except RequestException as exc:
                elapsed = time.monotonic() - attempt_started
                if attempt >= attempts:
                    raise

                wait = min(2 ** attempt, 30)
                logging.warning(
                    "Google Sheets teve falha de rede/timeout após %.1fs durante %s: %s. "
                    "Tentativa %s/%s. Aguardando %.1f s.",
                    elapsed,
                    description,
                    exc.__class__.__name__,
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
                len(current) >= item_limit
                or current_bytes + item_bytes > byte_limit
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
        """Executa escrita com retry para 429 e erros 5xx."""
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
                    wait = retry_after if retry_after is not None else min(
                        2 ** attempt,
                        30,
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
            except RequestException as exc:
                if attempt >= attempts:
                    raise

                wait = min(2 ** attempt, 30)
                logging.warning(
                    "Google Sheets teve falha de rede/timeout durante escrita %s: %s. "
                    "Tentativa %s/%s. Aguardando %.1f s.",
                    description,
                    exc.__class__.__name__,
                    attempt,
                    attempts,
                    wait,
                )
                time.sleep(wait)

        raise RuntimeError("Retry de escrita Google Sheets esgotado.")

    def _read_header_bounded(
        self,
        ws: "Worksheet",
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

    def _get_or_create_sheet(
        self,
        title: str,
        headers: list[str],
        rows: int = 1000,
        *,
        existing_sheets: dict[str, Any] | None = None,
    ) -> "Worksheet":
        ws = (existing_sheets or {}).get(title)
        created = False
        structure_changed = False

        if ws is None:
            try:
                ws = self._read_with_retry(
                    f"localizar aba {title}",
                    lambda title=title: self.book.worksheet(title),
                )
            except WorksheetNotFound:
                ws = self._write_with_retry(
                    f"criação da aba {title}",
                    lambda: self.book.add_worksheet(
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
                    value_input_option="RAW",
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
                        value_input_option="RAW",
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
        self.bi_status = self._get_or_create_sheet(
            SHEET_BI_STATUS, BI_STATUS_COLUMNS, rows=100, existing_sheets=existing_sheets
        )
        self.control = self._get_or_create_sheet(
            SHEET_CONTROLE,
            CONTROL_COLUMNS,
            rows=100,
            existing_sheets=existing_sheets,
        )

    @staticmethod
    def _values_to_records(values: list[list[str]]) -> list[dict[str, str]]:
        if len(values) <= 1:
            return []
        headers = values[0]
        records = []
        for row in values[1:]:
            padded = row + [""] * (len(headers) - len(row))
            records.append(dict(zip(headers, padded)))
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
            raise RuntimeError(
                "A aba Base_Contatos não possui a coluna contact_uuid."
            )
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
            if current != merged:
                return True
        return False

    def _upsert_records_detailed(
        self,
        ws,
        records: list[dict[str, Any]],
        key_name: str,
        *,
        existing_values: list[list[str]] | None = None,
        ignore_compare_fields: set[str] | None = None,
        value_input_option: str = "RAW",
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
            logging.info("Google Sheets: %s - entradas consolidadas por chave (%s → %s).", ws.title, len(records), len(unique_records))
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
            raise RuntimeError(
                f"A aba {ws.title} não possui a chave {key_name!r}."
            )

        stage_started = time.monotonic()
        key_col = headers.index(key_name)
        existing: dict[str, tuple[int, list[str]]] = {}
        final_rows: list[list[str]] = []

        for row_number, row in enumerate(values[1:], start=2):
            padded = [str(value) if value is not None else "" for value in row] + [""] * (len(headers) - len(row))
            padded = padded[:len(headers)]
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
                        merged[index] = "" if value is None else str(value)
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
                changed_records.append(dict(zip(headers, merged)))
                updated += 1
            else:
                appended = [
                    "" if record.get(header, "") is None else str(record.get(header, ""))
                    for header in headers
                ]
                appends.append(appended)
                final_rows.append(appended)
                existing[key] = (len(final_rows) + 1, appended)
                changed_records.append(dict(zip(headers, appended)))
                inserted += 1

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

        processed = 0
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
            processed += len(batch)
            if self._should_log_progress(processed, len(updates)):
                logging.info(
                    "Google Sheets: %s - atualizações %s/%s (%.0f%%).",
                    ws.title,
                    processed,
                    len(updates),
                    self._progress_percent(processed, len(updates)),
                )

        processed = 0
        if append_batches:
            logging.info(
                "Google Sheets: %s - enviando %s nova(s) linha(s) em batches adaptativos.",
                ws.title,
                len(appends),
            )
        for batch in append_batches:
            self._write_with_retry(
                f"append_rows em {ws.title}",
                lambda batch=batch: ws.append_rows(
                    batch,
                    value_input_option=value_input_option,
                ),
            )
            processed += len(batch)
            if self._should_log_progress(processed, len(appends)):
                logging.info(
                    "Google Sheets: %s - inserções %s/%s (%.0f%%).",
                    ws.title,
                    processed,
                    len(appends),
                    self._progress_percent(processed, len(appends)),
                )

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
            final_records=[dict(zip(headers, row)) for row in final_rows],
        )

    def upsert_contacts_detailed(
        self,
        contacts: list[dict[str, str]],
        *,
        existing_values: list[list[str]] | None = None,
    ) -> UpsertResult:
        return self._upsert_records_detailed(
            self.base,
            contacts,
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
    ) -> UpsertResult:
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
        result = self._upsert_records_detailed(
            self.order_items,
            items,
            "item_chave",
            ignore_compare_fields={"capturado_em"},
        )
        stale_indexes = [
            index for index, record in enumerate(result.final_records)
            if record.get("pedido_chave") in active_keys
            and record.get("item_chave") not in active_keys[record["pedido_chave"]]
        ]
        if stale_indexes:
            headers = getattr(self, "_headers_cache", {}).get(self.order_items.title, ORDER_ITEM_COLUMNS)
            last_col = column_letter(len(headers))
            ranges = [f"A{index + 2}:{last_col}{index + 2}" for index in stale_indexes]
            # Limpar valores de linhas específicas é idempotente e não desloca
            # os demais pedidos, inclusive quando há retry da requisição.
            for start in range(0, len(ranges), 100):
                batch = ranges[start:start + 100]
                self._write_with_retry(
                    "reconciliar itens removidos dos pedidos atualizados",
                    lambda batch=batch: self.order_items.batch_clear(batch),
                )
            stale = set(stale_indexes)
            result.final_records = [record for index, record in enumerate(result.final_records) if index not in stale]
            result.removed = len(stale_indexes)
            logging.info("Google Sheets: %s item(ns) antigos removidos dos pedidos atualizados.", result.removed)
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
        logging.info(
            "Google Sheets: Historico_Alteracoes - montando linhas..."
        )
        sync_time = self.now_iso()
        rows = []

        for contact in contacts:
            uuid = contact.get("contact_uuid", "")
            action = (
                "Atualizado"
                if uuid in existing_uuids_before_sync
                else "Inserido"
            )
            record = {
                "acao": action,
                "sincronizado_em": sync_time,
            }
            record.update(contact)
            rows.append(
                [record.get(header, "") for header in headers]
            )

        batches = self._adaptive_batches(
            rows,
            max_items=GOOGLE_SHEETS_APPEND_BATCH_SIZE,
        )
        logging.info(
            "Google Sheets: Historico_Alteracoes - enviando %s linha(s) em %s batch(es) adaptativo(s).",
            len(rows),
            len(batches),
        )
        processed = 0
        for batch in batches:
            self._write_with_retry(
                "append_rows em Historico_Alteracoes",
                lambda batch=batch: self.history.append_rows(
                    batch,
                    value_input_option="RAW",
                ),
            )
            processed += len(batch)
            if self._should_log_progress(processed, len(rows)):
                logging.info(
                    "Google Sheets: Historico_Alteracoes - %s/%s linhas (%.0f%%).",
                    processed,
                    len(rows),
                    self._progress_percent(processed, len(rows)),
                )
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
    ) -> bool:
        data = [headers] + rows
        current = self._read_with_retry(
            f"ler {ws.title} antes de substituir tabela",
            ws.get_all_values,
        )
        if self._normalize_table(current) == self._normalize_table(data):
            logging.info(
                "Google Sheets: %s sem alterações; escrita ignorada.",
                ws.title,
            )
            return False

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
        self._write_with_retry(
            f"clear em {ws.title}",
            ws.clear,
        )
        self._write_with_retry(
            f"update em {ws.title}",
            lambda: ws.update(
                range_name=f"A1:{last_col}{last_row}",
                values=data,
                value_input_option=value_input_option,
            ),
        )
        return True

    def replace_metrics(self, rows: list[list[Any]]) -> None:
        self._replace_table(self.metrics, METRIC_COLUMNS, rows)

    def replace_sales_metrics(self, rows: list[list[Any]]) -> None:
        self._replace_table(
            self.sales_metrics, SALES_METRIC_COLUMNS, rows
        )

    def upsert_bi_summary(self, record: dict[str, Any]) -> UpsertResult:
        return self._upsert_records_detailed(
            self.bi_summary,
            [record],
            "data",
            ignore_compare_fields={"atualizado_em"},
            value_input_option="USER_ENTERED",
        )

    def upsert_bi_channels(self, records: list[dict[str, Any]]) -> UpsertResult:
        return self._upsert_records_detailed(
            self.bi_channels,
            records,
            "chave",
            ignore_compare_fields={"atualizado_em"},
            value_input_option="USER_ENTERED",
        )

    def upsert_bi_conversion(self, records: list[dict[str, Any]]) -> UpsertResult:
        return self._upsert_records_detailed(
            self.bi_conversion,
            records,
            "chave",
            ignore_compare_fields={"atualizado_em"},
            value_input_option="USER_ENTERED",
        )

    def replace_bi_sales(self, rows: list[list[Any]]) -> None:
        self._replace_table(
            self.bi_sales, BI_SALES_COLUMNS, rows, value_input_option="USER_ENTERED"
        )

    def replace_bi_ads(self, rows: list[list[Any]]) -> None:
        self._replace_table(
            self.bi_ads, BI_ADS_COLUMNS, rows, value_input_option="USER_ENTERED"
        )

    def replace_bi_status(self, row: list[Any]) -> None:
        self._replace_table(
            self.bi_status, BI_STATUS_COLUMNS, [row], value_input_option="USER_ENTERED"
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
                    value_input_option="RAW",
                ),
            )

        if appends:
            self._write_with_retry(
                "append_rows em Controle",
                lambda: self.control.append_rows(
                    appends,
                    value_input_option="RAW",
                ),
            )

        # Atualiza o cache local sem nova leitura da API.
        cached = [list(row) for row in values]
        cached_index = {
            row[0]: idx for idx, row in enumerate(cached)
            if row
        }
        for key, value in mapping.items():
            row = [key, value, now]
            if key in cached_index:
                cached[cached_index[key]] = row
            else:
                cached.append(row)
        self._control_values_cache = cached

    def append_event(self, row: list[Any]) -> None:
        self._write_with_retry(
            "append_row em Eventos_Anuncios",
            lambda: self.events.append_row(
                row,
                value_input_option="RAW",
            ),
        )

    def existing_event_ids(self) -> set[str]:
        values = self._read_with_retry(
            "ler IDs de Eventos_Anuncios",
            lambda: self.events.col_values(1),
        )
        return set(values[1:]) if len(values) > 1 else set()
# NexoFlow 1.0
