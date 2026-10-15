from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

from config import LOG_DIR, LOG_FILE


class BelemFormatter(logging.Formatter):
    """Use America/Belem (UTC-3) even when the machine runs in another zone."""

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        local = datetime.fromtimestamp(
            record.created,
            timezone(timedelta(hours=-3), "America/Belem"),
        )
        if datefmt:
            return local.strftime(datefmt)
        return f"{local:%Y-%m-%d %H:%M:%S},{int(record.msecs):03d} -03:00"


def configure_logging(log_file: Path | None = None) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    target = log_file or LOG_FILE
    formatter = BelemFormatter("%(asctime)s | %(levelname)s | %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in root.handlers:
        handler.close()
    root.handlers.clear()
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)
    file_handler = RotatingFileHandler(
        target,
        maxBytes=2_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
