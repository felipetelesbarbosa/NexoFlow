"""Migração opcional dos arquivos Google Sheets, com revisão antes da aplicação."""

from __future__ import annotations

import argparse
import logging
import re

from config import GOOGLE_CREDENTIALS_FILE, LOG_DIR
from sheets_migration import SheetsMigration
from sheets_storage import SheetsStorage


def spreadsheet_id(value: str) -> str:
    value = value.strip()
    if value.startswith("https://docs.google.com/spreadsheets/d/"):
        match = re.match(
            r"https://docs.google.com/spreadsheets/d/([A-Za-z0-9_-]+)(?:/|$)", value
        )
        if match:
            return match[1]
    elif re.fullmatch(r"[A-Za-z0-9_-]+", value):
        return value
    raise ValueError("Informe o ID ou o link nativo de uma planilha Google.")


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Divide operação, histórico e dashboard sem trocar as fontes BI do Looker."
    )
    parser.add_argument(
        "--operacao",
        required=True,
        help="ID ou link do arquivo de operação, compartilhado como Editor.",
    )
    parser.add_argument(
        "--historico",
        required=True,
        help="ID ou link do arquivo de histórico, compartilhado como Editor.",
    )
    parser.add_argument("--aplicar", action="store_true")
    parser.add_argument("--rotinas-paradas", action="store_true")
    parser.add_argument("--retirar-originais", action="store_true")
    args = parser.parse_args(argv)
    if args.aplicar and not args.rotinas_paradas:
        parser.error(
            "Encerre todas as rotinas antes de usar --aplicar --rotinas-paradas."
        )
    if args.retirar_originais and not args.aplicar:
        parser.error("A retirada dos originais exige --aplicar.")
    import secrets_config as secrets
    from google_sheets import GoogleSheetsStore
    from logging_config import configure_logging
    from proxy_config import configure_proxy
    from task_progress import TaskProgress

    layout = SheetsStorage(
        spreadsheet_id(str(getattr(secrets, "GOOGLE_SPREADSHEET_ID", ""))),
        spreadsheet_id(args.operacao),
        spreadsheet_id(args.historico),
    )
    SheetsStorage.from_values(layout.values(), layout.dashboard)
    configure_logging()
    configure_proxy()
    import gspread

    client = gspread.service_account(filename=str(GOOGLE_CREDENTIALS_FILE))
    client.set_timeout((10, 120))
    try:
        migration = SheetsMigration(
            client, layout, LOG_DIR / "privado" / "migracao_planilhas.json"
        )
        sheets = migration.plan(set(GoogleSheetsStore._schema_map()))
        for ws in sheets:
            role = (
                "histórico"
                if layout.destination(ws.title) == layout.history
                else "operação"
            )
            logging.info(
                "Migração: %s → %s (%s linhas × %s colunas).",
                ws.title,
                role,
                ws.row_count,
                ws.col_count,
            )
        if not args.aplicar:
            logging.info("Revisão concluída. Nenhuma cópia ou alteração foi aplicada.")
            return 0
        if not sheets:
            logging.info(
                "Os arquivos já estão separados; nenhuma nova cópia necessária."
            )
            return 0
        migration.copy_and_verify(sheets, progress_factory=TaskProgress)
        migration.activate(sheets)
        if args.retirar_originais:
            migration.remove_originals(
                sheets, routines_stopped=True, progress_factory=TaskProgress
            )
        logging.info(
            "Migração conferida e ativada. O dashboard e as fontes BI permanecem no arquivo original."
        )
        return 0
    finally:
        client.http_client.session.close()


if __name__ == "__main__":
    raise SystemExit(run())
