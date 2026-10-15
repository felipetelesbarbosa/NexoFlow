from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from config import WENI_UPDATE_CONTEXT_LOOKBACK_HOURS


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
    "mais de 18 anos",
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
CPF_TOKEN_PATTERN = re.compile(r"(?<!\d)(\d{3}[.\s]?\d{3}[.\s]?\d{3}[-\s]?\d{2})(?!\d)")


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
    return any(marker in normalized for marker in LGPD_CONTEXT_MARKERS) or bool(
        re.search(
            r"\b(?:uso|utilizacao|tratamento)\s+(?:de|dos|das)\s+"
            r"(?:(?:seus|suas|meus|minhas)\s+)?dados\b",
            normalized,
        )
    )


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
    response = _lgpd_response(text)
    if response is False:
        if _direct_majority(text) == "não" and re.search(
            r"\b(?:aceito|autorizo|concordo com|consinto com)\s+(?:o\s+|a\s+)?"
            r"(?:uso|tratamento|utilizacao|lgpd|politica de privacidade|dados pessoais)\b",
            normalized,
        ):
            return "ativo"
        return "recusado"
    if _is_uncertain_lgpd_response(normalized):
        return None
    if any(marker in normalized for marker in accept):
        return "ativo"
    return None


def _is_uncertain_lgpd_response(text: str) -> bool:
    return bool(
        re.search(
            r"\b(?:nao sei|nao entendi|nao tenho certeza|talvez|depende)\b"
            r"|\b(?:aceito|concordo|autorizo|sim)\s+se\b",
            text,
        )
    )


def _lgpd_response(text: str) -> bool | None:
    """Decisão expressa em resposta à pergunta, incluindo frases compostas."""
    normalized = normalize_text(text)
    if any(normalize_text(marker) in normalized for marker in LGPD_REFUSE_MARKERS):
        return False
    if re.match(r"^(?:eu\s+)?(?:nao|n|recuso)\b", normalized) and not re.search(
        r"\b(?:nao sei|nao entendi|nao tenho certeza)\b", normalized
    ):
        return False
    if _is_uncertain_lgpd_response(normalized):
        return None
    if re.match(
        r"^(?:eu\s+)?(?:sim|s|aceito|concordo|autorizo|consinto)\b", normalized
    ):
        return True
    return None


def _is_unambiguous_lgpd_question(text: str) -> bool:
    normalized = normalize_text(text)
    if not _is_lgpd_context(text) or text.count("?") > 1:
        return False
    if (
        _is_age_question(normalized)
        or _is_cpf_context(normalized)
        or re.search(
            r"\b(?:marketing|ofertas|promocoes|propaganda|publicidade|campanhas)\b"
            r"|receber novidades",
            normalized,
        )
    ):
        return False
    if _is_majority_question(normalized):
        return _is_combined_majority_lgpd_question(text)
    return bool(
        re.search(
            r"\b(?:aceita|aceitar|concorda|concordar|autoriza|autorizar|consente|consentir)\b",
            normalized,
        )
        or (
            re.search(
                r"\b(?:responda|responder|responde|digite|envie)\b"
                r"(?:\s+(?:com|apenas))?\s*[^a-z0-9]*(?:sim|aceito|concordo)\b",
                normalized,
            )
            and re.search(r"\b(?:termos|consentimento|autorizacao)\b", normalized)
        )
    )


def _is_combined_majority_lgpd_question(text: str) -> bool:
    """SIM confirma ambos apenas quando o fluxo explicita a confirmação conjunta."""
    normalized = normalize_text(text)
    if (
        text.count("?") > 1
        or not _is_lgpd_context(normalized)
        or _is_cpf_context(normalized)
        or re.search(
            r"\b(?:marketing|ofertas|promocoes|propaganda|publicidade|campanhas)\b"
            r"|receber novidades",
            normalized,
        )
        or not re.search(r"\b(?:confirme|confirma|confirmar)\b", normalized)
        or not re.search(r"\b(?:entrega|pedido|atendimento)\b", normalized)
        or not re.search(
            r"\b(?:responda|digite|envie)\b(?:\s+(?:com|apenas))?\s*[^a-z0-9]*sim\b",
            normalized,
        )
    ):
        return False
    majority = re.search(
        r"\b(?:maior de 18|mais de 18 anos|18 anos ou mais|maior de idade)\b",
        normalized,
    )
    authorization = re.search(
        r"\b(?:autoriza|autorizar|concorda|consente)\b", normalized
    )
    if majority is None or authorization is None:
        return False
    earlier, later = sorted((majority, authorization), key=lambda match: match.start())
    return bool(re.search(r"\be\b", normalized[earlier.end() : later.start()]))


