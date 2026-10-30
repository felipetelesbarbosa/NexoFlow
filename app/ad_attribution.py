from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse

from urn_utils import urn_channel

GOOGLE_ADS_ORIGIN = "Google Ads"
META_ADS_ORIGIN = "Meta Ads"

# Campos genéricos já usados pelo projeto para primeira/última atribuição.
GOOGLE_ADS_BASE_WRITE_FIELDS = {
    "primeiro_anuncio_origem",
    "primeiro_anuncio_id",
    "primeiro_anuncio_titulo",
    "primeiro_anuncio_url",
    "primeiro_anuncio_clique_id",
    "primeiro_anuncio_data",
    "ultimo_anuncio_origem",
    "ultimo_anuncio_id",
    "ultimo_anuncio_titulo",
    "ultimo_anuncio_url",
    "ultimo_anuncio_clique_id",
    "ultimo_anuncio_data",
}

# Metadados adicionais. São opcionais: só são escritos se os campos existirem na Weni.
GOOGLE_ADS_EXTRA_WRITE_FIELDS = {
    "primeiro_anuncio_tipo_campanha",
    "primeiro_anuncio_canal_destino",
    "ultimo_anuncio_tipo_campanha",
    "ultimo_anuncio_canal_destino",
}

GOOGLE_ADS_WRITE_FIELDS = GOOGLE_ADS_BASE_WRITE_FIELDS | GOOGLE_ADS_EXTRA_WRITE_FIELDS
AD_CLEARABLE_FIELDS = {
    "ultimo_anuncio_titulo",
    "ultimo_anuncio_url",
    "ultimo_anuncio_clique_id",
    "ultimo_anuncio_tipo_campanha",
    "ultimo_anuncio_canal_destino",
}

_CLICK_KEYS = ("gclid", "gbraid", "wbraid")
_URL_KEYS = {
    "url",
    "source_url",
    "referrer",
    "referer",
    "landing_page",
    "final_url",
    "destination_url",
    "link",
}
_SOURCE_KEYS = {
    "utm_source",
    "source",
    "ad_source",
    "ads_source",
    "platform",
    "ad_platform",
}
_MEDIUM_KEYS = {"utm_medium", "medium"}
_CAMPAIGN_TYPE_KEYS = {
    "campaign_type",
    "utm_campaign_type",
    "google_ads_campaign_type",
    "google_campaign_type",
}
_CAMPAIGN_ID_KEYS = {
    "ad_id",
    "creative_id",
    "google_ads_ad_id",
    "google_ad_id",
}
_TITLE_KEYS = {
    "headline",
    "ad_title",
    "creative_name",
    "utm_content",
}

_KEY_NORMALIZER = re.compile(r"[^a-z0-9]+")
_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_QUERY_TOKEN_RE = re.compile(
    r"(?i)(?:^|[?&\s])(?P<key>gclid|gbraid|wbraid|utm_source|utm_medium|utm_campaign|utm_content|utm_campaign_type|campaign_type|google_ads_campaign_type|ad_id|creative_id)=(?P<value>[^&\s]+)"
)


@dataclass(frozen=True)
class AdAttribution:
    occurred_at: str
    message_id: str
    click_id: str
    click_id_type: str
    ad_id: str
    title: str
    url: str
    campaign_type: str
    destination_channel: str
    reason: str
    origin: str = GOOGLE_ADS_ORIGIN


# Compatibilidade com consumidores do detector Google existente.
GoogleAdsAttribution = AdAttribution


def extract_meta_ads_attribution(message: dict[str, Any]) -> AdAttribution | None:
    """Lê referral estruturado; texto e ausência de metadados não provam anúncio.

    A API pública messages.json pode omitir o referral recebido pelo canal.
    Este detector não recupera dados que a Weni não disponibiliza.
    """
    if str(message.get("direction") or "").strip().casefold() not in {
        "in",
        "incoming",
        "received",
    }:
        return None
    metadata = message.get("metadata")
    containers = [message]
    if isinstance(metadata, dict):
        containers.append(metadata)
    referrals = [c["referral"] for c in containers if "referral" in c]
    if not referrals or any(not isinstance(r, dict) for r in referrals):
        return None
    referral = referrals[0]
    if any(r != referral for r in referrals[1:]):
        return None
    if _text(referral.get("source_type")).casefold() != "ad":
        return None
    ad_id = _text(referral.get("source_id"))
    if (
        not ad_id.isascii()
        or not ad_id.isdecimal()
        or int(ad_id) <= 0
        or not _message_id(message)
    ):
        return None
    destination = urn_channel(_message_urn(message))
    if destination == "other":
        destination = "outro"
    click_id = _text(referral.get("ctwa_clid"))
    return AdAttribution(
        occurred_at=_message_created_on(message),
        message_id=_message_id(message),
        click_id=click_id,
        click_id_type="ctwa_clid" if click_id else "",
        ad_id=ad_id,
        title=_text(referral.get("headline")),
        url=_text(referral.get("source_url")),
        # Referral não informa o objetivo da campanha no Gerenciador Meta.
        campaign_type="",
        destination_channel=destination,
        reason=(
            "evidência explícita de Meta Ads; referral.source_type=ad e source_id presentes"
            + (
                "; fonte=events.json"
                if message.get("event_source") == "weni_events_ctwa"
                else ""
            )
        ),
        origin=META_ADS_ORIGIN,
    )


