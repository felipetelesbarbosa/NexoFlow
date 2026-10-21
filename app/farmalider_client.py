from __future__ import annotations

import hashlib
import hmac
import json
import logging
import math
import re
import secrets
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Any, cast
from urllib.parse import urlsplit

import requests

from config import (
    FARMALIDER_5XX_COOLDOWN_SECONDS,
    FARMALIDER_429_COOLDOWN_SECONDS,
    FARMALIDER_CIRCUIT_MIN_5XX,
    FARMALIDER_CIRCUIT_MIN_DISTINCT_QUERIES,
    FARMALIDER_MAX_ADAPTIVE_DELAY_SECONDS,
    FARMALIDER_MAX_RETRIES,
    FARMALIDER_MAX_WORKERS,
    FARMALIDER_RECOVERY_MAX_DELAY_SECONDS,
    FARMALIDER_RECOVERY_PARALLEL_SUCCESSES,
    FARMALIDER_RECOVERY_SERIAL_SUCCESSES,
    FARMALIDER_REQUEST_DELAY_SECONDS,
    FARMALIDER_REQUEST_TIMEOUT_SECONDS,
    FARMALIDER_SLOW_REQUEST_SECONDS,
    farmalider_api_base_url,
)
from network_diagnostics import classify_network_failure
from private_diagnostics import append_private_failure


class FarmaliderError(RuntimeError):
    """Erro base da integração FarmaLíder."""


class FarmaliderBadRequestError(FarmaliderError):
    """Consulta rejeitada com HTTP 400, sem retry nem inferência de inexistência."""


class FarmaliderAuthError(FarmaliderError):
    """Token ausente, inválido ou sem permissão."""


class FarmaliderUnavailableError(FarmaliderError):
    """Circuito aberto após falhas persistentes em várias consultas da rota."""


@dataclass(frozen=True)
class RequestPermit:
    generation: int
    concurrency: int
    active_requests: int = 1


