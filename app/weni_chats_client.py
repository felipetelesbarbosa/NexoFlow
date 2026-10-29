"""Leitura dos atendimentos e tags pela API externa oficial do Weni Chats."""

from __future__ import annotations

import logging
import time
from datetime import datetime
from urllib.parse import urljoin, urlsplit
from uuid import UUID

import requests

from versioning import CURRENT_VERSION


class WeniChatsError(RuntimeError):
    pass


class WeniChatsClient:
    def __init__(self, base_url: str, token: str):
        parsed = urlsplit(base_url.strip())
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise WeniChatsError(
                "Configure WENI_CHATS_API_BASE_URL com a origem HTTPS da API do Chats, sem caminho ou credenciais."
            )
        try:
            UUID(token.strip())
        except (ValueError, AttributeError):
            raise WeniChatsError(
                "Configure WENI_CHATS_API_TOKEN com o token de integração do projeto no Chats; o token de Flows é diferente."
            ) from None
        self.endpoint = base_url.rstrip("/") + "/v2/external/rooms_metrics/"
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": "Bearer " + token.strip(),
                "Accept": "application/json",
                "User-Agent": f"NexoFlow/{CURRENT_VERSION}",
            }
        )

    def close(self):
        self.session.close()

    def _page(self, url, params):
        # Do not forward the integration token to a pagination URL/redirect from another origin.
        if (
            urlsplit(url)[:2] != urlsplit(self.endpoint)[:2]
            or urlsplit(url).path != urlsplit(self.endpoint).path
        ):
            raise WeniChatsError(
                "Paginação do Weni Chats retornou um destino diferente do endpoint configurado."
            )
        for attempt in range(4):
            try:
                response = self.session.get(
                    url, params=params, timeout=(10, 60), allow_redirects=False
                )
            except requests.RequestException:
                if attempt == 3:
                    raise WeniChatsError(
                        "Falha de rede na leitura do Weni Chats; nenhuma resposta parcial será aplicada."
                    ) from None
                time.sleep(2**attempt)
                continue
            status = response.status_code
            if status == 429 or status >= 500:
                if attempt < 3:
                    delay = max(2**attempt, self._retry_after(response))
                    logging.warning(
                        "Weni Chats: HTTP %s; nova tentativa em %.1fs (%s/4).",
                        status,
                        delay,
                        attempt + 1,
                    )
                    time.sleep(delay)
                    continue
            if status != 200:
                raise WeniChatsError(
                    f"Weni Chats respondeu HTTP {status}; confira o acesso do token de integração ao projeto Delivery FarmaLíder."
                )
            try:
                payload = response.json()
            except ValueError:
                raise WeniChatsError("Resposta JSON inválida do Weni Chats.") from None
            if not isinstance(payload, dict) or not isinstance(
                payload.get("results"), list
            ):
                raise WeniChatsError(
                    "Resposta do Weni Chats sem a lista paginada results; confira a versão do endpoint."
                )
            return payload
        raise WeniChatsError("Leitura do Weni Chats incompleta.")

    @staticmethod
    def _retry_after(response):
        try:
            return max(0, float(response.headers.get("Retry-After", "0")))
        except ValueError:
            return 0

    def list_closed_rooms(self, *, cutoff: datetime):
        url = self.endpoint
        params = {
            "page_size": 100,
            "is_active": "false",
            "created_on__lte": cutoff.isoformat(),
        }
        rooms, seen_pages, seen_rooms = [], set(), set()
        while url:
            if url in seen_pages:
                raise WeniChatsError(
                    "A paginação do Weni Chats repetiu uma página; a leitura foi interrompida."
                )
            seen_pages.add(url)
            payload = self._page(url, params)
            params = None
            for room in payload["results"]:
                if not isinstance(room, dict) or not room.get("uuid"):
                    raise WeniChatsError(
                        "Atendimento do Weni Chats sem UUID; leitura incompleta."
                    )
                if room["uuid"] not in seen_rooms:
                    seen_rooms.add(room["uuid"])
                    rooms.append(room)
            logging.info(
                "Weni Chats: página %s; atendimentos acumulados=%s.",
                len(seen_pages),
                len(rooms),
            )
            following = payload.get("next")
            if following is not None and not isinstance(following, str):
                raise WeniChatsError("Paginação inválida do Weni Chats.")
            url = urljoin(self.endpoint, following) if following else ""
        return rooms
