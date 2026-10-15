"""Proteções compartilhadas pelos webhooks opcionais.

O lock serializa requisições no mesmo processo. Ele não coordena outros workers,
servidores ou a sincronização periódica: Google Sheets não oferece uma transação
de leitura e inclusão para esses escritores independentes.
"""

from __future__ import annotations

import hmac
from threading import RLock

WEBHOOK_WRITE_LOCK = RLock()


def shared_secret_matches(expected: str, supplied: str | None) -> bool:
    """Compara o segredo sem rejeitar caracteres UTF-8 ou aceitar valor vazio."""
    if not expected or supplied is None:
        return False
    return hmac.compare_digest(expected.encode("utf-8"), supplied.encode("utf-8"))
