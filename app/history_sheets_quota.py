"""Ritmo HTTP do histórico, sem mudar o contrato ou repetir gravações.

O ledger guarda somente hashes de escopos Google e horários. É compartilhado
pelos comandos de histórico desta instalação; não coordena outros aplicativos
ou computadores. A sessão/autenticação/TLS/proxy existentes são preservados.
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
import random
import sqlite3
import time
from contextlib import closing, contextmanager
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit

from requests.adapters import BaseAdapter

from duration_display import duration
from order_history import HistoryError

PERIOD = 60.0
DEFAULT_RPM = 45
PROJECT_RPM = 240


def _scope(kind, value):
    return hashlib.sha256((kind + "\0" + value).encode()).hexdigest()


def _rate(name):
    value = os.environ.get(name, str(DEFAULT_RPM))
    if (
        not 1 <= len(value) <= 2
        or not value.isascii()
        or not value.isdigit()
        or not 1 <= int(value) <= 50
    ):
        raise HistoryError("SHEETS_COTA_CONFIGURACAO: RPM deve estar entre 1 e 50.")
    return int(value)


class QuotaGate:
    def __init__(
        self,
        path,
        *,
        user,
        project,
        read_rpm=DEFAULT_RPM,
        write_rpm=DEFAULT_RPM,
        now=time.time,
        sleep=time.sleep,
    ):
        if (
            not isinstance(user, str)
            or not user
            or not isinstance(project, str)
            or not project
            or any(
                type(v) is not int or not 1 <= v <= 50 for v in (read_rpm, write_rpm)
            )
        ):
            raise HistoryError("SHEETS_COTA_IDENTIDADE_OU_LIMITE_INVALIDO")
        self.path = Path(path)
        self.scopes = (
            _scope("project", project),
            _scope("user", project + "\0" + user),
        )
        self.rates = {
            "read": (PROJECT_RPM, read_rpm),
            "write": (PROJECT_RPM, write_rpm),
        }
        self.now, self.sleep = now, sleep
        self.calls = {"read": 0, "write": 0}
        self.wait_seconds = 0.0
        self.limited = 0
        self.last_progress = self.now()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(fd)
        with self.transaction() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            tables = {
                r[0]
                for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if version == 0 and not tables:
                db.execute(
                    "CREATE TABLE quota(scope TEXT,kind TEXT,next_at REAL,cooldown REAL,last_at REAL,PRIMARY KEY(scope,kind))"
                )
                db.execute("PRAGMA user_version=1")
            elif (
                version != 1
                or tables != {"quota"}
                or [r[1] for r in db.execute("PRAGMA table_info(quota)")]
                != ["scope", "kind", "next_at", "cooldown", "last_at"]
            ):
                raise HistoryError(
                    "SHEETS_COTA_ESTADO_INVALIDO: preservar arquivo para diagnóstico."
                )
            if db.execute("PRAGMA quick_check").fetchone() != ("ok",):
                raise HistoryError(
                    "SHEETS_COTA_ESTADO_INVALIDO: preservar arquivo para diagnóstico."
                )

    @contextmanager
    def transaction(self):
        try:
            with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
                db.execute("BEGIN IMMEDIATE")
                yield db
        except sqlite3.Error:
            raise HistoryError(
                "SHEETS_COTA_ESTADO_INDISPONIVEL: nenhuma chamada liberada; preserve a revisão."
            ) from None

    def acquire(self, kind):
        if kind not in self.rates:
            raise HistoryError("SHEETS_COTA_OPERACAO_INVALIDA")
        started = self.now()
        while True:
            with self.transaction() as db:
                now = self.now()
                if not math.isfinite(now):
                    raise HistoryError("SHEETS_COTA_RELOGIO_INVALIDO")
                rows = []
                for key in self.scopes:
                    row = db.execute(
                        "SELECT next_at,cooldown,last_at FROM quota WHERE scope=? AND kind=?",
                        (key, kind),
                    ).fetchone() or (0.0, 0.0, 0.0)
                    if (
                        any(
                            not isinstance(v, (float, int)) or not math.isfinite(v)
                            for v in row
                        )
                        or now < row[2] - 5
                    ):
                        raise HistoryError("SHEETS_COTA_RELOGIO_OU_ESTADO_INVALIDO")
                    rows.append(row)
                wait = max(0.0, *(max(row[:2]) - now for row in rows))
                if wait > 300 or now - started > 300:
                    raise HistoryError(
                        "SHEETS_COTA_PAUSA_LONGA: aguarde o prazo do serviço e retome a mesma revisão."
                    )
                if not wait:
                    for key, rate, row in zip(
                        self.scopes, self.rates[kind], rows, strict=True
                    ):
                        db.execute(
                            "INSERT OR REPLACE INTO quota VALUES(?,?,?,?,?)",
                            # Margem mínima evita que arredondamento acumule
                            # uma chamada extra na fronteira de 60 segundos.
                            (key, kind, now + PERIOD / rate + 0.001, row[1], now),
                        )
            if not wait:
                self.calls[kind] += 1
                self.progress()
                return now
            # Não manter conexão/trava durante espera. Outra instância pode ter
            # recebido 429 e estendido o prazo: reler antes de liberar a chamada.
            delay = min(wait, 30.0)
            self.sleep(delay)
            self.wait_seconds += delay
            self.progress()

    def cooldown(self, kind, seconds):
        if kind not in self.rates or not math.isfinite(seconds) or seconds < 0:
            raise HistoryError("SHEETS_COTA_PAUSA_INVALIDA")
        with self.transaction() as db:
            now = self.now()
            for key in self.scopes:
                db.execute(
                    "INSERT INTO quota VALUES(?,?,?,?,?) ON CONFLICT(scope,kind) DO UPDATE SET cooldown=max(cooldown,excluded.cooldown)",
                    (key, kind, now, now + seconds, now),
                )
        self.limited += 1
        logging.warning(
            "Google Sheets: HTTP 429; pausa compartilhada de pelo menos %s para %s. Nenhum POST será repetido pelo limitador.",
            duration(seconds),
            "leituras" if kind == "read" else "escritas",
        )

    def progress(self):
        if self.now() - self.last_progress >= 60:
            self.last_progress = self.now()
            print(
                f"[REDE SHEETS] Tentativas HTTP: leituras={self.calls['read']}; escritas={self.calls['write']}; 429={self.limited}; espera preventiva={duration(self.wait_seconds)}. Lotes são confirmados pelo journal.",
                flush=True,
            )


def request_kind(request):
    path = urlsplit(request.url).path
    if request.method.upper() in ("GET", "HEAD") or (
        request.method.upper() == "POST"
        and path.endswith(
            (
                ":getByDataFilter",
                "/values:batchGetByDataFilter",
                "/developerMetadata:search",
            )
        )
    ):
        return "read"
    return "write"


class QuotaAdapter(BaseAdapter):
    """Decorador do adaptador existente: não altera payload, TLS ou retries."""

    def __init__(self, delegate, gate):
        super().__init__()
        self.delegate, self.gate = delegate, gate

    def send(self, request, **kwargs):
        kind = request_kind(request)
        self.gate.acquire(kind)
        response = self.delegate.send(request, **kwargs)
        if response.status_code == 429:
            delay = 65.0 + random.uniform(0, 1)
            value = response.headers.get("Retry-After")
            if value:
                try:
                    retry = float(value)
                except ValueError:
                    try:
                        retry = (
                            parsedate_to_datetime(value).timestamp() - self.gate.now()
                        )
                    except (ValueError, TypeError, OverflowError):
                        retry = 0.0
                if math.isfinite(retry):
                    delay = max(delay, retry)
            self.gate.cooldown(kind, delay)
        return response

    def close(self):
        # O adaptador delegado permanece montado em https:// e é fechado pela
        # própria sessão. Não fechar duas vezes nem invalidar suas conexões.
        pass


def google_store_type():
    # Import tardio: perfil/rede precisam estar definidos antes de config.
    from order_history_sheets import google_store_type as base_store_type

    class HistoryQuotaStore(base_store_type()):
        def _read_with_retry(self, description, func):
            session = self.client.http_client.session
            prefix = "https://sheets.googleapis.com/"
            if not isinstance(session.get_adapter(prefix), QuotaAdapter):
                from project_paths import ROOT

                auth = getattr(self.client.http_client, "auth", None)
                user = getattr(auth, "service_account_email", "")
                project = (
                    getattr(auth, "quota_project_id", None)
                    or getattr(auth, "project_id", "")
                    or "unknown-project"
                )
                read_rpm = _rate("NEXOFLOW_SHEETS_READ_RPM")
                write_rpm = _rate("NEXOFLOW_SHEETS_WRITE_RPM")
                gate = QuotaGate(
                    ROOT / "logs" / "privado" / "sheets_quota.sqlite",
                    user=user,
                    project=project,
                    read_rpm=read_rpm,
                    write_rpm=write_rpm,
                )
                adapter = QuotaAdapter(session.get_adapter(prefix), gate)
                session.mount(prefix, adapter)
                session.mount("https://sheets.googleapis.com:443/", adapter)
                print(
                    f"[INFO] Sheets: ritmo preventivo compartilhado nesta instalação; leitura={read_rpm}/min; escrita={write_rpm}/min. Outras aplicações podem consumir a mesma cota.",
                    flush=True,
                )
            return super()._read_with_retry(description, func)

    return HistoryQuotaStore
