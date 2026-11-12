"""Entradas dos contêineres; DSN somente em Docker secret da VPS."""

import json
import os
from pathlib import Path

from integrations.datastudio.api import create_app
from integrations.datastudio.reader import Reader
from integrations.datastudio.store import Store


def app_factory():
    config = json.loads(
        Path(os.environ["DATASTUDIO_CONFIG_FILE"]).read_text(encoding="utf-8-sig")
    )
    reader = config["mode"] == "read"
    if config["mode"] not in ("read", "publish"):
        raise RuntimeError("DS_MODO_INVALIDO")
    token = Path(config["token_file"]).read_text(encoding="utf-8-sig").strip()
    dsn = Path(config["dsn_file"]).read_text(encoding="utf-8-sig").strip()
    cls = Reader if reader else Store
    store = cls(
        dsn, config["environment"], config["segment"], require_dedicated_role=True
    )
    store.info()
    return create_app(store, token, reader=reader)
