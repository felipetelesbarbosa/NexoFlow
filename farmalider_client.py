from __future__ import annotations

import logging
import math
import threading
import time
from email.utils import parsedate_to_datetime
from typing import Any

import requests

from config import (
    FARMALIDER_429_COOLDOWN_SECONDS,
    FARMALIDER_MAX_ADAPTIVE_DELAY_SECONDS,
    FARMALIDER_MAX_RETRIES,
    FARMALIDER_REQUEST_DELAY_SECONDS,
    FARMALIDER_REQUEST_TIMEOUT_SECONDS,
    FARMALIDER_SLOW_REQUEST_SECONDS,
    farmalider_api_base_url,
)


class FarmaliderError(RuntimeError):
    """Erro base da integração FarmaLíder."""


class FarmaliderAuthError(FarmaliderError):
    """Token ausente, inválido ou sem permissão."""


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

        self._thread_local = threading.local()
        self._sessions: list[requests.Session] = []
        self._sessions_lock = threading.Lock()

        self._rate_lock = threading.Lock()
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

    def close(self) -> None:
        with self._sessions_lock:
            sessions = list(self._sessions)
            self._sessions.clear()

        for session in sessions:
            session.close()

    def _delivery_path(self, path: str) -> str:
        prefix = "/api/Delivery/hml" if self.use_hml else "/api/Delivery"
        return f"{prefix}/{path.lstrip('/')}"

    def _wait_before_request(self) -> None:
        """
        Aplica um limitador global entre inícios de requests.

        O mesmo limitador é usado por todas as threads, então adicionar workers
        não remove a proteção de ritmo configurada no projeto.
        """
        while True:
            with self._rate_lock:
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
                    return

            time.sleep(wait)

    def _increase_adaptive_delay(self) -> float:
        """Reduz automaticamente a pressão sobre a API após HTTP 429."""
        base = max(0.0, float(FARMALIDER_REQUEST_DELAY_SECONDS))
        maximum = max(base, float(FARMALIDER_MAX_ADAPTIVE_DELAY_SECONDS))

        with self._rate_lock:
            current = max(base, self._effective_delay_seconds)
            increased = max(base, current * 2 if current > 0 else 0.01)
            self._effective_delay_seconds = min(increased, maximum)
            return self._effective_delay_seconds

    def _activate_global_cooldown(self, seconds: float) -> None:
        seconds = max(0.0, float(seconds))
        if seconds <= 0:
            return

        with self._rate_lock:
            self._cooldown_until = max(
                self._cooldown_until,
                time.monotonic() + seconds,
            )

    @staticmethod
    def _retry_after_seconds(response: requests.Response) -> float | None:
        raw = response.headers.get("Retry-After", "").strip()
        if not raw:
            return None

        try:
            return max(0.0, float(raw))
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
        if "/pedido/" in path:
            return "pedido"
        return "delivery"

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

        with self._metrics_lock:
            total = self._total_requests
            average = (
                self._total_response_seconds / total
                if total > 0
                else 0.0
            )
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
            }

    def _sleep_before_retry(
        self,
        attempt: int,
        *,
        response: requests.Response | None = None,
    ) -> None:
        self._record_retry()
        status_code = response.status_code if response is not None else None
        server_delay = (
            self._retry_after_seconds(response)
            if response is not None
            else None
        )

        if status_code == 429:
            fallback = min(
                float(FARMALIDER_429_COOLDOWN_SECONDS) * (2 ** (attempt - 1)),
                30.0,
            )
            delay = max(server_delay or 0.0, fallback)
            effective_delay = self._increase_adaptive_delay()
            self._activate_global_cooldown(delay)
            logging.warning(
                "FarmaLíder retornou 429. Pausa global de %.1fs; "
                "intervalo global adaptado para %.0f ms "
                "(tentativa %s/%s).",
                delay,
                effective_delay * 1000,
                attempt,
                FARMALIDER_MAX_RETRIES,
            )
            return

        delay = (
            server_delay
            if server_delay is not None
            else float(2 ** (attempt - 1))
        )
        logging.warning(
            "FarmaLíder: repetindo requisição em %.1fs (tentativa %s/%s).",
            delay,
            attempt,
            FARMALIDER_MAX_RETRIES,
        )
        time.sleep(delay)

    def _request_json(
        self,
        path: str,
        *,
        allow_not_found: bool = False,
    ) -> dict[str, Any] | None:
        url = f"{self.base_url}{path}"
        endpoint_label = self._endpoint_label(path)

        for attempt in range(1, FARMALIDER_MAX_RETRIES + 1):
            response: requests.Response | None = None
            self._wait_before_request()
            started = time.monotonic()

            try:
                response = self._get_session().get(
                    url,
                    params={"token": self.token},
                    timeout=FARMALIDER_REQUEST_TIMEOUT_SECONDS,
                )
            except requests.RequestException as exc:
                self._record_request(
                    time.monotonic() - started,
                    network_error=True,
                    endpoint_label=endpoint_label,
                )
                if attempt >= FARMALIDER_MAX_RETRIES:
                    raise FarmaliderError(
                        "Não foi possível alcançar a FarmaLíder API."
                    ) from exc
                self._sleep_before_retry(attempt)
                continue

            self._record_request(
                time.monotonic() - started,
                status_code=response.status_code,
                endpoint_label=endpoint_label,
            )

            if response.status_code == 401:
                raise FarmaliderAuthError(
                    "FarmaLíder API retornou 401 Unauthorized. "
                    "Verifique o token enviado por QueryString."
                )
            if response.status_code == 403:
                raise FarmaliderAuthError(
                    "FarmaLíder API retornou 403 Forbidden. "
                    "O token não possui permissão para esta rota."
                )
            if response.status_code == 404 and allow_not_found:
                return None
            if response.status_code == 400:
                raise FarmaliderError(
                    "FarmaLíder API retornou HTTP 400 para a consulta."
                )

            if response.status_code == 429 or response.status_code >= 500:
                if attempt >= FARMALIDER_MAX_RETRIES:
                    raise FarmaliderError(
                        f"FarmaLíder API retornou HTTP {response.status_code} "
                        "após as tentativas configuradas."
                    )
                self._sleep_before_retry(attempt, response=response)
                continue

            try:
                response.raise_for_status()
                payload = response.json()
            except requests.RequestException as exc:
                raise FarmaliderError(
                    f"FarmaLíder API retornou HTTP {response.status_code}."
                ) from exc
            except ValueError as exc:
                raise FarmaliderError(
                    "FarmaLíder API retornou JSON inválido."
                ) from exc

            if not isinstance(payload, dict):
                raise FarmaliderError(
                    "FarmaLíder API retornou um formato inesperado."
                )
            return payload

        raise FarmaliderError("Falha inesperada ao consultar a FarmaLíder API.")

    def get_cliente_by_cpf(self, cpf: str) -> dict[str, Any] | None:
        return self._request_json(
            self._delivery_path(f"cliente/cpf/{cpf}"),
            allow_not_found=True,
        )

    def get_pedido(self, codigo: str | int) -> dict[str, Any] | None:
        return self._request_json(
            self._delivery_path(f"pedido/{codigo}"),
            allow_not_found=True,
        )

    def test_connection(self) -> dict[str, Any]:
        """Valida rede e autenticação sem depender de um CPF real."""
        path = self._delivery_path("cliente/cpf/00000000000")
        url = f"{self.base_url}{path}"

        self._wait_before_request()
        started = time.monotonic()
        try:
            response = self._get_session().get(
                url,
                params={"token": self.token},
                timeout=FARMALIDER_REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            self._record_request(
                time.monotonic() - started,
                network_error=True,
                endpoint_label=self._endpoint_label(path),
            )
            raise FarmaliderError(
                "Não foi possível alcançar a FarmaLíder API."
            ) from exc

        self._record_request(
            time.monotonic() - started,
            status_code=response.status_code,
            endpoint_label=self._endpoint_label(path),
        )

        if response.status_code == 401:
            raise FarmaliderAuthError(
                "FarmaLíder API retornou 401 Unauthorized. "
                "Verifique o token enviado por QueryString."
            )
        if response.status_code == 403:
            raise FarmaliderAuthError(
                "FarmaLíder API retornou 403 Forbidden. "
                "Token sem permissão para a rota."
            )
        if response.status_code == 429:
            raise FarmaliderError(
                "FarmaLíder API retornou 429 Too Many Requests."
            )
        if response.status_code >= 500:
            raise FarmaliderError(
                f"FarmaLíder API retornou HTTP {response.status_code}."
            )

        # 400/404 são aceitáveis neste teste porque o CPF é fictício.
        return {
            "ok": True,
            "status_code": response.status_code,
            "environment": "hml" if self.use_hml else "producao",
            "auth_mode": "QueryString token only",
            "base_url": self.base_url,
        }
