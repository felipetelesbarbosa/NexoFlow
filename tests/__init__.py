"""Ambiente sintético da suíte, instalado antes dos módulos do projeto."""

import socket
import sys
from pathlib import Path
from types import ModuleType

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))


def _block_network(*args, **kwargs):
    raise RuntimeError("Teste tentou abrir uma conexão real. Use mocks.")


settings = ModuleType("secrets_config")
for name, value in {
    "WENI_API_TOKEN": "TOKEN_SINTETICO_WENI",
    "WENI_CHATS_API_BASE_URL": "https://chats.example.invalid",
    "WENI_CHATS_API_TOKEN": "TOKEN_SINTETICO_CHATS",
    "WENI_CHATS_ORDER_ID_FIELD": "",
    "GOOGLE_SPREADSHEET_ID": "PLANILHA_SINTETICA",
    "FARMALIDER_API_ENABLED": True,
    "FARMALIDER_API_TOKEN": "TOKEN_SINTETICO_FARMALIDER",
    "FARMALIDER_USE_HML": False,
    "PROXY_MODE": "off",
    "PROXY_HOST": "",
    "PROXY_PORT": 0,
    "PROXY_USER": "",
    "PROXY_PASSWORD": "",
    "PROXY_BYPASS": "localhost,127.0.0.1",
    "PROXY_DETECTION_TIMEOUT": 0.1,
    "WEBHOOK_SHARED_SECRET": "SEGREDO_SINTETICO_WEBHOOK",
    "WEBHOOK_PEDIDOS_ENABLED": False,
    "RECOMPRA_ENABLED": False,
}.items():
    setattr(settings, name, value)
sys.modules["secrets_config"] = settings

# TestClient/ASGI e mocks não abrem sockets; chamadas acidentais falham antes
# de transmitir tokens ou dados. Esta proteção existe somente na suíte.
socket.socket.connect = _block_network
socket.socket.connect_ex = _block_network
