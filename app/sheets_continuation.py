"""Contratos de capacidade, índice e exclusão mútua das continuações Sheets."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import time
from dataclasses import asdict, dataclass
from email.utils import parsedate_to_datetime
from typing import Any
from uuid import uuid4

from google.auth.exceptions import TransportError
from gspread.exceptions import APIError
from requests import RequestException

INDEX_TITLE = "NexoFlow_Continuidade"
INDEX_HEADERS = ["tipo", "chave", "valor"]
CELL_LIMIT = 20_000_000
ROTATE_AT = 18_000_000
MAX_PART_ROWS = 500_000
LEASE_ID = 191126102
LEASE_KEY = "nexoflow_continuation_writer_v1"
LEASE_SECONDS = 300
FILE_MARKER_KEY = "nexoflow_continuation_origin_v1"


class ContinuationError(RuntimeError):
    """Continuação indisponível; preservar dados e checkpoint para retomada."""


def fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()
    ).hexdigest()


def stamp_book(book, *, hub: str, segment: str, role: str):
    """Origem legível pelo conector somente leitura, sem credenciais no índice."""
    value = json.dumps({"hub": hub, "segment": segment, "role": role}, sort_keys=True)

    def matches():
        metadata = book.fetch_sheet_metadata(params={"fields": "developerMetadata"})
        found = [
            m
            for m in metadata.get("developerMetadata", [])
            if m.get("metadataKey") == FILE_MARKER_KEY
        ]
        if found and (
            len(found) != 1
            or found[0].get("metadataValue") != value
            or found[0].get("location") != {"spreadsheet": True}
            or found[0].get("visibility") != "DOCUMENT"
        ):
            raise ContinuationError(
                "A origem do arquivo diverge do segmento configurado."
            )
        return bool(found)

    if not matches():
        book.batch_update(
            {
                "requests": [
                    {
                        "createDeveloperMetadata": {
                            "developerMetadata": {
                                "metadataKey": FILE_MARKER_KEY,
                                "metadataValue": value,
                                "location": {"spreadsheet": True},
                                "visibility": "DOCUMENT",
                            }
                        }
                    }
                ]
            }
        )
        if not matches():
            raise ContinuationError("A origem do arquivo não foi confirmada.")


def allocated_cells(metadata: dict[str, Any]) -> int:
    total = 0
    for sheet in metadata.get("sheets", []):
        properties = sheet.get("properties", {})
        if properties.get("sheetType", "GRID") != "GRID":
            continue
        grid = properties.get("gridProperties", {})
        rows, columns = grid.get("rowCount"), grid.get("columnCount")
        if type(rows) is not int or type(columns) is not int or rows < 1 or columns < 1:
            raise ContinuationError(
                "Dimensões inválidas ao conferir capacidade do Sheets."
            )
        total += rows * columns
    return total


def additional_rows(cells: int, columns: int, *, threshold: int = ROTATE_AT) -> int:
    if columns < 1 or cells < 0 or not 100 <= threshold <= CELL_LIMIT:
        raise ValueError("Capacidade ou largura inválida.")
    return max(0, (threshold - cells) // columns)


@dataclass(frozen=True)
class Part:
    title: str
    number: int
    book_id: str
    sheet_id: int
    width: int
    schema: str

    @property
    def key(self) -> str:
        return f"{self.title}#{self.number}"


class ContinuationIndex:
    def __init__(self, hub: str, segment: str, roots: dict[str, str]):
        self.config: dict[str, Any] = {
            "format": 1,
            "hub": hub,
            "segment": segment,
            "roots": roots,
            "enabled": True,
            "threshold": ROTATE_AT,
            "max_part_rows": MAX_PART_ROWS,
            "connector_tables": [],
        }
        self.files: dict[str, dict[str, Any]] = {}
        self.parts: dict[str, Part] = {}
        self.status: dict[str, dict[str, Any]] = {}
        self.intents: dict[str, dict[str, Any]] = {}

    def table_parts(self, title: str) -> list[Part]:
        return sorted(
            (part for part in self.parts.values() if part.title == title),
            key=lambda part: part.number,
        )

    def values(self) -> list[list[str]]:
        result = [INDEX_HEADERS[:]]
        for kind, mapping in (
            ("config", {"principal": self.config}),
            ("arquivo", self.files),
            ("parte", {key: asdict(part) for key, part in self.parts.items()}),
            ("estado", self.status),
            ("criacao", self.intents),
        ):
            result.extend(
                [kind, key, json.dumps(value, ensure_ascii=False, sort_keys=True)]
                for key, value in sorted(mapping.items())
            )
        return result

    @classmethod
    def parse(cls, values, *, hub: str, segment: str, roots: dict[str, str]):
        if not values or list(values[0]) != INDEX_HEADERS:
            raise ContinuationError("Cabeçalho inválido em NexoFlow_Continuidade.")
        mappings: dict[str, dict[str, dict[str, Any]]] = {
            key: {} for key in ("config", "arquivo", "parte", "estado", "criacao")
        }
        try:
            for row in values[1:]:
                if not row or not any(row):
                    continue
                if (
                    len(row) != 3
                    or row[0] not in mappings
                    or row[1] in mappings[row[0]]
                ):
                    raise ValueError("Registro duplicado ou inválido.")
                value = json.loads(row[2])
                if not isinstance(value, dict):
                    raise ValueError("Registro sem objeto.")
                mappings[row[0]][row[1]] = value
            config = mappings["config"]["principal"]
            if set(mappings["config"]) != {"principal"} or any(
                config.get(key) != expected
                for key, expected in (
                    ("format", 1),
                    ("hub", hub),
                    ("segment", segment),
                    ("roots", roots),
                )
            ):
                raise ValueError("Perfil ou destinos divergentes.")
            if config.get("enabled") is not True:
                raise ValueError("Índice desativado ou incompleto.")
            threshold = config["threshold"]
            if type(threshold) is not int or not 100 <= threshold <= CELL_LIMIT - 100:
                raise ValueError("Reserva de capacidade inválida.")
            if type(config["max_part_rows"]) is not int or config["max_part_rows"] < 2:
                raise ValueError("Tamanho de parte inválido.")
            if not isinstance(config["connector_tables"], list) or any(
                not isinstance(title, str) or not title.startswith("BI_")
                for title in config["connector_tables"]
            ):
                raise ValueError("Fontes Data Studio inválidas.")
            index = cls(hub, segment, roots)
            index.config = config
            index.files = mappings["arquivo"]
            index.status = mappings["estado"]
            index.intents = mappings["criacao"]
            for key, data in mappings["parte"].items():
                part = Part(**data)
                if (
                    key != part.key
                    or not isinstance(part.title, str)
                    or not part.title
                    or type(part.number) is not int
                    or part.number < 0
                    or type(part.sheet_id) is not int
                    or part.sheet_id < 0
                    or type(part.width) is not int
                    or part.width < 1
                    or not isinstance(part.schema, str)
                    or not re.fullmatch(r"[a-f0-9]{64}", part.schema)
                    or part.book_id not in set(roots.values()) | set(index.files)
                ):
                    raise ValueError("Parte inválida.")
                index.parts[key] = part
            for file_id, info in index.files.items():
                if (
                    file_id in roots.values()
                    or not re.fullmatch(r"[A-Za-z0-9_-]+", file_id)
                    or info.get("role") not in roots
                    or type(info.get("number")) is not int
                    or info["number"] < 1
                    or info.get("source") != roots[info["role"]]
                ):
                    raise ValueError("Arquivo de continuação inválido.")
            for part in index.parts.values():
                role = (
                    "dashboard"
                    if part.title.startswith("BI_")
                    else "historico"
                    if part.title == "Historico_Alteracoes"
                    else "operacao"
                )
                if (part.book_id in roots.values() and part.book_id != roots[role]) or (
                    part.book_id in index.files
                    and index.files[part.book_id]["role"] != role
                ):
                    raise ValueError("Parte pertence a outro papel de armazenamento.")
            for title, status in index.status.items():
                if (
                    not index.table_parts(title)
                    or status.get("state") not in {"WRITING", "READY"}
                    or not isinstance(status.get("revision"), str)
                    or not re.fullmatch(r"[a-f0-9]{32}", status["revision"])
                ):
                    raise ValueError("Estado de tabela inválido.")
                if status["state"] == "READY":
                    rows = status.get("parts")
                    if (
                        not isinstance(rows, list)
                        or len(rows) != len(index.table_parts(title))
                        or any(
                            not isinstance(r, dict)
                            or type(r.get("number")) is not int
                            or r["number"] != n
                            or type(r.get("rows")) is not int
                            or r["rows"] < 0
                            for n, r in enumerate(rows)
                        )
                    ):
                        raise ValueError("Contagens de partes inválidas.")
            for key, intent in index.intents.items():
                role = intent.get("role")
                title = intent.get("table")
                if (
                    not isinstance(title, str)
                    or not title
                    or role
                    != (
                        "dashboard"
                        if title.startswith("BI_")
                        else "historico"
                        if title == "Historico_Alteracoes"
                        else "operacao"
                    )
                ):
                    raise ValueError("Criação pertence a outro papel de armazenamento.")
                if (
                    role not in roots
                    or intent.get("hub") != hub
                    or intent.get("segment") != segment
                    or intent.get("source") != roots[role]
                    or key != f"{intent.get('table')}#{intent.get('part')}"
                    or type(intent.get("part")) is not int
                    or intent["part"] != len(index.table_parts(title))
                    or not isinstance(intent.get("operation"), str)
                    or not re.fullmatch(r"[a-f0-9]{32}", intent["operation"])
                    or intent.get("create_state")
                    not in {"prepared", "sending", "rejected"}
                    or not isinstance(intent.get("parents"), list)
                    or not isinstance(intent.get("permissions"), list)
                    or not isinstance(intent.get("schema"), str)
                    or not re.fullmatch(r"[a-f0-9]{64}", intent["schema"])
                ):
                    raise ValueError("Intenção de criação inválida.")
                if "file_id" in intent and (
                    not isinstance(intent["file_id"], str)
                    or not re.fullmatch(r"[A-Za-z0-9_-]+", intent["file_id"])
                ):
                    raise ValueError("Arquivo de criação inválido.")
            physical = [(p.book_id, p.sheet_id) for p in index.parts.values()]
            if len(physical) != len(set(physical)):
                raise ValueError("A mesma aba foi vinculada duas vezes.")
            for title in {p.title for p in index.parts.values()}:
                parts = index.table_parts(title)
                if [p.number for p in parts] != list(range(len(parts))):
                    raise ValueError("Sequência de partes incompleta.")
                if len({(p.width, p.schema) for p in parts}) != 1:
                    raise ValueError("Schemas divergentes entre continuações.")
            return index
        except (KeyError, TypeError, ValueError) as exc:
            raise ContinuationError(
                "Índice de continuações inválido ou pertencente a outro segmento; gravação bloqueada."
            ) from exc


class SheetsLease:
    """Lease remoto por metadataId único; troca expirada usa comparação do valor."""

    def __init__(self, book, *, now=None, sleep=time.sleep):
        self.book = book
        self.now = now or time.time
        self.server_clock = now is None and hasattr(book, "client")
        self.sleep = sleep
        self.uncertain = False
        self.owner = uuid4().hex
        self.value: str | None = None
        self.renewed_at = 0.0

    def _lookup(self):
        if self.server_clock:
            raw = self.book.client.request(
                "get",
                f"https://sheets.googleapis.com/v4/spreadsheets/{self.book.id}",
                params={"fields": "developerMetadata"},
            )
            try:
                server_time = parsedate_to_datetime(raw.headers["Date"]).timestamp()
                if not math.isfinite(server_time):
                    raise ValueError
            except (KeyError, TypeError, ValueError, OverflowError) as exc:
                raise ContinuationError(
                    "A resposta do Google não confirmou o horário do bloqueio remoto."
                ) from exc
            received = time.monotonic()
            self.now = lambda: server_time + time.monotonic() - received
            response = raw.json()
        else:
            response = self.book.fetch_sheet_metadata(
                params={"fields": "developerMetadata"}
            )
        matches = [
            m
            for m in response.get("developerMetadata", [])
            if m.get("metadataId") == LEASE_ID
        ]
        if len(matches) > 1:
            raise ContinuationError("Bloqueio remoto inconsistente.")
        if matches and matches[0].get("metadataKey") != LEASE_KEY:
            raise ContinuationError(
                "ID de bloqueio remoto ocupado por outra configuração."
            )
        return matches[0].get("metadataValue") if matches else None

    @staticmethod
    def _owner(value):
        try:
            data = json.loads(value)
            if (
                not isinstance(data, dict)
                or not isinstance(data.get("owner"), str)
                or not re.fullmatch(r"[a-f0-9]{32}", data["owner"])
                or type(data.get("expires")) not in (int, float)
            ):
                raise ValueError
            if not math.isfinite(data["expires"]):
                raise ValueError
            return data
        except (TypeError, ValueError, KeyError) as exc:
            raise ContinuationError(
                "Bloqueio remoto inválido; exige conferência."
            ) from exc

    @staticmethod
    def _filter(value):
        return {
            "developerMetadataLookup": {
                "metadataId": LEASE_ID,
                "metadataKey": LEASE_KEY,
                "metadataValue": value,
            }
        }

    def note_uncertain(self):
        self.uncertain = True

    def require(self, *, wait_seconds=0):
        if self.uncertain:
            raise ContinuationError(
                "Uma gravação ficou sem confirmação. Aguarde até 5 minutos e retome a carga; os dados serão conferidos antes da repetição."
            )
        now = self.now()
        if self.value is not None and now - self.renewed_at < 30:
            return
        previous = self._lookup()
        now = self.now()
        deadline = now + wait_seconds
        while previous is not None and self.value is None:
            data = self._owner(previous)
            if data["expires"] <= now or data["owner"] == self.owner:
                break
            if now >= deadline:
                break
            logging.info(
                "Google Sheets: aguardando liberação da gravação anterior (até %.0f s).",
                min(deadline, data["expires"]) - now,
            )
            self.sleep(min(15, deadline - now, data["expires"] - now))
            now = self.now()
            previous = self._lookup()
            now = self.now()
        if previous is not None:
            data = self._owner(previous)
            if self.value is not None and data["owner"] != self.owner:
                raise ContinuationError(
                    "O bloqueio da carga mudou; preservar a aplicação para revisão."
                )
            if data["owner"] != self.owner and data["expires"] > now:
                raise ContinuationError(
                    "Outra carga está gravando neste segmento. Aguarde sua conclusão."
                )
        elif self.value is not None:
            raise ContinuationError(
                "O bloqueio da carga foi removido; gravação interrompida."
            )
        proposed = json.dumps(
            {"owner": self.owner, "expires": now + LEASE_SECONDS}, sort_keys=True
        )
        requests = []
        if previous is not None:
            requests.append(
                {"deleteDeveloperMetadata": {"dataFilter": self._filter(previous)}}
            )
        requests.append(
            {
                "createDeveloperMetadata": {
                    "developerMetadata": {
                        "metadataId": LEASE_ID,
                        "metadataKey": LEASE_KEY,
                        "metadataValue": proposed,
                        "location": {"spreadsheet": True},
                        "visibility": "DOCUMENT",
                    }
                }
            }
        )
        try:
            self.book.batch_update({"requests": requests})
        except (APIError, RequestException, TransportError):
            # Confirmar por leitura: nunca repetir cegamente a tomada do bloqueio.
            if self._lookup() != proposed:
                raise
        if self._lookup() != proposed:
            raise ContinuationError("Não foi possível confirmar o bloqueio remoto.")
        self.value, self.renewed_at = proposed, now

    def release(self):
        if self.value is None:
            return
        if self.uncertain:
            logging.warning(
                "Google Sheets: gravação sem confirmação; a proteção remota será mantida por até 5 minutos para permitir a retomada segura."
            )
            self.value = None
            return
        try:
            self.book.batch_update(
                {
                    "requests": [
                        {
                            "deleteDeveloperMetadata": {
                                "dataFilter": self._filter(self.value)
                            }
                        }
                    ]
                }
            )
        except (APIError, RequestException, TransportError):
            logging.warning(
                "A liberação da trava remota não foi confirmada; aguarde a expiração de até 5 minutos antes de outra carga."
            )
        finally:
            self.value = None
