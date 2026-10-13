"""Padronização local e determinística de endereços, sem consultar APIs."""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from functools import lru_cache
from typing import Any

from geography_catalog import MUNICIPALITIES, NEIGHBORHOODS, STATES

GEOGRAPHY_FIELDS = frozenset({"cidade", "estado", "bairro"})
GEOGRAPHY_VERSION = "geography_v1"


def _text(value: Any) -> str:
    while isinstance(value, dict) and "value" in value:
        value = value["value"]
    return "" if value is None else str(value).strip()


@lru_cache(maxsize=16384)
def _key(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    text = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(re.findall(r"[a-z0-9]+", text))


_STATES = {_key(name): uf for uf, name in STATES.items()}
_STATES.update({_key(uf): uf for uf in STATES})
_CITIES: dict[str, list[tuple[str, str]]] = defaultdict(list)
for _name, _uf in MUNICIPALITIES:
    _CITIES[_key(_name)].append((_name, _uf))
_NEIGHBORHOODS = {
    city: {_key(name): name for name in names} for city, names in NEIGHBORHOODS.items()
}

# Grafias revisadas da base. Não usar similaridade livre para trocar localidades.
_CITY_ALIASES = {
    "bele": "Belém",
    "belen": "Belém",
    "belenm": "Belém",
    "bellem": "Belém",
    "belemn": "Belém",
    "anbelem": "Belém",
    "anani": "Ananindeua",
    "ananideua": "Ananindeua",
    "ananindeu": "Ananindeua",
    "anaindeua": "Ananindeua",
    "anindeua": "Ananindeua",
    "aninindeua": "Ananindeua",
    "ananimeuia": "Ananindeua",
    "icoaraci": "Belém",
}
_MISPLACED_CITY = {
    "para",
    "pa",
    "parque verde",
    "cidade nova",
    "curucamba",
    "mangueirao",
    "augusto montenegro",
    "rodovia augusto montenegro",
    "dovia augusto montenegro",
}
_NEIGHBORHOOD_ALIASES = {
    "valdecaes": "Val-de-Cans",
    "valdecans": "Val-de-Cans",
    "val de cans": "Val-de-Cans",
    "val de caes": "Val-de-Cans",
    "val decaes": "Val-de-Cans",
    "curioutinga": "Curió-Utinga",
    "curio utinga": "Curió-Utinga",
    "curio tinga": "Curió-Utinga",
    "sao braz": "São Brás",
    "terrafirme": "Terra Firme",
    "icui guajara": "Icuí-Guajará",
    "icuiguajara": "Icuí-Guajará",
    "icu iguajara": "Icuí-Guajará",
    "icuilaranjeira": "Icuí-Laranjeira",
    "quarenta horas": "40 Horas",
    "40horas": "40 Horas",
    "40 hras": "40 Horas",
    "quarenta horas coqueiro": "40 Horas",
    "coqueiro 40 horas": "40 Horas",
    "quarenta horas coqueiro 385 b": "40 Horas",
    "telegrafo sem fio": "Telégrafo",
    "levilania": "Levilândia",
    "lezilandia": "Levilândia",
    "sousa": "Souza",
    "cfremacao": "Cremação",
    "creamacao": "Cremação",
    "cremcao": "Cremação",
    "cremacaoa": "Cremação",
    "sacramente": "Sacramenta",
    "sacramanta": "Sacramenta",
    "mrambaia": "Marambaia",
    "marambia": "Marambaia",
    "maracangalia": "Maracangalha",
    "cabanazem": "Cabanagem",
    "coquiero": "Coqueiro",
    "coquerio": "Coqueiro",
    "benguim": "Benguí",
    "cidade nvelha": "Cidade Velha",
    "pederira": "Pedreira",
    "pdreira": "Pedreira",
    "castnaheira": "Castanheira",
    "mangeirao": "Mangueirão",
    "park verde": "Parque Verde",
    "parque guaraja": "Parque Guajará",
    "park guajara": "Parque Guajará",
    "humarizal": "Umarizal",
    "umarazal": "Umarizal",
    "umarisal": "Umarizal",
    "gau anabara": "Guanabara",
    "gau an abara": "Guanabara",
    "gauanabara": "Guanabara",
    "julia seffer": "Júlia Sefer",
    "conjunto paar": "PAAR",
    "conjunto maguari": "Maguari",
    "distrito ind": "Distrito Industrial",
    "cid nova": "Cidade Nova",
    "entrocamento": "Entroncamento",
    "entroncamento": "Entroncamento",
    "montese": "Terra Firme",
}
_ROMANS = {
    str(i): r
    for i, r in enumerate(("", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX"))
    if i
}
_NUMBERS = {r.casefold(): number for number, r in _ROMANS.items()}

_COMMON_NAMES = {
    "atlantico": "Atlântico",
    "atlantico 2": "Atlântico II",
    "atlantico ii": "Atlântico II",
    "vila sao geraldo": "Vila São Geraldo",
    "sao vicente": "São Vicente",
    "joao paulo ii": "João Paulo II",
    "sao jose operario": "São José Operário",
    "promissao": "Promissão",
    "fe em deus": "Fé em Deus",
    "nova maraba": "Nova Marabá",
    "almir grabriel": "Almir Gabriel",
}


def _neighborhood(value: str, city: str, uf: str) -> str:
    key = _key(value)
    if key in _COMMON_NAMES:
        return _COMMON_NAMES[key]
    if not key or (uf and uf != "PA") or (city and city not in NEIGHBORHOODS):
        return value
    candidates = (
        (_NEIGHBORHOODS.get(city),)
        if city in NEIGHBORHOODS
        else tuple(_NEIGHBORHOODS.values())
    )
    for catalog in candidates:
        if catalog and key in catalog:
            return catalog[key]
    if key.startswith("bairro "):
        return _neighborhood(value[7:].strip(), city, uf)
    # Distrito redundante, sem apagar ruas/números nem escolher entre dois bairros.
    without_district = re.sub(r"\s+(?:icoaraci|outeiro|mosqueiro|bengui)$", "", key)
    if without_district != key:
        candidate = _neighborhood(without_district, city, uf)
        if candidate != without_district or any(
            without_district in (c or {}) for c in candidates
        ):
            return candidate
    alias = _NEIGHBORHOOD_ALIASES.get(key)
    if alias and (
        alias == "Entroncamento" or any(_key(alias) in (c or {}) for c in candidates)
    ):
        return alias
    # Preservar as subdivisões, corrigindo somente a grafia/numeração equivalente.
    match = re.fullmatch(
        r"(?:conjunto )?(?:cidade|cid)\s*nova\s*(0?[1-9]|i{1,3}|iv|vi{0,3}|ix)", key
    )
    if not match:
        match = re.fullmatch(r"cidade (0?[1-9]) nova", key)
    if match and city in {"", "Ananindeua"}:
        raw = match[1]
        number = str(int(raw)) if raw.isdigit() else _NUMBERS.get(raw, "")
        if number in _ROMANS:
            return "Cidade Nova " + _ROMANS[number]
    match = re.fullmatch(
        r"(pratinha|paracuri|tenone|jaderlandia|guajara)\s*(0?[1-3]|i{1,3})", key
    )
    if match:
        raw = match[2]
        number = str(int(raw)) if raw.isdigit() else _NUMBERS.get(raw, "")
        name = {
            "pratinha": "Pratinha",
            "paracuri": "Paracuri",
            "tenone": "Tenoné",
            "jaderlandia": "Jaderlândia",
            "guajara": "Guajará",
        }[match[1]]
        if number in _ROMANS:
            return name + " " + _ROMANS[number]
    return value


@lru_cache(maxsize=16384)
def canonical_geography(
    city: str, state: str, neighborhood: str, postal_present: bool = False
) -> tuple[str, str, str]:
    """Não preencher campos vazios nem resolver homônimos ou valores desconhecidos."""
    city, state, neighborhood = city.strip(), state.strip(), neighborhood.strip()
    uf = _STATES.get(_key(state), "")
    canonical_state = STATES.get(uf, state)
    city_key = _key(city)
    options = _CITIES.get(city_key, [])
    compatible = [(name, code) for name, code in options if not uf or code == uf]
    if compatible:
        city = compatible[0][0]  # Homônimos têm a mesma grafia; não inferir a UF.
    elif city_key in _CITY_ALIASES and uf in {"", "PA"}:
        city = _CITY_ALIASES[city_key]
    # Recuperar município mal posicionado somente com bairro local inequívoco.
    if city_key in _MISPLACED_CITY and uf == "PA" and not postal_present:
        candidate = _neighborhood(neighborhood, "", uf)
        owners = [
            c for c, catalog in _NEIGHBORHOODS.items() if _key(candidate) in catalog
        ]
        if len(owners) == 1:
            city = owners[0]
        elif _key(neighborhood) == "ananindeua":
            city = "Ananindeua"
    canonical_neighborhood = _neighborhood(neighborhood, city, uf)
    # Dois erros de UF revisados contra os CEPs, sem tratar números como códigos de UF.
    if city == "Belém" and (_key(state), _key(canonical_neighborhood)) in {
        ("51", "tapana"),
        ("en", "nazare"),
    }:
        canonical_state = "Pará"
    return city, canonical_state, canonical_neighborhood


def normalize_geography(
    record: dict[str, Any], *, postal_reference: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Copie o registro, alterando exclusivamente cidade, estado e bairro existentes."""
    result = dict(record)
    if postal_reference and not postal_reference.get("erro"):
        postcode = re.sub(r"\D", "", _text(record.get("cep")))
        reference_code = re.sub(r"\D", "", _text(postal_reference.get("cep")))
        uf = _text(postal_reference.get("uf")).upper()
        locality = _text(postal_reference.get("localidade"))
        if (
            len(postcode) == 8
            and postcode == reference_code
            and (locality, uf) in _CITIES.get(_key(locality), [])
        ):
            for key, value in (
                ("cidade", locality),
                ("estado", STATES[uf]),
                ("bairro", _text(postal_reference.get("bairro"))),
            ):
                if key in result and value:
                    result[key] = value
    values = canonical_geography(
        *(_text(result.get(key)) for key in ("cidade", "estado", "bairro")),
        postal_present=bool(_text(result.get("cep"))),
    )
    for key, value in zip(("cidade", "estado", "bairro"), values, strict=True):
        if key in result:
            result[key] = value
    return result


def geography_changes(fields: dict[str, Any]) -> dict[str, str]:
    clean = normalize_geography(fields)
    return {
        key: clean[key]
        for key in GEOGRAPHY_FIELDS
        if clean.get(key) and fields.get(key) != clean[key]
    }


def geography_review_reason(fields: dict[str, Any]) -> str:
    """Sinalize conflitos para consulta de CEP/revisão, sem adivinhar um endereço."""
    clean = normalize_geography(fields)
    city, neighborhood = clean.get("cidade", ""), clean.get("bairro", "")
    if city and _key(city) not in _CITIES:
        return "MUNICIPIO_NAO_RECONHECIDO"
    if city not in _NEIGHBORHOODS or not neighborhood:
        return ""
    candidate = _neighborhood(_text(fields.get("bairro")), "", "PA")
    key = _key(candidate)
    # Conjuntos reconhecidos continuam associados ao bairro, sem perder números.
    for prefix in (
        "cidade nova",
        "pratinha",
        "paracuri",
        "tenone",
        "jaderlandia",
        "guajara",
    ):
        if re.fullmatch(prefix + r" (?:i{1,3}|iv|vi{0,3}|ix)", key):
            key = prefix
            break
    owners = [name for name, catalog in _NEIGHBORHOODS.items() if key in catalog]
    if owners and city not in owners:
        return "BAIRRO_DE_OUTRO_MUNICIPIO"
    if not owners and candidate == _text(fields.get("bairro")):
        return "BAIRRO_NAO_RECONHECIDO_OU_COMPLEMENTO"
    return ""
