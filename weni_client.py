from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

import requests

from config import (
    MAX_RETRIES,
    PAGE_LIMIT,
    REQUEST_TIMEOUT_SECONDS,
    WENI_CONTACT_ACTIONS_API_URL,
    WENI_CONTACTS_API_URL,
    WENI_FIELDS_API_URL,
    WENI_GROUPS_API_URL,
    WENI_MESSAGES_API_URL,
)


class WeniClient:
    def __init__(self, token: str) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Token {token}",
                "Accept": "application/json",
                "User-Agent": "GrupoLider-NexoFlow/1.0",
            }
        )

    def close(self) -> None:
        self.session.close()

    @staticmethod
    def format_datetime(dt: datetime) -> str:
        return (
            dt.astimezone(timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )

    def _request_json(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        last_error = "erro desconhecido"

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = self.session.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )

                if response.status_code == 401:
                    raise RuntimeError(
                        "Weni retornou 401. Verifique o token da API."
                    )
                if response.status_code == 403:
                    raise RuntimeError(
                        "Weni retornou 403. O token não tem permissão."
                    )

                if response.status_code == 429 or response.status_code >= 500:
                    if attempt >= MAX_RETRIES:
                        response.raise_for_status()
                    wait = float(2 ** (attempt - 1))
                    logging.warning(
                        "Weni indisponível/limitando requisições. "
                        "Tentativa %s/%s. Repetindo em %.1fs.",
                        attempt,
                        MAX_RETRIES,
                        wait,
                    )
                    time.sleep(wait)
                    continue

                response.raise_for_status()
                if not response.content:
                    return {}
                return response.json()

            except RuntimeError:
                raise
            except (requests.RequestException, ValueError) as exc:
                last_error = exc.__class__.__name__
                if attempt >= MAX_RETRIES:
                    break
                wait = float(2 ** (attempt - 1))
                logging.warning(
                    "Falha temporária ao acessar Weni. Tentativa %s/%s. "
                    "Repetindo em %.1fs.",
                    attempt,
                    MAX_RETRIES,
                    wait,
                )
                time.sleep(wait)

        raise RuntimeError(
            "Não foi possível acessar a API da Weni. "
            f"Último tipo de erro: {last_error}."
        )

    def _get_json(
        self,
        url: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        return self._request_json("GET", url, params=params)

    def _post_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        return self._request_json(
            "POST",
            url,
            params=params,
            json_body=json_body,
        )

    @staticmethod
    def extract_results(
        payload: Any,
    ) -> tuple[list[dict[str, Any]], str | None]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)], None

        if isinstance(payload, dict):
            results = payload.get("results")
            if isinstance(results, list):
                next_url = payload.get("next")
                if not isinstance(next_url, str) or not next_url.strip():
                    next_url = None
                return (
                    [item for item in results if isinstance(item, dict)],
                    next_url,
                )

        raise RuntimeError(
            "A API da Weni retornou um formato paginado não reconhecido."
        )

    def _list_paginated(
        self,
        base_url: str,
        params: dict[str, Any] | None = None,
        *,
        item_label: str,
        max_results: int | None = None,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        url: str | None = base_url
        first_request = True
        page = 1

        while url:
            payload = self._get_json(
                url,
                params=params if first_request else None,
            )
            first_request = False
            page_results, next_url = self.extract_results(payload)
            results.extend(page_results)
            if max_results is not None and len(results) >= max_results:
                results = results[:max_results]
                next_url = None
            logging.info(
                "Weni %s página %s: %s registro(s).",
                item_label,
                page,
                len(page_results),
            )
            page += 1
            url = urljoin(base_url, next_url) if next_url else None

        return results

    def list_contacts(
        self,
        after: datetime | None = None,
        limit: int = PAGE_LIMIT,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "deleted": "false",
            "order_by": "modified_on",
            "limit": limit,
        }
        if after is not None:
            params["after"] = self.format_datetime(after)
        return self._list_paginated(
            WENI_CONTACTS_API_URL,
            params,
            item_label="contatos",
        )

    def get_contact(
        self,
        *,
        uuid: str | None = None,
        urn: str | None = None,
    ) -> dict[str, Any] | None:
        if not uuid and not urn:
            raise ValueError("Informe uuid ou urn para localizar o contato.")
        params: dict[str, Any] = {"deleted": "false"}
        if uuid:
            params["uuid"] = uuid
        if urn:
            params["urn"] = urn
        payload = self._get_json(WENI_CONTACTS_API_URL, params=params)
        results, _ = self.extract_results(payload)
        return results[0] if results else None

    def list_messages(
        self,
        *,
        after: datetime | None = None,
        before: datetime | None = None,
        contact: str | None = None,
        urn: str | None = None,
        folder: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if after is not None:
            params["after"] = self.format_datetime(after)
        if before is not None:
            params["before"] = self.format_datetime(before)
        if contact:
            params["contact"] = contact
        if urn:
            params["urn"] = urn
        if folder:
            params["folder"] = folder
        max_results = None
        if limit is not None:
            max_results = max(1, int(limit))
            params["limit"] = min(max_results, PAGE_LIMIT)
        return self._list_paginated(
            WENI_MESSAGES_API_URL,
            params,
            item_label="mensagens",
            max_results=max_results,
        )

    def update_contact_fields(
        self,
        contact_uuid: str,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        if not contact_uuid:
            raise ValueError("UUID do contato não informado.")
        clean_fields = {
            str(key): value
            for key, value in fields.items()
            if str(key).strip() and value is not None and str(value).strip() != ""
        }
        if not clean_fields:
            return {"skipped": True, "reason": "nenhum campo para atualizar"}
        payload = self._post_json(
            WENI_CONTACTS_API_URL,
            params={"uuid": contact_uuid},
            json_body={"fields": clean_fields},
        )
        return payload if isinstance(payload, dict) else {"result": payload}

    def contact_group_action(
        self,
        contact_uuid: str,
        *,
        action: str,
        group: str,
    ) -> dict[str, Any]:
        if action not in {"add", "remove"}:
            raise ValueError("Ação de grupo deve ser 'add' ou 'remove'.")
        if not contact_uuid:
            raise ValueError("UUID do contato não informado.")
        if not group.strip():
            raise ValueError("Grupo da Weni não informado.")
        payload = self._post_json(
            WENI_CONTACT_ACTIONS_API_URL,
            json_body={
                "contacts": [contact_uuid],
                "action": action,
                "group": group,
            },
        )
        return payload if isinstance(payload, dict) else {"result": payload}

    def list_fields(self, key: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if key:
            params["key"] = key
        return self._list_paginated(
            WENI_FIELDS_API_URL,
            params,
            item_label="campos",
        )

    def list_groups(self, name: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if name:
            params["name"] = name
        return self._list_paginated(
            WENI_GROUPS_API_URL,
            params,
            item_label="grupos",
        )

    def test_connection(self) -> dict[str, Any]:
        payload = self._get_json(
            WENI_CONTACTS_API_URL,
            params={"deleted": "false", "limit": 1},
        )
        results, _ = self.extract_results(payload)
        return {"ok": True, "sample_count": len(results)}

    def test_update_access(self, opt_out_group: str) -> dict[str, Any]:
        # Somente leitura. Confirma acesso aos recursos necessários sem alterar
        # nenhum contato durante o diagnóstico.
        contacts_payload = self._get_json(
            WENI_CONTACTS_API_URL,
            params={"deleted": "false", "limit": 1},
        )
        contacts, _ = self.extract_results(contacts_payload)
        messages_payload = self._get_json(
            WENI_MESSAGES_API_URL,
            params={"folder": "incoming"},
        )
        messages, _ = self.extract_results(messages_payload)
        groups = self.list_groups(opt_out_group)
        return {
            "ok": True,
            "sample_contacts": len(contacts),
            "sample_messages": len(messages),
            "opt_out_group_found": any(
                str(item.get("name") or "").strip().casefold()
                == opt_out_group.strip().casefold()
                for item in groups
            ),
        }
