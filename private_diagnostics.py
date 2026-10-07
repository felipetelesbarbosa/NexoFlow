"""Local-only failure journal; public logs never receive CPF or response text."""
from __future__ import annotations

from datetime import datetime
import json
import math
import os
from pathlib import Path
import re
import threading
from urllib.parse import quote, quote_plus

from config import LOG_DIR
from pedido_utils import BUSINESS_TIMEZONE

_WRITE_LOCK = threading.Lock()
_DIAGNOSTIC_KEYS = {
    "message", "mensagem", "msg", "error", "erro", "title", "detail",
    "exceptionmessage", "errormessage", "description", "descricao",
    "status", "statuscode", "code", "codigo", "success", "sucesso",
}


def private_diagnostic_directory() -> Path:
    if os.name == "nt":
        base = os.getenv("LOCALAPPDATA")
        if base:
            return Path(base) / "NexoFlow" / "diagnosticos_privados"
        return Path.home() / "AppData" / "Local" / "NexoFlow" / "diagnosticos_privados"
    return LOG_DIR / "privado"


def sanitize_error_body(raw: bytes, token: str) -> dict:
    """Keep bounded diagnostic fields; omit headers, URLs and customer objects."""
    if len(raw) > 4096:
        return {"estado": "omitido_por_tamanho", "bytes": len(raw)}
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError):
        return {"estado": "omitido_nao_json", "bytes": len(raw)}

    def clean(text: str) -> str:
        if "-----BEGIN" in text or "private_key" in text.casefold():
            return "[conteúdo sensível omitido]"
        for secret in sorted({token, quote(token, safe=""), quote_plus(token)}, key=len, reverse=True):
            if secret:
                text = text.replace(secret, "[credencial removida]")
        text = re.sub(r"(?i)https?://[^\s<>]+", "[URL removida]", text)
        text = re.sub(r"(?i)\b(?:bearer|basic)\s+[\w+/=.-]+", "[autenticação removida]", text)
        text = re.sub(r"(?i)\b(?:token|senha|password|passwd|secret|api[_-]?key|authorization|cookie)\b\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)", "[credencial removida]", text)
        text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[email removido]", text)
        text = re.sub(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b|\b\d{8,}\b", "[identificador removido]", text)
        text = re.sub(r"\+?\d{2}\s*\(?\d{2}\)?\s*\d{4,5}[-\s]\d{4}\b|\(?\d{2}\)?\s*\d{4,5}[-\s]\d{4}\b", "[telefone removido]", text)
        return text[:2048]

    if isinstance(value, str):
        return {"estado": "json_texto_sanitizado", "mensagem": clean(value)}
    if not isinstance(value, dict):
        return {"estado": "omitido_formato_nao_diagnostico", "bytes": len(raw)}
    fields = {}
    for key, item in value.items():
        normalized = key.casefold() if isinstance(key, str) else ""
        if normalized not in _DIAGNOSTIC_KEYS:
            continue
        if isinstance(item, str):
            fields[normalized] = clean(item)
        elif item is None or isinstance(item, bool):
            fields[normalized] = item
        elif isinstance(item, int) or isinstance(item, float) and math.isfinite(item):
            fields[normalized] = item if abs(item) < 10_000_000 else "[identificador removido]"
    return {"estado": "campos_diagnosticos_sanitizados", "campos": fields, "campos_omitidos": len(value) - len(fields)}


def append_private_failure(*, execution_id: str, reference: str, cpf: str,
                           status: int, attempts: int, reason: str,
                           environment: str, raw: bytes, token: str,
                           summary: str) -> Path | None:
    if not re.fullmatch(r"[0-9]{11}", cpf):
        return None
    record = {
        "execucao_id": execution_id,
        "consulta_ref": reference,
        "horario": datetime.now(BUSINESS_TIMEZONE).isoformat(timespec="seconds"),
        "cpf": cpf,
        "endpoint": "cliente/cpf",
        "ambiente": environment,
        "status_http_5xx": status,
        "tentativas_realizadas": attempts,
        "motivo_encerramento": reason,
        "diagnostico_publico": summary,
        "resposta": sanitize_error_body(raw, token),
    }
    data = (json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    directory = private_diagnostic_directory()
    path = directory / f"farmalider_falhas_{execution_id}.jsonl"
    with _WRITE_LOCK:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(descriptor, "ab") as stream:
            stream.write(data)
    return path
