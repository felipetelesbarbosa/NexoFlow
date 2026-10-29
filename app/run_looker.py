"""Recalcula as tabelas comerciais usando o histórico já gravado no Sheets."""

from __future__ import annotations

import argparse
import logging
from datetime import datetime
from zoneinfo import ZoneInfo


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Atualiza as tabelas do Looker Studio a partir do Google Sheets."
    )
    parser.add_argument("--inicio", help="Início do período ABC, AAAA-MM-DD")
    parser.add_argument("--fim", help="Fim do período ABC, AAAA-MM-DD")
    args = parser.parse_args(argv)
    from looker_bi import build_looker_tables, reporting_period

    now = datetime.now(ZoneInfo("America/Belem"))
    # Validar antes de abrir qualquer conexão ou criar uma aba.
    start, end = reporting_period(now.date().isoformat(), args.inicio, args.fim)
    from proxy_config import configure_proxy

    configure_proxy()
    from project_paths import load_private_settings

    secrets = load_private_settings()
    from google_sheets import GoogleSheetsStore
    from logging_config import configure_logging

    configure_logging()
    spreadsheet_id = str(getattr(secrets, "GOOGLE_SPREADSHEET_ID", "") or "").strip()
    if not spreadsheet_id or "COLE_" in spreadsheet_id:
        raise ValueError(
            "Configure o ID da planilha Google antes de atualizar o Looker."
        )
    store = GoogleSheetsStore(spreadsheet_id)
    try:
        _, base, _ = store.load_base_snapshot()
        orders, items = store.load_order_records(), store.load_order_item_records()
        tables = build_looker_tables(
            base,
            orders,
            items,
            snapshot_date=now.date().isoformat(),
            updated_at=now.isoformat(timespec="seconds"),
            period_start=start,
            period_end=end,
            history_observed_since=store.get_control("historico_observado_desde"),
        )
        store.migrate_bi_summary_numbers()
        store.replace_looker_tables(tables)
        logging.info(
            "Tabelas comerciais atualizadas para %s a %s. Histórico operacional preservado.",
            start,
            end,
        )
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
