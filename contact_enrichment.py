from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class FieldEvidence:
    field: str
    value: str | int
    message_id: str
    created_on: str
    reason: str


@dataclass(frozen=True)
class MessageView:
    message_id: str
    created_on: str
    text: str
    direction: str


def normalize_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text)


def message_id(message: dict[str, Any]) -> str:
    value = message.get("id")
    if value in (None, ""):
        value = message.get("uuid")
    return str(value or "").strip()


def message_created_on(message: dict[str, Any]) -> str:
    for key in ("created_on", "sent_on", "modified_on"):
        value = str(message.get(key) or "").strip()
        if value:
            return value
    return ""


def message_text(message: dict[str, Any]) -> str:
    value = message.get("text")
    if isinstance(value, str):
        return value.strip()
    return str(value or "").strip()


def message_direction(message: dict[str, Any]) -> str:
    raw = normalize_text(message.get("direction"))
    if raw in {"in", "incoming", "inbound"}:
        return "in"
    if raw in {"out", "outgoing", "outbound"}:
        return "out"

    folder = normalize_text(message.get("folder"))
    if folder in {"incoming", "inbox"}:
        return "in"
    if folder in {"sent", "outbox", "flows"}:
        return "out"
    return raw


def _parse_datetime(value: str) -> datetime:
    text = (value or "").strip()
    if not text:
        return datetime.min.replace(tzinfo=UTC)
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)


def _view(message: dict[str, Any]) -> MessageView:
    return MessageView(
        message_id=message_id(message),
        created_on=message_created_on(message),
        text=message_text(message),
        direction=message_direction(message),
    )


AGE_DIRECT_PATTERNS = (
    re.compile(r"\b(?:eu\s+)?tenho\s+(\d{1,3})\s*anos?\b", re.I),
    re.compile(r"\bminha\s+idade\s+(?:e|eh|é)?\s*[:=-]?\s*(\d{1,3})\s*anos?\b", re.I),
    re.compile(r"\b(?:fiz|completei|completo)\s+(\d{1,3})\s*anos?\b", re.I),
)

ADULT_PATTERNS = (
    "sou maior de idade",
    "sou maior de 18",
    "tenho mais de 18",
    "tenho 18 ou mais",
    "ja sou maior de idade",
    "sou de maior",
)

MINOR_PATTERNS = (
    "sou menor de idade",
    "sou menor de 18",
    "tenho menos de 18",
    "nao sou maior de idade",
    "nao tenho 18 anos",
)

AGE_CONTEXT_PATTERNS = (
    re.compile(r"\bqual\s+(?:e\s+)?(?:a\s+)?sua\s+idade\b", re.I),
    re.compile(r"\bquantos\s+anos\b", re.I),
    re.compile(r"\binforme\s+(?:a\s+)?sua\s+idade\b", re.I),
    re.compile(r"\bdigite\s+(?:a\s+)?sua\s+idade\b", re.I),
)

MAJORITY_CONTEXT_MARKERS = (
    "maior de 18",
    "18 anos ou mais",
    "maior de idade",
    "tem 18 anos",
    "possui 18 anos",
)

LGPD_CONTEXT_MARKERS = (
    "lgpd",
    "tratamento de dados",
    "dados pessoais",
    "politica de privacidade",
    "politica de dados",
    "consentimento",
    "consentir",
    "privacidade",
)

LGPD_ACCEPT_MARKERS = (
    "aceito",
    "eu aceito",
    "concordo",
    "autorizo",
    "dou consentimento",
    "consinto",
)

LGPD_REFUSE_MARKERS = (
    "nao aceito",
    "não aceito",
    "nao concordo",
    "não concordo",
    "nao autorizo",
    "não autorizo",
    "recuso",
    "nao consinto",
    "não consinto",
)

CPF_CONTEXT_PATTERNS = (
    re.compile(r"\b(?:qual\s+(?:e\s+)?(?:o\s+)?)?cpf\b", re.I),
    re.compile(r"\binforme\s+(?:o\s+)?(?:seu\s+)?cpf\b", re.I),
    re.compile(r"\bdigite\s+(?:o\s+)?(?:seu\s+)?cpf\b", re.I),
    re.compile(r"\bconfirme\s+(?:o\s+)?(?:seu\s+)?cpf\b", re.I),
    re.compile(r"\bnumero\s+do\s+cpf\b", re.I),
)