def _norm_key(value: Any) -> str:
    text = str(value or "").strip().casefold()
    return _KEY_NORMALIZER.sub("_", text).strip("_")


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value).strip()
    return ""


def _flatten_strings(
    value: Any, *, path: tuple[str, ...] = (), depth: int = 0
) -> list[tuple[str, str]]:
    """Extrai strings de metadados sem interpretar objetos arbitrários como atribuição."""
    if depth > 5:
        return []
    out: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = _norm_key(key)
            child_path = path + (normalized,)
            if isinstance(item, (dict, list)):
                out.extend(_flatten_strings(item, path=child_path, depth=depth + 1))
            else:
                text = _text(item)
                if text:
                    out.append((".".join(child_path), text))
    elif isinstance(value, list):
        for item in value:
            out.extend(_flatten_strings(item, path=path, depth=depth + 1))
    return out


def _last_key(path: str) -> str:
    return path.rsplit(".", 1)[-1]


def _query_values(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    candidates = list(_URL_RE.findall(text))
    if not candidates and any(
        token in text.casefold()
        for token in ("gclid=", "gbraid=", "wbraid=", "utm_source=")
    ):
        candidates.append(text)

    for candidate in candidates:
        try:
            query = urlparse(candidate).query
            parsed = parse_qs(query, keep_blank_values=False)
            for key, items in parsed.items():
                if not items:
                    continue
                normalized = _norm_key(key)
                value = str(items[-1]).strip()
                if value and normalized not in values:
                    values[normalized] = value
        except ValueError:
            pass

    for match in _QUERY_TOKEN_RE.finditer(text):
        key = _norm_key(match.group("key"))
        value = match.group("value").strip().rstrip(".,;)")
        if value and key not in values:
            values[key] = value
    return values


def _first_field(
    items: Iterable[tuple[str, str]], keys: set[str] | tuple[str, ...]
) -> str:
    key_set = set(keys)
    for path, value in items:
        if _last_key(path) in key_set and value:
            return value
    return ""


def _campaign_type(value: str, *, source: str = "", medium: str = "") -> str:
    explicit = str(value or "").strip().casefold().replace("_", " ").replace("-", " ")
    explicit = " ".join(explicit.split())
    mappings = (
        (("performance max", "pmax", "performancemax"), "Performance Max"),
        (("search", "pesquisa", "paid search", "paidsearch"), "Search"),
        (("display", "banner", "gdn"), "Display/Banner"),
        (("youtube", "you tube", "video"), "YouTube"),
        (("demand gen", "demandgen", "discovery"), "Demand Gen"),
        (("shopping",), "Shopping"),
    )
    if explicit:
        for aliases, label in mappings:
            if explicit in aliases:
                return label

    src = str(source or "").strip().casefold()
    med = str(medium or "").strip().casefold().replace("_", " ").replace("-", " ")
    # Só classifica quando o meio é explícito. CPC sozinho não distingue Search de PMax.
    if "youtube" in src or med in {"video", "youtube", "paid video"}:
        return "YouTube"
    if med in {"display", "banner", "gdn", "paid display"}:
        return "Display/Banner"
    if med in {"search", "paid search", "sem"}:
        return "Search"
    return ""


def _is_google_source(source: str) -> bool:
    value = str(source or "").strip().casefold().replace("_", " ").replace("-", " ")
    value = " ".join(value.split())
    return value in {
        "google",
        "google ads",
        "googleads",
        "adwords",
        "google adwords",
        "youtube ads",
    }


def _message_id(message: dict[str, Any]) -> str:
    return str(
        message.get("id") or message.get("uuid") or message.get("message_id") or ""
    ).strip()


def _message_created_on(message: dict[str, Any]) -> str:
    return str(
        message.get("created_on")
        or message.get("created_at")
        or message.get("timestamp")
        or ""
    ).strip()


def _message_urn(message: dict[str, Any]) -> str:
    for key in ("urn", "contact_urn"):
        value = str(message.get(key) or "").strip()
        if value:
            return value
    contact = message.get("contact")
    if isinstance(contact, dict):
        value = str(contact.get("urn") or "").strip()
        if value:
            return value
    return ""


def extract_google_ads_attribution(
    message: dict[str, Any],
) -> GoogleAdsAttribution | None:
    """
    Detecta somente evidência explícita de Google Ads.

    A origem é aceita quando há gclid/gbraid/wbraid, marcador explícito Google Ads/AdWords,
    ou UTM de origem Google com contexto pago. Não infere Google Ads apenas por domínio google.com.
    """
    direction = str(message.get("direction") or "").strip().casefold()
    if direction in {"out", "outgoing", "sent"}:
        return None
    items = _flatten_strings(message)
    query: dict[str, str] = {}
    url = ""

    structured_keys = (
        _URL_KEYS
        | set(_CLICK_KEYS)
        | _SOURCE_KEYS
        | _MEDIUM_KEYS
        | _CAMPAIGN_TYPE_KEYS
        | _CAMPAIGN_ID_KEYS
        | _TITLE_KEYS
    )
    for path, value in items:
        key = _last_key(path)
        # Atribuição usa campos/metadados estruturados da Weni. Não varremos o
        # texto livre por URLs com gclid: o cliente poderia apenas colar um link
        # de anúncio durante uma conversa já existente.
        if key not in structured_keys:
            continue
        if (
            not url
            and key in _URL_KEYS
            and value.lower().startswith(("http://", "https://"))
        ):
            url = value
        for qkey, qvalue in _query_values(value).items():
            query.setdefault(qkey, qvalue)
        if not url and key in _URL_KEYS:
            match = _URL_RE.search(value)
            if match:
                candidate_url = match.group(0).rstrip(".,;)")
                candidate_query = _query_values(candidate_url)
                if any(k in candidate_query for k in (*_CLICK_KEYS, "utm_source")):
                    url = candidate_url

    click_id = ""
    click_type = ""
    for key in _CLICK_KEYS:
        direct = _first_field(items, {key})
        candidate = direct or query.get(key, "")
        if candidate:
            click_id = candidate
            click_type = key
            break

    source = _first_field(items, _SOURCE_KEYS) or query.get("utm_source", "")
    medium = _first_field(items, _MEDIUM_KEYS) or query.get("utm_medium", "")
    explicit_type = (
        _first_field(items, _CAMPAIGN_TYPE_KEYS)
        or query.get("utm_campaign_type", "")
        or query.get("campaign_type", "")
        or query.get("google_ads_campaign_type", "")
    )
    ad_id = (
        _first_field(items, _CAMPAIGN_ID_KEYS)
        or query.get("ad_id", "")
        or query.get("creative_id", "")
    )
    title = _first_field(items, _TITLE_KEYS) or query.get("utm_content", "")

    # Marcadores explícitos em chaves também contam, mesmo sem UTM.
    has_google_key = any(
        "google_ads" in path or "googlead" in path or "adwords" in path
        for path, _ in items
    )
    paid_medium = str(medium or "").strip().casefold() in {
        "cpc",
        "ppc",
        "paid",
        "paid_search",
        "paid-search",
        "search",
        "sem",
        "display",
        "banner",
        "gdn",
        "video",
        "youtube",
        "paid_video",
        "paid-video",
    }
    google_source = _is_google_source(source)

    if not (click_id or has_google_key or (google_source and paid_medium)):
        return None

    campaign_type = _campaign_type(explicit_type, source=source, medium=medium)
    destination = urn_channel(_message_urn(message))
    if destination == "other":
        destination = "outro"

    reason_parts = ["evidência explícita de Google Ads"]
    if click_type:
        reason_parts.append(f"{click_type} presente")
    elif google_source:
        reason_parts.append("origem/UTM Google Ads")
    if campaign_type:
        reason_parts.append(f"campanha={campaign_type}")
    if destination:
        reason_parts.append(f"destino={destination}")

    return GoogleAdsAttribution(
        occurred_at=_message_created_on(message),
        message_id=_message_id(message),
        click_id=click_id,
        click_id_type=click_type,
        ad_id=ad_id,
        title=title,
        url=url,
        campaign_type=campaign_type,
        destination_channel=destination,
        reason="; ".join(reason_parts),
    )
