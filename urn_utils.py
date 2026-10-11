from __future__ import annotations

from dataclasses import dataclass
from typing import Any

CHANNEL_PRIORITY = ("whatsapp", "instagram", "facebook")
CHANNEL_FIELD_MAP = {
    "whatsapp": "contact_urn_whatsapp",
    "instagram": "contact_urn_instagram",
    "facebook": "contact_urn_facebook",
}


@dataclass(frozen=True)
class ResolvedContactUrns:
    principal_urn: str
    principal_channel: str
    channel_urns: dict[str, str]
    native_urns: tuple[str, ...]


def _text(value: Any) -> str:
    return str(value or "").strip()


def urn_channel(urn: Any) -> str:
    """Classifica somente esquemas de URN conhecidos, sem inferir origem de anúncio."""
    text = _text(urn)
    if not text:
        return ""
    scheme = text.split(":", 1)[0].strip().casefold()
    if (
        scheme == "whatsapp"
        or scheme.startswith("whatsapp-")
        or scheme.startswith("whatsapp_")
    ):
        return "whatsapp"
    if (
        scheme == "instagram"
        or scheme.startswith("instagram-")
        or scheme.startswith("instagram_")
    ):
        return "instagram"
    if (
        scheme
        in {
            "facebook",
            "messenger",
            "facebookmessenger",
            "facebook-messenger",
            "facebook_messenger",
            "fb",
        }
        or scheme.startswith("facebook-")
        or scheme.startswith("facebook_")
        or scheme.startswith("messenger-")
        or scheme.startswith("messenger_")
    ):
        return "facebook"
    return "other"


def native_contact_urns(contact: dict[str, Any]) -> tuple[str, ...]:
    """Retorna as URNs nativas da Weni em ordem estável, sem fabricar valores."""
    values: list[str] = []
    urns = contact.get("urns")
    if isinstance(urns, list):
        for item in urns:
            text = _text(item)
            if text and text not in values:
                values.append(text)

    fallback = _text(contact.get("urn"))
    if fallback and fallback not in values:
        values.append(fallback)
    return tuple(values)


def _fields(contact: dict[str, Any], fields: dict[str, Any] | None) -> dict[str, Any]:
    if fields is not None:
        return fields
    value = contact.get("fields")
    return value if isinstance(value, dict) else {}


def resolve_contact_urns(
    contact: dict[str, Any],
    fields: dict[str, Any] | None = None,
) -> ResolvedContactUrns:
    """
    Resolve as identidades de canal usando a Weni como fonte de verdade.

    Prioridade do principal quando há URNs nativas reconhecidas:
    WhatsApp > Instagram > Facebook/Messenger > primeira URN nativa de outro esquema.

    Campos já preenchidos só são usados como fallback ou para manter a mesma URN
    quando ela continua presente na lista nativa. Nunca é inventada uma URN.
    """
    current = _fields(contact, fields)
    native = native_contact_urns(contact)

    by_channel: dict[str, list[str]] = {channel: [] for channel in CHANNEL_PRIORITY}
    for urn in native:
        channel = urn_channel(urn)
        if channel in by_channel:
            by_channel[channel].append(urn)

    resolved: dict[str, str] = {}
    for channel in CHANNEL_PRIORITY:
        field_name = CHANNEL_FIELD_MAP[channel]
        existing = _text(current.get(field_name))
        candidates = by_channel[channel]
        if existing and existing in candidates:
            resolved[channel] = existing
        elif candidates:
            resolved[channel] = candidates[0]
        elif existing and urn_channel(existing) == channel:
            # Não apagamos uma identidade válida apenas porque ela não veio nesta resposta.
            resolved[channel] = existing
        else:
            resolved[channel] = ""

    principal_urn = ""
    principal_channel = ""

    # Quando a Weni retorna um canal reconhecido, ele governa a escolha do principal.
    for channel in CHANNEL_PRIORITY:
        native_candidates = by_channel[channel]
        if native_candidates:
            chosen = (
                resolved[channel]
                if resolved[channel] in native_candidates
                else native_candidates[0]
            )
            principal_urn = chosen
            principal_channel = channel
            break

    if not principal_urn:
        existing_principal = _text(current.get("contact_urn"))
        if existing_principal:
            principal_urn = existing_principal
            principal_channel = urn_channel(existing_principal)
        elif native:
            principal_urn = native[0]
            principal_channel = urn_channel(principal_urn)
        else:
            for channel in CHANNEL_PRIORITY:
                if resolved[channel]:
                    principal_urn = resolved[channel]
                    principal_channel = channel
                    break

    if principal_channel == "other":
        principal_channel = "outro"

    return ResolvedContactUrns(
        principal_urn=principal_urn,
        principal_channel=principal_channel,
        channel_urns=resolved,
        native_urns=native,
    )