class FarmaliderClient:
    """
    Cliente da API FarmaLíder usando autenticação via QueryString.

    O cliente pode ser compartilhado entre várias threads. Cada thread recebe
    sua própria requests.Session, enquanto o limitador de ritmo e o cooldown de
    HTTP 429 são compartilhados globalmente entre todas elas.
    """

    def __init__(self, token: str, use_hml: bool = False) -> None:
        self.token = str(token or "").strip()
        self.use_hml = bool(use_hml)

        if not self.token:
            raise ValueError("Token da FarmaLíder API não informado.")

        self.base_url = farmalider_api_base_url().rstrip("/")
        # Identificadores de diagnóstico não permitem reconstruir CPFs por
        # enumeração e são estáveis apenas durante esta execução.
        self._diagnostic_key = secrets.token_bytes(32)
        self._diagnostic_execution_id = secrets.token_hex(8)
        self._private_diagnostic_lock = threading.Lock()
        self._private_recorded_refs: set[str] = set()

        self.customer_directory = None
        self._directory_attempted = False
        self._directory_lock = threading.Lock()
        self._execution_cache = None
        self._directory_hits = 0
        self._thread_local = threading.local()
        self._sessions: list[requests.Session] = []
        self._sessions_lock = threading.Lock()

        self._rate_lock = threading.Lock()
        self._request_gate = threading.Condition(self._rate_lock)
        self._in_flight = 0
        self._closed = False
        self._cancelled = False
        self._normal_concurrency = max(1, int(FARMALIDER_MAX_WORKERS))
        self._concurrency_limit = self._normal_concurrency
        self._recovery_generation = 0
        self._healthy_streak = 0
        self._delay_healthy_streak = 0
        self._recovery_activations = 0
        self._route_failures: dict[str, tuple[int, set[str]]] = {}
        self._open_circuits: set[str] = set()
        self._server_error_refs: set[str] = set()
        self._serial_error_refs: set[str] = set()
        self._last_request_started_at = 0.0
        self._cooldown_until = 0.0
        self._effective_delay_seconds = max(
            0.0,
            float(FARMALIDER_REQUEST_DELAY_SECONDS),
        )

        self._metrics_lock = threading.Lock()
        self._total_requests = 0
        self._total_retries = 0
        self._rate_limit_responses = 0
        self._server_error_responses = 0
        self._network_errors = 0
        self._total_response_seconds = 0.0
        self._max_response_seconds = 0.0
        self._slow_requests = 0
        self._response_times_seconds: list[float] = []
        self._status_counts: dict[int, int] = {}

    def _new_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": "GrupoLider-NexoFlow/1.0",
            }
        )
        # Segurança: estes endpoints não usam Authorization/Bearer.
        session.headers.pop("Authorization", None)
        return session

    def _get_session(self) -> requests.Session:
        session = getattr(self._thread_local, "session", None)
        if session is not None:
            return session

        session = self._new_session()
        self._thread_local.session = session
        with self._sessions_lock:
            self._sessions.append(session)
        return session

    @property
    def session(self) -> requests.Session:
        """Sessão da thread atual, mantida por compatibilidade/testes."""
        return self._get_session()

    def _sync_base_url_from_environment(self) -> bool:
        """Sincroniza a URL FarmaLíder caso outra integração tenha trocado a rota."""
        new_base_url = farmalider_api_base_url().rstrip("/")
        if new_base_url == self.base_url:
            return False
        previous_base_url = self.base_url
        self.base_url = new_base_url
        logging.warning(
            "FarmaLíder: mudança de rota detectada por outra etapa da carga; "
            "URL operacional atualizada de %s para %s.",
            "proxy" if ":3200" not in previous_base_url else "direta",
            "proxy" if ":3200" not in new_base_url else "direta",
        )
        return True

    def _refresh_network_route(self, *, reason: str) -> bool:
        """Redetecta direta/proxy e atualiza a URL FarmaLíder sem reiniciar a carga."""
        from proxy_config import refresh_network_route

        previous_base_url = self.base_url
        result = refresh_network_route(reason=reason)
        self._sync_base_url_from_environment()
        changed = result.changed or self.base_url != previous_base_url
        if changed:
            logging.warning(
                "FarmaLíder: rota atualizada durante a execução; retomando na %s.",
                "rota com proxy" if result.current_active else "rota direta",
            )
        return changed

    def _request_route(self, path: str) -> tuple[str, dict[str, str]]:
        from proxy_config import snapshot_request_route

        def current_url() -> str:
            self._sync_base_url_from_environment()
            # Não reutilize o atributo compartilhado para escolher o destino:
            # outro worker pode sincronizá-lo durante uma redetecção.
            return f"{farmalider_api_base_url().rstrip('/')}{path}"

        return snapshot_request_route(current_url)

    @staticmethod
    def _route_summary(url: str, proxies: dict[str, str]) -> str:
        destination = urlsplit(url)
        port = destination.port or (443 if destination.scheme == "https" else 80)
        route = "proxy" if proxies.get("https") or proxies.get("all") else "direta"
        # Somente autoridade pública, sem caminho/CPF/token ou URL do proxy.
        return f"Destino={destination.hostname}:{port}; rota={route}."

    def close(self) -> None:
        with self._request_gate:
            if self._closed:
                return
            self._closed = True
            self._request_gate.notify_all()
            while self._in_flight:
                self._request_gate.wait()
        metrics = self.metrics_snapshot()
        if self._directory_attempted or self._execution_cache is not None:
            logging.info(
                "FarmaLíder: reaproveitamento nesta execução | cadastros locais=%s | leituras HTTP evitadas=%s | cadastros FARMA=%s.",
                metrics["customer_directory_hits"],
                metrics["execution_read_cache_hits"],
                metrics["customer_directory_records"],
            )
        if metrics["total_requests"]:
            logging.info(
                "FarmaLíder diagnóstico final: HTTP=%s; 200=%s; 404=%s; 5xx=%s; "
                "consultas distintas com 5xx=%s; consultas com 5xx em modo serial=%s; "
                "recuperações=%s; circuitos abertos=%s.",
                metrics["total_requests"],
                metrics["responses_200"],
                metrics["responses_404"],
                metrics["server_errors"],
                metrics["server_error_unique_queries"],
                metrics["server_error_serial_queries"],
                metrics["recovery_activations"],
                metrics["open_circuits"],
            )
        if self._execution_cache is not None:
            self._execution_cache.close()
            self._execution_cache = None
        self.customer_directory = None
        with self._sessions_lock:
            sessions = list(self._sessions)
            self._sessions.clear()

        for session in sessions:
            session.close()

    def cancel_pending_requests(self) -> None:
        """Stop admissions without waiting for HTTP calls already in flight."""
        with self._request_gate:
            self._cancelled = True
            self._request_gate.notify_all()

    def _delivery_path(self, path: str) -> str:
        prefix = "/api/Delivery/hml" if self.use_hml else "/api/Delivery"
        return f"{prefix}/{path.lstrip('/')}"

    def _wait_before_request(self, endpoint_label: str) -> RequestPermit:
        """Reserve a slot only when both global pacing and concurrency permit it."""
        while True:
            with self._request_gate:
                if self._closed or self._cancelled:
                    raise FarmaliderUnavailableError(
                        "FarmaLíder: cliente encerrado; consulta cancelada."
                    )
                if endpoint_label in self._open_circuits:
                    raise FarmaliderUnavailableError(
                        f"FarmaLíder: circuito aberto na rota {endpoint_label}; "
                        "carga interrompida para evitar novas consultas sem resposta válida."
                    )
                if self._in_flight >= self._concurrency_limit:
                    self._request_gate.wait()
                    continue
                delay = self._effective_delay_seconds
                now = time.monotonic()
                next_by_rate = (
                    self._last_request_started_at + delay
                    if self._last_request_started_at > 0
                    else now
                )
                allowed_at = max(next_by_rate, self._cooldown_until)
                wait = allowed_at - now

                if wait <= 0:
                    self._last_request_started_at = now
                    self._in_flight += 1
                    return RequestPermit(
                        self._recovery_generation,
                        self._concurrency_limit,
                        self._in_flight,
                    )
                self._request_gate.wait(timeout=wait)

    @contextmanager
    def _request_slot(self, endpoint_label: str):
        permit = self._wait_before_request(endpoint_label)
        try:
            yield permit
        finally:
            with self._request_gate:
                self._in_flight -= 1
                self._request_gate.notify_all()

    def _retry_delay(
        self,
        attempt: int,
        response: requests.Response | None = None,
    ) -> float:
        status = response.status_code if response is not None else None
        server_delay = (
            self._retry_after_seconds(response) if response is not None else 0
        )
        base = (
            float(FARMALIDER_5XX_COOLDOWN_SECONDS)
            if status is not None and status >= 500
            else float(FARMALIDER_429_COOLDOWN_SECONDS)
            if status == 429
            else 1.0
        )
        return max(server_delay or 0.0, min(base * 2 ** (attempt - 1), 20.0))

    def _protect_after_failure(
        self,
        *,
        endpoint_label: str,
        diagnostic_ref: str,
        permit: RequestPermit,
        delay: float,
        status_code: int | None,
    ) -> None:
        """Apply protection before releasing the failed HTTP request's slot."""
        with self._request_gate:
            previous_limit = self._concurrency_limit
            self._concurrency_limit = 1
            self._recovery_generation += 1
            self._healthy_streak = self._delay_healthy_streak = 0
            self._cooldown_until = max(self._cooldown_until, time.monotonic() + delay)
            base = max(0.0, float(FARMALIDER_REQUEST_DELAY_SECONDS))
            maximum = max(base, float(FARMALIDER_RECOVERY_MAX_DELAY_SECONDS))
            if status_code == 429:
                maximum = max(
                    base,
                    self._effective_delay_seconds,
                    float(FARMALIDER_MAX_ADAPTIVE_DELAY_SECONDS),
                )
            self._effective_delay_seconds = min(
                maximum,
                max(base, 0.1, self._effective_delay_seconds * 2),
            )
            if previous_limit > 1:
                self._recovery_activations += 1
            if status_code is not None and status_code >= 500:
                self._server_error_refs.add(f"{endpoint_label}:{diagnostic_ref}")
                if permit.concurrency == 1:
                    self._serial_error_refs.add(f"{endpoint_label}:{diagnostic_ref}")
                count, refs = self._route_failures.setdefault(
                    endpoint_label, (0, set())
                )
                refs.add(diagnostic_ref)
                self._route_failures[endpoint_label] = (count + 1, refs)
                if (
                    count + 1 >= FARMALIDER_CIRCUIT_MIN_5XX
                    and len(refs) >= FARMALIDER_CIRCUIT_MIN_DISTINCT_QUERIES
                ):
                    self._open_circuits.add(endpoint_label)
            opened = endpoint_label in self._open_circuits
            effective_delay = self._effective_delay_seconds
            self._request_gate.notify_all()
        if previous_limit > 1:
            logging.warning(
                "FarmaLíder %s: recuperação serial ativada após HTTP %s; "
                "requisições anteriores em voo concluirão antes de novas admissões.",
                endpoint_label,
                status_code if status_code is not None else "rede",
            )
        logging.warning(
            "FarmaLíder %s [consulta %s]: pausa global %.1fs; "
            "limite=1; intervalo=%.0fms%s.",
            endpoint_label,
            diagnostic_ref,
            delay,
            effective_delay * 1000,
            "; circuito aberto por falhas persistentes em várias consultas"
            if opened
            else "",
        )

    def _mark_healthy(self, permit: RequestPermit, endpoint_label: str) -> None:
        with self._request_gate:
            # Any valid response shows the route is responsive. Generation only
            # controls whether that response can expand concurrency again.
            self._route_failures.pop(endpoint_label, None)
            # Successes already in flight before a failure cannot unlock workers.
            if permit.generation != self._recovery_generation:
                return
            self._healthy_streak += 1
            self._delay_healthy_streak += 1
            previous_limit = self._concurrency_limit
            required = (
                FARMALIDER_RECOVERY_SERIAL_SUCCESSES
                if previous_limit == 1
                else FARMALIDER_RECOVERY_PARALLEL_SUCCESSES
            )
            if (
                previous_limit < self._normal_concurrency
                and self._healthy_streak >= required
            ):
                self._concurrency_limit = min(
                    self._normal_concurrency, previous_limit * 2
                )
                self._healthy_streak = 0
            if self._delay_healthy_streak >= FARMALIDER_RECOVERY_SERIAL_SUCCESSES:
                self._effective_delay_seconds = max(
                    float(FARMALIDER_REQUEST_DELAY_SECONDS),
                    self._effective_delay_seconds / 2,
                )
                self._delay_healthy_streak = 0
            new_limit = self._concurrency_limit
            self._request_gate.notify_all()
        if new_limit != previous_limit:
            logging.info(
                "FarmaLíder: recuperação gradual; limite simultâneo %s → %s "
                "após %s respostas saudáveis da geração atual.",
                previous_limit,
                new_limit,
                required,
            )

    def _mark_unhealthy(self) -> None:
        with self._request_gate:
            self._healthy_streak = self._delay_healthy_streak = 0

    @staticmethod
    def _retry_after_seconds(response: requests.Response) -> float | None:
        raw = response.headers.get("Retry-After", "").strip()
        if not raw:
            return None

        try:
            seconds = float(raw)
            return max(0.0, seconds) if math.isfinite(seconds) else None
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(raw)
                return max(0.0, retry_at.timestamp() - time.time())
            except (TypeError, ValueError, OverflowError):
                return None

    @staticmethod
    def _endpoint_label(path: str) -> str:
        # Não registra CPF/código do pedido no log.
        if "/cliente/cpf/" in path:
            return "cliente/cpf"
        if "/clientes/" in path:
            return "clientes/segmento"
        if "/pedido/" in path:
            return "pedido"
        return "delivery"

    def _diagnostic_ref(self, kind: str, identity: str | int) -> str:
        message = f"{kind}:{identity}".encode()
        return hmac.new(self._diagnostic_key, message, hashlib.sha256).hexdigest()[:12]

    def cpf_diagnostic_ref(self, cpf: str) -> str:
        """Referência opaca para ligar as tentativas ao contato no log."""
        return self._diagnostic_ref("cliente/cpf", cpf)

    def weni_contact_diagnostic_ref(self, contact_uuid: str) -> str:
        """Referência opaca do contato, sem expor ou hashear o UUID diretamente."""
        return self._diagnostic_ref("weni/contact", contact_uuid)

    def _safe_server_error_summary(self, response: requests.Response) -> str:
        """Classifica o corpo sem registrar texto arbitrário ou dados pessoais."""
        raw = response.content
        if not isinstance(raw, bytes):
            raw = raw.encode("utf-8", errors="replace") if isinstance(raw, str) else b""
        content_type = response.headers.get("Content-Type", "")
        if not isinstance(content_type, str):
            content_type = ""
        content_type = content_type.split(";", 1)[0].strip().lower()
        kind = (
            "json"
            if (
                content_type == "application/json"
                or content_type == "text/json"
                or content_type.endswith("+json")
            )
            else "texto"
            if content_type == "text/plain"
            else "html"
            if content_type == "text/html"
            else "outro"
        )
        category = "vazio" if not raw else "nao_classificado"
        if raw and len(raw) <= 4096 and kind in {"json", "texto"}:
            value: Any = raw.decode("utf-8", errors="replace").strip()
            if kind == "json":
                try:
                    payload = json.loads(value)
                    value = (
                        " ".join(
                            item
                            for key, item in payload.items()
                            if key.casefold()
                            in {
                                "title",
                                "message",
                                "mensagem",
                                "msg",
                                "detail",
                                "error",
                                "erro",
                                "exceptionmessage",
                                "errormessage",
                            }
                            and isinstance(item, str)
                        )
                        if isinstance(payload, dict)
                        else ""
                    )
                except ValueError:
                    value = ""
            if isinstance(value, str):
                normalized = value.strip().casefold()
                if (
                    "nullreferenceexception" in normalized
                    or "object reference not set to an instance" in normalized
                ):
                    category = "null_reference"
                elif "sequence contains no elements" in normalized:
                    category = "sequencia_vazia"
                elif (
                    "execution timeout expired" in normalized
                    or "timeout expired" in normalized
                ):
                    category = "timeout_backend"
                elif "deadlock victim" in normalized:
                    category = "conflito_banco"
                elif "cannot insert duplicate key" in normalized:
                    category = "registro_duplicado"
                elif normalized == "internal server error":
                    category = "internal_server_error"
                elif normalized in {
                    "an error has occurred.",
                    "an error has occurred",
                    "erro interno do servidor",
                }:
                    category = "erro_generico_backend"
        signature = (
            hmac.new(self._diagnostic_key, raw, hashlib.sha256).hexdigest()[:12]
            if raw
            else "-"
        )
        # Only a strict UUID supplied in a tracing header is safe to echo.
        trace_id = "-"
        for header, value in response.headers.items():
            if (
                str(header).lower() in {"x-request-id", "x-correlation-id"}
                and isinstance(value, str)
                and re.fullmatch(
                    r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", value
                )
            ):
                trace_id = value.lower()
                break
        return (
            f"tipo={kind} bytes={len(raw)} "
            f"categoria={category} assinatura={signature} trace_id={trace_id}"
        )

    def _record_request(
        self,
        elapsed_seconds: float,
        *,
        status_code: int | None = None,
        network_error: bool = False,
        endpoint_label: str = "delivery",
    ) -> None:
        elapsed_seconds = max(0.0, elapsed_seconds)
        slow_threshold = max(0.0, float(FARMALIDER_SLOW_REQUEST_SECONDS))
        is_slow = slow_threshold > 0 and elapsed_seconds >= slow_threshold

        with self._metrics_lock:
            self._total_requests += 1
            if status_code is not None:
                self._status_counts[status_code] = (
                    self._status_counts.get(status_code, 0) + 1
                )
            self._total_response_seconds += elapsed_seconds
            self._max_response_seconds = max(
                self._max_response_seconds,
                elapsed_seconds,
            )
            self._response_times_seconds.append(elapsed_seconds)
            if is_slow:
                self._slow_requests += 1
            if network_error:
                self._network_errors += 1
            if status_code == 429:
                self._rate_limit_responses += 1
            elif status_code is not None and status_code >= 500:
                self._server_error_responses += 1

        if is_slow:
            status_text = str(status_code) if status_code is not None else "rede"
            logging.warning(
                "FarmaLíder: requisição lenta em %s: %.2fs (HTTP=%s).",
                endpoint_label,
                elapsed_seconds,
                status_text,
            )

    def _record_retry(self) -> None:
        with self._metrics_lock:
            self._total_retries += 1

    def metrics_snapshot(self) -> dict[str, int | float]:
        with self._rate_lock:
            effective_delay_ms = self._effective_delay_seconds * 1000
            recovery = {
                "concurrency_limit": self._concurrency_limit,
                "recovery_activations": self._recovery_activations,
                "open_circuits": len(self._open_circuits),
                "server_error_unique_queries": len(self._server_error_refs),
                "server_error_serial_queries": len(self._serial_error_refs),
                "cooldown_remaining_ms": max(0, self._cooldown_until - time.monotonic())
                * 1000,
            }

        with self._metrics_lock:
            total = self._total_requests
            average = self._total_response_seconds / total if total > 0 else 0.0
            response_times = sorted(self._response_times_seconds)
            if response_times:
                p95_index = max(
                    0,
                    min(
                        len(response_times) - 1,
                        math.ceil(len(response_times) * 0.95) - 1,
                    ),
                )
                p95 = response_times[p95_index]
            else:
                p95 = 0.0
            return {
                "customer_directory_hits": self._directory_hits,
                "execution_read_cache_hits": self._execution_cache.hits
                if self._execution_cache is not None
                else 0,
                "customer_directory_records": len(self.customer_directory.by_id)
                if self.customer_directory is not None
                else 0,
                "total_requests": total,
                "retries": self._total_retries,
                "rate_limits": self._rate_limit_responses,
                "server_errors": self._server_error_responses,
                "network_errors": self._network_errors,
                "slow_requests": self._slow_requests,
                "average_response_ms": average * 1000,
                "p95_response_ms": p95 * 1000,
                "max_response_ms": self._max_response_seconds * 1000,
                "effective_delay_ms": effective_delay_ms,
                "responses_200": self._status_counts.get(200, 0),
                "responses_404": self._status_counts.get(404, 0),
                **recovery,
            }

    def _sleep_before_retry(
        self,
        attempt: int,
        *,
        response: requests.Response | None = None,
        endpoint_label: str = "delivery",
        diagnostic_ref: str = "-",
    ) -> None:
        self._record_retry()
        status_code = response.status_code if response is not None else None
        delay = self._retry_delay(attempt, response)
        logging.warning(
            "FarmaLíder %s [consulta %s]: HTTP %s; nova tentativa em %.1fs (%s/%s).",
            endpoint_label,
            diagnostic_ref,
            status_code if status_code is not None else "rede",
            delay,
            attempt,
            FARMALIDER_MAX_RETRIES,
        )
        # Protection is already global. The next admission waits for the
        # cooldown without holding a request slot, including retries from peers.

    def _request_json(
        self,
        path: str,
        *,
        allow_not_found: bool = False,
        allow_customer_list: bool = False,
        diagnostic_ref: str = "-",
        private_cpf: str | None = None,
    ) -> dict[str, Any] | list[dict[str, Any]] | None:
        endpoint_label = self._endpoint_label(path)
        last_server_response: requests.Response | None = None

        for attempt in range(1, FARMALIDER_MAX_RETRIES + 1):
            response: requests.Response | None = None
            with self._private_request_slot(
                endpoint_label,
                private_cpf,
                diagnostic_ref,
                last_server_response,
                attempt,
            ) as permit:
                url, proxies = self._request_route(path)
                started = time.monotonic()
                try:
                    response = self._get_session().get(
                        url,
                        params={"token": self.token},
                        timeout=FARMALIDER_REQUEST_TIMEOUT_SECONDS,
                        allow_redirects=False,
                        proxies=proxies,
                    )
                except requests.RequestException as exc:
                    self._record_request(
                        time.monotonic() - started,
                        network_error=True,
                        endpoint_label=endpoint_label,
                    )
                    failure = classify_network_failure(exc)
                    if not failure.retryable:
                        self._mark_unhealthy()
                        raise FarmaliderError(
                            "Falha de rede não recuperável na FarmaLíder: "
                            + failure.summary
                            + " "
                            + self._route_summary(url, proxies)
                        ) from None
                    self._protect_after_failure(
                        endpoint_label=endpoint_label,
                        diagnostic_ref=diagnostic_ref,
                        permit=permit,
                        delay=self._retry_delay(attempt),
                        status_code=None,
                    )
                    if attempt < FARMALIDER_MAX_RETRIES:
                        self._refresh_network_route(
                            reason=f"falha recuperável em {endpoint_label}"
                        )

                if response is not None:
                    elapsed = time.monotonic() - started
                    self._record_request(
                        elapsed,
                        status_code=response.status_code,
                        endpoint_label=endpoint_label,
                    )
                    status = response.status_code
                    if status in {401, 403}:
                        self._mark_unhealthy()
                        logging.error(
                            "FarmaLíder %s [consulta %s]: HTTP %s; "
                            "falha de autenticação/permissão, interrompendo a fila.",
                            endpoint_label,
                            diagnostic_ref,
                            status,
                        )
                        self.cancel_pending_requests()
                        raise FarmaliderAuthError(
                            f"FarmaLíder API retornou HTTP {status}. "
                            "Verifique o token e a permissão para esta rota."
                        )
                    if status == 404 and allow_not_found:
                        self._mark_healthy(permit, endpoint_label)
                        return None
                    if status == 400:
                        self._mark_unhealthy()
                        raise FarmaliderBadRequestError(
                            "FarmaLíder API retornou HTTP 400 para a consulta."
                        )
                    if status == 429 or status >= 500:
                        if status >= 500:
                            last_server_response = response
                        self._protect_after_failure(
                            endpoint_label=endpoint_label,
                            diagnostic_ref=diagnostic_ref,
                            permit=permit,
                            delay=self._retry_delay(attempt, response),
                            status_code=status,
                        )
                        if status >= 500 and (
                            attempt == 1 or attempt == FARMALIDER_MAX_RETRIES
                        ):
                            logging.warning(
                                "FarmaLíder %s [consulta %s]: HTTP %s; %.2fs; "
                                "limite_inicial=%s; em_voo_ao_iniciar=%s; resposta %s.",
                                endpoint_label,
                                diagnostic_ref,
                                status,
                                elapsed,
                                permit.concurrency,
                                permit.active_requests,
                                self._safe_server_error_summary(response),
                            )
                        with self._rate_lock:
                            circuit_open = endpoint_label in self._open_circuits
                        if circuit_open:
                            self._record_private_failure(
                                private_cpf,
                                diagnostic_ref,
                                last_server_response,
                                attempt,
                                "circuito_aberto",
                            )
                            raise FarmaliderUnavailableError(
                                f"FarmaLíder: falhas 5xx persistentes em várias consultas "
                                f"da rota {endpoint_label}, inclusive após redução de ritmo. "
                                "Circuito aberto; verifique os logs do servidor."
                            )
                    else:
                        try:
                            response.raise_for_status()
                            payload = response.json()
                        except requests.RequestException:
                            self._mark_unhealthy()
                            raise FarmaliderError(
                                f"FarmaLíder API retornou HTTP {status}."
                            ) from None
                        except ValueError:
                            self._mark_unhealthy()
                            raise FarmaliderError(
                                "FarmaLíder API retornou JSON inválido."
                            ) from None
                        if not isinstance(payload, dict) and not (
                            allow_customer_list
                            and isinstance(payload, list)
                            and all(
                                isinstance(candidate, dict) for candidate in payload
                            )
                        ):
                            self._mark_unhealthy()
                            raise FarmaliderError(
                                "FarmaLíder API retornou um formato inesperado."
                            )
                        self._mark_healthy(permit, endpoint_label)
                        return payload

            if attempt >= FARMALIDER_MAX_RETRIES:
                if last_server_response is not None:
                    self._record_private_failure(
                        private_cpf,
                        diagnostic_ref,
                        last_server_response,
                        attempt,
                        "tentativas_esgotadas"
                        if response is not None
                        else "rede_sem_resposta_apos_5xx",
                    )
                if response is None:
                    raise FarmaliderError(
                        "Não foi possível alcançar a FarmaLíder API."
                    ) from None
                raise FarmaliderError(
                    f"FarmaLíder API retornou HTTP {response.status_code} "
                    "após as tentativas configuradas."
                )
            self._sleep_before_retry(
                attempt,
                response=response,
                endpoint_label=endpoint_label,
                diagnostic_ref=diagnostic_ref,
            )

        raise FarmaliderError("Falha inesperada ao consultar a FarmaLíder API.")

    def prepare_customer_directory(self, *, expected_contacts: int | None) -> bool:
        import sqlite3

        from farmalider_customers import CustomerDirectory, ExecutionReadCache
        from project_paths import load_private_settings
        from task_progress import TaskProgress

        settings = load_private_settings()
        mode = (
            str(getattr(settings, "FARMALIDER_CUSTOMER_DIRECTORY_MODE", "auto"))
            .strip()
            .lower()
        )
        if mode not in {"auto", "on", "off"}:
            raise ValueError(
                "FARMALIDER_CUSTOMER_DIRECTORY_MODE deve ser auto, on ou off."
            )
        minimum = max(
            1, int(getattr(settings, "FARMALIDER_CUSTOMER_DIRECTORY_MIN_CONTACTS", 500))
        )
        with self._directory_lock:
            if self._execution_cache is None:
                try:
                    self._execution_cache = ExecutionReadCache()
                except (OSError, ValueError, sqlite3.Error):
                    logging.warning(
                        "FarmaLíder: cache privado indisponível; consultas diretas preservadas."
                    )
            if mode == "off" or (
                mode == "auto"
                and expected_contacts is not None
                and expected_contacts < minimum
            ):
                return False
            if self._directory_attempted:
                return self.customer_directory is not None
            self._directory_attempted = True
            try:
                with TaskProgress(
                    "FarmaLíder: base cadastral FARMA", 1, unit="consultas"
                ) as progress:
                    directory = CustomerDirectory(self.get_clientes_segmento("FARMA"))
                    progress.advance()
                self.customer_directory = directory
                logging.info(
                    "FarmaLíder: índice cadastral FARMA pronto; %s. Ausência no índice não confirma ausência de compra.",
                    directory.metrics(),
                )
            except (FarmaliderAuthError, FarmaliderUnavailableError):
                raise
            except (FarmaliderError, ValueError) as exc:
                logging.warning(
                    "FarmaLíder: índice FARMA indisponível (%s); consultas individuais continuam.",
                    type(exc).__name__,
                )
            return self.customer_directory is not None

    def reset_execution_reads(self):
        """Uma aplicação exige consultas novas, mesmo com o mesmo cliente Python."""
        with self._directory_lock:
            if self._execution_cache is not None:
                self._execution_cache.close()
                self._execution_cache = None
            self.customer_directory = None
            self._directory_attempted = False

    def get_clientes_segmento(self, segmento: str = "FARMA"):
        if segmento not in {"FARMA", "PET"}:
            raise ValueError("Segmento deve ser FARMA ou PET.")
        return self._request_json(
            self._delivery_path(f"clientes/{segmento}"),
            allow_not_found=True,
            allow_customer_list=True,
        )

    def get_cliente_cadastro_by_cpf(self, cpf: str):
        if self.customer_directory is not None:
            candidates = self.customer_directory.candidates(cpf)
            if candidates:
                with self._metrics_lock:
                    self._directory_hits += 1
                return candidates
        return self.get_cliente_by_cpf(cpf)

    def _cached_read(self, kind: str, key: str, fetch):
        # Ativado somente para a preparação desta execução, nunca persistido
        # entre dry-run e apply ou tratado como prova de uma compra posterior.
        if self._execution_cache is not None:
            return self._execution_cache.read(kind, key, fetch)
        return fetch()

    def get_cliente_by_cpf(
        self, cpf: str
    ) -> dict[str, Any] | list[dict[str, Any]] | None:
        return self._cached_read(
            "cpf",
            cpf,
            lambda: self._request_json(
                self._delivery_path(f"cliente/cpf/{cpf}"),
                allow_not_found=True,
                allow_customer_list=True,
                diagnostic_ref=self.cpf_diagnostic_ref(cpf),
                private_cpf=cpf,
            ),
        )

    def _record_private_failure(
        self,
        cpf: str | None,
        reference: str,
        response: requests.Response | None,
        attempts: int,
        reason: str,
    ) -> None:
        if cpf is None or response is None:
            return
        with self._private_diagnostic_lock:
            if reference in self._private_recorded_refs:
                return
            try:
                raw = response.content if isinstance(response.content, bytes) else b""
                path = append_private_failure(
                    execution_id=self._diagnostic_execution_id,
                    reference=reference,
                    cpf=cpf,
                    status=response.status_code,
                    attempts=attempts,
                    reason=reason,
                    environment="homologacao" if self.use_hml else "producao",
                    raw=raw,
                    token=self.token,
                    summary=self._safe_server_error_summary(response),
                )
                if path is not None:
                    self._private_recorded_refs.add(reference)
                    logging.warning(
                        "FarmaLíder [consulta %s]: diagnóstico privado local gravado em %s; contém CPF, acesso restrito.",
                        reference,
                        path,
                    )
            except Exception as exc:
                logging.warning(
                    "FarmaLíder [consulta %s]: diagnóstico privado não pôde ser gravado (%s); a falha original foi preservada.",
                    reference,
                    type(exc).__name__,
                )

    @contextmanager
    def _private_request_slot(
        self,
        endpoint: str,
        cpf: str | None,
        reference: str,
        previous_response: requests.Response | None,
        attempt: int,
    ):
        admitted = False
        try:
            with self._request_slot(endpoint) as permit:
                admitted = True
                yield permit
        except FarmaliderUnavailableError:
            if not admitted and previous_response is not None:
                self._record_private_failure(
                    cpf,
                    reference,
                    previous_response,
                    attempt - 1,
                    "circuito_aberto_na_fila",
                )
            raise

    def get_pedido(self, codigo: str | int) -> dict[str, Any] | None:
        return cast(
            dict[str, Any] | None,
            self._cached_read(
                "pedido",
                str(codigo),
                lambda: self._request_json(
                    self._delivery_path(f"pedido/{codigo}"),
                    allow_not_found=True,
                    diagnostic_ref=self._diagnostic_ref("pedido", codigo),
                ),
            ),
        )

    def test_connection(self) -> dict[str, Any]:
        """Valida rede/autenticação com a mesma resiliência das consultas reais."""
        path = self._delivery_path("cliente/cpf/00000000000")
        endpoint_label = self._endpoint_label(path)
        diagnostic_ref = "preflight"
        last_network_summary = ""

        for attempt in range(1, FARMALIDER_MAX_RETRIES + 1):
            response: requests.Response | None = None

            with self._request_slot(endpoint_label) as permit:
                url, proxies = self._request_route(path)
                started = time.monotonic()
                try:
                    response = self._get_session().get(
                        url,
                        params={"token": self.token},
                        timeout=FARMALIDER_REQUEST_TIMEOUT_SECONDS,
                        allow_redirects=False,
                        proxies=proxies,
                    )
                except requests.RequestException as exc:
                    elapsed = time.monotonic() - started
                    self._record_request(
                        elapsed,
                        network_error=True,
                        endpoint_label=endpoint_label,
                    )
                    failure = classify_network_failure(exc)
                    last_network_summary = failure.summary

                    # Proxy 407, TLS inválido e outras falhas marcadas como não
                    # recuperáveis não devem consumir retries inúteis.
                    if not failure.retryable:
                        self._mark_unhealthy()
                        raise FarmaliderError(
                            "Falha de rede no preflight da FarmaLíder: "
                            + failure.summary
                            + " "
                            + self._route_summary(url, proxies)
                        ) from None

                    self._protect_after_failure(
                        endpoint_label=endpoint_label,
                        diagnostic_ref=diagnostic_ref,
                        permit=permit,
                        delay=self._retry_delay(attempt),
                        status_code=None,
                    )
                    if attempt < FARMALIDER_MAX_RETRIES:
                        self._refresh_network_route(
                            reason="falha recuperável no preflight FarmaLíder"
                        )
                    logging.warning(
                        "FarmaLíder %s [preflight]: %s Tentativa %s/%s.",
                        endpoint_label,
                        failure.summary,
                        attempt,
                        FARMALIDER_MAX_RETRIES,
                    )

                if response is not None:
                    elapsed = time.monotonic() - started
                    self._record_request(
                        elapsed,
                        status_code=response.status_code,
                        endpoint_label=endpoint_label,
                    )
                    status = response.status_code

                    if status == 401:
                        self._mark_unhealthy()
                        raise FarmaliderAuthError(
                            "FarmaLíder API retornou 401 Unauthorized. "
                            "Verifique o token enviado por QueryString."
                        )
                    if status == 403:
                        self._mark_unhealthy()
                        raise FarmaliderAuthError(
                            "FarmaLíder API retornou 403 Forbidden. "
                            "Token sem permissão para a rota."
                        )

                    if status == 429 or status >= 500:
                        self._protect_after_failure(
                            endpoint_label=endpoint_label,
                            diagnostic_ref=diagnostic_ref,
                            permit=permit,
                            delay=self._retry_delay(attempt, response),
                            status_code=status,
                        )
                        if status >= 500 and (
                            attempt == 1 or attempt == FARMALIDER_MAX_RETRIES
                        ):
                            logging.warning(
                                "FarmaLíder %s [preflight]: HTTP %s; resposta %s.",
                                endpoint_label,
                                status,
                                self._safe_server_error_summary(response),
                            )
                    else:
                        # O CPF é propositalmente fictício. 400/404 são
                        # esperados, mas qualquer resposta não transitória prova
                        # que rede, proxy e serviço foram alcançados.
                        self._mark_healthy(permit, endpoint_label)
                        return {
                            "ok": True,
                            "status_code": status,
                            "environment": "hml" if self.use_hml else "producao",
                            "auth_mode": "QueryString token only",
                            "base_url": self.base_url,
                            "attempts": attempt,
                        }

            if attempt >= FARMALIDER_MAX_RETRIES:
                if response is None:
                    detail = (
                        f" Último diagnóstico: {last_network_summary}"
                        if last_network_summary
                        else ""
                    )
                    raise FarmaliderError(
                        "Não foi possível alcançar a FarmaLíder API após "
                        f"{FARMALIDER_MAX_RETRIES} tentativa(s).{detail}"
                    ) from None
                if response.status_code == 429:
                    raise FarmaliderError(
                        "FarmaLíder API retornou 429 Too Many Requests "
                        f"após {FARMALIDER_MAX_RETRIES} tentativa(s)."
                    )
                raise FarmaliderError(
                    f"FarmaLíder API retornou HTTP {response.status_code} "
                    f"após {FARMALIDER_MAX_RETRIES} tentativa(s)."
                )

            self._sleep_before_retry(
                attempt,
                response=response,
                endpoint_label=endpoint_label,
                diagnostic_ref=diagnostic_ref,
            )

        raise FarmaliderError("Falha inesperada no preflight da FarmaLíder API.")
