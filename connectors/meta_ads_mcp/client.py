"""Cliente reutilizável pela aplicação NexoFlow e pelo servidor MCP.

Somente GET; sem endpoints de escrita, sem escopo ads_management e sem suporte
para URLs arbitrárias. Cada conta exige inclusão explícita na allowlist local.
"""

from __future__ import annotations

import json
import math
import time
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote, quote_plus

import requests

from connectors.meta_ads_mcp.settings import MetaSettings, account_number


class MetaReadError(RuntimeError):
    """Erro público sanitizado de consulta à Meta."""

    def __init__(self, message, *, status_code=None, critical=False, retryable=False):
        super().__init__(message)
        self.status_code = status_code
        self.critical = critical
        self.retryable = retryable


class MetaAdsClient:
    def __init__(
        self,
        settings: MetaSettings,
        session: Any | None = None,
        *,
        max_attempts=3,
        sleep_fn=time.sleep,
    ):
        if not isinstance(settings, MetaSettings):
            raise MetaReadError("Configuração Meta inválida.")
        if type(max_attempts) is not int or not 1 <= max_attempts <= 5:
            raise MetaReadError("Máximo de tentativas deve estar entre 1 e 5.")
        self.max_attempts = max_attempts
        self.sleep = sleep_fn
        self._http_metrics = {
            "GET": 0,
            "retries": 0,
            "seconds": 0.0,
            "network_errors": 0,
        }
        self._permissions_checked = False
        self.settings = settings
        self.session = session if session is not None else requests.Session()
        self.base_url = f"https://graph.facebook.com/{settings.api_version}"

    def metrics_snapshot(self):
        return dict(self._http_metrics)

    def close(self):
        close = getattr(self.session, "close", None)
        if close is not None:
            close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _ensure_ads_read(self):
        if self._permissions_checked:
            return
        permissions = self._get("me/permissions", {}, check_permissions=False)
        rows = permissions.get("data")
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise MetaReadError("Não foi possível comprovar a permissão ads_read.")
        granted = {
            row.get("permission") for row in rows if row.get("status") == "granted"
        }
        if "ads_read" not in granted:
            raise MetaReadError(
                "A permissão ads_read não foi concedida ao token configurado.",
                critical=True,
            )
        if "ads_management" in granted:
            raise MetaReadError(
                "Use um token dedicado somente de leitura, sem ads_management.",
                critical=True,
            )
        self._permissions_checked = True

    def accounts(self) -> dict[str, Any]:
        return {
            "contas_permitidas": list(self.settings.allowed_account_ids),
            "modo": "somente_leitura",
        }

    def _account(self, account_id: str) -> str:
        number = account_number(account_id)
        if number not in self.settings.allowed_account_ids:
            raise MetaReadError("Conta fora da lista autorizada do MCP local.")
        return number

    @staticmethod
    def _limits(limit: int, pages: int) -> tuple[int, int]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise MetaReadError("Limite deve ser inteiro entre 1 e 100.")
        if type(pages) is not int or not 1 <= pages <= 10:
            raise MetaReadError("Páginas deve ser inteiro entre 1 e 10.")
        return limit, pages

    def _get(
        self, relative_path: str, params: dict[str, Any], *, check_permissions=True
    ) -> dict[str, Any]:
        # Endpoints são construídos internamente, nunca aceitos como URL do usuário.
        if set(params) - {
            "fields",
            "limit",
            "after",
            "level",
            "time_range",
            "time_increment",
            "action_report_time",
            "action_attribution_windows",
            "use_account_attribution_setting",
        }:
            raise MetaReadError("Parâmetro fora das consultas de leitura autorizadas.")
        allowed = {"me/permissions"} | {
            f"act_{account}{suffix}"
            for account in self.settings.allowed_account_ids
            for suffix in ("", "/campaigns", "/adsets", "/ads", "/insights")
        }
        if relative_path not in allowed:
            raise MetaReadError("Caminho fora dos endpoints de leitura autorizados.")
        if check_permissions and relative_path != "me/permissions":
            self._ensure_ads_read()
        try:
            response = self._request_response(relative_path, params)
            body = response.json()
        except requests.RequestException:
            raise MetaReadError(
                "Falha de rede ou timeout ao consultar a API Meta."
            ) from None
        except ValueError:
            raise MetaReadError("A Meta retornou JSON inválido.") from None
        if not isinstance(body, dict):
            raise MetaReadError("Resposta inesperada da Meta.")
        if body.get("error"):
            raise MetaReadError(
                "A Meta retornou erro de API. Confira o token e as permissões da conta.",
                status_code=response.status_code,
                critical=self._critical_error_code(response),
                retryable=bool(
                    isinstance(body.get("error"), dict)
                    and body["error"].get("is_transient") is True
                ),
            )
        clean = self._sanitize(body)
        if isinstance(body.get("paging"), dict) and body["paging"].get("next"):
            clean.setdefault("paging", {})["_has_next"] = True
        return clean

    def _request_response(self, path, params):
        for attempt in range(self.max_attempts):
            started = time.monotonic()
            self._http_metrics["GET"] += 1
            self._http_metrics["retries"] += int(attempt > 0)
            try:
                response = self.session.get(
                    f"{self.base_url}/{path}",
                    params=params,
                    headers={
                        "Authorization": f"Bearer {self.settings.token}",
                        "Accept": "application/json",
                    },
                    timeout=(8, 40),
                    allow_redirects=False,
                )
            except requests.RequestException:
                self._http_metrics["network_errors"] += 1
                self._http_metrics["seconds"] += time.monotonic() - started
                if attempt + 1 < self.max_attempts:
                    self.sleep(2**attempt)
                    continue
                raise MetaReadError(
                    "Falha de rede ou timeout ao consultar a API Meta.", retryable=True
                ) from None
            self._http_metrics["seconds"] += time.monotonic() - started
            status = response.status_code
            status_key = "HTTP_" + str(status)
            self._http_metrics[status_key] = self._http_metrics.get(status_key, 0) + 1
            if 300 <= status < 400:
                raise MetaReadError(
                    "Redirecionamento inesperado da API Meta.", status_code=status
                )
            retryable = status == 429 or 500 <= status < 600
            if retryable and attempt + 1 < self.max_attempts:
                wait = self._retry_after(
                    getattr(response, "headers", {}).get("Retry-After"), 2**attempt
                )
                if wait <= 60:
                    self.sleep(wait)
                    continue
            if status >= 400:
                raise MetaReadError(
                    f"A Meta recusou a consulta (HTTP {status}).",
                    status_code=status,
                    critical=status in (401, 403)
                    or self._critical_error_code(response),
                    retryable=retryable,
                )
            return response
        raise MetaReadError("Consulta Meta não concluída.", retryable=True)

    @staticmethod
    def _critical_error_code(response):
        try:
            body = response.json()
            error = body.get("error") if isinstance(body, dict) else None
            return isinstance(error, dict) and error.get("code") in (10, 190, 200, 294)
        except (ValueError, TypeError):
            return False

    @staticmethod
    def _retry_after(value, default):
        if not value:
            return default
        try:
            seconds = float(value)
            return max(0, seconds) if math.isfinite(seconds) else default
        except (TypeError, ValueError):
            try:
                dt = parsedate_to_datetime(str(value))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
                return max(0, (dt - datetime.now(UTC)).total_seconds())
            except (TypeError, ValueError, OverflowError):
                return default

    def _sanitize(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: self._sanitize(item)
                for key, item in value.items()
                if key.lower()
                not in {"access_token", "authorization", "next", "previous"}
            }
        if isinstance(value, list):
            return [self._sanitize(item) for item in value]
        if isinstance(value, str):
            for secret in {
                self.settings.token,
                quote(self.settings.token, safe=""),
                quote_plus(self.settings.token),
            }:
                value = value.replace(secret, "[oculto]")
            return value
        return value

    def _pages(
        self, path: str, params: dict[str, Any], limit: int, pages: int
    ) -> dict[str, Any]:
        limit, pages = self._limits(limit, pages)
        local = {**params, "limit": limit}
        result: list[dict[str, Any]] = []
        seen_cursors = set()
        truncated = False
        for current in range(pages):
            body = self._get(path, local)
            items = body.get("data")
            if not isinstance(items, list) or not all(
                isinstance(x, dict) for x in items
            ):
                raise MetaReadError("Lista de dados inválida na resposta Meta.")
            if len(items) > limit:
                raise MetaReadError("Resposta Meta excedeu o limite solicitado.")
            result.extend(items)
            paging = body.get("paging") or {}
            cursors = paging.get("cursors") if isinstance(paging, dict) else None
            after = cursors.get("after") if isinstance(cursors, dict) else None
            # Usar cursor com URL fixa, NUNCA seguir paging.next (pode conter token).
            if not isinstance(paging, dict) or not paging.get("_has_next"):
                break
            if not isinstance(after, str) or not after or len(after) > 4096:
                raise MetaReadError("Cursor de paginação Meta ausente ou inválido.")
            if after in seen_cursors:
                raise MetaReadError("Paginação Meta retornou cursor repetido.")
            seen_cursors.add(after)
            if current == pages - 1:
                truncated = True
            else:
                local["after"] = after
        return {"dados": result, "total_retornado": len(result), "parcial": truncated}

    def account_details(self, account_id: str) -> dict[str, Any]:
        account_id = self._account(account_id)
        return self._get(
            f"act_{account_id}",
            {"fields": "id,account_id,name,currency,account_status,timezone_name"},
        )

    def campaigns(
        self, account_id: str, limit: int = 50, pages: int = 2
    ) -> dict[str, Any]:
        account_id = self._account(account_id)
        return self._pages(
            f"act_{account_id}/campaigns",
            {
                "fields": "id,name,status,effective_status,objective,created_time,updated_time"
            },
            limit,
            pages,
        )

    def adsets(
        self, account_id: str, limit: int = 50, pages: int = 2
    ) -> dict[str, Any]:
        account_id = self._account(account_id)
        return self._pages(
            f"act_{account_id}/adsets",
            {
                "fields": "id,name,campaign_id,status,effective_status,daily_budget,lifetime_budget,optimization_goal,billing_event"
            },
            limit,
            pages,
        )

    def ads(self, account_id: str, limit: int = 50, pages: int = 2) -> dict[str, Any]:
        account_id = self._account(account_id)
        return self._pages(
            f"act_{account_id}/ads",
            {"fields": "id,name,adset_id,campaign_id,status,effective_status"},
            limit,
            pages,
        )

    def insights(
        self,
        account_id: str,
        start_date: str,
        end_date: str,
        level: str = "campaign",
        limit: int = 100,
        pages: int = 3,
        *,
        time_increment: int | None = None,
        action_report_time: str | None = None,
        action_attribution_windows: tuple[str, ...] | None = None,
        use_account_attribution_setting: bool = False,
    ) -> dict[str, Any]:
        account_id = self._account(account_id)
        if level not in {"account", "campaign", "adset", "ad"}:
            raise MetaReadError("Nível permitido: account, campaign, adset ou ad.")
        try:
            start = date.fromisoformat(start_date)
            end = date.fromisoformat(end_date)
            if start.isoformat() != start_date or end.isoformat() != end_date:
                raise ValueError()
        except (ValueError, TypeError):
            raise MetaReadError("Datas devem estar no formato AAAA-MM-DD.") from None
        if end < start or (end - start).days > 92:
            raise MetaReadError(
                "Informe período de até 93 dias, com início anterior ao fim."
            )
        if time_increment not in (None, 1) or type(time_increment) is bool:
            raise MetaReadError("Incremento permitido: 1 dia ou período agregado.")
        if action_report_time not in (None, "impression", "conversion", "mixed"):
            raise MetaReadError("action_report_time inválido.")
        if type(use_account_attribution_setting) is not bool:
            raise MetaReadError(
                "Configuração de atribuição de conta deve ser booleana."
            )
        if action_attribution_windows is not None and (
            not isinstance(action_attribution_windows, tuple)
            or not action_attribution_windows
            or any(not isinstance(w, str) for w in action_attribution_windows)
            or len(set(action_attribution_windows)) != len(action_attribution_windows)
            or any(
                w not in {"1d_click", "7d_click", "1d_view", "7d_view"}
                for w in action_attribution_windows
            )
        ):
            raise MetaReadError("Janelas de atribuição inválidas.")
        if use_account_attribution_setting and action_attribution_windows is not None:
            raise MetaReadError("Escolha atribuição da conta ou janelas explícitas.")
        attribution = {
            "action_report_time": action_report_time or "api_default",
            "mode": "account_setting"
            if use_account_attribution_setting
            else "explicit_windows"
            if action_attribution_windows
            else "api_default",
            "action_attribution_windows": list(action_attribution_windows or ()),
            "use_account_attribution_setting": use_account_attribution_setting,
        }
        options = {}
        if time_increment is not None:
            options["time_increment"] = time_increment
        if action_report_time is not None:
            options["action_report_time"] = action_report_time
        if action_attribution_windows is not None:
            options["action_attribution_windows"] = json.dumps(
                list(action_attribution_windows)
            )
        if use_account_attribution_setting:
            options["use_account_attribution_setting"] = "true"
        # A Marketing API informa métricas de atribuição em arrays; não as reinterprete.
        fields = (
            "date_start,date_stop,account_id,account_name,campaign_id,campaign_name,"
            "adset_id,adset_name,ad_id,ad_name,spend,impressions,reach,"
            "clicks,inline_link_clicks,ctr,cpc,cpm,frequency,actions,action_values,purchase_roas,cost_per_action_type"
        )
        result = self._pages(
            f"act_{account_id}/insights",
            {
                **options,
                "fields": fields,
                "level": level,
                "time_range": json.dumps({"since": start_date, "until": end_date}),
            },
            limit,
            pages,
        )
        result.update(
            {
                "conta": account_id,
                "inicio": start_date,
                "fim": end_date,
                "nivel": level,
                "time_increment": time_increment,
                "attribution": attribution,
                "api_version": self.settings.api_version,
            }
        )
        return result

    def daily_insights(
        self,
        account_id,
        start_date,
        end_date,
        limit=100,
        pages=10,
        *,
        action_report_time="impression",
        action_attribution_windows=("7d_click", "1d_view"),
        use_account_attribution_setting=False,
    ):
        return self.insights(
            account_id,
            start_date,
            end_date,
            "ad",
            limit,
            pages,
            time_increment=1,
            action_report_time=action_report_time,
            action_attribution_windows=action_attribution_windows,
            use_account_attribution_setting=use_account_attribution_setting,
        )
