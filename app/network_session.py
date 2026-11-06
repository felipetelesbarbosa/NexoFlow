"""Compartilha somente a rota entre processos de uma mesma execução."""

import json
import os
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4


@contextmanager
def session_scope():
    inherited = bool(os.environ.get("NEXOFLOW_NETWORK_SESSION"))
    if not inherited:
        os.environ["NEXOFLOW_NETWORK_SESSION"] = uuid4().hex
    try:
        yield
    finally:
        if not inherited:
            path = session_path()
            if path is not None:
                path.unlink(missing_ok=True)
            os.environ.pop("NEXOFLOW_NETWORK_SESSION", None)


def session_path() -> Path | None:
    token = os.environ.get("NEXOFLOW_NETWORK_SESSION", "")
    if not token:
        return None
    if not re.fullmatch(r"[a-zA-Z0-9-]{8,100}", token):
        raise ValueError("Identificador de sessão de rede inválido.")
    return Path(tempfile.gettempdir()) / f"nexoflow-network-{token}.json"


def read_choice() -> str | None:
    path = session_path()
    if path is None or not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        choice = value["mode"]
        if choice not in ("personal", "corporate"):
            raise ValueError
        return choice
    except (OSError, ValueError, KeyError, TypeError):
        raise ValueError("Sessão de rede inválida; reinicie a execução.") from None


def save_choice(choice: str) -> None:
    path = session_path()
    if path is None:
        return
    if choice not in ("personal", "corporate"):
        raise ValueError("Escolha de rede inválida.")
    temporary = path.with_suffix(f".{uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as output:
            os.chmod(temporary, 0o600)
            json.dump({"mode": choice}, output)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
