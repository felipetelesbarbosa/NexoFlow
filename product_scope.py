"""Escopo comercial da farmácia, por evidência explícita no catálogo.

O filtro usa nome e categoria; não presume uso animal de princípios ativos
compartilhados com medicamentos humanos ou de embalagens identificadas PET.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from typing import Any


def _normalized(value: Any) -> str:
    return _normalized_text(str(value or ""))


@lru_cache(maxsize=32768)
def _normalized_text(value: str) -> str:
    text = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in text if not unicodedata.combining(char))


_ANIMAL_TERMS = re.compile(
    r"\b(?:caes|cao|cachorros?|gatos?|felin[oa]s?|canin[oa]s?|"
    r"equinos?|bovinos?|suinos?|aves|passaros?|papagaios?|periquitos?|coelhos?|roedores?|hamsters?|"
    r"pet\s*shop|petfood|veterinari\w*|vet|racoes|racao|antipulgas?|"
    r"carrapaticidas?|anticarrapatos?|vermivet|doxivet|ciprovet|"
    r"bravecto|nexgard|simparic|credelio|drontal|milbemax|endogard|canex|"
    r"capstar|silmox|prediderm|petix|huspet|pipicat|frontline|"
    r"vetnil|biovet|organnact|nutrisana|cispet|alantol|periovet|promun|"
    r"virbac|vibrac|cardalis)\b"
)
_CATEGORY_TERMS = re.compile(r"\b(?:pets?|animais?|animal|vet|veterinari\w*)\b")
_PET_PRODUCT = re.compile(
    r"\b(?:petiscos?\s+(?:p\s*/?\s*|para\s+)?(?:pets?|caes|cao|gatos?)|"
    r"areia\b[^,;\n]*\bcats?|areia\s+hig\w*|tapete\s+hig\w*|"
    r"(?:spin\s+pet|great\s+pets|finotrato|granplus)|uso\s+(?:animal|vet)|"
    r"patas|sup(?:lem)?\b[^,;\n]*\b(?:dogs?|cats?)|"
    r"brinq\w*\b[^,;\n]*\bpetisco|cama\b[^,;\n]*\bpet)\b"
)


def is_animal_product(item: dict[str, Any]) -> bool:
    name = _normalized(item.get("produto_nome") or item.get("nome"))
    category = _normalized(item.get("categoria"))
    return bool(
        _ANIMAL_TERMS.search(name)
        or _PET_PRODUCT.search(name)
        or _ANIMAL_TERMS.search(category)
        or _CATEGORY_TERMS.search(category)
    )


def pharmacy_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Preserve ordem e valores dos itens sem indicação de uso animal."""
    return [item for item in items if not is_animal_product(item)]
