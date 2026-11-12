"""Sonda privada, sem emitir headers ou conteúdo de tabelas."""

import json
import os
import urllib.request
from pathlib import Path

config = json.loads(
    Path(os.environ["DATASTUDIO_CONFIG_FILE"]).read_text(encoding="utf-8-sig")
)
token = Path(config["token_file"]).read_text(encoding="utf-8-sig").strip()
request = urllib.request.Request(
    "http://127.0.0.1:8080/v1/destino", headers={"Authorization": "Bearer " + token}
)
with urllib.request.urlopen(request, timeout=8) as response:
    assert response.status == 200