# Aceita 11 dígitos contínuos ou a apresentação usual 000.000.000-00.
# Os lookarounds impedem capturar um trecho de telefone/código maior.
CPF_TOKEN_PATTERN = re.compile(
    r"(?<!\d)(\d{3}[.\s]?\d{3}[.\s]?\d{3}[-\s]?\d{2})(?!\d)"
)


def _normalize_cpf(value: str) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _is_valid_cpf(value: str) -> bool:
    cpf = _normalize_cpf(value)
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False

    def digit(base: str, factor: int) -> str:
        total = sum(
            int(number) * weight
            for number, weight in zip(base, range(factor, 1, -1), strict=False)
        )
        result = (total * 10) % 11
        return "0" if result == 10 else str(result)

    return cpf[9] == digit(cpf[:9], 10) and cpf[10] == digit(cpf[:10], 11)


def _cpf_candidates(text: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for match in CPF_TOKEN_PATTERN.finditer(text or ""):
        cpf = _normalize_cpf(match.group(1))
        if cpf in seen or not _is_valid_cpf(cpf):
            continue
        seen.add(cpf)
        found.append(cpf)
    return found


def _is_cpf_context(text: str) -> bool:
    normalized = normalize_text(text)
    if "cpf" in normalized:
        return True
    return any(pattern.search(normalized) for pattern in CPF_CONTEXT_PATTERNS)


def _direct_cpf(text: str) -> str | None:
    # Fora de uma resposta contextual, exige que a mensagem apresente o CPF
    # como sendo do próprio cliente ("meu CPF") ou use um rótulo direto
    # ("CPF: ..."). Isso evita capturar CPF de terceiro citado na conversa.
    normalized = normalize_text(text)
    explicit_self = bool(
        re.search(r"\b(?:o\s+)?meu\s+(?:(?:novo|correto|atual)\s+)?cpf\b", normalized)
        or re.search(r"\bcpf\s*(?::|=|-)\s*", normalized)
        or re.search(r"\bcpf\s+(?:novo|correto|atual)\b", normalized)
    )
    if not explicit_self:
        return None
    candidates = _cpf_candidates(text)
    return candidates[0] if len(candidates) == 1 else None


def _standalone_cpf(text: str) -> str | None:
    # Resposta curta contendo somente o documento. Exige pergunta contextual
    # anterior no fluxo para não confundir CPF com pedido, telefone ou código.
    candidates = _cpf_candidates(text)
    if len(candidates) != 1:
        return None
    residual = CPF_TOKEN_PATTERN.sub("", text or "")
    residual = re.sub(r"[\s:;,.\-_/()]+", "", residual)
    return candidates[0] if residual == "" else None


def _valid_age(value: int) -> bool:
    return 1 <= value <= 120


def _extract_direct_age(text: str) -> int | None:
    for pattern in AGE_DIRECT_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        age = int(match.group(1))
        if _valid_age(age):
            return age
    return None


def _standalone_age(text: str) -> int | None:
    match = re.fullmatch(r"\s*(\d{1,3})\s*(?:anos?)?\s*[.!]?\s*", text, re.I)
    if not match:
        return None
    age = int(match.group(1))
    return age if _valid_age(age) else None


def _is_age_question(text: str) -> bool:
    return any(pattern.search(text) for pattern in AGE_CONTEXT_PATTERNS)


def _is_majority_question(text: str) -> bool:
    normalized = normalize_text(text)
    return any(marker in normalized for marker in MAJORITY_CONTEXT_MARKERS)


def _is_lgpd_context(text: str) -> bool:
    normalized = normalize_text(text)
    return any(marker in normalized for marker in LGPD_CONTEXT_MARKERS)


def _yes_no(text: str) -> bool | None:
    normalized = normalize_text(text)
    normalized = re.sub(r"[^a-z0-9 ]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if normalized in {"sim", "s", "aceito", "concordo", "autorizo"}:
        return True
    if normalized in {"nao", "n", "recuso", "nao aceito", "nao concordo"}:
        return False
    return None


def _direct_majority(text: str) -> str | None:
    normalized = normalize_text(text)
    if any(marker in normalized for marker in MINOR_PATTERNS):
        return "não"
    if any(marker in normalized for marker in ADULT_PATTERNS):
        return "sim"
    return None


def _direct_lgpd(text: str) -> str | None:
    if not _is_lgpd_context(text):
        return None
    normalized = normalize_text(text)
    refuse = tuple(normalize_text(item) for item in LGPD_REFUSE_MARKERS)
    accept = tuple(normalize_text(item) for item in LGPD_ACCEPT_MARKERS)
    if any(marker in normalized for marker in refuse):
        return "recusado"
    if any(marker in normalized for marker in accept):
        return "ativo"
    return None


def _previous_prompt(views: list[MessageView], index: int) -> MessageView | None:
    # Prioriza uma mensagem de saída/flow, mas aceita a mensagem anterior
    # quando a API não informar direction. Limita a busca a 8 mensagens para
    # evitar usar contexto distante.
    fallback: MessageView | None = None
    for candidate in reversed(views[max(0, index - 8):index]):
        if not candidate.text:
            continue
        if fallback is None:
            fallback = candidate
        if candidate.direction == "out":
            return candidate
    return fallback


def infer_contact_fields(
    context_messages: Iterable[dict[str, Any]],
    *,
    candidate_message_ids: set[str],
) -> dict[str, FieldEvidence]:
    """
    Infere somente campos de baixo risco a partir de mensagens novas.

    Respostas curtas (ex.: "Sim", "Não", "27" ou um CPF isolado) só são aceitas
    quando há contexto explícito imediatamente anterior sobre maioridade, LGPD, idade ou CPF.
    Para CPF, somente documentos com 11 dígitos e dígitos verificadores válidos são aceitos.
    """
    views = [_view(message) for message in context_messages]
    views.sort(key=lambda item: (_parse_datetime(item.created_on), item.message_id))

    evidences: dict[str, FieldEvidence] = {}

    def save(field: str, value: str | int, current: MessageView, reason: str) -> None:
        evidences[field] = FieldEvidence(
            field=field,
            value=value,
            message_id=current.message_id,
            created_on=current.created_on,
            reason=reason,
        )

    for index, current in enumerate(views):
        if current.message_id not in candidate_message_ids:
            continue
        if not current.text:
            continue

        direct_cpf = _direct_cpf(current.text)
        if direct_cpf is not None:
            save(
                "cpf",
                direct_cpf,
                current,
                "CPF válido informado explicitamente pelo cliente",
            )

        direct_age = _extract_direct_age(current.text)
        if direct_age is not None:
            save("idade", direct_age, current, "idade explícita na mensagem")
            save(
                "maior_de_18_anos",
                "sim" if direct_age >= 18 else "não",
                current,
                "maioridade calculada a partir da idade explícita",
            )

        direct_majority = _direct_majority(current.text)
        if direct_majority is not None:
            save(
                "maior_de_18_anos",
                direct_majority,
                current,
                "maioridade declarada explicitamente",
            )

        direct_lgpd = _direct_lgpd(current.text)
        if direct_lgpd is not None:
            save(
                "opt_in_lgpd",
                direct_lgpd,
                current,
                "decisão LGPD explícita na mensagem",
            )

        previous = _previous_prompt(views, index)
        if previous is None:
            continue

        standalone_cpf = _standalone_cpf(current.text)
        if standalone_cpf is not None and _is_cpf_context(previous.text):
            save(
                "cpf",
                standalone_cpf,
                current,
                "CPF válido informado em resposta à solicitação de CPF",
            )

        standalone_age = _standalone_age(current.text)
        if standalone_age is not None and _is_age_question(previous.text):
            save(
                "idade",
                standalone_age,
                current,
                "idade informada em resposta a pergunta de idade",
            )
            save(
                "maior_de_18_anos",
                "sim" if standalone_age >= 18 else "não",
                current,
                "maioridade calculada a partir da idade informada",
            )

        yes_no = _yes_no(current.text)
        if yes_no is None:
            continue

        if _is_majority_question(previous.text):
            save(
                "maior_de_18_anos",
                "sim" if yes_no else "não",
                current,
                "resposta contextual à validação de maioridade",
            )

        if _is_lgpd_context(previous.text):
            save(
                "opt_in_lgpd",
                "ativo" if yes_no else "recusado",
                current,
                "resposta contextual à solicitação LGPD",
            )

    return evidences
