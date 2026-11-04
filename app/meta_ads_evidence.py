"""Evidências CTWA oficiais por projeto, sem trocar o perfil global ou gravar dados."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from meta_events import event_datetime, event_message
from urn_utils import native_contact_urns
from weni_client import WeniClient

PROJECT_NAMES = {"FARMA": "Delivery FarmaLíder", "PET": "Delivery Pets Líder"}


class ReadOnlyEvidenceClient(WeniClient):
    """Transporte existente, limitado a GET e com projeto validado por instância."""

    def __init__(self, token: str, *, segment: str):
        super().__init__(token)
        self.evidence_segment = segment

    def _request_json(self, method, url, **kwargs):
        if method.upper() != "GET":
            raise ValueError("A coleta de evidências Weni permite somente GET.")
        return super()._request_json(method, url, **kwargs)


def _profile(settings: Any, segment: str) -> dict[str, Any]:
    profiles = getattr(settings, "PERFIS", None)
    if isinstance(profiles, dict):
        value = profiles.get(segment, {})
        return value if isinstance(value, dict) else {}
    if segment == "FARMA":
        return {"WENI_API_TOKEN": getattr(settings, "WENI_API_TOKEN", "")}
    return {}


def collect_weni_evidence(
    settings: Any,
    *,
    start: datetime,
    end: datetime,
    segments=("FARMA", "PET"),
    client_factory=None,
    contacts_by_segment: dict[str, list[dict[str, Any]]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Consulta janelas de até sete dias; cobertura incompleta impede rateio exclusivo.

    Um evento sem contato associado continua comprovando o projeto do anúncio,
    mas nunca comprova venda ou conversa distinta. Nenhum dado cadastral é retornado.
    """
    if start.tzinfo is None or end.tzinfo is None or end <= start:
        raise ValueError("O intervalo exige datas com fuso e fim posterior ao início.")
    start, end = start.astimezone(UTC), end.astimezone(UTC)
    factory = client_factory or ReadOnlyEvidenceClient
    report: dict[str, Any] = {
        "segments": {"FARMA": False, "PET": False},
        "history_complete": False,
        "auth_failed": [],
        "details": {},
    }
    result: list[dict[str, Any]] = []
    for segment in dict.fromkeys(segments):
        if segment not in PROJECT_NAMES:
            raise ValueError("Segmento de evidências desconhecido.")
        detail = {
            "status": "incompleto",
            "batches": 0,
            "invalid": 0,
            "unmatched": 0,
            "ambiguous": 0,
            "conflicts": 0,
            "events": 0,
        }
        report["details"][segment] = detail
        profile = _profile(settings, segment)
        token = profile.get("WENI_API_TOKEN")
        if not isinstance(token, str) or not token.strip():
            detail["status"] = "token_ausente"
            continue
        client = None
        complete = True
        rows: dict[str, dict[str, Any]] = {}
        conflicts: set[str] = set()
        try:
            client = factory(token=token, segment=segment)
            org = client.get_org()
            expected_uuid = profile.get("WENI_ORG_UUID")
            if (
                not isinstance(org, dict)
                or org.get("name") != PROJECT_NAMES[segment]
                or (expected_uuid and org.get("uuid") != expected_uuid)
            ):
                detail["status"] = "projeto_divergente"
                continue
            # A prova acima pertence a ESTA instância, inclusive quando o processo
            # opera PET e consulta somente leitura no projeto FARMA (ou vice-versa).
            client._profile_verified = True
            contacts = (contacts_by_segment or {}).get(segment)
            if contacts is None:
                contacts = client.list_contacts()
            if not isinstance(contacts, list):
                raise ValueError("Formato de contatos inválido.")
            urns: dict[str, set[str]] = {}
            for contact in contacts:
                if not isinstance(contact, dict):
                    complete = False
                    detail["invalid"] += 1
                    continue
                uuid = contact.get("uuid")
                if isinstance(uuid, str) and uuid:
                    for urn in native_contact_urns(contact):
                        urns.setdefault(urn, set()).add(uuid)
            cursor = start
            while cursor < end:
                stop = min(cursor + timedelta(days=7), end)
                try:
                    events = client.list_ctwa_events(after=cursor, before=stop)
                    if not isinstance(events, list):
                        raise ValueError("Formato de eventos inválido.")
                    detail["batches"] += 1
                    for event in events:
                        try:
                            if not isinstance(event, dict):
                                raise ValueError("Evento inválido.")
                            message = event_message(event)
                            if message is None:
                                continue
                            date = event_datetime(event.get("date"))
                            if date is None or not cursor <= date < stop:
                                continue
                            meta = event["metadata"]
                            urn = message["urn"]
                            matches = urns.get(urn, set())
                            row = {
                                "segment": segment,
                                "event_id": message["id"],
                                "ad_id": meta["campaign_source"],
                                "date": date.isoformat(),
                                "contact_uuid": next(iter(matches))
                                if len(matches) == 1
                                else "",
                                "contact_urn": urn,
                                "channel": "whatsapp",
                                "channel_uuid": meta["channel"],
                                "clique_id": meta["ctwa_id"],
                                "evidence_source": "weni_events_ctwa",
                                "link_status": "unique"
                                if len(matches) == 1
                                else "ambiguous"
                                if matches
                                else "unmatched",
                            }
                            conversation = meta.get(
                                "conversation_id", event.get("conversation_id")
                            )
                            if isinstance(conversation, str) and conversation:
                                row["conversation_id"] = conversation
                            identity = message["id"]
                            if identity in rows and rows[identity] != row:
                                conflicts.add(identity)
                                complete = False
                            else:
                                rows[identity] = row
                        except (ValueError, KeyError, TypeError):
                            complete = False
                            detail["invalid"] += 1
                except Exception as exc:
                    complete = False
                    detail["status"] = "consulta_falhou"
                    if getattr(exc, "status_code", None) in {401, 403}:
                        report["auth_failed"].append(segment)
                        break
                cursor = stop
            for identity in conflicts:
                rows.pop(identity, None)
            detail["conflicts"] = len(conflicts)
            detail["unmatched"] = sum(
                r["link_status"] == "unmatched" for r in rows.values()
            )
            detail["ambiguous"] = sum(
                r["link_status"] == "ambiguous" for r in rows.values()
            )
            complete = complete and not detail["ambiguous"]
            detail["events"] = len(rows)
            report["segments"][segment] = complete
            if complete:
                detail["status"] = "completo"
            result.extend(rows.values())
        except Exception as exc:
            detail["status"] = "consulta_falhou"
            if getattr(exc, "status_code", None) in {401, 403}:
                report["auth_failed"].append(segment)
        finally:
            if client is not None:
                client.close()
    return sorted(
        result, key=lambda row: (row["segment"], row["date"], row["event_id"])
    ), report