def _lgpd_decision(
    views: list[MessageView], index: int
) -> tuple[str, bool, str] | None:
    current = views[index]
    # Uma mensagem do próprio bot/atendente não declara a vontade do cliente.
    # Datas ausentes ou inválidas não podem vincular respostas a uma sessão.
    current_dt = _parse_datetime(current.created_on)
    if current.direction != "in" or current_dt == datetime.min.replace(tzinfo=UTC):
        return None
    direct = _direct_lgpd(current.text)
    if direct is not None:
        return direct, False, "decisão LGPD explícita na mensagem do cliente"

    previous = _previous_prompt(views, index)
    if previous is None or previous.direction != "out":
        return None
    previous_dt = _parse_datetime(previous.created_on)
    elapsed = (current_dt - previous_dt).total_seconds()
    if (
        previous_dt == datetime.min.replace(tzinfo=UTC)
        or elapsed < 0
        or elapsed > WENI_UPDATE_CONTEXT_LOOKBACK_HOURS * 3600
        or not _is_unambiguous_lgpd_question(previous.text)
    ):
        return None

    decision = _lgpd_response(current.text)
    combined = _is_combined_majority_lgpd_question(previous.text)
    if (
        combined
        and decision is False
        and not any(
            normalize_text(marker) in normalize_text(current.text)
            for marker in LGPD_REFUSE_MARKERS
        )
    ):
        # Um NÃO isolado pode negar a maioridade ou a autorização. Não atribuir
        # automaticamente ambas as negativas sem o cliente indicar o escopo.
        return None
    if decision is not None:
        return (
            "ativo" if decision else "recusado",
            False,
            f"resposta explícita à pergunta LGPD {previous.message_id}",
        )
    if combined:
        return None
    continuation = normalize_text(current.text).strip(".!?,;:")
    if continuation in {
        "pode continuar",
        "continuar",
        "pode prosseguir",
        "podemos continuar",
        "vamos continuar",
        "vamos seguir",
        "quero continuar",
        "quero continuar o atendimento",
        "quero seguir com o atendimento",
        "pode continuar com o atendimento",
        "pode prosseguir com o atendimento",
        "quero fazer meu pedido",
        "quero fazer o pedido",
        "vamos fazer o pedido",
    }:
        return (
            "ativo",
            True,
            f"continuidade explícita do atendimento após pergunta LGPD {previous.message_id}; sem consentimento de marketing",
        )
    return None


def _previous_prompt(views: list[MessageView], index: int) -> MessageView | None:
    # Prioriza uma mensagem de saída/flow, mas aceita a mensagem anterior
    # quando a API não informar direction. Limita a busca a 8 mensagens para
    # evitar usar contexto distante.
    fallback: MessageView | None = None
    for candidate in reversed(views[max(0, index - 8) : index]):
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
    current_lgpd: Any = None,
) -> dict[str, FieldEvidence]:
    """
    Infere somente campos de baixo risco a partir de mensagens novas.

    Respostas curtas (ex.: "Sim", "Não", "27" ou um CPF isolado) exigem
    contexto explícito sobre maioridade, LGPD, idade ou CPF. Decisões LGPD
    exigem mensagem recebida e data válida; respostas contextuais usam a janela
    de sessão configurada. Continuidade não substitui uma recusa registrada.
    Para CPF, somente documentos com 11 dígitos e dígitos verificadores válidos são aceitos.
    """
    views = [_view(message) for message in context_messages]
    views.sort(key=lambda item: (_parse_datetime(item.created_on), item.message_id))

    evidences: dict[str, FieldEvidence] = {}
    lgpd_refused = normalize_text(current_lgpd) in {
        "recusado",
        "recuso",
        "nao",
        "negado",
        "inativo",
        "opt-out",
        "opt out",
        "false",
        "0",
        "nao autorizado",
    }

    def save(field: str, value: str | int, current: MessageView, reason: str) -> None:
        evidences[field] = FieldEvidence(
            field=field,
            value=value,
            message_id=current.message_id,
            created_on=current.created_on,
            reason=reason,
        )

    for index, current in enumerate(views):
        lgpd = _lgpd_decision(views, index)
        if lgpd is not None and lgpd[0] == "recusado":
            lgpd_refused = True
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

        if lgpd is not None:
            value, implicit, reason = lgpd
            if not implicit or not lgpd_refused:
                save("opt_in_lgpd", value, current, reason)
                if not implicit and value == "ativo":
                    lgpd_refused = False

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
        if _is_majority_question(previous.text):
            if _is_lgpd_context(previous.text):
                current_dt = _parse_datetime(current.created_on)
                previous_dt = _parse_datetime(previous.created_on)
                elapsed = (current_dt - previous_dt).total_seconds()
                if (
                    _is_combined_majority_lgpd_question(previous.text)
                    and direct_majority is None
                    and current.direction == "in"
                    and previous.direction == "out"
                    and current_dt != datetime.min.replace(tzinfo=UTC)
                    and previous_dt != datetime.min.replace(tzinfo=UTC)
                    and 0 <= elapsed <= WENI_UPDATE_CONTEXT_LOOKBACK_HOURS * 3600
                    and re.match(r"^(?:eu\s+)?sim\b", normalize_text(current.text))
                    and not _is_uncertain_lgpd_response(normalize_text(current.text))
                ):
                    save(
                        "maior_de_18_anos",
                        "sim",
                        current,
                        "resposta SIM à confirmação conjunta de maioridade e LGPD",
                    )
            elif yes_no is not None:
                save(
                    "maior_de_18_anos",
                    "sim" if yes_no else "não",
                    current,
                    "resposta contextual à validação de maioridade",
                )

    return evidences
