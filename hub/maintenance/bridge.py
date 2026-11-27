"""Unprivileged internal-only HTTP bridge. No shell, Docker socket, R2 creds, paths."""
from __future__ import annotations

import hmac
import json
import os
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TOKEN = Path("/run/secrets/maintenance_token")
REQUEST = Path("/request/request.json")
STATUS = Path("/status")
ROUTES = {"/limpeza": "limpeza", "/monitorar": "monitorar"}
TERMINAL = {"concluida", "adiada", "falhou"}
MUTEX = threading.Lock()


def authenticated(header: str, token: str) -> bool:
    return bool(token) and hmac.compare_digest(header, "Bearer " + token)


def get_status(action: str) -> dict:
    try:
        obj = json.loads((STATUS / (action + ".json")).read_text())
        return obj if isinstance(obj, dict) else {}
    except (OSError, ValueError):
        return {}


class Handler(BaseHTTPRequestHandler):
    server_version = "NexoFlowMaintenance"
    sys_version = ""

    def log_message(self, *_args):
        pass

    def send_json(self, code: int, data: dict):
        raw = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def authorized(self):
        return authenticated(self.headers.get("Authorization", ""), self.server.token)

    def do_GET(self):
        if not self.authorized():
            return self.send_json(401, {"estado": "nao_autorizado"})
        if self.path not in {"/estado/limpeza", "/estado/monitorar"}:
            return self.send_json(404, {"estado": "rota_invalida"})
        return self.send_json(200, get_status(self.path.rsplit("/", 1)[-1]) or {"estado": "sem_execucao"})

    def do_POST(self):
        if not self.authorized():
            return self.send_json(401, {"estado": "nao_autorizado"})
        if self.path not in ROUTES or self.headers.get("Content-Length", "0") != "0":
            return self.send_json(400, {"estado": "solicitacao_invalida"})
        action = ROUTES[self.path]
        with MUTEX:
            if any((s := get_status(a)).get("estado") == "em_andamento"
                   and time.time() - s.get("inicio_epoch", 0) < 3700 for a in ROUTES.values()):
                return self.send_json(409, {"estado": "ocupado"})
            job = uuid.uuid4().hex
            raw = json.dumps({"id": job, "acao": action}, separators=(",", ":")).encode()
            try:
                # Atomic publish: create the private temporary marker before linking.
                temp = REQUEST.with_name("tmp-" + job)
                fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                with os.fdopen(fd, "wb") as f:
                    f.write(raw)
                try:
                    if os.path.lexists(REQUEST):
                        raise FileExistsError
                    os.rename(temp, REQUEST)
                finally:
                    temp.unlink(missing_ok=True)
            except FileExistsError:
                return self.send_json(409, {"estado": "ocupado"})
            except OSError:
                return self.send_json(503, {"estado": "fila_indisponivel"})
        for _ in range(240):
            current = get_status(action)
            if current.get("id") == job and current.get("estado") in TERMINAL:
                return self.send_json(200 if current["estado"] != "falhou" else 500, current)
            time.sleep(1)
        return self.send_json(202, {"id": job, "acao": action, "estado": "em_andamento"})


def main():
    token = TOKEN.read_text().strip()
    if len(token) < 48:
        raise ValueError("private_credential_required")
    server = ThreadingHTTPServer(("0.0.0.0", 8080), Handler)
    server.token = token
    server.serve_forever()


if __name__ == "__main__":
    main()
